"""The research tree, read from the frames production actually stopped on.

2026-09-27: KEEP_RESEARCH_PRODUCTIVE reached the tech tree nine times and every
time ended at "research_page_no_startable_node" -- on a page that draws four
unfinished nodes.  Two things caused it, both visible only on the real client:

    1. the client renders node level suffixes as Unicode Roman numerals (Ⅰ-Ⅻ),
       which RapidOCR reads as '！' or drops; the reader only knew ASCII
       IVXLCDM, so every real name failed the label pattern;
    2. the tree's third tab 战斗 was read as '木' (conf 0.63) on all three
       frames, so the all-three-tabs rule refused to call the page the tree.

These three frames are AUTO's own production screenshots of that page, committed
under dataset/evidence, so the regression test runs wherever the repo does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRAMES = ROOT / "dataset" / "evidence" / "research_tree_20260927"
FRAME_NAMES = (
    "research_tree_step015_after.png",
    "research_tree_step021_after.png",
    "research_tree_step001_after.png",
)

pytestmark = pytest.mark.skipif(
    not all((FRAMES / name).exists() for name in FRAME_NAMES),
    reason="production research-tree frames are not present in this checkout",
)


@pytest.fixture(scope="module")
def states():
    from PIL import Image
    from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, RapidOCRBackend

    backend = RapidOCRBackend()
    classifier = OCRPageClassifier()
    out = []
    for name in FRAME_NAMES:
        image = Image.open(FRAMES / name).convert("RGB")
        result = OCRResult(tuple(backend.recognize(image)), "production_replay")
        out.append(classifier.classify(result, frame_size=image.size))
    return out


def test_the_production_tree_is_classified_as_the_research_page(states):
    """Two of three tabs and real node pills must name the page, despite 战斗→木."""
    for state in states:
        assert state.page.name == "RESEARCH", (
            f"the real tech tree must classify as RESEARCH, got {state.page}"
        )


def test_the_production_tree_yields_unfinished_nodes_with_tap_points(states):
    """Four unfinished nodes are drawn; the chain needs at least one readable one."""
    for state in states:
        nodes = state.research.get("node_candidates") or []
        unfinished = [n for n in nodes if n.get("status") == "UNFINISHED"]
        assert len(unfinished) >= 3, (
            f"the tree draws four unfinished nodes, got {len(unfinished)}: "
            f"{[n.get('name') for n in nodes]}"
        )
        for node in unfinished:
            assert isinstance(node.get("tap_norm"), (list, tuple)), node
            assert 0.0 < node["tap_norm"][0] < 1.0 and 0.0 < node["tap_norm"][1] < 1.0
            assert node["level_max"] > node["level"] > 0


def test_maxed_nodes_are_read_but_never_selected(states):
    """The three maxed nodes must be read as MAXED -- never as candidates to start."""
    for state in states:
        nodes = state.research.get("node_candidates") or []
        maxed = [n for n in nodes if n.get("status") == "MAXED"]
        assert len(maxed) >= 3, (
            f"the tree draws three maxed nodes (满级), got {len(maxed)}"
        )


def test_the_unicode_roman_suffix_is_what_the_reader_now_knows():
    """Pin the pattern change itself: Ⅰ (U+2160) and its '！' misread are node names."""
    from winter_agent_v2.ocr import RESEARCH_NODE_NAME_RE

    assert RESEARCH_NODE_NAME_RE.fullmatch("生存特训Ⅰ")
    assert RESEARCH_NODE_NAME_RE.fullmatch("突击特训！")
    assert RESEARCH_NODE_NAME_RE.fullmatch("工具改良IV")
    assert not RESEARCH_NODE_NAME_RE.fullmatch("发展")
    assert not RESEARCH_NODE_NAME_RE.fullmatch("木")
    assert not RESEARCH_NODE_NAME_RE.fullmatch("研究")


def test_the_sheet_title_matches_its_tree_candidate_despite_suffix_spelling():
    """The exact pair that failed two production episodes must now verify.

    2026-09-26T18:14Z / 18:25Z: the tree named the candidate '防御特训', the
    sheet it opened titled itself '防御特训！' -- the same node, one Unicode Ⅰ
    read once and dropped once -- and RESEARCH_NODE_DETAIL_NOT_PROVEN failed a
    correctly opened, completely read sheet.
    """
    from dataclasses import replace as _replace

    from winter_agent_v2.models import Page, WorldState
    from winter_agent_v2.verifier import verify_research_node_inspected

    candidate = {
        "node_id": "防御特训", "name": "防御特训", "level": 2, "level_max": 3,
        "status": "UNFINISHED", "tap_norm": [0.5, 0.41], "confidence": 0.99,
        "source": "CURRENT_FRAME_OCR",
    }
    before = WorldState(page=Page.RESEARCH, research={"node_candidates": [candidate]})
    after = WorldState(page=Page.RESEARCH, research={
        "selected_node": "防御特训！", "selected_node_name": "防御特训！",
        "node": "防御特训！", "node_detail_visible": True,
        "research_control_norm": [0.709, 0.7594],
    })

    result = verify_research_node_inspected(before, after)
    assert result.ok, result.evidence
    assert result.evidence["expected_base"] == result.evidence["selected_base"]

    # And a genuinely different node still fails: normalisation must not erase identity.
    wrong = _replace(after, research={**after.research, "selected_node": "编制扩展！"})
    assert not verify_research_node_inspected(before, wrong).ok
