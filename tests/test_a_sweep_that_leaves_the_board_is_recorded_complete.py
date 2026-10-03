"""A sweep that is answered by leaving must be recorded as complete, not as unmeasured.

Follows ``tests/test_sweep_that_leaves_the_board_is_unrecorded.py``, which pinned the
defect without proposing a fix.  That file's ``test_the_goal_exists_only_while_the_panel_is_closed``
is *expected to fail from here on*, and its docstring says to read that failure as a fix
rather than a regression.  This file is the other half: it says what the row must say instead.

The change is one row, and it copies a shape that already exists in this module rather than
inventing one.  ``goal_library.py`` already keeps a finished goal on the board as
``GoalStatus.COMPLETE`` with ``completion=1.0`` and ``distance=0.0`` and no
``available_skills`` -- ``ALLIANCE_DONATION`` at line 1109 does it for ``status ==
"CONTRIBUTED"``, ``CLEAR_INTEL`` at line 1118 for an expired intel row.  So there is no new
status, no new meter and no new channel: the sweep says the same thing those two already say.

Why this is honest rather than convenient
-----------------------------------------
``DISCOVER_QUICK_PANEL_TASKS`` exists to make AUTO *look at* the daily board once.  Its
whole content is "the handle is collapsed and the board has not been read".  The frame where
the panel is open therefore satisfies it -- the look happened.  Marking that ``COMPLETE`` is
the same statement ``CLEAR_INTEL`` makes when its refresh window closes.

What it is **not** is a statement that the daily board is finished.  That is why the row
keeps ``reward_value=0`` and declares no skills: it must not be re-selectable, or AUTO would
re-open the panel it just opened, forever.  ``GoalState.priority`` returns ``-inf`` for every
status in ``NOT_ACTIONABLE``, and ``goal_utility.rank`` drops a ``-inf`` breakdown, so the row
is inert for the Scheduler by construction rather than by a check somebody has to remember.

The two accounting channels this repairs
----------------------------------------
* ``newly_completed_goal_ids`` requires a COMPLETE row in ``after``.  With the row present and
  the before-frame row READY, the transition is counted -- which is the first time this goal
  has ever produced an outcome in 1291 selections.
* ``progress_moved`` starts ``now = next((goal for goal in after ...), None)`` and returns
  ``None`` when the row is absent.  Now the row is there, ``distance`` reads 0.0 against the
  remembered 0.5, and ``0.0 < 0.5`` is progress.  The goal stops being permanently unmeasured.

Both channels were silent for the same reason, and one row fixes both because it gives them
the thing they were both missing: a row on the frame that answers the question.
"""

import pytest

from winter_agent_v2.goal_library import (
    GoalLibrary,
    GoalStatus,
    newly_completed_goal_ids,
    progress_moved,
)
from winter_agent_v2.goal_utility import UtilityBreakdown, rank
from winter_agent_v2.models import Page, WorldState

ROLE = "R"
GOAL = "DISCOVER_QUICK_PANEL_TASKS"
SKILL = "OPEN_QUICK_PANEL"


def _board(panel_open):
    panel = {"open": panel_open, "rows": [{"key": "TRAINING", "label": "部队训练"}]}
    if not panel_open:
        panel["handle"] = {"state": "COLLAPSED", "point_norm": [0.5, 0.9]}
    return GoalLibrary().discover(
        WorldState(page=Page.HOME, confidence=0.99, march_used=1, march_max=6,
                   quick_panel=panel),
        role_id=ROLE, observations={},
    )


def _sweep(board):
    return next(g for g in board if g.goal_id == GOAL)


def test_the_answered_sweep_stays_on_the_board_as_complete():
    """The row the other file said was missing, and what it must say.

    ``COMPLETE`` here is "this occurrence was answered", the same claim ``CLEAR_INTEL``
    makes when its window closes.  It is not "the daily board is finished" -- that is why
    the row is unpriced and skill-less below.
    """
    answered = _sweep(_board(True))
    assert answered.status is GoalStatus.COMPLETE
    assert answered.completion == 1.0
    assert answered.distance == 0.0


def test_completion_names_the_evidence_that_answered_it():
    """A COMPLETE row with no evidence is indistinguishable from a guess.

    The source records the one thing this frame proves -- the panel is open -- and
    ``served_by`` names the precondition that stopped holding, so an auditor can tell
    "answered" from "never asked" without replaying the frame.
    """
    answered = _sweep(_board(True))
    assert answered.evidence["source"] == "LIVE_QUICK_PANEL_OPEN"
    assert answered.evidence["panel_open"] is True
    assert answered.evidence["served_by"] == SKILL
    assert "reward_value" not in answered.evidence


def test_an_answered_sweep_is_not_re_selectable():
    """The failure mode this shape has to avoid: re-opening the panel forever.

    A COMPLETE row priced like the READY one would outrank most of the board (260 against
    a field where eight of nine rows carry 0) and AUTO would reopen what it just opened.
    So the row carries no price and no skills, and ``priority`` is ``-inf``.
    """
    answered = _sweep(_board(True))
    assert answered.reward_value == 0.0
    assert answered.available_skills == ()
    assert answered.priority == float("-inf")


def test_the_scheduler_cannot_see_it():
    """``priority == -inf`` is only a claim until ``rank`` agrees.

    This is the property that makes the whole change safe: the row exists for the two
    accounting channels, which read the board ``discover`` returned, and is invisible to
    the one channel that acts on it.  Measured on this frame the open panel leaves 26 other
    rows ranked, so the assertion is scoped to this goal -- the point is that the sweep is
    gone from ranking, not that the board empties.
    """
    board = rank(_board(True), ledger={})
    assert board, "the open panel still carries the rest of the board; this is the control"
    assert all(goal.goal_id != GOAL for goal, _ in board)
    assert GOAL in {g.goal_id for g in _board(True)}, (
        "the row has to be on the board for the accounting channels to see it at all"
    )


def test_the_closed_panel_still_offers_the_sweep_at_260():
    """The control: the fix must not weaken the ticket that does the work.

    Without this, a change that quietly dropped the row would pass every test above.
    """
    pending = _sweep(_board(False))
    assert pending.status is GoalStatus.READY
    assert pending.reward_value == 260
    assert pending.available_skills == (SKILL,)
    assert pending.distance == 0.5


def test_both_accounting_channels_now_answer():
    """The point of the whole change, asserted through the real functions.

    ``observed`` carries the remembered 0.5 from the frame where the handle was collapsed,
    exactly as ``runtime._remember_goal_meters`` wrote it.
    """
    before, after = _board(False), _board(True)
    observed = {GOAL: 0.5}
    assert progress_moved(observed, after, GOAL) is True
    assert newly_completed_goal_ids(before, after, [GOAL]) == (GOAL,)


def test_an_unasked_frame_is_still_merely_unmeasured():
    """The ambiguity the previous file refused to resolve, now resolved by position.

    On a MAP frame the sweep is absent because nothing asked -- no row, no completion, and
    ``progress_moved`` still says "not measured".  This is the case that made "absence means
    served" wrong, and it is unchanged: the answer comes from the row existing, not from a
    guess about why it does not.
    """
    map_board = GoalLibrary().discover(
        WorldState(page=Page.MAP, confidence=0.99, march_used=1, march_max=6), role_id=ROLE,
    )
    assert all(g.goal_id != GOAL for g in map_board)
    assert progress_moved({GOAL: 0.5}, map_board, GOAL) is None
    assert newly_completed_goal_ids(_board(False), map_board, [GOAL]) == ()