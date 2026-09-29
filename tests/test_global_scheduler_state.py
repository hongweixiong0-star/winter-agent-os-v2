import json
from datetime import datetime, timezone

import pytest

from winter_agent_v2.global_scheduler_state import (
    GlobalSchedulerStateStore,
    RoleRuntimeState,
)


def test_restart_uses_actual_identity_and_discards_ephemeral_state(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "global_scheduler_state.json")
    store.save(store.load())
    store.record_role_observation(
        role_id="A", observed_at="2026-09-29T00:00:00+08:00", page="HOME",
        page_confidence=0.99,
        goal_summaries=[{"goal_id": "TRAIN", "status": "READY", "priority": 10}],
    )
    state = store.load()
    state.roles["A"].health = "ACTIVE"
    state.roles["A"].page = "RALLY_LIST"
    store.save(state)

    recovered = store.recover_after_restart(
        actual_role_id="B", actual_role_name="Role B", observed_at="2026-09-29T00:01:00+08:00"
    )

    assert recovered.active_role_id == "B"
    assert recovered.roles["A"].health == "STALE"
    assert recovered.roles["A"].page is None
    assert recovered.roles["B"].health == "NEEDS_FRESH_OBSERVATION"
    assert recovered.roles["B"].role_name == "Role B"
    assert recovered.roles["B"].dirty_live_state is True


