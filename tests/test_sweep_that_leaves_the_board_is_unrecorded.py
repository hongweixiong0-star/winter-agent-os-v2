"""A sweep goal that leaves the board when it has been served is not recorded as done.

Measured 2026-10-03 on the live ledger:

    DISCOVER_QUICK_PANEL_TASKS   1291 selections (the most-selected goal in the project)
      recent 54 runs: OPEN_QUICK_PANEL 54/54 SUCCESS, goal_progress None 54/54

The goal is not failing and not idle.  It opens the panel, the panel answers, and then the
goal is *gone*: ``goal_library.py:912`` constructs it only while
``quick_panel["open"] is False``, so the frame that answers the question cannot carry the row
that asked it.  Both completion channels then miss it:

* ``progress_moved`` starts ``now = next((goal for goal in after ...), None)`` and
  **returns ``None`` when the row is absent** -- and ``None`` means *unobserved*, which is
  correct as a statement and useless as a score: the goal is never recorded as advanced and
  never recorded as stalled.
* ``newly_completed_goal_ids`` requires a ``COMPLETE`` row in ``after``.  A goal that
  disappears is not a goal that completed, so it is not counted either.

The result is a goal that ran 1291 times, opened the panel 1291 times, and has no outcome
recorded for any of them.  This file exists to name that shape, because it is not a defect in
the goal's skill or its price -- the skill is registered, the price (260) outranks every
sweep, and every attempt succeeded.  The gap is that **the ledger has no way to say "asked
and answered" for a goal that answers by leaving**.

These tests pin the two facts that any fix has to respect, and deliberately do not propose
one:

* ``None`` must stay distinct from ``False``. The project's own note says so
  ("unobservable is not failure"), and collapsing them would start incrementing
  ``no_progress_streak`` for a goal that did exactly the right thing.
* Absence from ``after`` is ambiguous on its own -- the goal may have been served, or it may
  simply not have been discovered this frame.  Any change has to tell those apart rather than
  read every disappearance as an answer.

**Status 2026-10-03: the defect above is fixed**, by keeping the answered sweep on the board
as ``COMPLETE`` (``tests/test_a_sweep_that_leaves_the_board_is_recorded_complete.py``).  Two
assertions here were rewritten rather than deleted, because both had encoded the defect:

* ``test_the_goal_exists_only_while_the_panel_is_closed`` -> ``test_the_goal_stops_leaving_the_board_when_it_is_answered``
* ``test_absence_is_not_by_itself_an_answer`` -> ``test_the_two_absences_are_now_told_apart``

The second rewrite is the one worth keeping an eye on: it still asserts that an unasked frame
reads ``None``, which is what stops a future change from "absence means success".
"""

import pytest

from winter_agent_v2.goal_library import GoalLibrary, progress_moved
from winter_agent_v2.models import Page, WorldState

ROLE = "R"
GOAL = "DISCOVER_QUICK_PANEL_TASKS"


def _board(panel_open):
    panel = {"open": panel_open, "rows": [{"key": "TRAINING", "label": "部队训练"}]}
    if not panel_open:
        panel["handle"] = {"state": "COLLAPSED", "point_norm": [0.5, 0.9]}
    return GoalLibrary().discover(
        WorldState(page=Page.HOME, confidence=0.99, march_used=1, march_max=6,
                   quick_panel=panel),
        role_id=ROLE, observations={},
    )


def test_the_goal_stops_leaving_the_board_when_it_is_answered():
    """The measured cause -- asserted so the diagnosis cannot quietly stop being true.

    Originally this read ``GOAL not in opened``: the row existed only while the panel was
    closed, which is why the goal had no outcome to record.  That is now **fixed**, and this
    assertion was flipped with it -- see
    ``tests/test_a_sweep_that_leaves_the_board_is_recorded_complete.py`` for the replacement
    contract (an answered sweep stays on as COMPLETE, unpriced, invisible to the Scheduler).

    What is still pinned here is the half of the cause that must not move: while the handle
    is collapsed and the board unread, the sweep has to be on the board, or nothing sends
    AUTO to the panel at all.
    """
    closed = {g.goal_id for g in _board(False)}
    assert GOAL in closed, "the sweep ticket is what sends AUTO to the panel at all"


def test_a_served_sweep_is_not_stalled_and_not_unmeasured_either():
    """``None`` must never collapse into ``False``; the third answer is now available.

    ``False`` would increment ``no_progress_streak`` and drain the fairness bonus of a goal
    that just did its job correctly -- that collapse is still forbidden, and it is why the
    fix does not read absence as failure.

    What changed: this used to assert the served sweep reads ``None``, which was the defect.
    It now reads ``True`` (the answered frame carries the row), and the ``is not False`` half
    is unchanged and still the reason a future change may not take the lazy route.
    """
    before = _board(False)
    after = _board(True)
    moved = progress_moved({GOAL: 0.5}, after, GOAL)
    assert moved is True, "answered == advanced; see the companion file for the contract"
    assert moved is not False


def test_the_two_absences_are_now_told_apart():
    """The ambiguity that stopped the cheap fix -- and the reason the fix was safe.

    The same ``None`` used to come back whether the panel opened because this goal asked it
    to, or because discovery simply did not produce the row on this frame.  Those are
    different facts, and treating every disappearance as success would have been wrong half
    the time.

    They are now told apart **by the row, not by a guess**: the served frame carries a
    COMPLETE row and reads ``True``; the MAP frame carries nothing and still reads ``None``.
    A future change that made absence mean success would break the second half of this test,
    which is the half that has to hold.
    """
    empty_board = GoalLibrary().discover(
        WorldState(page=Page.MAP, confidence=0.99, march_used=1, march_max=6), role_id=ROLE,
    )
    served = _board(True)          # panel open: the goal is present because it was answered
    unrelated = empty_board         # map: the goal is absent because it was never built
    assert progress_moved({GOAL: 0.5}, served, GOAL) is True
    assert progress_moved({GOAL: 0.5}, unrelated, GOAL) is None, (
        "an unasked frame must stay unmeasured; if this starts reading True, absence has been "
        "turned into success and the sweep will claim credit for frames nobody acted on"
    )


def test_the_sweep_is_the_only_row_that_asks_the_panel_opened():
    """The control that keeps this from being a pricing or discovery problem.

    Measured on the frame where the panel is closed: nine goals are on the board, eight of
    them carry ``reward_value = 0`` (their price lives elsewhere -- the observation ticket
    and fairness), and only this one carries 260 and names ``OPEN_QUICK_PANEL``.  So it is
    chosen, its step runs, and the panel opens.  The failure is entirely in what happens
    after -- which is what these tests are about.
    """
    board = _board(False)
    sweep = next(g for g in board if g.goal_id == GOAL)
    priced = [g for g in board if g.reward_value]
    assert [g.goal_id for g in priced] == [GOAL], (
        "this sweep is the only priced row on this frame; if that stops being true the "
        "diagnosis here is wrong and the problem is pricing"
    )
    assert sweep.available_skills == ("OPEN_QUICK_PANEL",)
    assert sweep.status.value == "READY"

