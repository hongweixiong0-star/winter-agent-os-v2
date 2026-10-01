from datetime import datetime, timedelta, timezone
import json
import pytest

from winter_agent_v2 import learning_funnel as funnel
from winter_agent_v2 import unknown_learning as learning


def test_candidate_keeps_real_verifier_provenance_without_frame_geometry(tmp_path):
    ledger = learning.VerifiedStepLedger(tmp_path / "steps.jsonl")
    step = learning.record_verified_step(
        trace_id="first", parent_trace_id="session-a", frame_id="frame-1", frame_hash="sha256:abc",
        episode_id="episode-a", role_id="role-a", goal_id="MARKSMAN_CAMP_TRAINING",
        page_before="HOME", page_after="HOME", semantic_target="MARKSMAN_CAMP_BODY",
        relevant_state_signature="HOME|MARKSMAN_FOCUSED", model_used=True,
        grounding_basis="TEMPLATE_MATCH", verifier_ok=True,
        verifier_evidence={"camp": "MARKSMAN", "action_bar_open": True,
                           "measurement": {"bbox": [0.2, 0.3, 0.1, 0.2], "confidence": 0.99}},
        visual_evidence={"template": "camp_marksman.png", "target_point": [0.2, 0.4],
                         "candidate_bbox_norm": [0.1, 0.2, 0.3, 0.4]},
        ledger=ledger,
    )
    row = ledger.rows()[0]
    assert row["trace_id"] == "first"
    assert row["parent_trace_id"] == "session-a"
    assert row["frame_id"] == "frame-1"
    assert row["verifier_evidence"] == {
        "camp": "MARKSMAN", "action_bar_open": True, "measurement": {"confidence": 0.99},
    }
    assert row["visual_evidence"] == {"template": "camp_marksman.png"}
    assert row["unknown_identity"] == "MARKSMAN_CAMP_TRAINING|HOME|MARKSMAN_CAMP_BODY|HOME|MARKSMAN_FOCUSED"
    assert step.as_row()["model_used"] is True


def test_reuse_requires_target_and_current_relevant_state_when_requested(tmp_path):
    ledger = learning.VerifiedStepLedger(tmp_path / "steps.jsonl")
    for role, state in (("role-a", "FOCUSED"), ("role-b", "UNFOCUSED")):
        learning.record_verified_step(
            role_id=role, goal_id="TRAIN", page_before="HOME", page_after="TRAINING",
            semantic_target="MARKSMAN", relevant_state_signature=state, verifier_ok=True,
            ledger=ledger,
        )
    matches = learning.learned_steps_for(
        ledger.rows(), page_key="HOME", goal_id="TRAIN", semantic_target="MARKSMAN",
        relevant_state_signature="FOCUSED",
    )
    assert len(matches) == 1
    assert matches[0]["role_id"] == "role-a"
    assert learning.learned_steps_for(ledger.rows(), page_key="HOME", goal_id="TRAIN",
                                     semantic_target="SHIELD", relevant_state_signature="FOCUSED") == []
    # Generic semantic knowledge may cross roles; its live preconditions must still match.
    assert matches[0]["unknown_identity"] != ledger.rows()[1]["unknown_identity"]


def test_explicit_unknown_identity_is_provenance_not_the_learned_semantic_key(tmp_path):
    ledger = learning.VerifiedStepLedger(tmp_path / "steps.jsonl")
    step = learning.record_verified_step(
        goal_id="TRAIN", page_before="HOME", page_after="TRAINING",
        semantic_target="ORDINARY_CONTROL[训练]", relevant_state_signature="MARKSMAN_FOCUSED",
        unknown_identity="TRAIN|HOME|MARKSMAN_CAMP_ENTRY|MARKSMAN_FOCUSED",
        verifier_ok=True, ledger=ledger,
    )
    row = ledger.rows()[0]
    assert row["unknown_identity"] == "TRAIN|HOME|MARKSMAN_CAMP_ENTRY|MARKSMAN_FOCUSED"
    assert row["semantic_target"] == "ORDINARY_CONTROL[训练]"
    assert step.key.startswith("HOME|TRAIN|ORDINARY_CONTROL[训练]|TRAINING")
    assert learning.learned_steps_for([row], page_key="HOME", goal_id="TRAIN",
                                     semantic_target="MARKSMAN_CAMP_ENTRY") == []


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _event(now, stage, *, trace="first", call="", **extra):
    return {
        "recorded_at": now.isoformat(), "layer": stage, "trace_id": trace,
        "role_id": "role-a", "goal_id": "MARKSMAN_CAMP_TRAINING", "page": "HOME",
        "unknown_identity": "marksman-entrance", "frame_id": "fresh-1", "call_id": call,
        **extra,
    }


