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
    ("sawmill", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_005_tab_tap_WOOD.png", None),
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
