"""The frame whose goals are recorded must carry the counts those goals are measured by.

``runtime.py`` stamped the intel board's ``untried_pins`` / ``detected_pins`` at the top of
the step, onto the frame that becomes ``before``, and the comment there is about *planning*:
the same frame and the same candidate list must serve the decision and the execution.  That
is right for planning and wrong for accounting, because ``goals_after`` is read from the
**after** frame, which was never stamped.

Measured 2026-10-05 over ``learning/episodes.jsonl`` (one line = one step, carrying
``state_before.page`` / ``state_after.page`` / ``repo_revision``), banded by revision:

    board -> other page      old: False 4/4      new: False 4/4  -> not this file's fix
    board -> board (a pin handled)                 <- invisible on both sides

The second row is what this file is about, and it is worse than the first: the board's own
count is the one thing this goal family exists to move, and a pin that was genuinely consumed
could not register, because the after row had no count at all.  The comparison then fell to
the constant ``distance``, where ``1.0 < 1.0`` is ``False`` -- a hard "the action landed and
the goal did not move", which ``runtime.py:9734`` counts against the goal.

The fix is a placement, not a new measurement: ``_record_goals`` stamps the frame it is handed.
That is the single seam every frame passes through -- before, after, refresh and recovery all
reach it -- so no call site can forget.  The planner's own copy stays where it was, and the two
agree because they are the same computation over the same path and the same tapped-pin list.

What these tests pin is the seam and its three boundaries.  The negative cases matter as much
as the positive one: a count taken from a frame that is not the board would not be a count of
the board, and inventing one is the failure mode this repository keeps having to remove.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_live_runtime import FakeDevice, FakeSemantic, FakeVision  # noqa: E402

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.goal_library import _observation_meter  # noqa: E402
from winter_agent_v2.intel_pins import IntelPin  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

#: Two pins, so "one was handled" is a number rather than a boolean.
PINS = [IntelPin(200, 600, "ORANGE", 900), IntelPin(400, 700, "PURPLE", 700)]


@pytest.fixture()
def runtime(tmp_path):
    """A runtime that can record goals without a device.

    ``FakeVision([])`` on purpose: ``_record_goals`` never observes -- the frame is handed to
    it -- and an empty list makes that a checked property rather than a hope, since any
    accidental observation would raise ``StopIteration`` instead of quietly using a frame.
    """
    return LiveRuntime(
        device=FakeDevice(), vision=FakeVision([]), semantic_vision=FakeSemantic(),
        capture_dir=tmp_path, brain=RuleBrain(current_goal="INTEL"), sleeper=lambda _: None,
    )


@pytest.fixture()
def frame(tmp_path):
    path = tmp_path / "board.png"
    path.write_bytes(b"not-a-real-frame")  # the detector is patched; only the path is used
    return path


def _board(**extra) -> WorldState:
    """A board frame as the observation layer delivers it: no pin count of its own.

    ``pins`` is present because the brain's own gate requires it (``brain.py:2398``) and the
    live reading carries it; ``untried_pins`` is deliberately absent, because that is the field
    only the runtime knows how to compute, and its absence is the thing under test.
    """
    return WorldState(page=Page.INTEL, confidence=0.99,
                      intel={"status": "AVAILABLE", "pins": len(PINS), "list_read": True, **extra})


def _row(runtime, world, frame):
    """Record this frame's goals with the detector replaced, and hand back the intel row.

    The detector is patched rather than handed a real screenshot: the unit under test is where
    the counts are computed, not how the contours are found, and ``intel_pins`` has its own
    tests for the second half.
    """
    with patch("winter_agent_v2.runtime.intel_pin_centers", return_value=PINS) as detect:
        goals = runtime._record_goals(world, frame=frame)
    return next(g for g in goals if g.goal_id == "CLEAR_INTEL"), detect


def _stamp(runtime, world, frame):
    """``_stamp_intel_pin_counts`` with the detector replaced -- it is not a real image."""
    with patch("winter_agent_v2.runtime.intel_pin_centers", return_value=PINS):
        return runtime._stamp_intel_pin_counts(world, frame)


def test_a_board_frame_is_stamped_wherever_it_is_recorded(runtime, frame) -> None:
    """The defect, gone: the row carries the count even though the world never did.

    This is the after frame's shape -- the observation layer hands over a board and the runtime
    is the only thing that can say how many pins have not been tried.  If the stamp lives at the
    step's top instead of at the seam, this row has ``untried_pins: None`` and the meter is
    ``None``, so a pin handled on the board cannot show up as work on either side.
    """
    row, detect = _row(runtime, _board(), frame)
    assert row.evidence.get("untried_pins") == len(PINS), (
        f"the recorded row must carry the board's own count; evidence={row.evidence!r}"
    )
    assert detect.call_count == 1, "the counts are computed from the frame, once"
    # Negated, because progress_moved compares observation meters with `>` while the raw count
    # falls as work is done (goal_library.py:2602-2614).
    assert _observation_meter(row) == -float(len(PINS))


def test_the_same_board_row_is_not_measurable_without_the_stamp(runtime, frame) -> None:
    """The before-state, kept as arithmetic so the fix cannot be removed quietly.

    ``_stamp_intel_pin_counts`` is replaced by an identity, which is what the code effectively
    was for every after frame.  The row still exists and still reports its status -- the goal is
    not missing, it is unmeasurable -- and that is the distinction the whole report turns on.
    """
    runtime_stamp = runtime._stamp_intel_pin_counts
    with patch.object(runtime, "_stamp_intel_pin_counts", side_effect=lambda world, _frame: world):
        row, _ = _row(runtime, _board(), frame)
    assert row is not None, "the goal is still emitted; only its measurement is missing"
    assert row.evidence.get("untried_pins") is None
    assert _observation_meter(row) is None, (
        "with no count the goal falls back to its constant distance, which is what makes "
        "every comparison 1.0 < 1.0 and therefore False"
    )
    assert runtime_stamp is not None  # keeps the real method referenced, not shadowed forever


def test_stamping_twice_is_the_same_as_stamping_once(runtime, frame) -> None:
    """Why the planner's copy and the seam's copy can both exist.

    The step top stamps ``before`` for the decision and the pin list; the seam stamps the same
    frame again when it records the goals.  That is only safe if the second pass cannot disagree
    with the first, and it cannot: same path, same tapped-pin list, same detector.
    """
    once, _ = _row(runtime, _stamp(runtime, _board(), frame), frame)
    twice, _ = _row(runtime, _board(), frame)
    assert once.evidence == twice.evidence, (
        f"a pre-stamped frame must record the same row as an unstamped one; "
        f"{once.evidence!r} != {twice.evidence!r}"
    )


def test_a_frame_that_is_not_the_board_gets_no_count(runtime, frame) -> None:
    """The first boundary: no board, no count.

    A count computed from a map frame would be a count of something else, and the goal's own
    visit ticket is what belongs on that frame.  ``detect.call_count == 0`` is the real
    assertion -- the absence of the field could also be produced by stamping zeros.
    """
    world = WorldState(page=Page.MAP, confidence=0.99)
    row, detect = _row(runtime, world, frame)
    assert detect.call_count == 0, "the detector must not run on a frame that is not the board"
    assert "untried_pins" not in row.evidence, (
        f"the visit ticket must not borrow the board's field; evidence={row.evidence!r}"
    )
    assert _observation_meter(row) is None


def test_a_board_with_a_card_open_gets_no_count(runtime, frame) -> None:
    """The second boundary: a card is not the board.

    ``mission_type`` means a mission card is showing, so whatever the contour pass finds there
    is not the board's pin map.  This is the same gate the planner's copy uses, and it is
    restated here because the stamp now runs on far more frames than it used to.
    """
    row, detect = _row(runtime, _board(mission_type="BEAST"), frame)
    assert detect.call_count == 0
    assert row.evidence.get("untried_pins") is None
    assert _observation_meter(row) is None


def test_a_handled_pin_is_visible_as_a_drop_in_the_count(runtime, frame) -> None:
    """The point of the whole change, stated as the number the meter will compare.

    A pin is tapped -- which is what the runtime records in ``_tapped_intel_pins`` -- and the
    board still shows both pins.  The count must fall from two to one, because that drop is the
    only signal that intel work happened, and until the after frame carried a count there was
    nowhere for it to appear.
    """
    before = _stamp(runtime, _board(), frame)
    assert before.intel["untried_pins"] == len(PINS)

    runtime._tapped_intel_pins.append((PINS[0].x, PINS[0].y))
    after = _stamp(runtime, _board(), frame)
    assert after.intel["untried_pins"] == len(PINS) - 1, (
        "a tapped pin must leave the untried count; otherwise the meter can never move"
    )
    assert after.intel["detected_pins"] == len(PINS), (
        "the pin is still drawn and still detected -- only 'untried' falls"
    )
    before_row, _ = _row(runtime, _board(), frame)
    assert _observation_meter(before_row) == -1.0
