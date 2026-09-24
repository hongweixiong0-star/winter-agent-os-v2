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
