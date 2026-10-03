"""The calendar goal must not erase itself by finishing its own scan.

Measured 2026-10-03 on live revision 58dccc8b, 174 steps: EVENT frames split exactly
19/19.  The 19 carrying ``regular_events_hub`` keep ``DISCOVER_EVENT_CALENDAR`` on the
board and run ``OPEN_EVENT_CALENDAR_TAB``.  The 19 without it all read ``entries=5``
with ``details_observed=5`` -- the branch correctly reporting the scan finished -- and
then the goal was nowhere on the board, because COMPLETE carries no skills and COMPLETE
is in NOT_ACTIONABLE, so ``priority`` is ``-inf`` and ``goal_utility.rank`` drops the row.

That is a self-erasing cycle rather than a missing feature:

    HOME --(OPEN_EVENT_CALENDAR_FROM_HOME, gp=True)--> EVENT
         --(OPEN_EVENT_CALENDAR_TAB)--> CALENDAR_GRID: hub gone, goal gone
         --(BACK, "leaves_unrelated_event_session")--> HOME, and round again

19 transitions each way, every navigation step gp=True and every return step worthless.
Each hop was individually correct, which is exactly why no FAIL ever reached the ledger
and the loop ran unnoticed.  The full replay over the live frames is
``tools/calendar_completion_record_replay.py``; this file is the part that must keep
holding, so it asserts on the two states rather than on a fixture.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import GoalLibrary, GoalStatus  # noqa: E402
from winter_agent_v2.models import WorldState  # noqa: E402
from winter_agent_v2.skills import Page  # noqa: E402

CALENDAR_GOAL = "DISCOVER_EVENT_CALENDAR"


def _finished_grid() -> dict:
    """A calendar grid whose every entry has been observed -- the frame that erased it."""
    return {
        "hub": "REGULAR_EVENTS",
        "calendar": {
            "kind": "CALENDAR_GRID",
            "recognized": True,
            "visible_dates_raw": ["10/01", "10/02", "10/03"],
            "entries": [
                {"event_id": f"E{i}", "tap_norm": [0.2, 0.3], "details_observed": True}
                for i in range(5)
            ],
        },
    }


def _unfinished_grid() -> dict:
    """The same grid with one entry still to open -- which must stay actionable."""
    grid = _finished_grid()
    grid["calendar"]["entries"][0]["details_observed"] = False
    return grid


def _calendar_goal(events: dict):
    library = GoalLibrary()
    for goal in library.discover(WorldState(page=Page.EVENT, events=events)):
        if goal.goal_id == CALENDAR_GOAL:
            return goal
    return None


def test_a_finished_calendar_scan_is_still_on_the_board_and_says_why():
    goal = _calendar_goal(_finished_grid())
    assert goal is not None, (
        "a finished scan produced no DISCOVER_EVENT_CALENDAR row at all; that absence is "
        "the defect -- the goal erased itself by finishing, and the scheduler could not "
        "tell 'answered' from 'never asked'"
    )
    assert goal.status is GoalStatus.COMPLETE
    assert not goal.available_skills, (
        "a finished scan must carry no skills, or AUTO reopens the panel it just read "
        "-- this is why COMPLETE is the right state and must not be priced like READY"
    )
    # The load-bearing field: what stopped the goal from being actionable.
    assert (goal.evidence or {}).get("served_by"), (
        "a COMPLETE row has to name the precondition that stopped holding, otherwise "
        "'answered' and 'never asked' are the same thing in the ledger"
    )


def test_an_unfinished_calendar_scan_stays_actionable():
    """The other half, and the reason the fix is not simply "always COMPLETE".

    A grid with an unopened entry must keep offering the skill that opens it.  Asserting
    "finished frames are COMPLETE" alone would pass against a change that completed every
    scan unconditionally -- which would silently stop the agent ever reading an activity
    detail, and would be worse than the defect it replaced.
    """
    goal = _calendar_goal(_unfinished_grid())
    assert goal is not None
    assert goal.status is GoalStatus.READY
    assert goal.available_skills, "an unfinished scan must still say what to do next"
    assert not (goal.evidence or {}).get("served_by"), (
        "an actionable row must not claim the goal has already been served"
    )


def test_a_hub_frame_keeps_the_navigation_skills_that_get_there():
    """The path in, which the completion record must not close.

    Measured: the 19 hub frames run OPEN_EVENT_CALENDAR_TAB and stay on the board.  If
    completing a scan had been implemented by touching the hub branch, this would go.
    """
    events = {
        "hub": "REGULAR_EVENTS",
        "regular_events_hub": {
            "kind": "REGULAR_EVENT_HUB",
            "recognized": True,
            "calendar_tab_visible": True,
            "scroll_to_start_norm": None,
        },
    }
    goal = _calendar_goal(events)
    assert goal is not None
    assert goal.status is GoalStatus.READY
    assert goal.available_skills == ("OPEN_EVENT_CALENDAR_TAB",)
