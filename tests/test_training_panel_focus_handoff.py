from pathlib import Path
from unittest.mock import patch

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry


def _brain_for(camp: str) -> RuleBrain:
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = f"{camp}_CAMP_TRAINING"
    return brain


def test_panel_focused_camp_selects_the_same_camps_body_tap():
    for camp in ("SHIELD", "LANCER", "MARKSMAN"):
        world = WorldState(
            page=Page.HOME,
            training={
                "navigation": "PANEL_CAMP_FOCUSED",
                "camp_focus_tap_norm": [0.50, 0.48],
                "camp_focus_source": "CURRENT_FRAME_SELECTION_HALO",
                "queue_available": True,
            },
        )
        decision = _brain_for(camp).decide(world, v2_registry())
        assert decision.skill == f"TAP_FOCUSED_TRAINING_CAMP_{camp}"
        assert decision.expected_result == "camp_action_bar_open"


def test_focused_body_target_is_remeasured_from_the_current_frame():
    runtime = LiveRuntime.__new__(LiveRuntime)
    world = WorldState(
        page=Page.HOME,
        training={
            "navigation": "PANEL_CAMP_FOCUSED",
            "camp_focus_tap_norm": [0.42, 0.41],
            "camp_focus_source": "CURRENT_FRAME_SELECTION_HALO",
        },
    )
    frame = Path("current-focus-frame.png")
    with patch(
        "winter_agent_v2.camp_ring.focused_camp_body_tap_norm",
        return_value=(0.51, 0.48),
    ) as locate:
        point = runtime._resolve_semantic_target(
            "TRAINING_CAMP_BODY_FROM_FOCUS", world, frame_path=frame
        )
    assert point == (0.51, 0.48)
    locate.assert_called_once_with(frame)


def test_focused_body_target_refuses_stale_or_wrong_page_state():
    runtime = LiveRuntime.__new__(LiveRuntime)
    world = WorldState(
        page=Page.MAP,
        training={
            "navigation": "PANEL_CAMP_FOCUSED",
            "camp_focus_tap_norm": [0.50, 0.48],
            "camp_focus_source": "CURRENT_FRAME_SELECTION_HALO",
        },
    )
    with patch("winter_agent_v2.camp_ring.focused_camp_body_tap_norm") as locate:
        point = runtime._resolve_semantic_target(
            "TRAINING_CAMP_BODY_FROM_FOCUS", world, frame_path=Path("map.png")
        )
    assert point is None
    locate.assert_not_called()


def test_focused_camp_actions_have_named_production_verifiers():
    for camp in ("SHIELD", "LANCER", "MARKSMAN"):
        skill = f"TAP_FOCUSED_TRAINING_CAMP_{camp}"
        assert skill in LiveRuntime.VERIFIED_ATOMIC
        before = WorldState(
            page=Page.HOME,
            training={
                "navigation": "PANEL_CAMP_FOCUSED",
                "camp_focus_tap_norm": [0.50, 0.48],
            },
        )
        after = WorldState(
            page=Page.HOME,
            training={
                "camp": f"{camp}_CAMP",
                "menu_open": True,
                "train_tap_norm": [0.60, 0.50],
            },
        )
        assert LiveRuntime.VERIFIED_ATOMIC[skill](before, after).ok
