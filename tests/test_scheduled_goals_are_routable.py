"""The UNKNOWN -> observation chain: a goal the library emits must be routable, and only a routable
goal may be priced onto the board.

WB-1002-24.  Measured on the live board 2026-10-02, 32 goals, 23 UNKNOWN with no ``available_skills``
and ``priority: None`` on the panel.  Two complementary halves of one requirement were missing, and
each half is fatal on its own:

* **20 ``SCHEDULED_*`` goals have no route.**  ``runtime_snapshot.capability_discovery`` classifies
  every one as ``MISSING_NAVIGATION`` / ``NAVIGATION_GAP`` with ``route_exists=False``, and
  ``tools/full_auto_coverage_audit.py`` prices them at ``chooser_base = -inf`` with the reason
  ``OFF_BOARD_NOTHING_DECLARED``.  Their own evidence already declares the route: ``SCHEDULED_BEAR_
  HUNT`` carries ``registered_goal_ids: ["DISCOVER_EVENT_CALENDAR"]`` and the discovered-event rows
  carry ``["DISCOVER_EVENT_CALENDAR", "EVENT_MINIMUM_GUARANTEE"]`` -- **all three are ``EVENT``**.
  They also state ``availability_state: AWAITING_LIVE_CLIENT_READING`` / ``CALENDAR_PREVIEW_ONLY``,
  i.e. "waiting for a live read", but never set ``required_observation``, which is the only field
  ``goal_utility.observation_ticket`` reads to decide that a goal is worth going to read.

* **3 goals carry a ticket and no route** (``ALLIANCE_TIMED_EVENTS``, ``USE_FREE_ARENA_ATTEMPTS``,
  ``LABYRINTH_DAILY``).  That is the mirror defect and the more dangerous one: the ticket prices
  them at the 50.0 floor, ``capability_gate.blocks`` only consults capability and no-progress
  deferrals -- it never asks whether the goal has any skill -- so they pass ``_selectable``, and a
  selected goal with no route is given ``brain.current_goal = None``, which is the state the existing
  test's own docstring records: *"a goal that is missing from that table is not 'handled elsewhere'
  -- it is scheduled, given current_goal=None, and left to whatever RuleBrain does with no goal at
  all.  That is how four panel routines stayed invisible while their capabilities worked: the goals
  were emitted, priced, selected, and then produced no action."*  ``_append_prepared_workflows``
  says the same thing from the other side: these records "deliberately have no skills ... registering
  the workflow must not invite the scheduler to navigate by guessed controls or prior-only data".

So one rule closes both: **ticketed implies routable**, and the ``SCHEDULED_*`` family is routable
because its own evidence says so.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_schedule  # noqa: E402
from winter_agent_v2 import goal_utility  # noqa: E402
from winter_agent_v2.goal_library import (  # noqa: E402
    ROUTE_DOMAINS,
    GoalLibrary,
    GoalState,
    GoalStatus,
    route_for,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

#: One real role, so the calendar snapshot is the one the runtime would load rather than a shape
#: this test invented.  A fixture that does not come from the client is a fixture that cannot fail
#: for the reason the defect exists.
ROLE = "1061663148"

SCHEDULED_IDS = (
    "SCHEDULED_BEAR_HUNT",
    "SCHEDULED_BROTHERS_IN_ARMS",
    "SCHEDULED_CANYON_CLASH",
    "SCHEDULED_FORTRESS_CONTEST",
    "SCHEDULED_UNDERGROUND_EXPLORATION",
    "SCHEDULED_FISHING_TOURNAMENT",
    "SCHEDULED_ICEBOUND_TREASURE",
    "SCHEDULED_DISCOVERED_EVENT_4178AC2F00",
)


class TheScheduledFamilyHasARouteTests(unittest.TestCase):
    def test_an_activity_row_carries_the_route_its_own_evidence_names(self) -> None:
        """The row's ``registered_goal_ids`` are the declaration; every one of them is EVENT."""
        for goal_id in SCHEDULED_IDS:
            self.assertEqual(route_for(goal_id), "EVENT", goal_id)

    def test_the_prefix_rule_covers_ids_no_table_could_enumerate(self) -> None:
        """``SCHEDULED_{event_id}`` is generated per discovered event, so a table cannot hold it.

        The same function already answers ``CLAIM_FREE_*`` by prefix for exactly this reason.
        """
        for goal_id in ("SCHEDULED_ANY_NEW_EVENT",
                        "SCHEDULED_DISCOVERED_EVENT_0000000000",
                        "SCHEDULED_ICEBOUND_TREASURE_MYSTERY_SHOP"):
            self.assertEqual(route_for(goal_id), "EVENT", goal_id)
        # And the rule must not swallow anything else.
        self.assertIsNone(route_for("SCHEDULEDX_NOT_A_FAMILY"))
        self.assertIsNone(route_for("NOT_SCHEDULED_AT_ALL"))

    def test_every_goal_the_library_emits_from_a_calendar_has_a_route(self) -> None:
        """The family is enumerated from the calendar-carrying world state, not from a list.

        ``tests/test_every_goal_has_a_route.py`` sweeps pages and collects "the ids that only appear
        from a reading", but none of its pages carries a calendar, so the branch that emits
        ``SCHEDULED_*`` was never reached and 20 unrouted goals hid behind a green test.  This drives
        that branch with the runtime's own snapshot loader.
        """
        snapshot = event_schedule.latest_calendar_snapshot(ROLE)
        self.assertTrue(snapshot, "no calendar snapshot on disk: this test would be vacuous")
        library = GoalLibrary()
        goals = library.discover(
            WorldState(page=Page.HOME, confidence=0.99),
            role_id=ROLE,
            calendar_snapshot=snapshot,
        )
        self.assertTrue(goals)
        unrouted = sorted(
            goal.goal_id for goal in goals
            if goal.goal_id.startswith("SCHEDULED_") and route_for(goal.goal_id) is None
        )
        self.assertEqual(unrouted, [], "this goal is scheduled and inert")
        self.assertTrue(any(goal.goal_id.startswith("SCHEDULED_") for goal in goals),
                        "the calendar branch emitted nothing: the enumeration is vacuous again")


