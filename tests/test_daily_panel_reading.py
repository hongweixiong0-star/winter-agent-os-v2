"""Pin what the production observer says about a real 每日任务 frame.

`tests/test_daily_verifier.py` drives ``ReplayVision`` over ``tests/replay/labels.json`` -- it
checks the *rules* against labels.  Nothing checked what the two real recognisers produce on a
real frame, and that is where the defect this file guards was found: ``vision.py``'s template
branches return literal dicts that were cut from a single panel, and on
``live_daily_after_beast.png`` the template layer used to say ``activity: 70`` while the frame
shows 270.

That *specific* separation ended on 2026-09-17 (``cb716da2``): the two 每日任务 tab records
are registered before the old activity branches -- because 'page is DAILY' never meant 'the
daily tab is showing' -- so the template layer stops at ``{"tab": "TASKS"}`` and publishes no
activity at all on every live daily frame.  What survives, and what the tests below assert, is
the separation the merge exists for: whatever the template layer carries (or fails to carry),
the production reading must be the measurement -- the number the frame draws, plus the task
rows it read.

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
#: this frame draws.
FRAME = ROOT / "dataset" / "raw" / "live_daily_after_beast.png"
MEASURED_ACTIVITY = 270

#: The constant the template layer used to publish on this frame (cut from a 70-activity
#: panel).  Unreachable since 2026-09-17 -- ``cb716da2`` put the tab records first -- but kept
#: to name the defect this file was written for: the constant must never come back as the
#: reading.
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
    """The reading must be the number on the frame, never a value a template was cut from.

    Re-derived 2026-10-16.  The old form asserted ``template == 70`` against
    ``production == 270``, and that separation ended with ``cb716da2`` (see the module
    docstring): the template layer stops at its tab record and carries no activity on any
    live daily frame, so the constant is unreachable.  The assertion kept is the one with
    teeth in the new shape -- the template layer must **not** publish the measurement (it
    cannot measure it), while the production reading must.  If a future change lets the
    template layer measure this itself, re-point the assertions rather than deleting them.
    """
    frame = _frame_or_skip()
    hybrid = _hybrid()

    template_daily = dict(hybrid.template_vision.observe(frame).daily or {})
    production_daily = dict(hybrid.observe(frame).daily or {})

    # The template layer is expected to stop at the tab record, having no activity read of
    # its own -- neither the cut constant nor the measurement.
    assert "activity" not in template_daily, (
        "the template layer is not supposed to publish an activity on a live daily frame -- "
        "it stops at its tab record; it now says "
        f"{template_daily.get('activity')!r}. If the template layer gained a real activity "
        "read, re-point this test at a frame where the two layers still disagree."
    )
    assert template_daily.get("tab") == "TASKS", (
        "the frame draws 每日任务 as the selected tab and the template layer must say so; "
        f"got {template_daily.get('tab')!r}"
    )
    assert production_daily.get("activity") == MEASURED_ACTIVITY, (
        "the production reading must be the number the frame draws "
        f"({MEASURED_ACTIVITY}), not a constant a template was cut from "
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
