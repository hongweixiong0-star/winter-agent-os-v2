from pathlib import Path
from PIL import Image, ImageDraw
from unittest.mock import patch

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.camp_ring import focused_camp_body_tap_norm
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


def test_focus_halo_is_not_merged_into_tutorial_hand(tmp_path):
    """A real production frame showed 5x5 closing merged both warm UI shapes.

    Keep a small synthetic regression fixture so the detector continues to reject the
    narrow tutorial hand while locating the separate focus halo.
    """
    frame = Image.new("RGB", (720, 1280), (125, 135, 145))
    draw = ImageDraw.Draw(frame)
    gold = (255, 205, 65)
    draw.ellipse((316, 545, 404, 623), outline=gold, width=4)
    # This tutorial-hand silhouette is close enough for a 5x5 close to join it to
    # the halo, but remains a separate component under the production 3x3 close.
    draw.polygon(
        [(358, 512), (412, 512), (412, 576), (407, 576), (407, 536), (358, 530)],
        fill=gold,
    )
    path = tmp_path / "focus_halo_with_tutorial_hand.png"
    frame.save(path)

    point = focused_camp_body_tap_norm(path)

    assert point is not None
    assert abs(point[0] - 0.501) < 0.02
    assert abs(point[1] - 0.457) < 0.02
