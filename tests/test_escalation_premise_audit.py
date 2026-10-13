"""The premise audit must not let one claim borrow another claim's evidence.

``audit_escalation_premises`` answers one question per pending record: does it still
describe the running client?  For a ``NO_GOAL_PROGRESS`` record it can answer with
goal progress, because that record's claim *is* about progress ("no part of it
advanced").  For a ``*_NOT_PROVEN`` record it cannot: that claim is about what the
client *drew*, and another skill advancing the goal says nothing about the
recognition that failed.

The cheap mistake is to run the progress comparison unconditionally.  Measured on the
live ledger 2026-10-14, doing that turned 6 ``UNKNOWN_UI`` records into "premise
falsified" on evidence that is silent about them -- the "two root causes, one reason"
failure this project has already paid for.  These tests pin the boundary, because the
boundary is the whole point.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_escalation_premises import audit


def _created(key: str, *, condition: str, failure_type: str, goal: str,
             recorded_at: str = "2026-10-01T00:00:00+00:00") -> dict:
    return {
        "event": "escalation_created", "key": key, "capability": "CAP",
        "condition": condition, "failure_type": failure_type, "skill": "SKILL",
        "goal": goal, "recorded_at": recorded_at,
    }


def _episode(goal: str, progress: bool, at: str) -> dict:
    return {"goal_id": goal, "goal_progress": progress, "recorded_at": at}


class EscalationPremiseAuditTest(unittest.TestCase):
    def _root(self, *, ledger: list[dict], episodes: list[dict]) -> Path:
        root = Path(tempfile.mkdtemp())
        learning = root / "learning"
        learning.mkdir(parents=True, exist_ok=True)
        for name, rows in (("workbuddy_escalations.jsonl", ledger),
                           ("episodes.jsonl", episodes)):
            (learning / name).write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
        return root

    @staticmethod
    def _verdicts(root: Path) -> dict[str, str]:
        return {str(row["key"]): str(row["premise"]) for row in audit(root)}

    def test_each_premise_gets_its_own_verdict(self):
        root = self._root(
            ledger=[
                _created("A", condition="REPEATED_LIVE_FAILURE",
                         failure_type="NO_GOAL_PROGRESS", goal="ADVANCES"),
                _created("B", condition="UNKNOWN_UI",
                         failure_type="INTEL_MISSION_SELECTION_NOT_PROVEN", goal="ADVANCES"),
                _created("C", condition="REPEATED_LIVE_FAILURE",
                         failure_type="NO_GOAL_PROGRESS", goal="NEVER"),
                _created("D", condition="REPEATED_LIVE_FAILURE",
                         failure_type="NO_GOAL_PROGRESS", goal="ABSENT"),
            ],
            episodes=[
                _episode("ADVANCES", True, "2026-10-05T00:00:00+00:00"),
                _episode("NEVER", False, "2026-10-05T00:00:00+00:00"),
            ],
        )
        self.assertEqual(
            self._verdicts(root),
            {
                "A": "FALSIFIED_SINCE_FILING",
                "B": "RECOGNITION_CLAIM_NEEDS_A_FRAME",
                "C": "HOLDS_NEVER_ADVANCED",
                "D": "GOAL_NEVER_RAN",
            },
        )

    def test_a_recognition_claim_does_not_borrow_the_progress_verdict(self):
        """The measured mistake, as a test.

        ``A`` and ``B`` describe the same goal on the same client.  ``A``'s claim is
        falsified by the stream; ``B``'s is not addressed by the stream at all.  One
        comparison, two answers -- and ``B`` must not read as "already fixed".
        """
        root = self._root(
            ledger=[
                _created("A", condition="REPEATED_LIVE_FAILURE",
                         failure_type="NO_GOAL_PROGRESS", goal="G"),
                _created("B", condition="UNKNOWN_UI",
                         failure_type="ALLY_GIFT_CLAIM_NOT_PROVEN", goal="G"),
            ],
            episodes=[_episode("G", True, "2026-10-05T00:00:00+00:00")],
        )
        verdicts = self._verdicts(root)
        self.assertEqual(verdicts["A"], "FALSIFIED_SINCE_FILING")
        self.assertEqual(verdicts["B"], "RECOGNITION_CLAIM_NEEDS_A_FRAME")

    def test_an_advance_before_the_record_was_filed_does_not_falsify_it(self):
        """Only progress *after* filing speaks to this record's premise."""
        root = self._root(
            ledger=[
                _created("A", condition="REPEATED_LIVE_FAILURE",
                         failure_type="NO_GOAL_PROGRESS", goal="G",
                         recorded_at="2026-10-10T00:00:00+00:00"),
            ],
            episodes=[_episode("G", True, "2026-10-05T00:00:00+00:00")],
        )
        self.assertEqual(self._verdicts(root)["A"], "ADVANCED_BEFORE_FILING")

    def test_settled_records_are_not_part_of_the_board(self):
        """A record a job already finished is not a gap the gate is waiting on.

        ``job_state`` is folded from a ``reconciled`` event (``escalation_queue`` folds
        it there and nowhere else), which is why the fixture uses that shape.
        """
        root = self._root(
            ledger=[
                _created("A", condition="REPEATED_LIVE_FAILURE",
                         failure_type="NO_GOAL_PROGRESS", goal="G"),
                {"event": "reconciled", "key": "A", "job_state": "DONE",
                 "outcome": "NO_IMPROVEMENT", "recorded_at": "2026-10-06T00:00:00+00:00"},
            ],
            episodes=[_episode("G", True, "2026-10-05T00:00:00+00:00")],
        )
        self.assertEqual(audit(root), [])


if __name__ == "__main__":
    unittest.main()
