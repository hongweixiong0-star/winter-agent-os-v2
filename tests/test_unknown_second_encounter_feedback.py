from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from winter_agent_v2 import unknown_learning as learning
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


@pytest.mark.parametrize("verified", [True, False])
def test_reuse_without_model_records_only_its_own_verified_second_encounter(tmp_path, monkeypatch, verified):
    ledger = learning.VerifiedStepLedger(tmp_path / "steps.jsonl")
    learning.record_verified_step(
        request_id="first-request", session_id="first-session", goal_id="DAILY",
        page_before="UNKNOWN::奖励", page_after="HOME", semantic_target="ORDINARY_CONTROL[关闭]",
        verifier_ok=True, expected_result="home_open", ledger=ledger,
    )
    runtime = object.__new__(LiveRuntime)
    runtime.learned_ledger = ledger
    runtime._candidate_skill_dir = tmp_path / "candidates"
    runtime.capture_dir = tmp_path / "second-session"
    runtime.role_id = "role-b"
    runtime._ordinary_tried = set()
    runtime._ordinary_attempts = 0
    runtime._ocr_service = Mock(return_value=object())
    runtime._l1_state = Mock(return_value="fresh")
    runtime._note_printed = Mock()
    runtime._advisor = Mock()
    runtime.brain = SimpleNamespace(goal_id="DAILY")
    runtime._committed_goal = "DAILY"
    monkeypatch.setattr("winter_agent_v2.runtime.find_printed_words", lambda *_: {
        "center_norm": (0.91, 0.12), "confidence": 0.99,
        "box_norm": {"x_norm": 0.9, "y_norm": 0.1, "w_norm": 0.02, "h_norm": 0.04},
    })
    frame = tmp_path / "fresh.png"
    point = runtime._advised_control("UNKNOWN", "奖励", frame, WorldState(page=Page.UNKNOWN), True)
    assert point == (0.91, 0.12)
    runtime._advisor.take_request.assert_not_called()
    runtime._note_learned_step(
        decision=SimpleNamespace(skill="PRINTED_TAP"),
        verification=SimpleNamespace(ok=verified, reason="OK" if verified else "NO_CHANGE"),
        result="SUCCESS" if verified else "FAILURE", observed_change="PAGE_CHANGED" if verified else "NONE",
        after=WorldState(page=Page.HOME), step_id=1,
    )
    rows = ledger.rows()
    assert len(rows) == (2 if verified else 1)
    assert runtime._advised_learn_context == {}
    candidates = list(runtime._candidate_skill_dir.glob("*.json"))
    assert len(candidates) == (1 if verified else 0)
    if verified:
        assert rows[-1]["session_id"] == "second-session"
        assert rows[-1]["role_id"] == "role-b"
        assert rows[-1]["visual_evidence"]["reader"] == "LEARNED_VERIFIED_STEP"


def test_unscoped_historical_step_is_not_a_wildcard_for_current_goal():
    row = {"page_before": "HOME", "goal_id": "", "verifier_ok": True,
           "semantic_target": "ORDINARY_CONTROL[领取]"}
    assert learning.learned_steps_for([row], page_key="HOME", goal_id="DAILY") == []
    assert learning.learned_steps_for([dict(row, goal_id="DAILY")], page_key="HOME", goal_id="") == []
