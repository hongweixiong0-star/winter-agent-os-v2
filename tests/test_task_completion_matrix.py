import json
from pathlib import Path

from winter_agent_v2.task_completion import TaskCompletionStore, task_types_for_goal


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_fishing_has_its_own_completion_category():
    assert task_types_for_goal("USE_NORMAL_FISHING_BAIT") == ("FISHING",)


def test_daily_board_is_role_scoped_and_keeps_event_windows_distinct(tmp_path):
    path = tmp_path / "learning" / "task_completion_matrix.json"
    store = TaskCompletionStore(path)
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).isoformat()

    store.observe_role(role_id="A", role_key="ROLE_A", observed_at=stamp, goals=[
        {"goal_id": "MAIL_ROUTINE", "status": "READY", "available_skills": ["OPEN_MAIL"]},
        {"goal_id": "SCHEDULED_BEAR_HUNT", "status": "SCHEDULED_NOT_OPEN",
         "evidence": {"note": "opens at its live event window"}},
        {"goal_id": "USE_FREE_ARENA_ATTEMPTS", "status": "UNKNOWN",
         "evidence": {"blocker": "missing production observation: world.attempts",
                      "required_observation": "free arena attempts counter"}},
    ])
    store.observe_role(role_id="B", role_key="ROLE_B", observed_at=stamp, goals=[
        {"goal_id": "MAIL_ROUTINE", "status": "COMPLETE", "completion": 1.0},
    ])

    matrix = _load(path)
    role_a = matrix["roles"]["A"]["daily_board"]["tasks"]
    role_b = matrix["roles"]["B"]["daily_board"]["tasks"]
    assert role_a["MAIL"]["status"] == "READY"
    assert role_b["MAIL"]["status"] == "COMPLETE"
    # An available Skill is a route prerequisite, not a learned L1 action.
    assert _load(path)["roles"]["A"]["tasks"]["MAIL_ROUTINE"]["L1"]["proven"] is False
    assert role_a["BEAR"]["status"] == "WAITING"
    assert role_a["BEAR"]["reason_code"] == "EVENT_NOT_OPEN"
    assert role_a["ARENA"]["status"] == "BLOCKED"
    assert role_a["ARENA"]["reason_code"] == "CAPABILITY_GAP"
    assert matrix["ROLE_A_REMAINING_TODAY"]["role_id"] == "A"
    assert matrix["ROLE_B_REMAINING_TODAY"]["role_id"] == "B"


def test_episode_levels_distinguish_step_success_from_goal_completion(tmp_path):
    store = TaskCompletionStore(tmp_path / "matrix.json")
    store.record_episode({
        "execution_mode": "PRODUCTION", "role_id": "A", "episode_id": "e1", "step_id": 2,
        "goal_id": "KEEP_TRAINING_PRODUCTIVE", "attached_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "skill": "TRAIN_TROOPS", "action": {"kind": "TAP_SEMANTIC", "target": "BTN_START_TRAINING"},
        "executor_backend": "MAA", "result": "SUCCESS", "verifier_ok": True,
        "goal_progress_by_id": {"KEEP_TRAINING_PRODUCTIVE": True}, "completed_goal_ids": [],
        "recorded_at": "2026-09-29T10:00:00+08:00",
    })

    matrix = _load(tmp_path / "matrix.json")
    task = matrix["roles"]["A"]["tasks"]["KEEP_TRAINING_PRODUCTIVE"]
    assert task["L3"]["proven"] is True
    assert task["L4"]["proven"] is True
    assert task["L5"]["proven"] is False
    assert task["last_success"] is None
    assert task["last_step_success"]["scope"] == "STEP_VERIFIED"
    assert matrix["roles"]["A"]["daily_board"]["tasks"]["TRAINING"]["PRODUCTIVE_CYCLE_VERIFIED"] is True

    store.record_episode({
        "execution_mode": "PRODUCTION", "role_id": "A", "episode_id": "e2", "step_id": 3,
        "goal_id": "KEEP_TRAINING_PRODUCTIVE", "attached_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "skill": "TRAIN_TROOPS", "action": {"kind": "TAP_SEMANTIC", "target": "BTN_START_TRAINING"},
        "executor_backend": "MAA", "result": "SUCCESS", "verifier_ok": True,
        "goal_progress_by_id": {"KEEP_TRAINING_PRODUCTIVE": True},
        "completed_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "recorded_at": "2026-09-29T10:01:00+08:00",
    })
    # Retrying the materialized-view write for the same persisted Episode is idempotent.
    store.record_episode({
        "execution_mode": "PRODUCTION", "role_id": "A", "episode_id": "e2", "step_id": 3,
        "goal_id": "KEEP_TRAINING_PRODUCTIVE", "attached_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "skill": "TRAIN_TROOPS", "action": {"kind": "TAP_SEMANTIC", "target": "BTN_START_TRAINING"},
        "executor_backend": "MAA", "result": "SUCCESS", "verifier_ok": True,
        "goal_progress_by_id": {"KEEP_TRAINING_PRODUCTIVE": True},
        "completed_goal_ids": ["KEEP_TRAINING_PRODUCTIVE"],
        "recorded_at": "2026-09-29T10:01:00+08:00",
    })
    task = _load(tmp_path / "matrix.json")["roles"]["A"]["tasks"]["KEEP_TRAINING_PRODUCTIVE"]
    assert task["L5"]["proven"] is True
    assert task["L4"]["count"] == 2
    assert task["L5"]["count"] == 1
    assert task["last_success"]["episode_id"] == "e2"


