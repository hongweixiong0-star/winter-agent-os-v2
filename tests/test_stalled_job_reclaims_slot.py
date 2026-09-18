"""A job that is not *doing* anything must not hold the only concurrency slot.

The stall this defends against, measured 2026-09-19 in production: the acceptance seed's
research job ``c743127e`` reported ``state=working / tempo=active / alive=True`` for **66
minutes** while its own gateway ``updatedAt`` had not moved since 6 seconds after it started,
and its detail read ``"No active coding session content provided"``.  The queue behind it was
**empty**, and that is exactly what made it unrecoverable:

``_reclaim_expired_slot`` opened with

    if not waiting or record.submitted_at is None:
        return ""

so the only path that could ever take the slot back was gated on somebody waiting behind the
job.  With an empty queue nothing was waiting, nothing was reclaimed, and the whole loop --
bootstrap, development, validation, reuse -- stalled behind a process that was doing nothing
while looking healthy.  ``alive`` cannot tell "busy" from "wedged"; the progress clock can,
because a thorough agent's clock advances with every tool call it makes.

These tests pin both reasons for taking the slot back, and -- just as important -- the cases
where it must **not** be taken, because the standing rule is that a valid WorkBuddy write
operation is never interrupted.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import escalation_queue as q  # noqa: E402
from winter_agent_v2.workbuddy_bridge import JobStatus  # noqa: E402

NOW = datetime(2026, 9, 19, 4, 0, 0, tzinfo=timezone.utc)
KEY = "ECONOMY_RESEARCH|CAPABILITY_MISSING|ECONOMY_RESEARCH"
WAITING_KEY = "A_LATER_CAPABILITY|CAPABILITY_MISSING|A_LATER_CAPABILITY"


class Availability:
    def __init__(self, available: bool, reason: str):
        self.available, self.reason = available, reason

    def __bool__(self) -> bool:
        return self.available


class ScriptedBridge:
    """A bridge whose job status is dictated, and which records every cancel."""

    def __init__(self, status: JobStatus | None):
        self._status = status
        self.cancels: list[str] = []

    def is_available(self):
        return Availability(True, "OK")

    def submit(self, context, *, name=None, model=None):
        return SimpleNamespace(job_id="job-new", state="working")

    def status(self, job_id):
        return self._status

    def cancel(self, job_id):
        self.cancels.append(job_id)
        return True


def job_status(*, stalled_minutes: float | None, verdict: str = "RUNNING") -> JobStatus:
    """A gateway job whose progress clock last moved ``stalled_minutes`` ago.

    ``None`` means the gateway published no clock at all -- the "cannot judge" case.
    """
    raw: dict[str, object] = {"state": "working"}
    if stalled_minutes is not None:
        moved = (NOW - timedelta(minutes=stalled_minutes)).timestamp() * 1000
        raw["updatedAt"] = int(moved)
    return JobStatus(
        job_id="c743127e", gateway_state="working", verdict=verdict,
        detail='{"summary": "No active coding session content provided"}',
        settled=False, alive=True, raw=raw,
    )


class Harness:
    """One in-flight job, a scripted gateway, and a temp ledger."""

    def __init__(self, *, status: JobStatus | None, with_waiting: bool = False,
                 timeout: int = 45, stall: int = 20):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "knowledge/goals").mkdir(parents=True)
        (root / "learning").mkdir(parents=True)
        (root / "knowledge/goals/capability_skill_map.json").write_text(
            json.dumps({"goals": []}), encoding="utf-8")
        self.root = root
        self.ledger = q.EscalationLedger(root / q.DEFAULT_LEDGER)
        self.bridge = ScriptedBridge(status)
        self.adapter = q.EscalationQueueAdapter(
            root=root, ledger=self.ledger, bridge=self.bridge,
            policy=q.EscalationPolicy(
                job_timebox_minutes=timeout, job_progress_stall_minutes=stall),
        )
        self.adapter._build_request = self._request
        self._seed(with_waiting=with_waiting)

    @staticmethod
    def _request(capability, condition, reason, **kwargs):
        from winter_agent_v2.workbuddy_bridge import EscalationContext

        return EscalationContext(
            capability=capability, condition=condition, failure_reason=reason,
            goal=kwargs.get("goal", ""), skill=kwargs.get("skill", ""),
            evidence_paths=tuple(kwargs.get("evidence_paths") or ()),
        )

    def _seed(self, *, with_waiting: bool) -> None:
        submitted = NOW - timedelta(minutes=60)
        self.ledger.append({
            "source": "queue", "event": "escalation_created", "origin": "bootstrap_seed",
            "key": KEY, "capability": "ECONOMY_RESEARCH", "condition": "CAPABILITY_MISSING",
            "skill": "ECONOMY_RESEARCH",
            "recorded_at": (submitted - timedelta(minutes=1)).isoformat(),
        })
        self.ledger.append({
            "source": "queue", "event": "submitted", "key": KEY, "job_id": "c743127e",
            "condition": "CAPABILITY_MISSING", "capability": "ECONOMY_RESEARCH",
            "recorded_at": submitted.isoformat(),
        })
        self.ledger.append({
            "source": "queue", "event": "job_state", "key": KEY, "job_id": "c743127e",
            "state": "WORKING", "recorded_at": (submitted + timedelta(seconds=10)).isoformat(),
        })
        if with_waiting:
            self.ledger.append({
                "source": "queue", "event": "escalation_created", "key": WAITING_KEY,
                "capability": "A_LATER_CAPABILITY", "condition": "CAPABILITY_MISSING",
                "skill": "A_LATER_CAPABILITY", "recorded_at": NOW.isoformat(),
            })

    def reconcile(self):
        return self.adapter.reconcile(now=NOW)

    def job_detail_notes(self) -> list[str]:
        return [str(e.get("job_detail") or "") for e in self.ledger.events()
                if e.get("event") == "job_state" and e.get("job_id") == "c743127e"]

    def record(self):
        return self.ledger.snapshot().records.get(KEY)

    def slot_is_free(self) -> bool:
        return self.ledger.snapshot().active_jobs() == ()


class TheWedgedJobLosesTheSlot(unittest.TestCase):
    """The production case, and the reason it was unreachable before."""

    def test_the_measured_case_is_reclaimed_with_an_empty_queue(self):
        """66 minutes past a 45-minute box, clock frozen, nothing waiting behind it."""
        harness = Harness(status=job_status(stalled_minutes=66))
        self.assertEqual(harness.bridge.cancels, [], "nothing is cancelled before reconcile")

        harness.reconcile()

        self.assertEqual(harness.bridge.cancels, ["c743127e"], "the wedged job must be stopped")
        self.assertTrue(harness.slot_is_free(), "the single slot must come back")
        self.assertNotEqual(harness.record().state, q.WORKING)

    def test_the_ledger_says_which_evidence_took_the_slot(self):
        """'Cancelled' with no reason is how a recovery becomes indistinguishable from a bug."""
        harness = Harness(status=job_status(stalled_minutes=66))
        harness.reconcile()
        notes = " ".join(harness.job_detail_notes())
        self.assertIn("progress clock", notes)
        self.assertIn("frozen for 66 min", notes)
        self.assertIn("the queue is empty", notes)

    def test_the_reclaim_is_visible_in_the_reconciled_explanation(self):
        """The settled row carries the cancellation, so 'why is this FAILED' has an answer."""
        harness = Harness(status=job_status(stalled_minutes=66))
        harness.reconcile()
        explanations = [str(e.get("explanation") or "") for e in harness.ledger.events()
                        if e.get("event") == "reconciled"]
        self.assertTrue(
            any(text.startswith("cancelled:") and "progress clock" in text
                for text in explanations),
            f"the cancellation must survive into the settled record: {explanations}",
        )


class AProductiveAgentIsNeverInterrupted(unittest.TestCase):
    """The half the operator's rule exists to protect.  Each case must NOT lose the slot."""

    def test_a_moving_progress_clock_keeps_the_slot(self):
        """Over the timebox, empty queue -- but its clock moved a minute ago, so it is working."""
        harness = Harness(status=job_status(stalled_minutes=1))
        harness.reconcile()
        self.assertEqual(harness.bridge.cancels, [], "a thorough agent must not be killed")
        self.assertEqual(harness.record().state, q.WORKING)

    def test_a_frozen_clock_inside_the_stall_window_keeps_the_slot(self):
        harness = Harness(status=job_status(stalled_minutes=5), stall=20)
        harness.reconcile()
        self.assertEqual(harness.bridge.cancels, [])

    def test_a_frozen_clock_inside_the_timebox_keeps_the_slot(self):
        """The contract half is still required: 'slow' is not the same as 'off-contract'."""
        harness = Harness(status=job_status(stalled_minutes=66), timeout=45)
        harness.ledger.append({
            "source": "queue", "event": "submitted", "key": KEY, "job_id": "c743127e",
            "recorded_at": (NOW - timedelta(minutes=10)).isoformat(),
        })
        harness.reconcile()
        self.assertEqual(
            harness.bridge.cancels, [],
            "a job inside its timebox keeps the slot however quiet it is",
        )

    def test_an_unreadable_progress_clock_keeps_the_slot(self):
        """Cannot judge must mean 'do not reclaim', not 'assume the worst'."""
        harness = Harness(status=job_status(stalled_minutes=None))
        harness.reconcile()
        self.assertEqual(harness.bridge.cancels, [])

    def test_a_job_with_no_status_at_all_keeps_the_slot(self):
        harness = Harness(status=None)
        self.assertEqual(harness.adapter._reclaim_expired_slot(
            harness.record(), (), NOW, [], None), "")


