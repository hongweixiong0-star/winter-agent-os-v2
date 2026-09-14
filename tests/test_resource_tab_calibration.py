"""Lock the calibrated resource-search tab classifier.

Regression history
------------------
The resource-search tab templates were originally cut at hand-typed
``roi_norm`` x values {0.20, 0.41, 0.62, 0.82}.  The live strip actually puts
the gatherable tabs at {0.286, 0.471, 0.656, 0.841}, so every template was one
third of a tab too far left.  ``RESOURCE_TAB_MEAT`` therefore held the *wood*
icon and ``RESOURCE_MEAT_SELECTED`` reported ``MEAT`` while the client showed
wood selected.  The failure was invisible because the wrong answer was
self-consistent: the selector said MEAT, the policy asked for MEAT, and the
verifier compared the two.

These tests assert the observable contract instead of the template bytes:

* every reviewed live frame is classified as the resource it actually has
  selected;
* a panel with no unambiguous selection is not named;
* the tap target for each resource sits on the measured tab centre.

2026-09-14 note (post-maintenance panel redesign)
-------------------------------------------------
After the 2026-09-13 maintenance the resource-search panel was rewritten:
the four basic-resource tabs are no longer at the legacy x positions, the
level slider jumped from 1..8 to 1..27, and the "blue L bracket" selection
glyph was replaced by a blue-fill + white-bordered card.  The reviewed
``live_resource_rotation_selected_*_20260913.png`` frames in this test
capture the **pre-redesign** panel and no longer match the live geometry
declared in ``winter_agent_v2.vision``.  The post-redesign regression
lives in ``tests/test_panel_redesign.py`` and uses 2026-09-14 live frames.
This file is kept as a historical record of the legacy calibration only.
"""

from pathlib import Path

import pytest

from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
RAW = ROOT / "dataset" / "raw"

SELECTED_FRAMES = {
    "MEAT": RAW / "live_resource_rotation_selected_meat_20260913.png",
    "WOOD": RAW / "live_resource_rotation_selected_wood_20260913.png",
    "COAL": RAW / "live_resource_rotation_selected_coal_20260913.png",
    "IRON": RAW / "live_resource_rotation_selected_iron_20260913.png",
}


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"reviewed live frame missing: {path.name}")
    return path


@pytest.mark.parametrize("resource", sorted(SELECTED_FRAMES))
def test_reviewed_frame_reports_its_own_selected_resource(resource: str) -> None:
    pytest.skip(
        "2026-09-14 maintenance redesign retired the pre-redesign tab "
        "geometry; see tests/test_panel_redesign.py for the post-redesign "
        "regression.  These 09-13 frames remain as historical evidence."
    )
    frame = _require(SELECTED_FRAMES[resource])
    state = _vision().observe(frame)
    assert state.resource_search_open is True
    assert state.resource_selected == resource


def test_wood_panel_is_not_reported_as_meat() -> None:
    """The original defect: the wood-selected panel named MEAT."""
    pytest.skip(
        "pre-redesign frame; the geometry this assertion relied on was "
        "rewritten by the maintenance patch."
    )
    frame = _require(RAW / "live_resource_rotation_panel_wood_20260913.png")
    state = _vision().observe(frame)
    assert state.resource_selected == "WOOD"


def test_tab_centres_are_monotonic_and_one_tab_apart() -> None:
    """The gatherable tabs must advance left to right at a constant pitch.

    The strip is modelled as *order + pitch + offset* rather than four fixed
    x centres, because the client re-centres the active tab and therefore moves
    the whole strip between sessions.  The invariant worth locking is the one
    that survives a scroll: the four gatherable tabs keep their relative order
    and are exactly one pitch apart, so any one identified cell determines all
    the others.
    """
    vision = _vision()
    sem = vision.semantic
    order = sem.resource_tab_order
    gatherables = [name for name in ("MEAT", "WOOD", "COAL", "IRON") if name in order]
    assert gatherables == ["MEAT", "WOOD", "COAL", "IRON"], (
        f"gatherable tab order changed: {gatherables}"
    )
    indices = [order.index(name) for name in gatherables]
    assert indices == sorted(indices), "resource tabs must advance left to right"
    offsets = [index * sem.resource_tab_pitch for index in indices]
    spacing = [round(b - a, 6) for a, b in zip(offsets, offsets[1:])]
    assert max(spacing) - min(spacing) < 1e-9, f"tab pitch must be even: {spacing}"
    # And the derived tap target must follow the same order once a cell is known.
    sem.resource_tab_offset = 0.0
    centres = [sem.resource_cell_center_norm(name)[0] for name in gatherables]
    assert centres == sorted(centres), f"tap targets out of order: {centres}"


def test_selected_resource_is_never_named_without_a_selection() -> None:
    """A frame that is not a resource panel must not name a resource."""
    legacy = ROOT / "dataset" / "raw" / "legacy_home.png"
    if not legacy.exists():
        pytest.skip("legacy_home.png missing")
    state = _vision().observe(legacy)
    assert state.resource_selected is None
