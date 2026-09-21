"""Single Device / Single UI Owner: the lease, and the yield it makes possible.

What these tests defend
-----------------------
*One owner* -- at any moment at most one owner holds the device, and a second one is
refused *by name*.  The refusal is the feature: the operator's §8 says a validation waits
for the safe point rather than clicking anyway.

*Releasing really releases* -- measured 2026-09-18 on the first version of this module: a
released record stayed in the file with ``released_at`` set and ``holder()`` kept returning
it, so §15's "release the lease whatever the outcome" would have handed the device back on
paper only.

*A dead owner does not own anything* -- §11: a lease past its expiry is not a holder, and
the device row says 恢复AUTO rather than showing a validation that no longer exists.

*V2 yields at a boundary, never mid-action* -- the runtime checks the lease at the top of
an iteration, where the previous step's action and verification are finished.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import device_lease as dl  # noqa: E402

NOW = datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc)


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "learning").mkdir(parents=True)
        self.lease = dl.DeviceLease(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_empty_device_is_gameplay_and_needs_no_record(self):
        self.assertIsNone(self.lease.holder(now=NOW))
        self.assertEqual(self.lease.state(now=NOW), dl.DEVICE_IDLE)

    def test_a_second_owner_is_refused_by_name(self):
        self.lease.acquire(owner=dl.OWNER_GAMEPLAY, capability_id="GATHER", now=NOW)
        record, why = self.lease.acquire(
            owner=dl.OWNER_DEVELOPMENT_VALIDATION, capability_id="X", now=NOW)
        self.assertIsNone(record)
        self.assertIn("GAMEPLAY", why)
        self.assertEqual(self.lease.state(now=NOW), dl.DEVICE_IDLE)

    def test_a_request_waits_until_the_device_is_free_then_acquires(self):
        """§8: request, wait for the atomic Skill to end, then take it."""
        self.lease.acquire(owner=dl.OWNER_GAMEPLAY, capability_id="GATHER", now=NOW)
        record, why = self.lease.request(capability_id="BEAST", job_id="j1", now=NOW)
        self.assertIsNone(record)
        self.assertIn("still owns", why)

        self.lease.release(result="yielded", now=NOW)
        record, why = self.lease.request(
            capability_id="BEAST", job_id="j1", now=NOW + timedelta(seconds=30))
        self.assertEqual(why, "acquired")
        self.assertEqual(record.owner, dl.OWNER_DEVELOPMENT_VALIDATION)
        self.assertEqual(self.lease.state(now=NOW + timedelta(seconds=30)), dl.DEVICE_VALIDATING)

    def test_releasing_really_returns_the_device(self):
        """Regression: the first version kept returned the released record."""
        self.lease.acquire(owner=dl.OWNER_DEVELOPMENT_VALIDATION, capability_id="X", now=NOW)
        self.assertEqual(self.lease.state(now=NOW), dl.DEVICE_VALIDATING)
        self.assertTrue(self.lease.release(result="LIVE_VERIFIED", now=NOW))
        self.assertIsNone(self.lease.holder(now=NOW))
        self.assertEqual(self.lease.state(now=NOW), dl.DEVICE_IDLE)
        # And gameplay can take it back.
        record, why = self.lease.acquire(owner=dl.OWNER_GAMEPLAY, now=NOW)
        self.assertEqual(why, "acquired")
        self.assertIsNotNone(record)

    def test_releasing_twice_is_a_no_op_that_still_leaves_a_row(self):
        self.assertFalse(self.lease.release(result="n/a", now=NOW))
        self.lease.acquire(owner=dl.OWNER_DEVELOPMENT_VALIDATION, now=NOW)
        self.assertTrue(self.lease.release(result="BLOCKED", now=NOW))
        self.assertFalse(self.lease.release(result="BLOCKED", now=NOW))
        events = [row["event"] for row in self.lease._trail()]
        self.assertEqual(events.count("release_noop"), 2)
        self.assertEqual(events.count("released"), 1)

    def test_an_expired_owner_does_not_own_the_device(self):
        """§11: a crashed validator must not hold MuMu forever."""
        self.lease.acquire(owner=dl.OWNER_DEVELOPMENT_VALIDATION, capability_id="X",
                           job_id="j1", ttl_seconds=60, now=NOW)
        later = NOW + timedelta(seconds=61)
        self.assertIsNone(self.lease.holder(now=later))
        self.assertEqual(self.lease.state(now=later), dl.DEVICE_RECOVERING)
        self.assertIn("expired", self.lease.describe(now=later))
        # And the device is takeable again without any manual cleanup.
        record, why = self.lease.acquire(owner=dl.OWNER_GAMEPLAY, now=later)
        self.assertEqual(why, "acquired")

    def test_renewing_extends_an_owner_that_is_still_working(self):
        self.lease.acquire(owner=dl.OWNER_DEVELOPMENT_VALIDATION, capability_id="X",
                           ttl_seconds=60, now=NOW)
        self.assertTrue(self.lease.renew(now=NOW + timedelta(seconds=50)))
        self.assertIsNotNone(self.lease.holder(now=NOW + timedelta(seconds=100)))
        self.assertIsNone(self.lease.holder(now=NOW + timedelta(seconds=200)))

    def test_the_audit_trail_carries_the_operators_fields(self):
        """§19 names them: trace_id, job_id, capability_id, owner, both times, result."""
        self.lease.request(capability_id="SPEND_STAMINA_ON_BEAST", job_id="j9",
                           trace_id="trace-9", reason="LIVE_VERIFY_PENDING", now=NOW)
        self.lease.release(result="LIVE_VERIFIED", now=NOW)
        row = [r for r in self.lease._trail() if r["event"] == "released"][-1]
        for field in ("trace_id", "job_id", "capability_id", "owner",
                      "acquired_at", "released_at", "result", "recorded_at"):
            self.assertIn(field, row, field)
        self.assertEqual(row["trace_id"], "trace-9")
        self.assertEqual(row["result"], "LIVE_VERIFIED")

    def test_the_file_is_the_truth_a_second_process_can_read(self):
        """Two owners are two processes, so the record has to survive one of them."""
        self.lease.acquire(owner=dl.OWNER_DEVELOPMENT_VALIDATION, capability_id="X",
                           job_id="j1", now=NOW)
        other = dl.DeviceLease(self.root)          # a different object, same file
        self.assertEqual(other.holder(now=NOW).job_id, "j1")
        self.assertEqual(other.state(now=NOW), dl.DEVICE_VALIDATING)
        payload = json.loads((self.root / dl.LEASE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(payload["owner"], dl.OWNER_DEVELOPMENT_VALIDATION)


class RuntimeYieldsTest(unittest.TestCase):
    """The runtime gives the device up at a boundary, which is the whole point."""

    @staticmethod
    def _runtime_module():
        from winter_agent_v2 import runtime

        return runtime

    def test_the_stop_reason_is_a_condition_not_a_capability_gap(self):
        from winter_agent_v2 import escalation_queue as q

        self.assertIn("device_leased_for_development", q.NON_ESCALATABLE_STOP_REASONS)

    def test_the_window_shows_it_as_waiting_rather_than_broken(self):
        from tools import control_panel

        self.assertIn("device_leased_for_development", control_panel.RUNTIME_WAITING_STOPS)

    def test_the_guard_is_at_the_top_of_an_iteration(self):
        """Checked before the screenshot, because that is where no input is in flight.

        The window is measured to the capture rather than to a fixed character count:
        the guard's own docstring grew on 2026-09-21 (it now explains why an examination
        does not yield to the lease it holds), and a literal 1200 was a bound on the
        *comment* while claiming to be a bound on the ordering.  Slicing to the capture
        asserts the same thing and cannot be broken by a longer explanation.
        """
        source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
        body = source.split("for index in range(1, max_actions + 1):")[1]
        head = body[:body.index('self._capture_path(index, "before")')]
        guard = head.index("self.device_lease.holder()")
        self.assertLess(guard, len(head), "the lease must be checked before the next step starts")
        self.assertIn("held.owner != OWNER_GAMEPLAY", head)
        # And the ownership question must be asked, not just the owner comparison: the
        # measured 2026-09-21 defect was a validation yielding to the lease it had itself
        # acquired, which the bare comparison cannot tell apart from a real examination.
        self.assertIn("self._owns_the_lease(held)", head)


class AReleasedLeaseIsNotAnOrphan(unittest.TestCase):
    """Operator P0, 2026-09-18: the window printed, verbatim, "lease expired ... without
    being released (its process is gone or hung)" for a lease that had been released three
    seconds after it was taken, with its result recorded.  The device was fine; the
    sentence was the defect, and it was read as a device fault."""

    def _record(self, **overrides):
        from winter_agent_v2.device_lease import LeaseRecord

        base = dict(
            owner="DEVELOPMENT_VALIDATION", capability_id="OPEN_MARCH_FORMATION",
            job_id="06271322", acquired_at=NOW - timedelta(minutes=20),
            expires_at=NOW - timedelta(minutes=5), released_at=None, result="",
        )
        base.update(overrides)
        return LeaseRecord(**base)

    def test_an_expired_record_that_was_released_is_not_expired(self):
        record = self._record(released_at=NOW - timedelta(minutes=19), result="NO_WAITING_VERSION")
        self.assertFalse(record.expired(NOW))

    def test_an_expired_record_that_was_never_released_is_expired(self):
        self.assertTrue(self._record().expired(NOW))

    def test_the_description_of_a_released_lease_says_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from winter_agent_v2.device_lease import LEASE_FILE, DeviceLease

            record = self._record(released_at=NOW - timedelta(minutes=19), result="NO_WAITING_VERSION")
            path = root / LEASE_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_as_row(record), ensure_ascii=False), encoding="utf-8")
            text = DeviceLease(root).describe(now=NOW)
            self.assertIn("released the device", text)
            self.assertIn("NO_WAITING_VERSION", text)
            self.assertNotIn("without being released", text)

    def test_the_description_of_a_real_orphan_still_says_so(self):
        # The honest half must survive the fix: a lease nobody handed back is reported.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from winter_agent_v2.device_lease import LEASE_FILE, DeviceLease

            path = root / LEASE_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_as_row(self._record()), ensure_ascii=False), encoding="utf-8")
            text = DeviceLease(root).describe(now=NOW)
            self.assertIn("without being released", text)


def _as_row(record) -> dict:
    return {
        "owner": record.owner, "trace_id": record.trace_id, "job_id": record.job_id,
        "capability_id": record.capability_id, "reason": record.reason,
        "acquired_at": record.acquired_at.isoformat() if record.acquired_at else "",
        "expires_at": record.expires_at.isoformat() if record.expires_at else "",
        "released_at": record.released_at.isoformat() if record.released_at else "",
        "result": record.result, "process": record.process,
    }


if __name__ == "__main__":
    unittest.main()