class TheOriginalRuleStillWorks(unittest.TestCase):
    """The waiting-behind half is not weakened by adding a second reason."""

    def test_a_job_starving_the_queue_is_still_reclaimed(self):
        harness = Harness(status=job_status(stalled_minutes=1), with_waiting=True)
        harness.reconcile()
        self.assertEqual(harness.bridge.cancels, ["c743127e"],
                         "a job starving a waiting record still loses the slot")
        notes = " ".join(harness.job_detail_notes())
        self.assertIn("waited for the single concurrency slot", notes)

    def test_the_two_reasons_are_distinguishable_in_the_ledger(self):
        """Same action, different facts -- a reader must be able to tell which happened."""
        starved = Harness(status=job_status(stalled_minutes=1), with_waiting=True)
        starved.reconcile()
        stalled = Harness(status=job_status(stalled_minutes=66))
        stalled.reconcile()
        starved_note = " ".join(starved.job_detail_notes())
        stalled_note = " ".join(stalled.job_detail_notes())
        self.assertNotEqual(starved_note, stalled_note)
        self.assertIn("waited for", starved_note)
        self.assertNotIn("waited for", stalled_note)


class TheProgressClockIsReadNotInvented(unittest.TestCase):
    """``progress_at`` is the gateway's own field; these pin how it is read."""

    def test_updated_at_wins(self):
        raw = {"updatedAt": 1_700_000_000_000, "state": "working"}
        status = JobStatus(job_id="j", gateway_state="working", verdict="RUNNING",
                           started_at=1_600_000_000_000, raw=raw)
        self.assertEqual(status.progress_at, 1_700_000_000_000)

    def test_it_falls_back_to_started_at_rather_than_returning_nothing(self):
        """A job that never updated has at least existed since it started."""
        status = JobStatus(job_id="j", gateway_state="working", verdict="RUNNING",
                           started_at=1_600_000_000_000, raw={"state": "working"})
        self.assertEqual(status.progress_at, 1_600_000_000_000)

    def test_a_junk_value_does_not_become_a_number(self):
        status = JobStatus(job_id="j", gateway_state="working", verdict="RUNNING",
                           raw={"updatedAt": "not-a-time"})
        self.assertIsNone(status.progress_at)

    def test_the_seconds_vs_millis_mistake_is_not_reachable(self):
        """``_from_millis`` exists because an int compared to a datetime fails silently."""
        status = JobStatus(job_id="j", gateway_state="working", verdict="RUNNING",
                           raw={"updatedAt": int(NOW.timestamp() * 1000)})
        self.assertAlmostEqual(
            q._progress_stall_minutes(status, NOW), 0.0, places=3,
            msg="a clock that just moved is not a stall",
        )


if __name__ == "__main__":
    unittest.main()
