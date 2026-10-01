from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry


def _board(**values):
    return WorldState(page=Page.INTEL, confidence=0.99, intel={
        "status": "AVAILABLE", "pins": 1, "available_count": 1,
        "list_read": True, "untried_pins": 0, **values,
    })


def _brain():
    brain = RuleBrain(current_goal="INTEL")
    brain.goal_id = "CLEAR_INTEL"
    return brain


def test_exhausted_intel_leaves_once_then_yields_instead_of_reopening():
    brain = _brain()
    registry = v2_registry()

    first = brain.decide(_board(), registry)
    after_back = brain.decide(WorldState(page=Page.MAP, confidence=0.99), registry)

    assert first.skill == "BACK"
    assert after_back.skill == "SAFE_STOP"
    assert after_back.reason == "intel_no_untried_pins"
    assert after_back.expected_result == "switch_task"


def test_unsuccessful_back_cannot_repeat_on_the_same_exhausted_board():
    brain = _brain()
    registry = v2_registry()

    assert brain.decide(_board(), registry).skill == "BACK"
    decision = brain.decide(_board(), registry)

    assert decision.skill == "SAFE_STOP"
    assert decision.reason == "intel_no_untried_pins"


def test_local_intel_exhaustion_does_not_block_another_goal():
    brain = _brain()
    registry = v2_registry()
    brain.decide(_board(), registry)
    brain.current_goal = "MAIL"
    brain.goal_id = "MAIL_ROUTINE"

    decision = brain.decide(WorldState(page=Page.MAP, confidence=0.99), registry)

    assert decision.skill == "OPEN_HOME"
    assert decision.reason == "mail_goal_requires_home"


def test_fresh_untried_pin_reopens_the_route_after_local_exhaustion():
    brain = _brain()
    registry = v2_registry()
    brain.decide(_board(), registry)

    assert brain.decide(_board(untried_pins=1), registry).skill == "SELECT_INTEL_PIN"
    assert brain.decide(WorldState(page=Page.MAP, confidence=0.99), registry).skill == "OPEN_INTEL"


def test_new_run_may_observe_the_board_again():
    registry = v2_registry()
    exhausted = _brain()
    exhausted.decide(_board(), registry)

    assert _brain().decide(WorldState(page=Page.MAP, confidence=0.99), registry).skill == "OPEN_INTEL"


def test_newly_claimable_rewards_still_execute_after_exhaustion():
    brain = _brain()
    registry = v2_registry()
    brain.decide(_board(), registry)

    decision = brain.decide(_board(status="CLAIMABLE", claimable_count=1), registry)

    assert decision.skill == "INTEL_CLAIM_REWARDS"


def test_opened_known_mission_is_not_suppressed_by_exhaustion():
    brain = _brain()
    registry = v2_registry()
    brain.decide(_board(), registry)

    decision = brain.decide(_board(mission_type="BEAST"), registry)

    assert decision.skill == "SELECT_INTEL_BEAST_MISSION"
