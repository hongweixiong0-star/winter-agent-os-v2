"""A ticket whose own page is already on file must stop asking for it.

Measured 2026-10-05 on the live board: of the 20 ``SCHEDULED_*`` tickets, 6 carried a calendar
grid row with ``details_observed=True`` and 3 more were in a role's activity-strip
``read_entries`` -- and every one of them still declared *"this event's own page once opened"*
as its outstanding observation, so ``capability_bootstrap`` called the goal
``MISSING_OBSERVATION`` and the ticket kept being handed a read it had already performed.

These tests pin the two halves of the repair:

* the ticket's own declaration (no skills, no outstanding observation, a named wait), and
* that the project's existing consumers read it as the honest answer -- ``WAIT_UNTIL`` in the
  capability projection, ``EVENT_NOT_OPEN`` on the task board.  Both names already existed;
  no new vocabulary is introduced.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from winter_agent_v2 import goal_library, task_completion
from winter_agent_v2.capability_bootstrap import project_runtime_discovery
from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.models import Page

ROLE = "1063040265"
OBSERVED = "LIVE_DETAIL_ALREADY_OBSERVED"


def ticket(goals, event_id):
    target = f"SCHEDULED_{event_id}"
    for goal in goals:
        if goal.goal_id == target:
            return goal
    raise AssertionError(f"{target} was not emitted; got {sorted(g.goal_id for g in goals)}")


def grid_frame():
    """A ``Page.EVENT`` frame whose sub-state is the calendar grid."""
    return SimpleNamespace(
        page=Page.EVENT,
        events={"calendar": {"recognized": True, "entries": []}, "regular_events_hub": None},
    )


class TheObservedTicketStopsAsking(unittest.TestCase):
    def emit(self, *, grid_rows=(), strip_reads=(), world=None):
        """Emit the board.

        ``world`` defaults to a frame that IS the calendar grid, because that is the only frame
        where this ticket's read is offered at all (see
        ``test_a_ticket_offers_the_read_only_where_it_can_run``).  The rule these tests are about
        -- "already on file" -- is independent of the frame, so the default keeps them about one
        thing.
        """
        if world is None:
            world = grid_frame()
        goals = []
        with mock.patch.object(goal_library, "_strip_read_entries",
                               return_value=tuple(strip_reads)):
            GoalLibrary()._append_known_activities(
                goals,
                role_id=ROLE,
                world=world,
                calendar_snapshot={"entries": list(grid_rows), "observed_at": "2026-10-05T00:00:00+00:00",
                                   "role_id": ROLE},
            )
        return goals

    # -- the rule ---------------------------------------------------------------

    def test_a_grid_row_whose_detail_was_opened_stops_the_ticket_asking(self):
        goals = self.emit(grid_rows=[{"event_id": "CANYON_CLASH", "details_observed": True}])
        found = ticket(goals, "CANYON_CLASH")
        self.assertEqual(found.available_skills, ())
        self.assertIsNone(found.evidence["required_observation"])
        self.assertEqual(found.evidence["condition"], "waiting_window")
        self.assertEqual(found.evidence["availability_state"], OBSERVED)

    def test_a_strip_read_entry_stops_the_ticket_asking_too(self):
        """The second record: the activity strip's ``read_entries``."""
        goals = self.emit(strip_reads=[{"event_id": "STATE_VS_STATE"}])
        found = ticket(goals, "STATE_VS_STATE")
        self.assertEqual(found.available_skills, ())
        self.assertIsNone(found.evidence["required_observation"])
        self.assertEqual(found.evidence["condition"], "waiting_window")

    def test_a_discovered_calendar_row_obeys_the_same_rule(self):
        """The second emission loop, whose rows carry ``details_observed`` directly."""
        goals = self.emit(grid_rows=[{"event_id": "DISCOVERED_EVENT_TEST", "details_observed": True}])
        found = ticket(goals, "DISCOVERED_EVENT_TEST")
        self.assertEqual(found.available_skills, ())
        self.assertIsNone(found.evidence["required_observation"])
        self.assertEqual(found.evidence["availability_state"], OBSERVED)

    # -- what must NOT change ---------------------------------------------------

    def test_an_unopened_detail_keeps_its_observation_ticket(self):
        goals = self.emit(grid_rows=[{"event_id": "CANYON_CLASH", "details_observed": False}])
        found = ticket(goals, "CANYON_CLASH")
        self.assertEqual(found.available_skills, ("READ_EVENT_CALENDAR",))
        self.assertTrue(found.evidence["required_observation"])
        self.assertNotIn("condition", found.evidence)

    def test_a_grid_row_with_no_details_flag_does_not_count_as_observed(self):
        """``details_observed`` absent is 'not recorded', never 'recorded as done'."""
        goals = self.emit(grid_rows=[{"event_id": "CANYON_CLASH"}])
        found = ticket(goals, "CANYON_CLASH")
        self.assertEqual(found.available_skills, ("READ_EVENT_CALENDAR",))
        self.assertTrue(found.evidence["required_observation"])

    def test_another_events_observation_does_not_mark_this_one(self):
        goals = self.emit(grid_rows=[{"event_id": "CANYON_CLASH", "details_observed": True}])
        found = ticket(goals, "BEAR_HUNT")
        self.assertEqual(found.available_skills, ("READ_EVENT_CALENDAR",))
        self.assertTrue(found.evidence["required_observation"])

    def test_every_ticket_still_carries_the_observation_key(self):
        """Readers test the key, not its truthiness -- dropping it would be a second shape."""
        for goal in self.emit():
            self.assertIn("required_observation", goal.evidence)

    # -- the consumers read it as the honest answer ------------------------------

    def test_the_task_board_names_the_wait_instead_of_a_missing_observation(self):
        goals = self.emit(grid_rows=[{"event_id": "CANYON_CLASH", "details_observed": True}])
        found = ticket(goals, "CANYON_CLASH")
        code, _ = task_completion._reason_code(
            {"status": found.status.value, "evidence": dict(found.evidence)}
        )
        self.assertEqual(code, "EVENT_NOT_OPEN")

    def test_the_capability_projection_calls_it_wait_until_not_missing_observation(self):
        goals = self.emit(grid_rows=[{"event_id": "CANYON_CLASH", "details_observed": True}])
        found = ticket(goals, "CANYON_CLASH")
        projected = project_runtime_discovery(
            [found], SimpleNamespace(page=Page.HOME, events={}), role_id=ROLE, frame_id="f-1",
        )
        rows = {str(row.get("goal_id")): row for row in projected.diagnostics}
        self.assertIn("SCHEDULED_CANYON_CLASH", rows)
        self.assertEqual(rows["SCHEDULED_CANYON_CLASH"]["reason"], "WAIT_UNTIL")

    def test_an_unobserved_ticket_still_reports_a_missing_observation(self):
        """The other half of the same projection, so the change cannot be 'always WAIT_UNTIL'."""
        goals = self.emit()
        found = ticket(goals, "CANYON_CLASH")
        projected = project_runtime_discovery(
            [found], SimpleNamespace(page=Page.HOME, events={}), role_id=ROLE, frame_id="f-1",
        )
        rows = {str(row.get("goal_id")): row for row in projected.diagnostics}
        self.assertEqual(rows["SCHEDULED_CANYON_CLASH"]["reason"], "MISSING_OBSERVATION")


if __name__ == "__main__":
    unittest.main()