def test_role_switch_is_transactional_and_requires_matching_identity(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.record_role_observation(role_id="A", observed_at=datetime.now(timezone.utc), page="HOME")

    pending = store.begin_role_switch(source_role_id="A", target_role_id="B", reason="B has P0")
    assert pending.active_role_id == "A"
    assert pending.role_switch_pending["target_role_id"] == "B"
    with pytest.raises(ValueError, match="ROLE_SWITCH_NOT_VERIFIED"):
        store.commit_role_switch(confirmed_role_id="A")
    with pytest.raises(RuntimeError, match="ROLE_SWITCH_ALREADY_PENDING"):
        store.begin_role_switch(source_role_id="A", target_role_id="B", reason="duplicate")

    committed = store.commit_role_switch(confirmed_role_id="B")
    assert committed.active_role_id == "B"
    assert committed.role_switch_pending is None
    assert committed.roles["A"].health == "STALE"
    assert committed.roles["B"].health == "NEEDS_FRESH_OBSERVATION"


def test_failed_switch_requires_observed_actual_role_or_degrades(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.begin_role_switch(source_role_id="A", target_role_id="B", reason="refresh B")

    degraded = store.abort_role_switch(reason="identity was unreadable")
    assert degraded.global_health == "DEGRADED"
    assert degraded.active_role_id == ""
    assert degraded.last_switch_reason.startswith("ROLE_SWITCH_ABORT:")

    store.begin_role_switch(source_role_id="A", target_role_id="B", reason="try again")
    recovered = store.abort_role_switch(actual_role_id="A", reason="still on source")
    assert recovered.global_health == "RUNNING"
    assert recovered.active_role_id == "A"
    assert recovered.roles["A"].health == "NEEDS_FRESH_OBSERVATION"
    target = recovered.roles["B"]
    assert target.switch_failure_streak == 2
    assert target.last_failure == "still on source"
    assert target.blocked_until is not None
    assert target.page is None


def test_failed_switch_uses_bounded_exponential_backoff_and_success_clears_it(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.begin_role_switch(source_role_id="A", target_role_id="B", reason="refresh B")
    failed = store.abort_role_switch(actual_role_id="A", reason="row did not load")
    first = datetime.fromisoformat(failed.roles["B"].blocked_until)
    remaining = (first - datetime.now(timezone.utc)).total_seconds()
    assert 0 < remaining <= 15
    assert failed.roles["B"].switch_failure_streak == 1

    store.begin_role_switch(source_role_id="A", target_role_id="B", reason="retry B")
    failed_again = store.abort_role_switch(actual_role_id="A", reason="row did not load")
    assert failed_again.roles["B"].switch_failure_streak == 2
    second = datetime.fromisoformat(failed_again.roles["B"].blocked_until)
    assert 0 < (second - datetime.now(timezone.utc)).total_seconds() <= 30

    store.begin_role_switch(source_role_id="A", target_role_id="B", reason="retry B")
    recovered = store.commit_role_switch(confirmed_role_id="B")
    assert recovered.roles["B"].switch_failure_streak == 0
    assert recovered.roles["B"].blocked_until is None


def test_action_outcome_persists_per_goal_verified_credit_without_live_ui_data(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    outcome = store.record_action_outcome({
        "action_id": "episode-1:3",
        "role_id": "A",
        "skill_id": "TRAIN_TROOPS",
        "goal_id": "KEEP_TRAINING_PRODUCTIVE",
        "attached_goal_ids": ["KEEP_TRAINING_PRODUCTIVE", "DAILY_TRAINING"],
        "action_sent": True,
        "post_action_observed": True,
        "observed_change": "TRAINING_STARTED",
        "verifier_result": "PASS",
        "goal_progress_by_id": {
            "KEEP_TRAINING_PRODUCTIVE": True,
            "DAILY_TRAINING": False,
        },
        "credited_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "completed_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "frame_path": "private-frame.png",
        "target_bbox": [1, 2, 3, 4],
    })

    assert outcome.latest_action_outcome["role_id"] == "A"
    assert outcome.latest_action_outcome["credited_goal_ids"] == ["KEEP_TRAINING_PRODUCTIVE"]
    assert "frame_path" not in outcome.latest_action_outcome
    assert "target_bbox" not in outcome.latest_action_outcome
    assert outcome.action_outcome_history[-1]["goal_progress_by_id"]["DAILY_TRAINING"] is False


def test_production_telemetry_counts_wait_invariant_and_shared_goal_credit(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.record_decision(decision={
        "decision": "GLOBAL_WAIT",
        "role_statuses": [{"role_id": "A", "runnable_count": 0}],
    })
    store.record_decision(decision={
        "decision": "GLOBAL_WAIT",
        "role_statuses": [{"role_id": "A", "runnable_count": 1}],
    })
    store.record_action_outcome({
        "action_id": "episode-2:4",
        "role_id": "A",
        "skill_id": "TRAIN_TROOPS",
        "credited_goal_ids": ["KEEP_TRAINING_PRODUCTIVE", "DAILY_TRAINING"],
        "completed_goal_ids": ["KEEP_TRAINING_PRODUCTIVE", "DAILY_TRAINING"],
        "action_sent": True,
        "post_action_observed": True,
        "verifier_result": "PASS",
    })

    metrics = store.production_telemetry_metrics()

    assert metrics["global_wait_count"] == 2
    assert metrics["global_wait_with_runnable_goal_count"] == 1
    assert metrics["action_outcome_count"] == 1
    assert metrics["shared_goal_credit_count"] == 1
    assert metrics["completed_goal_count_by_role"] == {"A": 2}
    assert metrics["since"]


def test_role_switch_metrics_track_verified_outcomes_and_latency_percentiles(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.begin_role_switch(source_role_id="A", target_role_id="B", reason="B has work")
    store.commit_role_switch(confirmed_role_id="B", elapsed_ms=1000)
    store.begin_role_switch(source_role_id="B", target_role_id="A", reason="A deadline")
    store.abort_role_switch(actual_role_id="B", reason="login failed", elapsed_ms=3000)

    metrics = store.role_switch_metrics()

    assert metrics == {
        "count": 2,
        "success_count": 1,
        "failure_count": 1,
        "success_rate": 0.5,
        "p50_ms": 1000.0,
        "p95_ms": 3000.0,
    }


def test_decision_history_is_bounded_and_excludes_live_coordinates(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    for index in range(12):
        store.record_decision(decision={
            "decision": "KEEP_ROLE",
            "reason": f"tick-{index}",
            "selected_goal": "TRAIN",
            "frame_path": "private-frame.png",
            "candidate": {"bbox": [1, 2, 3, 4], "goal_id": "TRAIN"},
        })

    state = store.load()
    assert len(state.decision_history) == 10
    assert state.decision_history[0]["reason"] == "tick-2"
    assert "frame_path" not in state.last_decision
    assert "bbox" not in state.last_decision["candidate"]


def test_a_list_row_that_mentions_a_live_key_keeps_its_logical_fields(tmp_path):
    """Stripping the live field must not delete the record that carried it.

    ``role_statuses`` is a list of per-role rows.  An earlier filter dropped any list
    element containing a live-only key at all, so one stray ``bbox`` silently removed the
    whole role row -- and every reader of that row (the panel, the ROLE_SESSION_POLICY
    refresh) then saw zeros instead of the real counts.
    """
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.record_decision(decision={
        "decision": "KEEP_ROLE",
        "role_statuses": [{
            "role_id": "A", "runnable_goal_count": 3, "ready_goal_count": 3,
            "bbox": [1, 2, 3, 4], "tap_point": [10, 20],
        }],
    })

    rows = store.load().last_decision["role_statuses"]
    assert len(rows) == 1
    assert rows[0]["role_id"] == "A"
    assert rows[0]["runnable_goal_count"] == 3
    assert "bbox" not in rows[0]
    assert "tap_point" not in rows[0]


def test_role_runtime_state_never_restores_as_fresh_live_state():
    role = RoleRuntimeState(
        role_key="A", role_id="A", health="ACTIVE", page="HOME",
        last_observed_at="2026-09-29T00:00:00Z", dirty_live_state=False,
    )
    assert role.health == "ACTIVE"
    assert role.dirty_live_state is True


def test_role_observation_requires_confirmed_identity_and_timestamp(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    with pytest.raises(ValueError, match="confirmed role_id"):
        store.record_role_observation(role_id="", observed_at="2026-09-29T00:00:00Z")
    with pytest.raises(ValueError, match="valid timestamp"):
        store.record_role_observation(role_id="A", observed_at="unknown")


def test_persisted_state_contains_logical_fields_but_no_frame_data(tmp_path):
    path = tmp_path / "state.json"
    store = GlobalSchedulerStateStore(path)
    store.record_role_observation(
        role_id="A", observed_at="2026-09-29T00:00:00Z", page="HOME",
        goal_summaries=[{
            "goal_id": "TRAIN", "status": "READY", "priority": 10,
            "evidence": {"estimated_duration_seconds": 30, "target_bbox": [1, 2, 3, 4]},
        }],
    )
    store.record_decision(decision={"decision": "KEEP_ROLE", "target_id": "BTN_TRAIN"})

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["roles"]["A"]["page"] == "HOME"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "target_bbox" not in serialized
    assert '"frame"' not in serialized


def test_observing_one_role_invalidates_other_roles_live_summary(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    store.record_role_observation(
        role_id="A", observed_at="2026-09-29T00:00:00Z", page="RALLY_LIST",
        current_skill="JOIN_RALLY",
    )
    store.record_role_observation(
        role_id="B", observed_at="2026-09-29T00:05:00Z", page="HOME",
    )

    state = store.load()
    assert state.active_role_id == "B"
    assert state.roles["A"].health == "STALE"
    assert state.roles["A"].page is None
    assert state.roles["A"].current_skill == ""
    assert state.roles["B"].health == "ACTIVE"


def test_live_role_catalog_registers_identities_but_keeps_both_world_states_stale(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    observed_at = "2026-09-29T01:11:09+08:00"
    state = store.register_role_catalog([
        {
            "role_key": "ROLE_A", "role_id": "1063040265",
            "display_name": "[ioi]零氪纯盾流", "identity_source": "LIVE_PROFILE",
            "identity_evidence": ["role_a_profile.png"],
        },
        {
            "role_key": "ROLE_B", "role_id": "1061663148",
            "display_name": "[DIW]xhw", "identity_source": "LIVE_PROFILE",
            "identity_evidence": ["role_b_profile.png"],
        },
    ], active_role_id="1063040265", observed_at=observed_at)

    assert state.active_role_id == "1063040265"
    assert state.roles["1063040265"].health == "NEEDS_FRESH_OBSERVATION"
    assert state.roles["1061663148"].health == "STALE"
    assert state.roles["1061663148"].role_name == "[DIW]xhw"
    assert state.roles["1061663148"].identity_source == "LIVE_PROFILE"
    assert state.roles["1061663148"].identity_evidence == ["role_b_profile.png"]
    assert state.roles["1061663148"].page is None
    assert state.roles["1061663148"].dirty_live_state is True


def test_live_role_catalog_refuses_unconfirmed_or_ambiguous_ids(tmp_path):
    store = GlobalSchedulerStateStore(tmp_path / "state.json")
    with pytest.raises(ValueError, match="confirmed role_id"):
        store.register_role_catalog([{"role_key": "ROLE_A"}])
    duplicate = [
        {"role_key": "ROLE_A", "role_id": "A"},
        {"role_key": "ROLE_B", "role_id": "A"},
    ]
    with pytest.raises(ValueError, match="duplicate role_id"):
        store.register_role_catalog(duplicate)
    with pytest.raises(ValueError, match="active_role_id"):
        store.register_role_catalog([{"role_key": "ROLE_A", "role_id": "A"}],
                                   active_role_id="B")