def test_joined_funnel_uses_one_window_and_deduplicates_the_same_stage(tmp_path):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=3)
    future = now + timedelta(days=1)
    rows = [
        _event(now, "UNKNOWN_OBSERVED"),
        _event(now, "VENUS_CALLED", call="call-1", model_used=True),
        _event(now, "VENUS_PROPOSED", call="call-1"),
        _event(now, "GROUNDING_VALID", call="call-1"),
        _event(now, "RISK_GATE_ALLOWED", call="call-1"),
        _event(now, "MAA_EXECUTED", call="call-1"),
        _event(now, "VERIFIER_SUCCESS", call="call-1"),
        _event(now, "CANDIDATE_STEP_CREATED", call="call-1"),
        _event(now, "SECOND_ENCOUNTER", trace="second", parent_trace_id="first"),
        _event(now, "CANDIDATE_STEP_REUSED", trace="second", parent_trace_id="first", model_used=False),
        _event(now, "SECOND_VERIFIER_SUCCESS", trace="second", parent_trace_id="first", model_used=False),
        _event(old, "VENUS_CALLED", trace="old", call="old-call"),
        _event(future, "VENUS_CALLED", trace="future", call="future-call"),
    ]
    rows.append(dict(rows[1]))
    _write(tmp_path / funnel.ONLINE_LEDGER, rows)
    _write(tmp_path / funnel.PLANNER_LEDGER, [
        {"recorded_at": now.isoformat(), "source": "LOCAL_GUI_MODEL", "page_key": "HOME",
         "goal": "OLD_PROBE", "decision": "EXECUTE"},
    ])
    report = funnel.build_funnel(root=tmp_path, now=now)
    assert report.joined_funnel["unknown_observed"] == 1
    assert report.joined_funnel["venus_called"] == 1
    assert report.joined_funnel["second_verifier_success"] == 1
    assert report.metrics["VENUS_CALLS_PER_UNKNOWN"] == 1
    assert report.metrics["CANDIDATE_REUSE_SUCCESS"] == 1
    assert report.metrics["FUNNEL_MEASUREMENT_SCOPE"] == "JOINED_TIMESTAMP_WINDOW"
    assert report.historical_unattributed["not_production_acceptance"] is True
    assert len(report.joined_traces) == 2
    assert next(t for t in report.joined_traces if t["trace_id"] == "second")["model_used"] is False


def test_legacy_counts_cannot_claim_a_joined_real_learning_loop(tmp_path):
    now = datetime.now(timezone.utc)
    _write(tmp_path / funnel.PLANNER_LEDGER, [
        {"recorded_at": now.isoformat(), "source": "LOCAL_GUI_MODEL", "page_key": "HOME",
         "goal": "TRAIN", "decision": "EXECUTE"},
        {"source": "LOCAL_GUI_MODEL", "request_id": "old", "record": "outcome", "verifier_ok": True},
    ])
    report = funnel.build_funnel(root=tmp_path, now=now)
    assert report.joined_funnel["venus_called"] == 0
    assert report.joined_funnel["verifier_success"] == 0
    assert report.metrics["VENUS_CALLS_PER_UNKNOWN"] is None
    assert report.metrics["FUNNEL_MEASUREMENT_SCOPE"] == "HISTORICAL_UNATTRIBUTED_ONLY"
    assert all(s.source.startswith("HISTORICAL_UNATTRIBUTED:") for s in report.funnel)


def test_same_legacy_request_id_cannot_join_results_across_roles(tmp_path):
    now = datetime.now(timezone.utc)
    _write(tmp_path / funnel.ONLINE_LEDGER, [
        _event(now, "UNKNOWN_OBSERVED"),
        _event(now, "VERIFIER_SUCCESS", role_id="role-b"),
    ])
    report = funnel.build_funnel(root=tmp_path, now=now)
    assert report.joined_funnel["verifier_success"] == 0
    assert report.metrics["JOINED_UNATTRIBUTED_WINDOW_ROWS"] == 1


@pytest.mark.parametrize("second_model_used", [False, True])
def test_first_second_closure_requires_a_new_model_free_verified_execution(tmp_path, second_model_used):
    now = datetime.now(timezone.utc)
    first_stages = ("UNKNOWN_OBSERVED", "VENUS_CALLED", "VENUS_PROPOSED", "GROUNDING_VALID",
                    "RISK_GATE_ALLOWED", "MAA_EXECUTED", "VERIFIER_SUCCESS", "CANDIDATE_STEP_CREATED")
    rows = [_event(now, stage, call="first-call", model_used=True) for stage in first_stages]
    second_stages = ("SECOND_ENCOUNTER", "CANDIDATE_STEP_REUSED", "MAA_EXECUTED", "SECOND_VERIFIER_SUCCESS")
    rows += [_event(now, stage, trace="second", call="second-action", parent_trace_id="first",
                    model_used=second_model_used) for stage in second_stages]
    _write(tmp_path / funnel.ONLINE_LEDGER, rows)
    _write(tmp_path / learning.LEARNED_STEPS_PATH, [
        {**_event(now, "", trace="first"), "step_index": 3, "semantic_target": "MARKSMAN",
         "verifier_ok": True, "model_used": True},
        {**_event(now, "", trace="second", parent_trace_id="first"), "step_index": 4,
         "semantic_target": "MARKSMAN", "verifier_ok": True, "model_used": second_model_used,
         "reused_from_trace_id": "first"},
    ])
    report = funnel.build_funnel(root=tmp_path, now=now)
    # Stage event and durable step record represent one creation/reuse, regardless of row keys.
    assert report.joined_funnel["candidate_step_created"] == 2
    assert report.joined_funnel["candidate_step_reused"] == 1
    assert report.joined_funnel["second_verifier_success"] == 1
    assert report.metrics["FIRST_SECOND_CLOSURES"] == (0 if second_model_used else 1)


def test_runtime_and_planner_failed_settlement_count_one_real_verifier_failure(tmp_path):
    now = datetime.now(timezone.utc)
    rows = [
        _event(now, "UNKNOWN_OBSERVED"),
        _event(now, "VERIFIER_FAILED", call="call-1"),
        _event(now, "VERIFIER_FAILED", call="call-1", record="outcome", verifier_ok=False),
    ]
    _write(tmp_path / funnel.ONLINE_LEDGER, rows)
    report = funnel.build_funnel(root=tmp_path, now=now)
    assert report.metrics["VERIFIER_FAILURES"] == 1
    assert report.joined_funnel["verifier_success"] == 0
