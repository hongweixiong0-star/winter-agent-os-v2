from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_panel_building_queue_opened


def token(text, box, confidence=0.99):
    x0, y0, x1, y1 = box
    return OCRToken(text, confidence, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def upgrade_sheet_tokens():
    # Positions replayed from the operator's 720x1280 production screenshot.
    return (
        token("升级", (581, 632, 641, 668)),
        token("1606.6万/100", (569, 671, 689, 698)),
        token("时间", (72, 767, 126, 796)),
        token("60秒", (223, 766, 285, 797)),
        token("属性", (73, 819, 127, 848)),
        token("17.5+0.5", (223, 820, 321, 847)),
    )


def test_unknown_template_frame_recognizes_building_upgrade_sheet_without_authorizing_spend():
    state = OCRPageClassifier().classify(
        OCRResult(upgrade_sheet_tokens(), "synthetic-production-replay"),
        frame_size=(720, 1280),
    )

    assert state.page is Page.BUILDING
    assert state.building["upgrade_dialog_visible"] is True
    assert state.building["identity"] == "UNKNOWN"
    assert "upgradeable" not in state.building


def test_generic_upgrade_word_and_cost_without_layout_stay_unknown():
    state = OCRPageClassifier().classify(
        OCRResult((token("升级", (581, 632, 641, 668)),
                  token("1606.6万/100", (569, 671, 689, 698))), "synthetic"),
        frame_size=(720, 1280),
    )
    assert state.page is Page.UNKNOWN


def test_building_row_navigation_can_verify_unknown_catalog_identity():
    before = WorldState(
        page=Page.HOME,
        building={"queue_available": True},
        quick_panel={"rows": [{"key": "BUILDING", "status": "IDLE",
                                "control": "ARROW", "arrow_basis": "ROW_BUTTON_SCAN"}]},
    )
    after = WorldState(
        page=Page.BUILDING,
        building={"id": "UNKNOWN", "upgrade_dialog_visible": True},
    )
    result = verify_panel_building_queue_opened(before, after)
    assert result.ok
    assert result.evidence["building_identity"] == "UNKNOWN"


def test_unidentified_detail_is_not_upgradeable():
    state = OCRPageClassifier().classify(
        OCRResult(upgrade_sheet_tokens(), "synthetic-production-replay"),
        frame_size=(720, 1280),
    )
    assert not state.building.get("upgradeable")


def test_building_goal_yields_instead_of_exploring_unknown_upgrade_sheet():
    state = OCRPageClassifier().classify(
        OCRResult(upgrade_sheet_tokens(), "synthetic-production-replay"),
        frame_size=(720, 1280),
    )
    decision = RuleBrain(current_goal="KEEP_BUILDING_PRODUCTIVE").decide(
        state, v2_registry()
    )
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == "building_identity_or_upgrade_conditions_unknown"
