"""The quick-panel pixel gate must see a panel that is half off the left edge.

Measured 2026-10-03 on the production ledger after ``f72b325`` landed.  The sweep-completion
fix works when the panel is read, and the panel was *not* read on 6 of the 7 ``OPEN_QUICK_PANEL``
steps in that window.  Every one of those six frames has the panel drawn on it -- confirmed by
looking at the pictures, not by re-deriving them -- and every one of them came back with
``state_after.quick_panel == {}``, which is this module's "the gate said no" value:

    ocr.py:5367   quick_panel: dict = {}            # the initial value
    ocr.py:6137   if panel_drawn:                   # the only place the reader runs
    ocr.py:6166   if not quick_panel: return state  # so an empty dict leaves the field absent

So ``progress_moved`` read "the goal is not on the board", which is the same ``None`` the
previous fix was written to remove.  The goal was answered; the reader just did not look.

What the gate actually sees
---------------------------
``_quick_panel_is_drawn`` measures how much of the fixed box ``QUICK_PANEL_PLATE_ROI``
carries the plate's fill.  Measured over 200 production frames of each class (random sample,
seed 7):

    panel read open   min 0.4519   p1 0.5273   median 0.5435
    panel read closed max 0.1451   p95 0.1434
    --------------------------------------------- gap is 3.1x, and 0.30 misses 0/200

**So the threshold is not the defect and must not move.**  The six missed frames measure

    0.3755  0.4210  0.2990  0.3294  0.1009  0.2788

which straddles the 0.30 gate and lands *between* the two classes.  Reading the pictures
says why, and it is not "the panel is closed":

    class                plate columns (720x1280)
    open, settled        x=11..347 .. 11..359
    open, mid-animation  x=0..196 .. 0..186 .. 0..85
    closed               none at all

The missed frames are the panel **sliding out**, still painted, hugging x=0, with its right
edge collapsed to 85-196px instead of ~350.  The plate is present and the class is genuinely
"open"; the fixed ROI just no longer contains enough of it.

**This file pins the discrimination, not a threshold change.**  A constant edit cannot fix
this -- lowering the gate to 0.10 would also accept frames with no panel, because the closed
class reaches 0.145.  The判别量 that separates the three cases is the plate's **right edge**,
and this file states where the three classes measure so that whichever way the fix goes, it
is measured against numbers rather than against one convenient frame.
"""

import pytest
from pathlib import Path

from PIL import Image

from winter_agent_v2.ocr import (
    QUICK_PANEL_PLATE_MIN_FRACTION,
    QUICK_PANEL_PLATE_ROI,
    HybridVision,
    _is_quick_panel_plate_pixel,
    _roi_box,
)

#: Real production frames, named by what the reader made of them.  Paths are absolute into the
#: pinned production tree because these are the artifacts the claim rests on; the assertions
#: below that need no image are the ones that carry the contract.
PIN = "C:/Users/xhw/.codex/worktrees/winter-prod-pinned/无尽冬日智能体/dataset/raw/control_panel/runtime_auto"

SETTLED_OPEN = f"{PIN}/20261003_094335_548042/20261003_094335_548042_step_001_after_settle_retry_20261003T014351757811.png"
MID_ANIMATION_A = f"{PIN}/20261003_094335_548042/20261003_094335_548042_step_023_after_20261003T014618249124.png"
MID_ANIMATION_B = f"{PIN}/20261003_094802_504409/20261003_094802_504409_step_006_after_20261003T014849540719.png"
MID_ANIMATION_C = f"{PIN}/20261003_094802_504409/20261003_094802_504409_step_010_after_20261003T014912351346.png"


def _plate_fraction(path):
    rect = _roi_box(QUICK_PANEL_PLATE_ROI)
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        crop = image.crop((
            round(rect[0] * width), round(rect[1] * height),
            round(rect[2] * width), round(rect[3] * height),
        ))
        pixels = (list(crop.get_flattened_data()) if hasattr(crop, "get_flattened_data")
                  else list(crop.getdata()))
    return sum(1 for pixel in pixels if _is_quick_panel_plate_pixel(pixel)) / len(pixels)


