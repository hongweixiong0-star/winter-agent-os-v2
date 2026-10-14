"""Retiring a record whose premise production data has falsified.

Before the ``FALSIFIED`` state existed there was no honest way to retire such a record:
``FAILED`` says a job ran and lost, ``BLOCKED`` says something external is in the way, and
neither is true of a premise that is simply no longer true.  So the record sat in ``NEW``
for ever -- and the preload gate is zero-tolerance (``capability_bootstrap.preload_gate``
refuses to dispatch while ``pending_records > 0``), so one stale record stopped the whole
route.  Measured 2026-10-14: 11 of the 17 pending records were exactly this shape.

These pin the two halves the operator's decision buys: the row leaves ``pending()``, and the
gate that reads the count therefore stops refusing.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from winter_agent_v2 import capability_bootstrap as bootstrap
from winter_agent_v2 import escalation_queue as q

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _created(key: str, *, goal: str = "BEAST_SEARCH", skill: str = "SUBMIT_BEAST_SEARCH") -> dict:
    return {
        "event": "escalation_created", "key": key,
        "capability": "BEAST_SEARCH", "condition": q.CAPABILITY_MISSING,
        "goal": goal, "skill": skill,
        "recorded_at": NOW.isoformat(),
    }


class PremiseFalsifiedTests(unittest.TestCase):
    def test_a_falsified_record_is_terminal_and_carries_its_reason(self):
        snapshot = q.fold([
            _created("K1"),
            {"event": "premise_falsified", "key": "K1",
             "reason": "the goal advanced after the record was filed",
             "premise": "FALSIFIED_SINCE_FILING",
             "measured_at": NOW.isoformat()},
        ])
        record = snapshot.records["K1"]
        self.assertEqual(record.state, q.FALSIFIED)
        self.assertTrue(any("premise falsified" in note for note in record.notes), record.notes)
        # The reason and the premise travel with the row, so a reader does not infer them
        # from an absence.
        self.assertTrue(any("FALSIFIED_SINCE_FILING" in note for note in record.notes))

    def test_pending_counts_new_and_queued_only(self):
        snapshot = q.fold([
            _created("STILL_NEW"),
            _created("WAS_QUEUED"),
            {"event": "queued", "key": "WAS_QUEUED", "recorded_at": NOW.isoformat()},
            _created("RETIRED"),
            {"event": "premise_falsified", "key": "RETIRED",
             "reason": "the skill it names has zero episodes",
             "premise": "SKILL_NEVER_DISPATCHED",
             "measured_at": NOW.isoformat()},
        ])
        waiting = {
            record.key for record in snapshot.records.values()
            if record.state in (q.NEW, q.QUEUED)
            and record.condition in q.AUTO_ESCALATION_CONDITIONS
        }
        self.assertEqual(waiting, {"STILL_NEW", "WAS_QUEUED"})

    def test_the_gate_stops_refusing_once_the_falsified_records_are_out(self):
        """The zero-tolerance gate reads a count; retiring is what changes the count."""
        still_pending = bootstrap.preload_gate(
            armed=True, arm_reason="ok", arm_detail="", active_jobs=0, pending_records=11,
        )
        self.assertFalse(still_pending.allowed)
        self.assertEqual(still_pending.reason, bootstrap.GATE_REAL_GAP_WAITING)

        after = bootstrap.preload_gate(
            armed=True, arm_reason="ok", arm_detail="", active_jobs=0, pending_records=0,
        )
        self.assertTrue(after.allowed)

    def test_a_falsified_record_is_not_resurrected_by_a_later_created_event(self):
        """A re-filed record for the same key must not silently clear the retirement."""
        snapshot = q.fold([
            _created("K1"),
            {"event": "premise_falsified", "key": "K1",
             "reason": "the goal never ran", "premise": "GOAL_NEVER_RAN",
             "measured_at": NOW.isoformat()},
            _created("K1"),
        ])
        self.assertEqual(snapshot.records["K1"].state, q.FALSIFIED)


if __name__ == "__main__":
    unittest.main()
