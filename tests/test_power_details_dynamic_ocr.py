from pathlib import Path

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import HybridVision
from winter_agent_v2.runtime import LiveRuntime
from tests.archived_frames import archived, require
from tests.live_stack import production_vision


ROOT = Path(__file__).resolve().parents[1]
#: A lookup, not a claim: measured 2026-10-16, the capture TTL pruned this episode before
#: anyone copied it to a protected tree, so the two tests skip -- naming what is gone --
#: instead of returning green on a frame nobody read.
LIVE_DETAILS = archived("*_step_005_after_refresh_2_20260924T164034575653.png")


def test_current_account_power_details_are_recognized_and_rows_are_read_from_this_frame():
    require(("the power-details frame", LIVE_DETAILS))
    production = production_vision()
    if production is None:
        return

    class UnknownTemplateVision:
        def observe(self, _path):
            return WorldState()

    vision = HybridVision(UnknownTemplateVision(), production.ocr)

    frame = vision.observe(LIVE_DETAILS)
    assert frame.page is Page.POPUP
    assert frame.popup == "POWER_DETAILS"

    runtime = object.__new__(LiveRuntime)
    runtime.vision = vision
    runtime.semantic_vision = None
    troop = runtime._resolve_semantic_target(
        "BTN_POWER_TROOP_IMPROVE", frame, frame_path=LIVE_DETAILS
    )
    research = runtime._resolve_semantic_target(
        "BTN_POWER_RESEARCH_IMPROVE", frame, frame_path=LIVE_DETAILS
    )

    assert troop is not None
    assert research is not None
    assert troop[0] > 0.65 and research[0] > 0.65
    assert troop != research
    # The live account currently draws six categories. These y positions are read
    # from the screenshot at execution time, not from a fixed seven-row crop.
    assert 0.40 < troop[1] < 0.50
    assert 0.65 < research[1] < 0.75


def test_power_category_action_refuses_a_wrong_page_even_with_the_live_frame():
    require(("the power-details frame", LIVE_DETAILS))
    production = production_vision()
    if production is None:
        return
    vision = production
    runtime = object.__new__(LiveRuntime)
    runtime.vision = vision
    runtime.semantic_vision = None
    wrong_page = WorldState(page=Page.HOME, confidence=0.99)
    assert runtime._resolve_semantic_target(
        "BTN_POWER_TROOP_IMPROVE", wrong_page, frame_path=LIVE_DETAILS
    ) is None
