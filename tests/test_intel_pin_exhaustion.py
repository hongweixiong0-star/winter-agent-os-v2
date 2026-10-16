"""0ba: attempted pins are a bounded deferral, not a vision failure."""
from pathlib import Path
from unittest.mock import patch

from tests.test_live_runtime import FakeDevice, FakeSemantic, FakeVision
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.intel_pins import IntelPin
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry


def board(**extra):
    return WorldState(page=Page.INTEL, confidence=0.99, intel={
        "status": "AVAILABLE", "pins": 1, "available_count": 1,
        "list_read": True, **extra,
    })


def test_exhaustion_is_not_goal_completion():
    state = board(untried_pins=0)
    brain = RuleBrain(current_goal="INTEL")
    # Exhaustion applies to the board, not to the AUTO cycle: the first sight leaves by
    # the already measured INTEL -> MAP Back (``intel_board_exhausted_return_to_map``)
    # so the same run can still discover ordinary map work, and only a *repeat* sight
    # stops with ``intel_no_untried_pins``.  Neither is a completion: the goal must not
    # be marked COMPLETE off an exhausted board.
    first = brain.decide(state, v2_registry())
    assert first.skill == "BACK"
    assert first.reason == "intel_board_exhausted_return_to_map"
    second = brain.decide(state, v2_registry())
    assert second.skill == "SAFE_STOP"
    assert second.reason == "intel_no_untried_pins"
    goals = {g.goal_id: g for g in GoalLibrary().discover(state)}
    assert goals["CLEAR_INTEL"].status.value != "COMPLETE"


def test_unknown_attempt_state_still_allows_a_pin():
    assert RuleBrain(current_goal="INTEL").decide(board(), v2_registry()).skill == "SELECT_INTEL_PIN"


def test_known_card_is_not_shadowed():
    state = board(untried_pins=0, mission_type="BEAST")
    assert RuleBrain(current_goal="INTEL").decide(state, v2_registry()).skill == "SELECT_INTEL_BEAST_MISSION"


def test_due_free_gift_still_has_priority():
    brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
    assert brain.decide(board(untried_pins=0), v2_registry()).skill == "BACK"


def test_due_gift_navigation_executes_through_the_scheduler(tmp_path):
    device = FakeDevice()
    runtime = LiveRuntime(
        device=device, vision=FakeVision([board(), WorldState(page=Page.MAP, confidence=0.99)]),
        semantic_vision=FakeSemantic(), capture_dir=tmp_path,
        brain=RuleBrain(current_goal="INTEL", claim_free_stamina=True),
        sleeper=lambda _: None,
    )
    with patch("winter_agent_v2.runtime.intel_pin_centers", return_value=[IntelPin(200, 600, "ORANGE", 900)]):
        result = runtime.run(max_actions=1)
    assert result.steps[0].decision.skill == "BACK"
    assert result.steps[0].verification.ok
    assert len(device.backs) == 1


def test_runtime_opens_once_then_defers_without_failed_execution(tmp_path):
    device = FakeDevice()
    opened = WorldState(page=Page.POPUP, popup="INTEL_MASTER_BOUNTY", confidence=0.99)
    runtime = LiveRuntime(
        device=device,
        vision=FakeVision([board(), opened, board(),
                           WorldState(page=Page.MAP, confidence=0.99), board()]),
        semantic_vision=FakeSemantic(), capture_dir=tmp_path,
        brain=RuleBrain(current_goal="INTEL"), sleeper=lambda _: None,
    )
    with patch("winter_agent_v2.runtime.intel_pin_centers", return_value=[IntelPin(200, 600, "ORANGE", 900)]) as detect:
        result = runtime.run(max_actions=3)
    assert result.stop_reason == "intel_no_untried_pins"
    assert len(device.taps) == 1
    assert result.steps[0].verification.ok
    # The first sight of the exhausted board leaves it by the measured INTEL -> MAP Back
    # (bounded to once per run by the brain's own flag), and only the repeat sight
    # defers -- with no execution at all, which is the "no failed execution" this test
    # exists for.  Two scans per bare-intel decision frame (the planning copy and the
    # goal-accounting stamp, both over the same path) and none for popup or map: three
    # board frames, six scans.
    assert result.steps[1].decision.reason == "intel_board_exhausted_return_to_map"
    assert result.steps[1].verification.ok
    assert len(device.backs) == 1
    assert result.steps[2].execution is None
    assert result.steps[2].before.intel["untried_pins"] == 0
    assert detect.call_count == 6


def test_existing_40px_boundary_and_new_pin(tmp_path):
    device = FakeDevice()
    runtime = LiveRuntime(
        device=device,
        vision=FakeVision([board(), WorldState(page=Page.POPUP, popup="INTEL_MASTER_BOUNTY", confidence=0.99)]),
        semantic_vision=FakeSemantic(), capture_dir=tmp_path,
        brain=RuleBrain(current_goal="INTEL"), sleeper=lambda _: None,
    )
    runtime._tapped_intel_pins = [(200, 600)]
    pins = [IntelPin(240, 600, "ORANGE", 900), IntelPin(241, 600, "BLUE", 900)]
    with patch("winter_agent_v2.runtime.intel_pin_centers", return_value=pins):
        result = runtime.run(max_actions=1)
    assert result.steps[0].before.intel["untried_pins"] == 1
    assert result.steps[0].verification.ok
    assert runtime._tapped_intel_pins[-1] == (241, 600)


def test_real_retained_board_exhaustion(tmp_path):
    from winter_agent_v2.intel_pins import intel_pin_centers
    frame = Path(__file__).resolve().parents[1] / "dataset/truth_audit/intel_pin_board_20260915/01_intel_board_5_pins_live.png"
    pins = intel_pin_centers(frame)
    assert len(pins) >= 5

    class RetainedFrameDevice(FakeDevice):
        def screenshot(self, path):
            path.write_bytes(frame.read_bytes())
            return path

    device = RetainedFrameDevice()
    runtime = LiveRuntime(
        device=device,
        vision=FakeVision([board(pins=len(pins)),
                           WorldState(page=Page.MAP, confidence=0.99),
                           board(pins=len(pins))]),
        semantic_vision=FakeSemantic(), capture_dir=tmp_path,
        brain=RuleBrain(current_goal="INTEL"), sleeper=lambda _: None,
    )
    runtime._tapped_intel_pins = [(p.x, p.y) for p in pins]
    result = runtime.run(max_actions=2)
    assert result.stop_reason == "intel_no_untried_pins"
    assert not device.taps
    # The exhausted board costs the measured Back off the page, never a tap: the run
    # leaves first (so map work stays reachable), and only the repeat sight stops.
    assert result.steps[0].decision.reason == "intel_board_exhausted_return_to_map"
    assert result.steps[0].verification.ok
    assert result.steps[1].execution is None
