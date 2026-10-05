"""Pin what the production observer says about a real 每日任务 frame.

`tests/test_daily_verifier.py` drives ``ReplayVision`` over ``tests/replay/labels.json`` -- it
checks the *rules* against labels.  Nothing checked what the two real recognisers produce on a
real frame, and that is where the defect this file guards was found: ``vision.py``'s template
branches return literal dicts with hardcoded numbers at confidence 0.99, and on
``live_daily_after_beast.png`` the template layer really does say ``activity: 70`` while the frame
shows 270.

``HybridVision`` hides that in the normal case, because it merges the OCR layer over the template
layer key by key.  So the thing worth pinning is not "the template is wrong" -- it is that **the
production reading is the measurement, not the constant**, and that the reading carries the task
rows it read rather than a shape with no rows in it.  Both are asserted on the frame where the two
layers disagree, which is the only frame where the distinction is visible.

The frames are gitignored (``.gitignore:37  dataset/raw/**/*.png``), so on a checkout without them
these tests skip with a reason instead of pretending to pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: A real 720x1280 daily frame.  Its label (tests/replay/labels.json) records activity 270 with
#: claimed_milestones [40, 80, 120, 160, 215, 270] and next_milestone 325, so 270 is the truth
#: this frame draws and 70 is the template layer's constant.
FRAME = ROOT / "dataset" / "raw" / "live_daily_after_beast.png"
MEASURED_ACTIVITY = 270
TEMPLATE_CONSTANT_ACTIVITY = 70


def _frame_or_skip() -> Path:
    if not FRAME.is_file():
        pytest.skip(f"real frame absent (gitignored): {FRAME}")
    return FRAME


def _hybrid():
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))
    return HybridVision(
        SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), ocr
    )


def test_the_production_reading_publishes_the_measurement_not_the_template_constant() -> None:
    """The reading must be the number on the frame, never the value a template was cut from."""
    frame = _frame_or_skip()
    hybrid = _hybrid()

    template_daily = dict(hybrid.template_vision.observe(frame).daily or {})
    production_daily = dict(hybrid.observe(frame).daily or {})

    # The two layers really do disagree on this frame, so the assertion below has teeth.
    # If a future change makes them agree, this test should be re-pointed at a frame that
    # still separates them rather than silently weakened -- so the disagreement is asserted.
    assert template_daily.get("activity") == TEMPLATE_CONSTANT_ACTIVITY, (
        "this frame no longer separates the two layers: the template layer used to say "
        f"{TEMPLATE_CONSTANT_ACTIVITY}, it now says {template_daily.get('activity')!r}. "
        "Re-point the test at a frame where they still disagree."
    )
    assert production_daily.get("activity") == MEASURED_ACTIVITY, (
        "the production reading must be the number the frame draws "
        f"({MEASURED_ACTIVITY}), not the template layer's constant "
        f"({TEMPLATE_CONSTANT_ACTIVITY}); got {production_daily.get('activity')!r}"
    )


def test_the_daily_reading_carries_its_task_rows_and_their_own_controls() -> None:
    """A daily reading with no rows is the shape the console was stuck on -- it must have rows.

    And the controls must belong to their own row: an ``AVAILABLE`` row carries
    ``BTN_DAILY_TASK_GO``, a finished one carries nothing, because a control offered on a
    finished row is a tap with no legal target.
    """
    frame = _frame_or_skip()
    daily = dict(_hybrid().observe(frame).daily or {})

    rows = daily.get("tasks")
    assert isinstance(rows, list) and rows, (
        "the production reading carries no task rows, which is exactly the shape that left "
        f"DAILY_ACTIVITY_TARGET unreadable; reading keys: {sorted(daily)}"
    )
    assert daily.get("visible_task_count") == len(rows)

    for row in rows:
        assert row.get("task_id"), f"a row without a task_id cannot be acted on: {row}"
        assert row.get("label"), f"a row without its own wording cannot be checked: {row}"
        assert row.get("progress", {}).get("target"), f"a row without a target: {row}"
        assert str(row.get("state")).upper() in {"AVAILABLE", "COMPLETED", "UNKNOWN"}

    available = [r for r in rows if str(r.get("state")).upper() == "AVAILABLE"]
    unreadable = [r for r in rows if str(r.get("state")).upper() == "UNKNOWN"]
    # Measured on this frame: three rows are AVAILABLE and one (采集50,000单位生肉) draws no
    # progress-vs-target contrast the reader can confirm a button against, so it reads UNKNOWN.
    # Asserting a COMPLETED row here would be asserting a shape this frame does not draw --
    # the completed row was measured on a later live panel, not on this frame.
    assert available, "this frame is labelled with available rows; none were read"
    assert unreadable, "this frame is labelled with an unreadable row; none were read"

    for row in available:
        button = row.get("action_button") or {}
        assert button.get("semantic_id") == "BTN_DAILY_TASK_GO", (
            f"an available row must carry its own 前往 control: {row.get('task_id')}"
        )
        assert button.get("bbox_norm"), "a control without a box is not clickable"
    for row in unreadable:
        assert not (row.get("action_button") or {}).get("semantic_id"), (
            "a row whose progress could not be read must not offer an action -- the button "
            f"would not belong to a confirmed row: {row.get('task_id')}"
        )

    # Each control's box must sit on its own row, below that row's title.  This is the property
    # that stops one row's 前往 being attributed to its neighbour.
    for row in available:
        title = row.get("bbox_norm") or []
        button = row.get("action_button") or {}
        box = button.get("bbox_norm") or []
        if len(title) == 4 and len(box) == 4:
            assert box[1] >= title[1], (
                f"{row.get('task_id')}: the control is drawn above its own title"
            )
