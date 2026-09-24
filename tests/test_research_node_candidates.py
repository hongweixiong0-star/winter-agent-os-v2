from dataclasses import replace

from winter_agent_v2.models import Page
from winter_agent_v2.models import WorldState
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_research_node_inspected


def _token(text, x, y, confidence=0.99):
    return OCRToken(text, confidence, ((x - 24, y - 10), (x + 24, y - 10),
                                      (x + 24, y + 10), (x - 24, y + 10)))


def test_research_nodes_are_read_from_current_frame_and_maxed_nodes_are_not_candidates():
    result = OCRResult((
        _token("科技研究", 125, 43),
        _token("3/3", 360, 228), _token("指挥艺术II", 360, 260),
        _token("1/3", 360, 497), _token("工具改良IV", 360, 534),
    ), "test")

    state = OCRPageClassifier().classify(result, frame_size=(720, 1280))

    assert state.page is Page.RESEARCH
    nodes = state.research["node_candidates"]
    assert [node["name"] for node in nodes] == ["指挥艺术II", "工具改良IV"]
    assert [node["status"] for node in nodes] == ["MAXED", "UNFINISHED"]
    assert nodes[1]["tap_norm"] == [0.5, 0.41719]
    assert "researchable" not in state.research


def test_research_detail_requires_a_current_node_and_exact_research_control():
    tree = (
        _token("科技研究", 125, 43),
        _token("1/3", 360, 497), _token("工具改良IV", 360, 534),
    )
    classifier = OCRPageClassifier()

    no_button = classifier.classify(OCRResult(tree, "test"), frame_size=(720, 1280))
    detail = classifier.classify(
        OCRResult(tree + (_token("研究", 602, 1040),), "test"),
        frame_size=(720, 1280),
    )

    assert no_button.research.get("node_detail_visible") is None
    assert detail.research["node_detail_visible"] is True
    assert detail.research["selected_node"] == "工具改良IV"
    assert detail.research["research_control_norm"] == [0.8361, 0.8125]


def test_research_detail_sheet_remains_identifiable_when_its_tree_header_is_dimmed():
    # Live screenshot 20260925_041205_184877 step 5: tapping a node opens this sheet,
    # but the dimmed 科技研究 header is no longer legible and the template page is lost.
    result = OCRResult((
        _token("工具改良IV", 355, 256),
        _token("研究消耗", 135, 679),
        _token("研究", 510, 972),
    ), "test")

    state = OCRPageClassifier().classify(result, frame_size=(720, 1280))

    assert state.page is Page.RESEARCH
    assert state.research["node_detail_visible"] is True
    assert state.research["selected_node"] == "工具改良IV"


def test_research_start_requires_readable_affordable_costs_and_current_duration():
    tokens = (
        _token("工具改良IV", 355, 256),
        _token("研究消耗", 135, 679),
        _token("1000/500", 210, 744), _token("2000/1500", 500, 744),
        _token("357.7万/69，000", 210, 794), _token("4000/3500", 500, 794),
        _token("5000/4400", 210, 844),
        _token("研究", 510, 972), _token("02:53:09", 511, 1005),
    )
    state = OCRPageClassifier().classify(OCRResult(tokens, "test"), frame_size=(720, 1280))

    assert state.page is Page.RESEARCH
    assert state.research["node"] == "工具改良IV"
    assert state.research["costs_readable"] is True
    assert state.research["costs_affordable"] is True
    assert len(state.research["cost_rows"]) == 5
    assert state.research["cost_rows"][2] == {
        "current": 3577000.0, "required": 69000.0, "affordable": True,
    }
    assert state.research["start_control_present"] is True
    assert state.research["researchable"] is True
    assert state.research["queue_available"] is True
    assert state.research["status"] == "IDLE"
    assert state.research["queue_source"] == "CURRENT_FRAME_RESEARCH_START_CONTROL"
    assert state.research["research_control_norm"] == [0.7083, 0.7594]