def test_l1_matrix_uses_the_existing_verified_control_ledger(tmp_path):
    learning = tmp_path / "learning"
    learning.mkdir()
    (learning / "control_experience.json").write_text(json.dumps({
        "schema_version": "1.0",
        "controls": {
            "HOME|BTN_OPEN_MAIL": {
                "level": "L1", "expected_effect": "MAIL page opens",
                "observed_effect": "MAIL page opened", "last_result": "PAGE_CHANGED",
                "goal_help": {"MAIL_ROUTINE": "MAIL page opened"},
            },
            "HOME|BTN_UNUSED": {
                "level": "", "expected_effect": "MAIL page opens",
                "observed_effect": "MAIL page opened", "last_result": "PAGE_CHANGED",
                "goal_help": {"MAIL_ROUTINE": "not an L1 record"},
            },
        },
    }), encoding="utf-8")
    store = TaskCompletionStore(learning / "task_completion_matrix.json")
    store.observe_role(role_id="A", role_key="ROLE_A", observed_at="2026-09-29T10:00:00+08:00", goals=[
        {"goal_id": "MAIL_ROUTINE", "status": "READY", "available_skills": ["OPEN_MAIL"]},
    ])

    history = _load(learning / "task_completion_matrix.json")["roles"]["A"]["tasks"]["MAIL_ROUTINE"]
    assert history["L1"]["proven"] is True
    assert history["L1"]["evidence_refs"] == ["HOME|BTN_OPEN_MAIL"]


def test_nonproduction_episode_cannot_credit_role_or_completion(tmp_path):
    store = TaskCompletionStore(tmp_path / "matrix.json")
    store.record_episode({
        "execution_mode": "DEVELOPMENT_VALIDATION", "role_id": "A", "episode_id": "test",
        "goal_id": "MAIL_ROUTINE", "action": {"kind": "TAP"}, "result": "SUCCESS",
        "verifier_ok": True,
    })
    assert _load(tmp_path / "matrix.json")["roles"] == {}


def test_midnight_resets_daily_board_but_preserves_cumulative_task_evidence(tmp_path):
    store = TaskCompletionStore(tmp_path / "matrix.json")
    store.observe_role(role_id="A", role_key="ROLE_A", observed_at="2026-09-29T23:55:00+08:00", goals=[
        {"goal_id": "MAIL_ROUTINE", "status": "COMPLETE", "completion": 1.0},
    ])
    store.observe_role(role_id="A", role_key="ROLE_A", observed_at="2026-09-30T00:05:00+08:00", goals=[])

    matrix = _load(tmp_path / "matrix.json")
    role = matrix["roles"]["A"]
    assert role["daily_board"]["game_date"] == "2026-09-30"
    assert role["daily_board"]["tasks"]["MAIL"]["status"] == "NOT_DISCOVERED"
    assert role["tasks"]["MAIL_ROUTINE"]["DISCOVER"]["proven"] is True


def test_goal_types_cover_current_task_families_and_future_events():
    assert "TRAINING" in task_types_for_goal("LANCER_CAMP_TRAINING")
    assert "ALLIANCE_DONATION" in task_types_for_goal("ALLIANCE_DONATION")
    assert "ICEFIELD_BEAST" in task_types_for_goal("SCHEDULED_ICEFIELD_BEAST")
    assert "OTHER_CURRENT_EVENTS" in task_types_for_goal("SCHEDULED_CANYON_CLASH")


def test_ready_fishing_cast_does_not_inherit_reward_observation_blocker(tmp_path):
    store = TaskCompletionStore(tmp_path / "matrix.json")
    store.observe_role(role_id="A", goals=[
        {"goal_id": "USE_NORMAL_FISHING_BAIT", "status": "READY",
         "available_skills": ["PLAY_NORMAL_FISHING_LEVEL"]},
        {"goal_id": "CLAIM_FISHING_FREE_REWARD", "status": "UNKNOWN",
         "reason_code": "ENVIRONMENT_BLOCKED", "current_blocker": "reward not read"},
    ])
    row = _load(tmp_path / "matrix.json")["roles"]["A"]["daily_board"]["tasks"]["FISHING"]
    assert row["status"] == "READY"
    assert row["current_blocker"] is None
    assert row["reason_code"] is None
    assert len(row["goal_states"]) == 2
