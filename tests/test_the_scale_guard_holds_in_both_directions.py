"""The scale guard in ``progress_moved`` was consulted in one direction only.

``goal_library.progress_moved`` compares two numbers and they have to be the same *kind* of
number, or "progress" becomes an artefact of switching scales mid-run.  The writer records the
kind next to the value in ``_METER_KINDS`` for exactly that reason, and the guard was written
as::

    reading = _observation_meter(now)
    if reading is not None:
        kind = _METER_KINDS.get(goal_id)
        if kind != "observation":
            return None
        return reading > previous
    return now.distance < previous          # <- no guard on this branch

So the guard caught "the current frame has a count, the remembered value is a distance" and
missed its mirror image: **the current frame has no count while the remembered value came from
a count**.  On that branch the code compared a navigation distance against a count.

Why that is not a theoretical slip
----------------------------------
``CLEAR_INTEL`` produces both shapes by construction, alternating between them every time the
robot moves.  Measured 2026-10-05 against the production row in ``learning/goal_state.json``:

* on a frame that read the intel board, ``goal_library.py:1220`` emits the row with
  ``evidence["untried_pins"]`` copied out of ``WorldState.intel``, so the meter is ``-untried``
  -- ``-7.0`` for a board holding seven missions;
* on every other frame the row is the sweep's *visit ticket* (``_append_panel_routine``), whose
  evidence is ``['age_minutes', 'has_actionable_daily_task_rows',
  'incomplete_queue_observation', 'observed', 'overdue', 'reading', 'reused']`` -- no count at
  all, skills ``('OPEN_INTEL',)``, ``distance`` the literal ``1.0``.  The production row read
  back from disk carries exactly those keys, which is how the two were tied together.

The comparison the old code made on the second shape was therefore ``1.0 < -7.0``: ``False``.
``False`` is not a neutral answer here -- ``progress_moved``'s docstring reserves ``None`` for
"not observable" and treats ``False`` as "the action landed and the goal did not move", and
``runtime.py:9734`` increments ``no_progress_streak`` on it.  The recorded blocker says what
that produces::

    CLEAR_INTEL  capability READ_INTEL_LIST  state DEFERRED  source NO_GOAL_PROGRESS
    reason "3 consecutive production episodes passed their verifier and advanced no part of
            this goal"        failure_signature READ_INTEL_LIST|NO_GOAL_PROGRESS|SELECT_INTEL_PIN

Three consecutive episodes, which is the streak length that defers a goal, for a run in which
the board was being read.  ``None`` is the honest verdict and is not counted against the goal.

What these tests pin
--------------------
The arithmetic (so the defect stays auditable), the guard (so it cannot come back), and the
two like-for-like cases plus a control group (so the fix cannot be "make everything return
``None``", which would pass the first assertion alone).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOAL = "CLEAR_INTEL"

#: Seven missions on the board, already read -- so the meter is ``-7.0``.  The count is negated
#: because ``progress_moved`` compares observation meters with ``>`` while the raw count falls as
#: work is done (``goal_library.py:2602-2614``).
BOARD_COUNT = 7

#: The production row, as read back from ``learning/goal_state.json`` on 2026-10-05: the sweep's
#: visit ticket.  ``untried_pins`` is absent, which is the whole point -- the goal exists, the
#: frame is honest, and there is no count on it.
VISIT_TICKET_EVIDENCE_KEYS = frozenset({
    "observed", "reused", "reading", "age_minutes", "overdue",
    "incomplete_queue_observation", "has_actionable_daily_task_rows",
})


@pytest.fixture(autouse=True)
def _clean_meter_kinds():
    """``_METER_KINDS`` is module-global state; leave it as it was found.

    Follows ``tests/test_scheduled_goals_have_no_progress_meter.py``, which seeds the same
    dictionary.  Without this, one test's kind leaks into the next and the guard answers about
    a frame nobody asked it to answer about.
    """
    from winter_agent_v2.goal_library import _METER_KINDS

    saved = dict(_METER_KINDS)
    yield
    _METER_KINDS.clear()
    _METER_KINDS.update(saved)


def _counted_board(count: int = BOARD_COUNT):
    """The row the intel branch emits on a frame that read the board."""
    from winter_agent_v2.goal_library import GoalState, GoalStatus

    return GoalState(
        GOAL, GoalStatus.READY, evidence={"status": "AVAILABLE", "untried_pins": count},
        distance=1.0,
    )


def _visit_ticket():
    """The row the sweep emits on every frame that did not read the board.

    Built by the real ``GoalLibrary`` from the shape the production observation store holds:
    a stored reading that exists but is past its TTL.  Not hand-written, because the point is
    that this is what the code produces, not what a test can be made to say.
    """
    from winter_agent_v2.goal_library import GoalLibrary
    from winter_agent_v2.models import Page, WorldState

    observations = {
        "intel": {
            "reading": {"status": "AVAILABLE", "stamina": 22, "refresh": "01:43:00",
                        "available_count": 7, "pins": 7, "list_read": True},
            "age_minutes": 129.4, "overdue": True, "observed": False, "reused": False,
        }
    }
    board = GoalLibrary().discover(
        WorldState(page=Page.HOME, confidence=0.99), role_id="R", observations=observations,
    )
    return board, next((g for g in board if g.goal_id == GOAL), None)


def _seed(goal_id: str, value: float, kind: str) -> dict[str, float]:
    """Seed the run dictionary the way ``runtime._remember_goal_meters`` seeds it."""
    from winter_agent_v2.goal_library import _METER_KINDS

    _METER_KINDS[goal_id] = kind
    return {goal_id: value}


def test_the_production_row_is_the_visit_ticket() -> None:
    """The two shapes are tied to the real row on disk, not to a description of it.

    If the sweep is ever changed to carry the count on its ticket, this fails and the record
    and the fix both want re-reading -- which is the correct trigger, because at that point the
    alternation that caused the defect no longer exists.
    """
    _, ticket = _visit_ticket()
    assert ticket is not None, "CLEAR_INTEL must be on the board for this to mean anything"
    assert set(ticket.evidence) == VISIT_TICKET_EVIDENCE_KEYS, (
        f"the visit ticket's evidence changed shape: {sorted(ticket.evidence)}"
    )
    assert "untried_pins" not in ticket.evidence
    assert ticket.available_skills == ("OPEN_INTEL",), (
        "the ticket's single entry skill is what distinguishes it from the intel branch's row"
    )


def test_the_old_comparison_was_a_cross_scale_one() -> None:
    """The defect, kept visible as arithmetic rather than prose.

    ``now.distance`` on the visit ticket is the literal ``1.0``; the remembered number was a
    count of ``-7.0``.  The comparison the unguarded branch made is reproduced here, and the
    assertion is that it is ``False`` -- a hard "no progress" verdict -- so that anyone
    proposing to remove the guard has to argue with the number.
    """
    _, ticket = _visit_ticket()
    previous = -float(BOARD_COUNT)
    assert ticket.distance == 1.0
    assert (ticket.distance < previous) is False, (
        "if this is no longer False the scales happened to line up and this test needs "
        "re-measuring rather than deleting"
    )


def test_a_visit_ticket_against_a_counted_board_is_unmeasured_not_stalled() -> None:
    """The fix.  ``None``, not ``False`` -- and the difference decides the streak.

    ``None`` is documented as "not observable", which is what this comparison actually is: the
    goal left its only page.  ``False`` is counted by ``runtime.py:9734`` against the goal, and
    three of them defer it.
    """
    from winter_agent_v2.goal_library import progress_moved

    board, ticket = _visit_ticket()
    observed = _seed(GOAL, -float(BOARD_COUNT), "observation")

    verdict = progress_moved(observed, [ticket], GOAL)
    assert verdict is None, (
        f"a frame with no count must not be compared against a remembered count; got {verdict!r}"
    )
    assert verdict is not False, "False here is what accumulated the deferral streak"


def test_a_real_count_change_on_the_board_is_still_progress() -> None:
    """Like-for-like, and the reason the fix is not "return None more often".

    Eight missions become seven with the goal still on its page: same kind both sides, and the
    count fell, so this is progress and must stay ``True``.
    """
    from winter_agent_v2.goal_library import progress_moved

    observed = _seed(GOAL, -8.0, "observation")
    assert progress_moved(observed, [_counted_board(7)], GOAL) is True


def test_an_unchanged_count_on_the_board_is_not_progress() -> None:
    """The other like-for-like case: nothing moved, so the answer is ``False`` and not ``None``.

    Without this, a fix that returned ``None`` whenever it was unsure would look correct.
    """
    from winter_agent_v2.goal_library import progress_moved

    observed = _seed(GOAL, -float(BOARD_COUNT), "observation")
    assert progress_moved(observed, [_counted_board(BOARD_COUNT)], GOAL) is False


def test_the_first_read_of_a_counted_board_is_progress() -> None:
    """The step that discovers the board, which the old code could not credit either.

    Before the read there is no meter at all, so the run dictionary holds the constant
    ``distance``; after the read the row carries ``untried_pins``.  Both directions of the
    guard now refuse that comparison -- the scales genuinely differ -- so the answer is
    ``None``.  That is the honest one: this step is not evidence of progress, it is the step
    that *makes* progress measurable from the next step on.
    """
    from winter_agent_v2.goal_library import progress_moved

    observed = _seed(GOAL, 1.0, "distance")
    assert progress_moved(observed, [_counted_board(7)], GOAL) is None


def test_a_goal_measured_by_its_own_distance_is_untouched() -> None:
    """The control group.  A goal that never uses the evidence meter keeps working.

    If this fails, the guard has been widened into the family that already had a working
    measurement, which is the regression this file is most likely to cause.
    """
    from winter_agent_v2.goal_library import progress_moved

    class _G:
        goal_id = "SOMETHING_ELSE"
        distance = 0.7
        evidence: dict = {}

    observed = _seed("SOMETHING_ELSE", 0.9, "distance")
    assert progress_moved(observed, [_G()], "SOMETHING_ELSE") is True
    assert progress_moved({"SOMETHING_ELSE": 0.1}, [_G()], "SOMETHING_ELSE") is False
    assert progress_moved({}, [_G()], "SOMETHING_ELSE") is None


def _board_row(count):
    """The intel branch's row for a board frame, built by the real ``GoalLibrary``.

    ``count=None`` is the shape production actually had: the branch copies the count out of
    ``WorldState.intel``, the reader never supplies one, so the row carries the key with
    ``None``.  ``_observation_meter`` refuses a non-``int``, so the row is *on its page* and
    has no meter -- which is not the visit ticket above: different evidence keys, different
    ``available_skills``.  Both therefore reach ``progress_moved`` as ``reading is None``,
    and the guard cannot tell them apart by reading alone.
    """
    from winter_agent_v2.goal_library import GoalLibrary
    from winter_agent_v2.models import Page, WorldState

    intel = {"status": "AVAILABLE", "stamina": 22, "pins": 7, "list_read": True}
    if count is not None:
        intel["untried_pins"] = count
    board = GoalLibrary().discover(
        WorldState(page=Page.INTEL, confidence=0.99, intel=intel), role_id="R",
    )
    return next((goal for goal in board if goal.goal_id == GOAL), None)


def test_a_board_row_without_a_count_reads_as_stalled_and_the_count_fixes_it() -> None:
    """**The test that was missing, and why this suite was green while production was not.**

    The two tests above ask the guard about a board row that *already carries* the count, and
    it answers ``None`` correctly.  Before 2026-10-05 the after row in production carried no
    count at all -- the stamp existed only on the ``before`` frame -- so the row that actually
    reached this comparison was the ``count=None`` one, and it fell straight through the guard
    to ``now.distance < previous``, ``1.0 < 1.0``, ``False``.  Measured on the ledger, banded by
    ``repo_revision``: ``other page -> board`` was ``False`` in every band up to ``ea349eba``
    and ``None`` from ``1132f9de``, the revision that stamped the frame whose goals are read.

    So this pair is not two unit cases, it is the before and after of one production
    measurement.  A test that supplies the input production lacks is the failure mode this
    file guards against as much as the defect itself: the suite said the direction was fixed
    while the row it never built was still being recorded as stalled.

    **Coverage boundary.**  Both rows are built here by hand, so this file says only what
    ``progress_moved`` answers for each shape.  That the *runtime* puts the count on the after
    frame -- the half that was missing -- is
    ``tests/test_the_after_frame_carries_the_pin_counts.py``, which fails when the seam stamp
    is disabled.  Neither file alone covers the chain, and this one must not be read as
    evidence that the stamp exists.
    """
    from winter_agent_v2.goal_library import progress_moved

    uncounted = _board_row(None)
    assert uncounted is not None, "the board must produce a CLEAR_INTEL row for this to mean anything"
    assert uncounted.evidence.get("untried_pins") is None, (
        f"this row is supposed to model a frame that was never stamped; got "
        f"{uncounted.evidence.get('untried_pins')!r}"
    )

    # The remembered value is the visit ticket's constant, which is what a run that has not yet
    # read the board holds -- the same seeding the production row had on this transition.
    observed = _seed(GOAL, 1.0, "distance")
    assert progress_moved(observed, [uncounted], GOAL) is False, (
        "this is the recorded 'the action landed and the goal did not move' that incremented "
        "no_progress_streak and deferred the goal"
    )
    # Same frame, stamped.  Now the row reports a count, the guard sees two scales and declines
    # to compare them -- which is what changed in production.
    assert progress_moved(observed, [_board_row(BOARD_COUNT)], GOAL) is None
