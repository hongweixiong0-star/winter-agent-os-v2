from pathlib import Path

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import HybridVision
from winter_agent_v2.runtime import LiveRuntime
from tests.live_stack import production_vision


ROOT = Path(__file__).resolve().parents[1]
LIVE_DETAILS = ROOT / "dataset/raw/control_panel/runtime_auto/20260925_003829_467215/20260925_003829_467215_step_005_after_refresh_2_20260924T164034575653.png"


def test_current_account_power_details_are_recognized_and_rows_are_read_from_this_frame():
    if not LIVE_DETAILS.exists():
        return
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
    if not LIVE_DETAILS.exists():
        return
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
