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


def test_tutorial_overlay_may_hide_cost_without_hiding_building_sheet_identity():
    # Replayed from AUTO step 1, where the tutorial hand obscured the cost label. The
    # two-column duration/attribute layout still proves the detail sheet was reached.
    tokens = tuple(item for item in upgrade_sheet_tokens()
                   if not item.text.startswith("1606.6万"))
    state = OCRPageClassifier().classify(
        OCRResult(tokens, "production-tutorial-overlay-replay"),
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


# The second layout the same page is drawn in.  The Research Institute always used these
# headers; measured 2026-10-05, an ordinary selected building (城墙) is drawn with them too.
# Every one of the 107 recorded OPEN_BUILDING_UPGRADE failures carried this layout while the
# classifier, which only knew the two-column one above, called the page UNKNOWN -- so the tap
# was correct and the reading of the frame it produced was not.
def header_sheet_tokens():
    # Positions replayed from the 720x1280 production after-frame
    # 20261005_130747_314531_step_003_after_refresh_2_20261005T050825668096.png, whose episode
    # recorded BUILDING_UPGRADE_PANEL_NOT_PROVEN with page_after=UNKNOWN.
    return (
        token("城墙", (323, 180, 397, 222)),
        token("升级效果", (304, 263, 418, 298)),
        token("城墙耐久度", (70, 323, 208, 356)),
        token("需要条件", (304, 537, 419, 574)),
        token("大熔炉等级24", (126, 597, 319, 629)),
        token("3.20亿/1410万", (125, 666, 303, 696)),
        token("3.54亿/1410万", (124, 733, 304, 765)),
        token("6714.63万/282万", (127, 803, 340, 829)),
        token("2781.44万/70.5万", (127, 870, 347, 897)),
        token("立即完成", (147, 1008, 253, 1043)),
        token("升级", (491, 1007, 552, 1044)),
    )


def test_header_layout_sheet_of_an_unlisted_building_is_recognised():
    state = OCRPageClassifier().classify(
        OCRResult(header_sheet_tokens(), "production-replay-header-layout"),
        frame_size=(720, 1280),
    )

    assert state.page is Page.BUILDING
    assert state.building["upgrade_dialog_visible"] is True
    # 城墙 is not in building_identity.BUILDING_IDS, and this must stay UNKNOWN rather than
    # become a guess: the layout says which page this is, never which building.
    assert state.building["identity"] == "UNKNOWN"
    assert "upgradeable" not in state.building


def test_the_header_layout_alone_does_not_claim_the_research_lab_identity():
    tokens = header_sheet_tokens()
    assert not OCRPageClassifier._research_lab_upgrade_sheet_evidence(
        tokens, frame_size=(720, 1280)
    ), "城墙 must not be read as the lab: the lab is that sheet *plus* its own title"

    as_lab = tuple(
        token("科研所", (323, 180, 397, 222)) if item.text == "城墙" else item
        for item in tokens
    )
    assert OCRPageClassifier._research_lab_upgrade_sheet_evidence(
        as_lab, frame_size=(720, 1280)
    ), "the same sheet with the lab's own title is the lab"


def test_the_header_layout_needs_all_of_its_own_structure():
    drops = ("需要条件", "大熔炉等级24", "升级效果")
    for dropped in drops:
        tokens = tuple(item for item in header_sheet_tokens() if item.text != dropped)
        state = OCRPageClassifier().classify(
            OCRResult(tokens, f"production-replay-without-{dropped}"),
            frame_size=(720, 1280),
        )
        assert state.page is Page.UNKNOWN, (
            f"without {dropped!r} the sheet is not proven and the page must stay UNKNOWN"
        )


def test_the_two_layouts_are_separate_readings_not_one_loose_one():
    header = OCRPageClassifier._upgrade_sheet_placed(
        header_sheet_tokens(), frame_size=(720, 1280)
    )
    two_column = OCRPageClassifier._upgrade_sheet_placed(
        upgrade_sheet_tokens(), frame_size=(720, 1280)
    )
    assert OCRPageClassifier._current_upgrade_sheet_layout(header) is True
    assert OCRPageClassifier._current_upgrade_sheet_layout(two_column) is False
    assert OCRPageClassifier._building_upgrade_sheet_evidence(
        header_sheet_tokens(), frame_size=(720, 1280)
    ) is True
    assert OCRPageClassifier._building_upgrade_sheet_evidence(
        upgrade_sheet_tokens(), frame_size=(720, 1280)
    ) is True


def test_the_header_sheet_output_satisfies_the_entry_verifier():
    # The link the fix exists to make: the classifier's own reading of that frame is what the
    # OPEN_BUILDING_UPGRADE verifier consumes, so it has to satisfy it without help.
    from winter_agent_v2.runtime import LiveRuntime

    after = OCRPageClassifier().classify(
        OCRResult(header_sheet_tokens(), "production-replay-header-layout"),
        frame_size=(720, 1280),
    )
    before = WorldState(
        page=Page.HOME, building={"upgrade_tap_norm": [0.5, 0.7195]},
    )
    result = LiveRuntime.VERIFIED_ATOMIC["OPEN_BUILDING_UPGRADE"](before, after)
    assert result.ok, result.reason
    assert result.reason == "BUILDING_UPGRADE_PANEL_OPENED"
