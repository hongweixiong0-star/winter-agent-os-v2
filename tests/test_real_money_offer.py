from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_popup_closed
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]
# 证据固化在受保护目录 dataset/truth_audit 下，不会被 retention.auto_prune 剪除。
# 历史路径 dataset/raw/control_panel/runtime_auto/20260913_071323_375697/
# step_003_after_refresh_2.png 已被剪除，改用同场景的 live 帧副本。
IMAGE = ROOT / "dataset/truth_audit/hard_block_evidence/real_money_offer__live_offer_dismiss_20260913__step_001_before.png"


def test_live_real_money_offer_is_hard_block_state() -> None:
    state = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").observe(IMAGE)
    assert state.page is Page.POPUP
    assert state.popup == "REAL_MONEY_OFFER"
    assert state.rewards["real_money_cost"] is True
    assert state.rewards["action"] == "BLOCKED"


def test_real_money_offer_only_routes_to_safe_dismiss() -> None:
    state = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").observe(IMAGE)
    decision = RuleBrain(current_goal="GATHER_RESOURCE").decide(state, v2_registry())
    assert decision.skill == "DISMISS_REAL_MONEY_OFFER"
    assert v2_registry().get(decision.skill).action.kind == "PRESS_BACK"


def test_decimal_real_money_price_is_skin_independent_hard_block() -> None:
    result = OCRResult((OCRToken("��30.00", 0.963), OCRToken("2500", 0.97)), "fake")
    state = OCRPageClassifier().classify(result)
    assert state.page is Page.POPUP
    assert state.popup == "REAL_MONEY_OFFER"


def test_unknown_after_popup_is_not_verified_closed() -> None:
    before = WorldState(page=Page.POPUP, popup="REAL_MONEY_OFFER", confidence=0.99)
    assert not verify_popup_closed(before, WorldState()).ok