class AnActivityRowSaysWhatMustBeReadTests(unittest.TestCase):
    def test_the_row_that_says_it_is_awaiting_a_reading_declares_what_to_read(self) -> None:
        """``availability_state`` is prose; ``required_observation`` is the field the ticket reads."""
        snapshot = event_schedule.latest_calendar_snapshot(ROLE)
        library = GoalLibrary()
        goals = library.discover(
            WorldState(page=Page.HOME, confidence=0.99),
            role_id=ROLE,
            calendar_snapshot=snapshot,
        )
        scheduled = [goal for goal in goals if goal.goal_id.startswith("SCHEDULED_")]
        self.assertTrue(scheduled)
        silent = sorted(goal.goal_id for goal in scheduled
                        if not (goal.evidence or {}).get("required_observation"))
        self.assertEqual(silent, [],
                         "a goal that is waiting for a live reading must say which reading")

    def test_the_declaration_is_what_earns_the_ticket(self) -> None:
        """End to end on the real objects: the row is UNKNOWN, so the ticket is the only way in."""
        snapshot = event_schedule.latest_calendar_snapshot(ROLE)
        goals = GoalLibrary().discover(
            WorldState(page=Page.HOME, confidence=0.99),
            role_id=ROLE,
            calendar_snapshot=snapshot,
        )
        unknown = [goal for goal in goals
                   if goal.goal_id.startswith("SCHEDULED_")
                   and str(getattr(goal.status, "value", goal.status)) == "UNKNOWN"]
        self.assertTrue(unknown, "without an UNKNOWN row this test measures nothing")
        for goal in unknown:
            self.assertGreater(
                goal_utility.observation_ticket(goal), 0.0,
                f"{goal.goal_id} is UNKNOWN, states what to read, and still gets no ticket",
            )


