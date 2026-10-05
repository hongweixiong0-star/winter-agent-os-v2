"""The board's "至" must be the deadline the gate actually applies.

Measured 2026-10-05, on the live board: ``DAILY_ACTIVITY_TARGET`` was rendered

    READ_DAILY_PROGRESS：repair budget exhausted (2/2) after CODE_CHANGED · [BLOCKED] · 至 2026-09-23T…

while that goal had produced an episode 28 minutes earlier and the gate would admit
it again 180 minutes after that attempt.  The printed value was the escalation
ledger's own ``cooldown_until`` -- one of the gate's two possible anchors, and the
older one.  Reading it, the natural conclusion was "three goals permanently stalled";
the measurement was "three goals on a three-hourly probe".

So ``until`` has exactly one meaning -- the moment this deferral stops applying --
and ``blocks()`` has to publish the deadline it judged with, not the field it
happened to start from.  These tests pin the two together: the published value is
checked against the gate's own answer one second either side.
"""

import unittest
from datetime import datetime, timedelta, timezone

from winter_agent_v2.capability_gate import (
    BLOCKED,
    BLOCKED_PROBE_MINUTES,
    COOLDOWN,
    DEFERRED,
    NO_PROGRESS_PROBE_MINUTES,
    SOURCE_NO_PROGRESS,
    SOURCE_QUEUE,
    CapabilityGate,
)
from winter_agent_v2.goal_library import GoalComposition, GoalState, GoalStatus

NOW = datetime(2026, 10, 5, 2, 23, tzinfo=timezone.utc)


def goal(goal_id="SEQ"):
    return GoalState(goal_id, GoalStatus.READY, available_skills=("SKILL",))


def seq_gate(**kwargs):
    base = {
        "compositions": {"SEQ": GoalComposition("SEQ", "SEQUENCE", ("A", "B"))},
        "capabilities": {},
        "streaks": {},
        "attempted": {},
        "reached": {},
    }
    base.update(kwargs)
    return CapabilityGate(**base)


class ThePublishedDeadlineIsTheOneItApplies(unittest.TestCase):
    def test_a_spent_budget_publishes_the_probe_window_not_the_ledger_field(self):
        """The ledger deadline is 12 days past; the applied deadline is 3 hours out."""
        ledger_deadline = NOW - timedelta(days=12)
        attempted_at = NOW - timedelta(minutes=28)
        gate = seq_gate(
            capabilities={"A": (BLOCKED, "repair budget exhausted (2/2)", ledger_deadline)},
            streaks={"SEQ": (1, attempted_at, "A", (1, 0, 0))},
        )
        found = gate.blocks(goal(), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.state, BLOCKED)
        self.assertEqual(
            found.until, attempted_at + timedelta(minutes=BLOCKED_PROBE_MINUTES),
            "the board must show when the path is re-admitted, not the ledger's older field",
        )
        self.assertNotEqual(found.until, ledger_deadline)
        self.assertEqual(found.probe_minutes, BLOCKED_PROBE_MINUTES)

    def test_the_published_deadline_is_exactly_when_the_goal_is_admitted_again(self):
        """One second either side of the published value, judged by the gate itself."""
        attempted_at = NOW - timedelta(minutes=28)
        gate = seq_gate(
            capabilities={"A": (BLOCKED, "repair budget exhausted (2/2)", NOW - timedelta(days=12))},
            streaks={"SEQ": (1, attempted_at, "A", (1, 0, 0))},
        )
        found = gate.blocks(goal(), now=NOW)
        self.assertIsNotNone(found)
        published = found.until
        self.assertIsNotNone(published)
        self.assertIsNotNone(
            gate.blocks(goal(), now=published - timedelta(seconds=1)),
            "one second before the published deadline the path is still held",
        )
        self.assertIsNone(
            gate.blocks(goal(), now=published),
            "at the published deadline the path is admitted -- that is what it claims",
        )

    def test_no_progress_publishes_its_own_shorter_window(self):
        gate = seq_gate(
            streaks={"SEQ": (5, NOW - timedelta(minutes=2), "EAT", (0, 0, 5))},
            attempted={"SEQ": frozenset({"EAT"})},
        )
        found = gate.blocks(goal(), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.state, DEFERRED)
        self.assertEqual(found.source, SOURCE_NO_PROGRESS)
        self.assertEqual(
            found.until, NOW - timedelta(minutes=2) + timedelta(minutes=NO_PROGRESS_PROBE_MINUTES),
        )

    def test_a_pending_reload_publishes_the_horizon_it_would_apply(self):
        """The reload branch is a re-labelling, not a different deadline."""
        attempted_at = NOW - timedelta(minutes=28)
        gate = seq_gate(
            capabilities={"A": (BLOCKED, "repair budget exhausted (2/2)", NOW - timedelta(days=12))},
            streaks={"SEQ": (1, attempted_at, "A", (1, 0, 0))},
            reload_pending=True,
        )
        found = gate.blocks(goal(), now=NOW)
        self.assertIsNotNone(found)
        self.assertIn("a runtime reload is pending", found.reason)
        self.assertEqual(
            found.until, attempted_at + timedelta(minutes=BLOCKED_PROBE_MINUTES),
        )

    def test_a_cooldown_still_publishes_the_ledger_deadline(self):
        """The one state where the ledger field *is* the deadline keeps behaving."""
        deadline = NOW + timedelta(minutes=40)
        gate = seq_gate(
            capabilities={"A": (COOLDOWN, "cooling down after 1 repair shot(s)", deadline)},
        )
        found = gate.blocks(goal(), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.state, COOLDOWN)
        self.assertEqual(found.until, deadline)

    def test_an_unreachable_anchor_publishes_no_deadline_rather_than_a_stale_one(self):
        """Nothing has been measured and the ledger carries no deadline of its own.

        Then the honest "至" is nothing at all -- printing some older field would make
        an indefinite hold look scheduled.  (This is also the one shape that really is
        indefinite: ``_probe_lapsed`` answers ``False`` when there is no anchor, which
        is why the row must not invent one.)
        """
        gate = seq_gate(
            capabilities={"A": (BLOCKED, "repair budget exhausted (2/2)", None)},
            streaks={"SEQ": (3, None, "", None)},
        )
        found = gate.blocks(goal(), now=NOW)
        self.assertIsNotNone(found)
        self.assertIsNone(found.until)


if __name__ == "__main__":
    unittest.main()
