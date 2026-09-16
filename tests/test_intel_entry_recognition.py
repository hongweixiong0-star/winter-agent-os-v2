"""Regression tests for OPEN_INTEL world-map entry recognition.

Work order WB-R19-OPEN-INTEL-MAA-RECOVERY.  The failure it fixes was not "the
threshold is a bit tight": on six consecutive production frames the fixed-ROI
phash path measured 34-38 against a threshold of 24 and refused, while the
control was visibly on screen 93 px lower.  The right-hand HUD stack is
bottom-anchored, so the control's row depends on which other buttons the client
is currently drawing, and a ROI that is both "where it is" and "where to look"
cannot follow it.

These tests pin the three things that fix depends on: the control is found
wherever the HUD put it, the tap target is the FOUND position rather than the
registration, and the threshold was not loosened to buy recall.

Frames live under ``dataset/truth_audit/`` because ``tests/`` may not reference
``dataset/raw`` or ``dataset/evidence`` -- see ``tests/test_evidence_integrity.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
EVIDENCE = ROOT / "dataset/truth_audit/intel_entry_20260916"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"

# The registration ROI centre, which is where the control sits in the older HUD
# layout.  Kept as a literal because the whole point is that a match may report
# something else.
REGISTERED_CENTRE_Y = 0.6727
MOVED_CENTRE_Y = 0.7453

FAILURE_FRAMES = [
    "fail1__intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "fail2__intel_pins_20260915_230510_nav_00_step_001_before_20260915T230612978098.png",
    "fail3__intel_pins_20260915_230917_nav_01_step_001_before_20260915T231108075082.png",
]
NEGATIVE_FRAMES = [
    "neg_home__live_page_20260915_151524.png",
    "neg_intel__one_decision_20260915_step_002_before_20260915T023512447163.png",
    "neg_gather_panel__live_runtime_step_003_before_20260915T160609443785.png",
]


@pytest.fixture()
def vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


def _frame(name: str) -> Path:
    path = EVIDENCE / name
    if not path.exists():
        pytest.skip("archived evidence frame not present: %s" % name)
    return path


# --------------------------------------------------------------- the real fix


@pytest.mark.parametrize("name", FAILURE_FRAMES)
def test_the_frames_that_failed_now_resolve(vision: SemanticWorldVision, name: str) -> None:
    match = vision.semantic.find(_frame(name), SEMANTIC)
    assert match is not None, "the control is visible on this frame; refusing it is the bug"


@pytest.mark.parametrize("name", FAILURE_FRAMES)
def test_the_tap_target_follows_the_control_not_the_registration(
    vision: SemanticWorldVision, name: str
) -> None:
    """The reported centre must be where the control was FOUND.

    This is the difference between a fix and a false sense of one: tapping the
    registration ROI on these frames lands 93 px above the button, in empty sky.
    """
    match = vision.semantic.find(_frame(name), SEMANTIC)
    assert match is not None
    x_norm, y_norm = match.center_norm
    assert y_norm == pytest.approx(MOVED_CENTRE_Y, abs=0.02), (
        "centre y %.4f should be the found row %.4f, not the registration row %.4f"
        % (y_norm, MOVED_CENTRE_Y, REGISTERED_CENTRE_Y)
    )
    # The column is stable; only the row moved.
    assert x_norm == pytest.approx(0.925, abs=0.02)


def test_the_older_layout_still_resolves_at_its_own_row(vision: SemanticWorldVision) -> None:
    match = vision.semantic.find(_frame("day_ok__live_runtime_step_001_before_20260915T133445437576.png"), SEMANTIC)
    assert match is not None
    assert match.center_norm[1] == pytest.approx(REGISTERED_CENTRE_Y, abs=0.02)


@pytest.mark.parametrize(
    "name",
    [
        "night_a__live_runtime_step_001_before_20260914T131236556151.png",
        "night_b__live_runtime_step_001_before_20260914T131355670095.png",
    ],
)
def test_the_night_theme_resolves(vision: SemanticWorldVision, name: str) -> None:
    """The day/night cycle repaints the HUD; one day-colour template saw 0.39-0.45."""
    match = vision.semantic.find(_frame(name), SEMANTIC)
    assert match is not None, "night frames are production MAP frames like any other"


# ------------------------------------------------------------- what must refuse


@pytest.mark.parametrize("name", NEGATIVE_FRAMES)
def test_control_absent_pages_are_refused(vision: SemanticWorldVision, name: str) -> None:
    assert vision.semantic.find(_frame(name), SEMANTIC) is None


# ------------------------------------------------------- the invariants that keep it


def test_the_threshold_was_not_loosened(vision: SemanticWorldVision) -> None:
    """Recall was not bought by lowering the bar.

    Measured: the worst accepted positive is distance 24 and the best negative
    frame is 28, so any loosening would put the threshold on top of a frame that
    must be refused.
    """
    assert vision.semantic.semantic_max_distance[SEMANTIC] == 24


def test_every_template_of_this_semantic_searches() -> None:
    """A template added later without the band would silently fall back to the ROI.

    That is exactly the state that produced the six failures, so it is asserted
    rather than assumed.
    """
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = [r for r in payload["records"] if r.get("semantic") == SEMANTIC]
    assert len(rows) >= 2, "both the day and the night theme must be registered"
    for row in rows:
        assert row.get("matcher") == "ccoeff", row["template_id"]
        band = row.get("search_band")
        assert band is not None, row["template_id"]
        # The band must reach the control in both measured layouts.
        assert band["y_norm"] <= 0.635 and band["y_norm"] + band["h_norm"] >= 0.82, row["template_id"]


def test_the_band_does_not_cover_the_map_field() -> None:
    """A search window that swallows the map would match scenery sooner or later."""
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    row = next(r for r in payload["records"] if r.get("semantic") == SEMANTIC)
    band = row["search_band"]
    assert band["x_norm"] >= 0.70, "the band must stay in the right-hand HUD column"
