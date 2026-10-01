from pathlib import Path

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


def runtime_entry():
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._committed_goal = "USE_FREE_ARENA_ATTEMPTS"
    runtime._calendar_role_id = lambda: "role-A"
    runtime._bootstrap_context = {
        "bootstrap_stage": "FIND_ENTRY",
        "bootstrap_goal_id": runtime._committed_goal,
        "bootstrap_role_id": "role-A",
        "bootstrap_entry_label": "竞技场",
        "bootstrap_semantic_target": "ARENA_ENTRY",
    }
    return runtime


def test_safe_discovery_calls_existing_advisor_without_entering_ordinary_claim_scan():
    runtime = runtime_entry()
    runtime._ordinary_last = {"word": "领取"}
    runtime._advised_learn_context = {"goal": "OTHER_GOAL"}
    calls = []

    def advise(*args, **kwargs):
        calls.append((runtime._unknown_semantic_target, runtime._unknown_skill_id))
        assert runtime._ordinary_last == {}
        assert runtime._advised_learn_context == {}
        return (0.2, 0.3)

    runtime._advised_control = advise
    runtime._ocr_service = lambda: (_ for _ in ()).throw(AssertionError("ordinary claim scan must not run"))
    assert runtime._ordinary_control_candidate(WorldState(page=Page.HOME), Path("current.png")) == (0.2, 0.3)
    assert calls == [("ARENA_ENTRY", "TRY_ORDINARY_CONTROL")]
    assert runtime._unknown_semantic_target == ""


def test_role_switch_invalidates_pending_safe_discovery_before_model_or_input():
    runtime = runtime_entry()
    runtime._calendar_role_id = lambda: "role-B"
    runtime._advised_control = lambda *a, **k: (_ for _ in ()).throw(AssertionError("stale role must not plan"))
    assert runtime._ordinary_control_candidate(WorldState(page=Page.HOME), Path("current.png")) is None


def test_safe_discovery_cannot_satisfy_unrelated_goal_with_same_page():
    runtime = runtime_entry()
    runtime._committed_goal = "KEEP_TRAINING_PRODUCTIVE"
    runtime._advised_control = lambda *a, **k: (_ for _ in ()).throw(AssertionError("stale goal must not plan"))
    assert runtime._ordinary_control_candidate(WorldState(page=Page.HOME), Path("current.png")) is None
