from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "dataset/raw/live_resource_rotation_current_20260913.png"


def test_live_disconnected_session_is_not_unknown_popup() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    state = vision.observe(IMAGE)
    assert state.page is Page.POPUP
    assert state.popup == "SESSION_DISCONNECTED"
    assert vision.semantic.find(IMAGE, "BTN_RECONNECT_SESSION") is not None


def test_disconnected_session_routes_only_to_reconnect() -> None:
    state = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").observe(IMAGE)
    decision = RuleBrain(current_goal="GATHER_RESOURCE").decide(state, v2_registry())
    assert decision.skill == "RECONNECT_SESSION"
    assert v2_registry().get("RECONNECT_SESSION").action.target == "BTN_RECONNECT_SESSION"
