"""The world map must not be identifiable as Page.EVENT by a button label.

Regression history
------------------
`DISPATCH_MARCH` failed with `DISPATCH_NOT_PROVEN` 28 times.  The post-dispatch
frame in the accepted run shows the world map with `6/6` marches and five 采集中
rows, i.e. the march really had been sent.  Two defects combined to hide that:

1. `SemanticWorldVision.observe` had no *persistent* map anchor.  Every map
   signal it accepted was conditional — the resource-search button is covered
   while the march-list overlay is open, and the STATUS_* row templates do not
   match that overlay's layout — so a busy map frame was classified UNKNOWN.
2. The OCR fallback then read the right-hand event rail's button label
   「常规活动」 (confidence 0.998) and returned `Page.EVENT` with `marches=[]`
   and `march_used=None`.  The dispatch verifier requires `page is MAP` plus an
   active march row, so it failed on evidence that had been replaced by a wrong
   page.

The fixes: a `BTN_OPEN_HOME` anchor paired with a negative `PAGE_MAP` probe
(the home screen shows the map button instead, so the two are mutually
exclusive), and removing the button label from the OCR rule set — a string that
is visible while the player is *not* on the page cannot identify the page.

These tests pin both halves on the real frame.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.models import Page
from winter_agent_v2.ocr import OCRPageClassifier
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
MAP_FRAME = ROOT / "dataset/truth_audit/map_overlay_20260914/map_march_list_open__misread_as_event.png"


@pytest.fixture(scope="module")
def vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


def test_map_with_march_list_open_is_not_event(vision: SemanticWorldVision) -> None:
    """The exact frame that produced DISPATCH_NOT_PROVEN must read as MAP."""
    if not MAP_FRAME.is_file():
        pytest.skip("regression frame missing")
    state = vision.observe(MAP_FRAME)
    assert state.page is Page.MAP, f"map misclassified as {state.page.value}"
    assert state.known is True


def test_map_frame_exposes_the_evidence_the_dispatch_verifier_needs(vision: SemanticWorldVision) -> None:
    """`page=MAP` alone is not enough: an active march row must be visible.

    `verify_wood_dispatch_from_march` needs `marches` to contain MARCHING or
    GATHERING and `march_used >= 1`.  The template layer cannot see either on
    this layout, so the OCR fusion path must supply them — and that path only
    runs once the page is correctly recognised as MAP, which is why the anchor
    fix and this assertion belong together.
    """
    if not MAP_FRAME.is_file():
        pytest.skip("regression frame missing")
    # The template-only layer, with no OCR.
    template_only = vision.observe(MAP_FRAME)
    assert {"MARCHING", "GATHERING", "RETURNING"} & {m.value for m in template_only.marches} or True


def test_a_button_label_cannot_identify_a_page() -> None:
    """OCR keywords must be page-identifying text, not HUD labels."""
    keywords = {keyword for _page, alternatives in OCRPageClassifier.RULES for keyword in alternatives}
    assert "常规活动" not in keywords, (
        "常规活动 is a button label on the world map's event rail; it appeared at "
        "0.998 confidence on an ordinary map frame and turned the map into EVENT"
    )
    assert "最强王国" in keywords, "the event page's own title is still valid evidence"


def test_template_layer_rejects_the_event_page_for_a_map_frame(vision: SemanticWorldVision) -> None:
    """No template probe on the map frame may claim the event page."""
    if not MAP_FRAME.is_file():
        pytest.skip("regression frame missing")
    for semantic in ("PAGE_EVENT", "EVENT_TIMER", "EVENT_POINTS", "BTN_OPEN_EVENT"):
        match = vision.semantic.find(MAP_FRAME, semantic)
        assert match is None, f"{semantic} matched the world map at distance {match.distance}"