def test_research_start_stays_blocked_when_cost_is_short_or_duration_is_missing():
    affordable = (
        _token("工具改良IV", 355, 256), _token("研究消耗", 135, 679),
        _token("1000/500", 210, 744), _token("2000/1500", 500, 744),
        _token("3000/2500", 210, 794), _token("4000/3500", 500, 794),
        _token("研究", 510, 972),
    )
    classifier = OCRPageClassifier()
    unaffordable = classifier.classify(
        OCRResult(affordable[:3] + (_token("400/1500", 500, 744),) + affordable[4:]
                  + (_token("02:53:09", 511, 1005),), "test"),
        frame_size=(720, 1280),
    )
    no_duration = classifier.classify(OCRResult(affordable, "test"), frame_size=(720, 1280))

    assert unaffordable.research["costs_readable"] is True
    assert unaffordable.research["costs_affordable"] is False
    assert unaffordable.research["researchable"] is False
    assert no_duration.research["costs_affordable"] is True
    assert no_duration.research["start_control_present"] is False
    assert no_duration.research["researchable"] is False


def test_a_generic_research_label_without_the_detail_sheet_evidence_stays_unknown():
    result = OCRResult((
        _token("工具改良IV", 355, 256),
        _token("研究", 510, 972),
    ), "test")

    state = OCRPageClassifier().classify(result, frame_size=(720, 1280))

    assert state.page is Page.UNKNOWN


def test_research_nodes_without_positions_are_not_action_targets():
    result = OCRResult((
        OCRToken("科技研究", 0.99), OCRToken("1/3", 0.99), OCRToken("工具改良IV", 0.99),
    ), "test")

    state = OCRPageClassifier().classify(result, frame_size=(720, 1280))

    assert state.research["node_candidates"] == []


def test_idle_research_goal_inspects_a_live_unfinished_node_without_claiming_affordability():
    node = {
        "node_id": "工具改良IV", "name": "工具改良IV", "level": 1, "level_max": 3,
        "status": "UNFINISHED", "tap_norm": [0.5, 0.42], "confidence": 0.99,
        "source": "CURRENT_FRAME_OCR",
    }
    before = WorldState(
        page=Page.RESEARCH, confidence=0.99,
        research={"status": "IDLE", "queue_available": True, "node_candidates": [node]},
    )

    brain = RuleBrain(current_goal="RESEARCH")
    brain.goal_id = "KEEP_RESEARCH_PRODUCTIVE"
    decision = brain.decide(before, v2_registry())
    runtime = LiveRuntime.__new__(LiveRuntime)
    point = runtime._resolve_semantic_target("RESEARCH_NODE_NEXT", before)
    after = replace(before, research={
        **before.research, "node_detail_visible": True, "selected_node": "工具改良IV",
    })
    verification = verify_research_node_inspected(before, after)

    assert decision.skill == "SELECT_RESEARCH_NODE"
    assert point == (0.5, 0.42)
    assert verification.ok
    assert "researchable" not in after.research


def test_idle_research_goal_uses_only_the_verified_current_frame_start_control():
    state = WorldState(page=Page.RESEARCH, confidence=0.99, research={
        "status": "IDLE", "queue_available": True, "node": "工具改良IV",
        "node_detail_visible": True, "selected_node": "工具改良IV",
        "researchable": True, "costs_readable": True, "costs_affordable": True,
        "start_control_present": True, "research_control_norm": [0.7083, 0.7594],
    })
    brain = RuleBrain(current_goal="RESEARCH")
    brain.goal_id = "KEEP_RESEARCH_PRODUCTIVE"
    runtime = LiveRuntime.__new__(LiveRuntime)
    decision = brain.decide(state, v2_registry())

    assert decision.skill == "RESEARCH"
    assert runtime._resolve_semantic_target("BTN_START_RESEARCH", state) == (0.7083, 0.7594)
    assert runtime._resolve_semantic_target("BTN_START_RESEARCH", replace(
        state, research={**state.research, "costs_affordable": False}
    )) is None
    assert runtime._resolve_semantic_target("BTN_START_RESEARCH", replace(
        state, research={**state.research, "queue_available": False}
    )) is None
    skill = v2_registry().get("RESEARCH")
    assert skill is not None and skill.semantic_contract_complete