class AnUnroutedGoalStaysOnTheBoardButIsNotActedOnTests(unittest.TestCase):
    """Both halves at once, because each half alone is a defect.

    The first version of this fix required a route before a goal could be priced at all, and
    ``tools/invariant_review.py`` refuted it outright: ``NO_PERMANENT_UNKNOWN_BLACKHOLE``,
    ``HIGH_VALUE_UNKNOWN_NOT_STARVED`` and ``NEVER_OBSERVED_UNKNOWN_STILL_ON_BOARD`` all define "on
    the board" as the ticket's answer, and the third one's own docstring says why --
    "a never-observed UNKNOWN that declares what it waits for" must be on the board *even when
    nothing can act on it yet*.  So the board keeps it and the refusal moves to where the step would
    happen.
    """

    @staticmethod
    def _runtime():
        class _Gate:
            reload_pending = False

            def blocks(self, *_args, **_kwargs):
                return None

        runtime = LiveRuntime.__new__(LiveRuntime)
        runtime.execution_mode = "PRODUCTION"
        runtime.validation_scope = {}
        runtime.device_lease = None
        runtime._yielded_goals = set()
        runtime._unrouted_goals = set()
        runtime._printed_deferrals = set()
        runtime._policy_allows = lambda _goal_id: True
        runtime._gate = lambda: _Gate()
        return runtime

    def test_an_unrouted_goal_keeps_its_ticket_so_it_stays_on_the_board(self) -> None:
        """The refuted design, pinned as a refutation so nobody re-tries it quietly."""
        goal = GoalState("LABYRINTH_DAILY", GoalStatus.UNKNOWN,
                         evidence={"required_observation": "Labyrinth attempts counter"})
        self.assertIsNone(route_for("LABYRINTH_DAILY"))
        self.assertGreater(
            goal_utility.observation_ticket(goal), 0.0,
            "unpriced and invisible is §5's forbidden blackhole; priced but not actable is honest",
        )
        self.assertIn("LABYRINTH_DAILY",
                      [g.goal_id for g, _ in goal_utility.rank([goal], world=WorldState(page=Page.HOME))])

    def test_the_run_refuses_to_act_on_it_and_says_why(self) -> None:
        """The step is what must not happen: no route means ``brain.current_goal = None``.

        ``_sync_brain_goal`` sets the brain's route from ``route_for(goal_id)``, so a null route
        leaves ``RuleBrain`` in its default branch -- its gather branch.  A goal that says the map
        has no reader for its counter must not reach that.
        """
        runtime = self._runtime()
        deferrals: list = []
        unrouted = GoalState("LABYRINTH_DAILY", GoalStatus.UNKNOWN,
                             evidence={"required_observation": "Labyrinth attempts counter"})
        routable = GoalState("SCHEDULED_BEAR_HUNT", GoalStatus.UNKNOWN,
                             evidence={"required_observation": "the event's live window"})
        kept = runtime._selectable([unrouted, routable], deferrals)
        ids = [goal.goal_id for goal in kept]
        self.assertNotIn("LABYRINTH_DAILY", ids, "an unrouted goal must not become a step")
        self.assertIn("SCHEDULED_BEAR_HUNT", ids)
        self.assertIn("LABYRINTH_DAILY", runtime._unrouted_goals,
                      "the refusal has to be readable from the artifacts afterwards")

    def test_a_routable_goal_keeps_its_ticket(self) -> None:
        """The rule must not cost the mechanism its purpose."""
        routable = GoalState("SCHEDULED_BEAR_HUNT", GoalStatus.UNKNOWN,
                             evidence={"required_observation": "the event's live window"})
        self.assertIsNotNone(route_for(routable.goal_id))
        self.assertGreater(goal_utility.observation_ticket(routable), 0.0)

    def test_the_route_table_and_the_entry_hint_table_agree_on_names(self) -> None:
        """Two tables name the same domains; ``TRAIN`` vs ``TRAINING`` silently disabled hints.

        ``runtime`` reads ``hints[route_for(goal_id)]`` to build entry-observation candidates from
        the current frame's labels.  The hint table was keyed ``TRAINING`` while the route domain is
        ``TRAIN``, so every training goal got an empty label set and no entry candidate -- a defect
        that cannot be seen from either table alone.

        The assertion is about **names**, not coverage: a hint table entry that names something which
        is not a route domain is a typo that disables a domain quietly, whereas a route domain with
        no entry is a recorded absence (this project's own labels are what may go in).
        """
        from winter_agent_v2.runtime import ROUTE_ENTRY_HINTS

        self.assertIn("TRAIN", ROUTE_ENTRY_HINTS, "the route domain must be the key")
        self.assertNotIn("TRAINING", ROUTE_ENTRY_HINTS, "that name is not a route domain")
        unknown = sorted(set(ROUTE_ENTRY_HINTS) - set(ROUTE_DOMAINS) - {"ARENA"})
        self.assertEqual(unknown, [], "these hint keys name something that is not a route")
        for route, labels in ROUTE_ENTRY_HINTS.items():
            self.assertTrue(labels and all(str(label).strip() for label in labels), route)


if __name__ == "__main__":
    unittest.main()
