"""A ticket offers the calendar read only on the frame where that read can pass.

``Page.EVENT`` covers two mutually exclusive sub-states and the read's verifier is satisfiable
in one of them.  Measured 2026-10-05 over the retained ledger:

* 9387 recorded frames split 7724 neither / **1173 regular-events hub** / **490 calendar grid**,
  never both;
* replaying ``verify_event_calendar_read`` over every captured grid frame passes **979/979**;
* all **40** production executions of ``READ_EVENT_CALENDAR`` stood on the hub and failed
  **40/40** (``calendar_recognized=false``, ``visible_dates=[]``, ``entry_count=0``).

So handing the read over on a hub or HOME frame is an action that cannot run -- the infinite
retry §0 forbids.  Withholding it is §5's ExecutionReadiness answering "how should this be
handled now", not the Goal losing its place on the board, and these tests pin both halves:
the skill follows the frame, the ticket and its status do not.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from winter_agent_v2 import goal_library
from winter_agent_v2.goal_library import GoalLibrary, _frame_shows_calendar_grid
from winter_agent_v2.models import Page

ROLE = "1063040265"
READ = ("READ_EVENT_CALENDAR",)


def grid_frame():
    return SimpleNamespace(
        page=Page.EVENT,
        events={"calendar": {"recognized": True, "entries": []}, "regular_events_hub": None},
    )


def hub_frame():
    return SimpleNamespace(
        page=Page.EVENT,
        events={"calendar": None,
                "regular_events_hub": {"recognized": True, "calendar_tab_visible": False}},
    )


def home_frame():
    return SimpleNamespace(page=Page.HOME, events={})


def emit(world, *, grid_rows=()):
    goals = []
    with mock.patch.object(goal_library, "_strip_read_entries", return_value=()):
        GoalLibrary()._append_known_activities(
            goals, role_id=ROLE, world=world,
            calendar_snapshot={"entries": list(grid_rows), "observed_at": "2026-10-05T00:00:00+00:00",
                               "role_id": ROLE},
        )
    return goals


def ticket(goals, event_id):
    target = f"SCHEDULED_{event_id}"
    for goal in goals:
        if goal.goal_id == target:
            return goal
    raise AssertionError(f"{target} was not emitted")


class TheReadFollowsTheFrame(unittest.TestCase):
    def test_on_the_grid_an_unobserved_ticket_carries_the_read(self):
        found = ticket(emit(grid_frame()), "BEAR_HUNT")
        self.assertEqual(found.available_skills, READ)

    def test_on_the_hub_it_carries_none(self):
        """The measured case: 40 executions, all here, all failures."""
        found = ticket(emit(hub_frame()), "BEAR_HUNT")
        self.assertEqual(found.available_skills, ())

    def test_on_home_it_carries_none(self):
        found = ticket(emit(home_frame()), "BEAR_HUNT")
        self.assertEqual(found.available_skills, ())

    def test_no_frame_makes_an_observed_ticket_carry_the_read(self):
        """The other rule wins where both apply."""
        rows = [{"event_id": "BEAR_HUNT", "details_observed": True}]
        for world in (grid_frame(), hub_frame(), home_frame()):
            found = ticket(emit(world, grid_rows=rows), "BEAR_HUNT")
            self.assertEqual(found.available_skills, ())

    def test_the_ticket_keeps_its_place_on_the_board_in_every_frame(self):
        """§5/§32: readiness changes, existence does not."""
        counts = []
        for world in (grid_frame(), hub_frame(), home_frame()):
            goals = emit(world)
            counts.append(len(goals))
            found = ticket(goals, "BEAR_HUNT")
            self.assertEqual(found.status.value, "UNKNOWN")
            self.assertTrue(found.evidence["required_observation"])
        # The registered activities are emitted identically; no frame drops one.
        self.assertEqual(len(set(counts)), 1)

    def test_the_frame_predicate_reads_the_calendar_and_nothing_else(self):
        self.assertTrue(_frame_shows_calendar_grid(grid_frame()))
        self.assertFalse(_frame_shows_calendar_grid(hub_frame()))
        self.assertFalse(_frame_shows_calendar_grid(home_frame()))
        self.assertFalse(_frame_shows_calendar_grid(None))
        self.assertFalse(_frame_shows_calendar_grid(
            SimpleNamespace(page=Page.EVENT, events={"calendar": {"recognized": False}})))
        self.assertFalse(_frame_shows_calendar_grid(
            SimpleNamespace(page=Page.EVENT, events=None)))


if __name__ == "__main__":
    unittest.main()