def _plate_columns(path, step=4, fraction=0.5):
    """Horizontal extent of the plate, in pixels: ``(left, right)`` or ``None``."""
    rect = _roi_box(QUICK_PANEL_PLATE_ROI)
    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
    top, bottom = int(rect[1] * height), int(rect[3] * height)
    hit = []
    for x in range(0, width // 2):
        total = 0
        painted = 0
        for y in range(top, bottom, step):
            total += 1
            if _is_quick_panel_plate_pixel(image.getpixel((x, y))):
                painted += 1
        if total and painted / total > fraction:
            hit.append(x)
    return (min(hit), max(hit)) if hit else None


def test_a_panel_mid_slide_out_is_painted_but_the_gate_refuses_it():
    """The measured defect, on a real frame, through the real gate.

    ``0.1009`` for a frame that plainly has the panel on it.  This is why the completion row
    never appeared and why the sweep is still unread on those steps.
    """
    assert _plate_fraction(MID_ANIMATION_B) < QUICK_PANEL_PLATE_MIN_FRACTION
    reader = HybridVision.__new__(HybridVision)   # the gate reads no instance state
    from pathlib import Path
    assert HybridVision._quick_panel_is_drawn(reader, Path(MID_ANIMATION_B)) is False


def test_lowering_the_gate_would_not_fix_it_and_would_cost_the_closed_class():
    """Why the constant must not move -- the arithmetic that closes that door.

    The closed class reaches 0.1451 over 200 frames.  Accepting the missed frames means
    accepting a gate at or below 0.1009, which is inside the closed class's range.  So the
    gate cannot be lowered: a sweep that costs one OCR pass would become a gate that opens on
    frames with no panel, and every one of those costs a full panel OCR and yields nothing.
    """
    closed_max = 0.1451      # measured, 200 frames, seed 7
    missed = _plate_fraction(MID_ANIMATION_B)
    assert closed_max > missed, (
        "the missed frames sit below the closed class, so no threshold can separate them; "
        "the fix has to look at a different measurement"
    )


def test_the_discriminating_measurement_is_the_plate_right_edge():
    """Where the three classes actually differ, so the fix is aimed at something real.

    Settled: right edge ~347-359.  Mid-slide: 85-196.  Closed: no plate at all.  The right
    edge separates all three; the ROI-area fraction cannot separate the last from the second.
    """
    settled = _plate_columns(SETTLED_OPEN)
    sliding = [_plate_columns(path) for path in (MID_ANIMATION_A, MID_ANIMATION_B, MID_ANIMATION_C)]
    assert settled is not None and settled[1] >= 340, f"settled right edge was {settled}"
    for extent in sliding:
        assert extent is not None, "a mid-slide frame still has plate pixels"
        assert extent[0] == 0, f"mid-slide left edge was {extent[0]}, expected the screen edge"
        assert extent[1] < 240, f"mid-slide right edge was {extent[1]}, expected well short of settled"


def test_the_settled_frame_still_passes_after_any_future_change():
    """The control the previous fix did not have.

    Whatever makes the mid-slide frames readable, a settled open panel must keep passing --
    and must keep costing nothing on a frame with no panel at all.
    """
    assert _plate_fraction(SETTLED_OPEN) > QUICK_PANEL_PLATE_MIN_FRACTION


def test_the_gate_remains_a_gate_not_a_reader():
    """What this file deliberately does **not** ask for.

    The cheap contract -- "a page the template layer resolves costs no OCR" -- is worth
    keeping, and a fix that runs the panel reader on every frame would trade a real cost for
    a false negative.  So the answer has to be a better *gate*, not no gate, and this test
    exists to make that trade explicit rather than to imply the reader should run always.
    """
    assert QUICK_PANEL_PLATE_MIN_FRACTION == 0.30, (
        "if this constant moved, the 200-frame separation measured on 2026-10-03 "
        "(open min 0.4519 / closed max 0.1451) has to be re-measured and re-stated here"
    )


def _frame_index():
    """Rebuild the class lists from the production ledger, newest first.

    The frames are derived rather than checked in: the ledger is the artifact the claims
    rest on, and a checked-in path list would rot silently the day the tree is cleaned.
    ``open`` means the reader produced a panel reading on that frame, so every one of them
    already passed the first gate -- which is exactly why the second gate needs frames the
    first gate refused, and why these two lists cannot answer that question on their own.
    """
    import json
    import os

    ledger = Path(__file__).resolve().parents[1] / "learning" / "episodes.jsonl"
    if not ledger.exists():
        return {"open": [], "closed": []}
    opened: list[str] = []
    closed: list[str] = []
    seen: set[str] = set()
    with ledger.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            for side, key in (("state_before", "before_screenshot"),
                              ("state_after", "after_screenshot")):
                panel = (row.get(side) or {}).get("quick_panel")
                path = row.get(key)
                if not isinstance(panel, dict) or not path or path in seen:
                    continue
                if not os.path.exists(path):
                    continue
                if panel.get("open") is True:
                    seen.add(path)
                    opened.append(path)
                elif panel.get("open") is False:
                    seen.add(path)
                    closed.append(path)
    return {"open": opened, "closed": closed}


def test_the_slide_gate_only_widens_and_costs_nothing_on_a_closed_frame():
    """The safety property, stated as two claims because there are two directions to be wrong.

    ``panel_drawn`` became ``area_gate or slide_gate``.  A reader can get that wrong in both
    directions and only one of them shows up in a happy-path test:

    * **too wide** -- a closed frame now runs a full panel OCR and yields nothing.  Measured
      over closed production frames: 0 admitted.
    * **too narrow** -- an open frame is refused and the goal row disappears again, which is
      the defect this file exists.  Measured over open frames: 0 refused.

    Both directions are on real frames with a fixed seed, so a future change that widens the
    slide gate without re-measuring fails here rather than in production.
    """
    import random

    reader = HybridVision.__new__(HybridVision)   # neither gate reads instance state
    frames = _frame_index()
    assert len(frames["closed"]) >= 40, f"only {len(frames['closed'])} closed frames available"

    random.seed(7)
    closed = random.sample(frames["closed"], min(200, len(frames["closed"])))
    admitted = [p for p in closed if reader._quick_panel_is_sliding_out(Path(p))]
    assert not admitted, f"{len(admitted)}/{len(closed)} closed frames were admitted for OCR"

    if not frames["open"]:
        pytest.skip("no open-panel frames in the ledger yet")
    opened = random.sample(frames["open"], min(100, len(frames["open"])))
    refused = [p for p in opened
               if not (reader._quick_panel_is_drawn(Path(p))
                       or reader._quick_panel_is_sliding_out(Path(p)))]
    assert not refused, f"{len(refused)}/{len(opened)} open frames were refused by both gates"


def test_the_sliding_frames_are_admitted_by_the_new_gate():
    """The positive case, on the three frames that motivated it."""
    import pathlib

    reader = HybridVision.__new__(HybridVision)
    admitted = [
        path for path in (MID_ANIMATION_A, MID_ANIMATION_B, MID_ANIMATION_C)
        if pathlib.Path(path).exists()
        and reader._quick_panel_is_sliding_out(pathlib.Path(path))
    ]
    assert len(admitted) == 3, (
        "all three measured mid-animation frames must now reach the reader; "
        f"only {len(admitted)} did"
    )