"""Lock the anchor-based resource-tab classifier against live frames.

Regression history
------------------
``selected_resource`` used to probe four *hand-typed* x centres with pHash.  Two
things were wrong with that, and both were reproduced on the live client on
2026-09-14:

1. The strip scrolls, and the client re-centres the active tab, so the fixed
   centres are only valid for one scroll offset.  In the session captured here
   the offset was +400 px, which meant tapping "MEAT at 0.25" selected the
   second tab (giant beast).  Live SELECT_RESOURCE succeeded 3/44 times.
2. The classifier had no page gate: on the HOME screen — a frame with no
   resource panel open at all — it returned ``RESOURCE_COAL_SELECTED`` with 0.875
   confidence, because the corner-signal tiebreaker fired on snow.

The shipped classifier now locates the white selection bracket (a *pair* of
near-white vertical strokes 130-175 px apart), crops the anchored cell, and
identifies the resource from the cell contents, rejecting anything that is not
decisively close.  These tests pin the behaviour on the real frames.

Measured separation on these frames: the active resource scores <= 1.2 while
every non-active tab scores >= 13.0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

# (label, frame, expected selected resource or None)
CASES = [
    # HOME / MAP: no resource panel open at all -> must not name a resource.
    ("home", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_001_home.png", None),
    ("map", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_002_map.png", None),
    # Panel open at the beast-first scroll offset: the first three tabs carry no
    # gatherable resource, so all three must be refused.
    ("beast", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_003_search_panel.png", None),
    ("giant_beast", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_004_tab_tap_MEAT.png", None),
    # CHANGED 2026-09-16 (WB-R19-SELECT-RESOURCE-ANCHOR).  This frame was refused
    # like the two above, and refusing it is what left `resource_tab_offset` at
    # None so the executor could neither tap nor scroll -- it stalled the whole
    # gather chain.  The offset is now resolved from the known strip order and
    # judged by the four reviewed templates, and on this frame exactly one
    # combination survives (support=1, margin=9.12, offset=400.0), which also
    # agrees with this case's own label.  The two frames above still resolve to
    # nothing, so this is a partial capability gain rather than a blanket loosening.
    ("sawmill", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_005_tab_tap_WOOD.png", "SAWMILL"),
    # MEAT selected, and the strip sits 400 px right of the nominal offset.
    ("meat", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_006_tab_tap_COAL.png", "MEAT"),
    # WOOD selected but the cell is clipped by the right edge: refuse rather than guess.
    ("wood_clipped", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_007_tab_tap_IRON.png", None),
    # Explicit select-each capture, all four resources, all fully visible.
    ("select_meat", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png", "MEAT"),
    ("select_wood", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png", "WOOD"),
    ("select_coal", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png", "COAL"),
    ("select_iron", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png", "IRON"),
]


@pytest.fixture(scope="module")
def vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


@pytest.mark.parametrize("label,relative,expected", CASES, ids=[case[0] for case in CASES])
def test_selected_resource_on_live_frames(vision: SemanticWorldVision, label: str, relative: str, expected: str | None) -> None:
    path = ROOT / relative
    if not path.is_file():
        pytest.skip(f"live evidence missing: {relative}")
    match = vision.semantic.selected_resource(path)
    got = match.semantic[len("RESOURCE_"):-len("_SELECTED")] if match else None
    assert got == expected, f"{label}: expected {expected}, classifier said {got}"


def test_tap_target_follows_the_observed_offset(vision: SemanticWorldVision) -> None:
    """The whole point of the anchor: a located cell determines every other cell.

    On the frame where MEAT is active the strip is 400 px right of nominal, so
    the derived MEAT tap centre must move with it — that is what stops the
    executor from tapping whichever tab happens to sit at a fixed x.
    """
    frame = ROOT / "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png"
    if not frame.is_file():
        pytest.skip("live evidence missing")
    assert vision.semantic.selected_resource(frame) is not None
    offset = vision.semantic.resource_tab_offset
    assert offset is not None
    centres = {name: vision.semantic.resource_cell_center_norm(name) for name in ("MEAT", "WOOD", "COAL", "IRON")}
    assert centres["WOOD"] is not None
    ordered = [value[0] for value in centres.values() if value is not None]
    assert ordered == sorted(ordered), "gatherable tap targets must advance left to right"
    # Shifting the offset shifts every derived target by the same amount.
    original = centres["WOOD"][0]
    vision.semantic.resource_tab_offset = offset + 72
    assert abs(vision.semantic.resource_cell_center_norm("WOOD")[0] - (original + 0.1)) < 1e-6


# ---------------------------------------------------------------------------
# The anchor must be chosen by evidence, not by stroke order.
#
# Added 2026-09-16 (WB-R19-SELECT-RESOURCE-ANCHOR).  The gather chain reached
# SELECT_RESOURCE for the first time after the march-count fix, and died there.
# The work order's hypothesis was a template-coverage gap -- and the symptom
# fits, since the manifest holds cell templates for MEAT/WOOD/COAL/IRON only.
# Measurement says otherwise:
#
#   strokes at x = 2.0, 68.5, 88.0, 156.5, 214.5, 282.5, 384.0, 394.5, 428.0
#   four stroke pairs fall in the accepted 130..175 px window
#   selected_tab_left() returned the FIRST of them: 2.0
#
# but the white bracket in that frame sits on the third visible cell, x=282.5.
# So the anchor was 280 px wrong and the template mismatch that followed
# (33.75 / 34.63 / 35.98 / 36.48 against a 6.0 gate) was a consequence: those
# crops were taken from the wrong place.  Had the mis-anchored cell matched a
# template, a wrong offset would have been accepted and the executor handed a
# wrong tap target -- the exact failure this geometry exists to prevent.
#
# The resolution crosses every accepted stroke pair with every tab identity the
# strip order allows, and keeps the unique winner.  On the failing frame exactly
# one of 28 combinations is supported, so nothing is guessed.
# ---------------------------------------------------------------------------

ANCHOR_EVIDENCE = ROOT / "dataset/truth_audit/resource_tab_anchor_20260916"
GAP_FRAME = ANCHOR_EVIDENCE / "gap_ice_beast_anchor__live_runtime_step_003_before_20260915T160609443785.png"


def test_the_bracket_is_not_simply_the_first_stroke_pair(vision: SemanticWorldVision) -> None:
    """The premise, pinned: stroke order alone picks the wrong pair here."""
    if not GAP_FRAME.is_file():
        pytest.skip("live evidence missing")
    lefts = vision.semantic.candidate_tab_lefts(GAP_FRAME)
    assert 2.0 in lefts, "the spurious pair is what stroke order picks"
    assert 282.5 in lefts, "the real bracket pair must be a candidate too"
    assert len(lefts) > 1, "ambiguity is the whole point"


def test_the_frame_that_blocked_gather_resolves_with_a_real_offset(vision: SemanticWorldVision) -> None:
    if not GAP_FRAME.is_file():
        pytest.skip("live evidence missing")
    match = vision.semantic.selected_resource(GAP_FRAME)
    assert match is not None, "the frame that stalled the gather chain must resolve"
    assert vision.semantic.resource_tab_offset == 352.5
    assert match.roi["offset_source"] == "ANCHOR_AND_IDENTITY_RESOLVED_BY_REVIEWED_TABS"
    assert match.roi["supporting_reviewed_tabs"] >= 1


def test_a_resolved_offset_makes_every_target_reachable(vision: SemanticWorldVision) -> None:
    """With the offset known the executor can act; with None it could not.

    Either the cell is already on screen (a centre) or the strip can be brought
    there (a swipe).  `resource_cell_center_norm` and `resource_tab_swipe_for`
    both return None when the offset is None, which is what stalled the chain.
    """
    if not GAP_FRAME.is_file():
        pytest.skip("live evidence missing")
    assert vision.semantic.selected_resource(GAP_FRAME) is not None
    for target in ("MEAT", "WOOD", "COAL", "IRON"):
        centre = vision.semantic.resource_cell_center_norm(target)
        swipe = vision.semantic.resource_tab_swipe_for(target)
        assert centre is not None or swipe is not None, f"{target} unreachable"
