"""The queue's clock: the consumer has to run when no run is running.

What these tests defend
-----------------------
*The same consumer, not a second one* -- ``pump()`` is ``observe_run`` with no run
behind it: same adapter, same ``decide`` throttle, same ledger, same reconcile.  The
test that proves it is the one that feeds a pending record through both entry points
and compares the outcome.

*A pump with nothing to do writes nothing* -- if a tick could manufacture a
candidate, every thirty seconds would add a row saying nothing happened, and the
ledger would become unreadable exactly when someone needs to read it.

*Restart recovers* -- the panel can be closed and reopened while a job is running.
The first tick must settle a job the gateway already finished, instead of leaving a
row that holds the only concurrency slot.

*The clock never takes the window down* -- a broken pass is a reported state, and
the next tick rebuilds rather than staying broken.  That is the same rule the AUTO
hook follows, and it is the reason the pump lives on a daemon thread at all.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import escalation_queue as q  # noqa: E402
from winter_agent_v2 import runtime_reload as reload_mod  # noqa: E402
from winter_agent_v2.workbuddy_bridge import Availability, JobStatus, Submission  # noqa: E402

NOW = datetime(2026, 9, 18, 1, 30, 0, tzinfo=timezone.utc)
PENDING_KEY = "DISPATCH_GATHER_MARCH|SEMANTIC_TARGET_NOT_VERIFIED|DISPATCH_MARCH"


def panel_module():
    """``tools.control_panel``, imported on demand.

    On demand because importing it at module scope would pull Tk into every run of
    this file, including the ones that only exercise the adapter.
    """
    from tools import control_panel

    return control_panel


class FakeBridge:
    """The bridge's HTTP surface, scripted.  Records what it was asked."""

    def __init__(self, *, available=True, reason="OK", status=None, submitted="job-1",
                 cancel_ok=True):
        self._available = available
        self._reason = reason
        self._status = status
        self._submitted = submitted
        self._cancel_ok = cancel_ok
        self.submits: list[dict] = []
        self.status_calls: list[str] = []
        self.cancels: list[str] = []

    def is_available(self):
        return Availability(self._available, self._reason, "http://127.0.0.1:8080")

    def submit(self, context, *, name=None, model=None, effort=None):
        self.submits.append({"capability": context.capability, "name": name, "model": model})
        return Submission(job_id=self._submitted, state="working")

    def status(self, job_id):
        self.status_calls.append(job_id)
        return self._status

    def cancel(self, job_id):
        self.cancels.append(job_id)
        if not self._cancel_ok:
            raise RuntimeError("stop endpoint refused")
        return True


class Harness:
    """An adapter on a temp ledger with a scripted bridge -- the same shape the
    escalation-queue tests use, kept local so this file can be read on its own."""

    def __init__(self, bridge=None):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "knowledge/goals").mkdir(parents=True)
        (root / "learning").mkdir(parents=True)
        (root / "knowledge/goals/capability_skill_map.json").write_text(
            json.dumps({"goals": []}), encoding="utf-8"
        )
        self.root = root
        self.ledger = q.EscalationLedger(root / q.DEFAULT_LEDGER)
        self.signal = reload_mod.ReloadSignal(reload_mod.default_path(root))
        self.bridge = bridge if bridge is not None else FakeBridge()
        self.adapter = q.EscalationQueueAdapter(
            root=root, ledger=self.ledger, bridge=self.bridge,
            reload_signal=self.signal, policy=q.EscalationPolicy(),
        )
        self.adapter._build_request = self._request

    @staticmethod
    def _request(capability, condition, reason, **kwargs):
        from winter_agent_v2.workbuddy_bridge import EscalationContext

        return EscalationContext(
            capability=capability, condition=condition, failure_reason=reason,
            goal=kwargs.get("goal", ""), skill=kwargs.get("skill", ""),
            evidence_paths=tuple(kwargs.get("evidence_paths") or ()),
        )

    def created_while_busy(self, key=PENDING_KEY):
        """The exact row shape the live ledger has for a record born during CONCURRENCY_WAIT."""
        self.ledger.append({
            "source": "queue",
            "event": "escalation_created",
            "key": key,
            "capability": "DISPATCH_GATHER_MARCH",
            "failure_type": "SEMANTIC_TARGET_NOT_VERIFIED",
            "skill": "DISPATCH_MARCH",
            "condition": q.UNKNOWN_UI,
            "goal": "AUTO_DISCOVERY",
            "dispatch": q.CONCURRENCY_WAIT,
            "dispatch_reason": "max_concurrent_jobs=1 is already used by a7ce58f0; "
                               "two agents must not edit this repository at once",
        })

    def cleanup(self):
        self._tmp.cleanup()

    def running_job(self, key="CAP|UI|SKILL", *, submitted_at):
        """A record that reached the bridge and whose job is still going."""
        self.ledger.append({"source": "queue", "event": "escalation_created", "key": key,
                            "capability": "CAP", "failure_type": "UI", "skill": "SKILL",
                            "condition": q.UNKNOWN_UI})
        self.ledger.append({"source": "queue", "event": "submitted", "key": key,
                            "job_id": "job-1", "recorded_at": submitted_at.isoformat()})
        self.ledger.append({"source": "queue", "event": "job_state", "key": key,
                            "state": q.WORKING})


class ProofBarTest(unittest.TestCase):
    """A proof has to show the wall is gone, not the observation that defines it.

    Measured 2026-09-18 01:43: job 2934e9cd was granted ``LIVE_VERIFIED`` on six
    SCAN_MAP_FOR_BEAST episodes with ``verifier_ok=True`` and ``goal_progress=False``
    on all six -- the capability's wall is literally "the goal does not move", so the
    reconciler was citing the failure as its own fix.  The job's own report said the
    opposite ("criterion 2 ... does not hold"), and a second job was dispatched for
    the same signature four seconds later, which is the system disagreeing with
    itself.
    """

    @staticmethod
    def _episode(progress, *, revision="bbb+0"):
        return {
            "skill": "SCAN_MAP_FOR_BEAST", "recorded_at": NOW.isoformat(),
            "verifier_ok": True, "result": "SUCCESS", "goal_progress": progress,
            "before_screenshot": "b.png", "after_screenshot": "a.png",
            "episode_id": "20260918_013000_000000", "repo_revision": revision,
        }

    def _measure(self, rows, *, failure_type):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "learning").mkdir(parents=True)
            (root / "learning/episodes.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            outcome, explanation, episodes = q.reconcile_outcome(
                capability="SPEND_STAMINA_ON_BEAST", skill="SCAN_MAP_FOR_BEAST",
                submitted_at=NOW - timedelta(minutes=5), job_verdict=q.DONE,
                before=q.RepoRevision(head="aaa", dirty=0, ok=True),
                after=q.RepoRevision(head="bbb", dirty=0, ok=True),
                wiring_problems=0, agent_report="I changed the beast route",
                root=root, failure_type=failure_type,
            )
        return outcome, explanation, episodes

    def test_a_flat_episode_cannot_prove_a_no_goal_progress_fix(self):
        outcome, _, episodes = self._measure([self._episode(False)],
                                             failure_type="NO_GOAL_PROGRESS")
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)
        self.assertEqual(episodes, ())

    def test_a_moving_episode_does_prove_it(self):
        outcome, _, episodes = self._measure([self._episode(True)],
                                             failure_type="NO_GOAL_PROGRESS")
        self.assertEqual(outcome, q.LIVE_VERIFIED)
        self.assertEqual(len(episodes), 1)

    def test_an_unmeasured_episode_is_not_a_move_either(self):
        """``None`` means the goal was not observable, which is not progress."""
        outcome, _, _ = self._measure([self._episode(None)],
                                      failure_type="NO_GOAL_PROGRESS")
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)

    def test_other_signatures_still_prove_by_their_own_verifier(self):
        """Only the signature whose definition is the missing measurement demands it."""
        outcome, _, episodes = self._measure([self._episode(False)],
                                             failure_type="SEMANTIC_TARGET_NOT_VERIFIED")
        self.assertEqual(outcome, q.LIVE_VERIFIED)
        self.assertEqual(len(episodes), 1)

    def test_the_ledger_says_why_the_episodes_were_rejected(self):
        """Otherwise TEST_PASS next to six episodes reads as "nearly there"."""
        harness = Harness()
        try:
            (Path(harness.root) / "learning/episodes.jsonl").write_text(
                json.dumps(dict(self._episode(False),
                                recorded_at=(NOW - timedelta(minutes=1)).isoformat())),
                encoding="utf-8")
            record = q.EscalationRecord(
                key="SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST",
                capability="SPEND_STAMINA_ON_BEAST", failure_type="NO_GOAL_PROGRESS",
                skill="SCAN_MAP_FOR_BEAST", submitted_at=NOW - timedelta(minutes=5),
            )
            note = harness.adapter._flat_episode_note(
                record, q.RepoRevision(head="aaa", dirty=0, ok=True))
            self.assertIn("1 verifier-passing production episode(s)", note)
            self.assertIn("goal actually moving", note)
            self.assertIn("LIVE_VERIFIED is not granted", note)
        finally:
            harness.cleanup()

    def test_the_release_path_uses_the_same_bar_as_reconciliation(self):
        """Releasing a record is the same claim, so it cannot have a lower bar."""
        harness = Harness()
        try:
            harness.created_while_busy()
            created = harness.ledger.snapshot().get(PENDING_KEY).first_seen
            (Path(harness.root) / "learning/episodes.jsonl").write_text(json.dumps(
                dict(self._episode(False), recorded_at=(created + timedelta(minutes=5)).isoformat())
            ), encoding="utf-8")
            observation = harness.adapter.pump(now=NOW)
            self.assertEqual(observation.released, (), "a flat episode must not release a record")
        finally:
            harness.cleanup()


class SlotReclaimTest(unittest.TestCase):
    """The single concurrency slot is the only thing between the queue and the next record."""

    @staticmethod
    def _working(job_id="job-1"):
        return JobStatus(job_id=job_id, gateway_state="working", verdict=q.WORKING,
                         settled=False, detail="still working")

    def test_a_job_past_its_timebox_loses_the_slot_when_records_are_waiting(self):
        """Without this, the best possible pump still cannot get a record past the slot."""
        harness = Harness(bridge=FakeBridge(status=self._working()))
        try:
            harness.adapter._wiring_problems = lambda: 0
            harness.running_job(submitted_at=NOW - timedelta(minutes=90))
            harness.created_while_busy()

            observation = harness.adapter.pump(now=NOW)

            self.assertEqual(harness.bridge.cancels, ["job-1"])
            slot = harness.ledger.snapshot().get("CAP|UI|SKILL")
            self.assertIn(slot.state, (q.DONE, q.FAILED))
            # The point of freeing it: in the same pass the waiting record takes the slot.
            active = [record.key for record in harness.ledger.snapshot().active_jobs()]
            self.assertEqual(active, [PENDING_KEY])
            self.assertEqual(observation.submitted, ("job-1",))
        finally:
            harness.cleanup()

    def test_a_thorough_agent_with_nothing_waiting_keeps_the_slot(self):
        """The other half of the rule: never interrupt a valid write for no reason."""
        harness = Harness(bridge=FakeBridge(status=self._working()))
        try:
            harness.running_job(submitted_at=NOW - timedelta(minutes=90))
            harness.adapter.pump(now=NOW)
            self.assertEqual(harness.bridge.cancels, [])
            self.assertEqual(harness.ledger.snapshot().get("CAP|UI|SKILL").state, q.WORKING)
        finally:
            harness.cleanup()

    def test_a_job_inside_its_timebox_keeps_the_slot(self):
        harness = Harness(bridge=FakeBridge(status=self._working()))
        try:
            harness.running_job(submitted_at=NOW - timedelta(minutes=10))
            harness.created_while_busy()
            harness.adapter.pump(now=NOW)
            self.assertEqual(harness.bridge.cancels, [])
            self.assertEqual(harness.ledger.snapshot().get("CAP|UI|SKILL").state, q.WORKING)
        finally:
            harness.cleanup()

    def test_a_refused_cancel_keeps_the_honest_state(self):
        """A slot is not free because we asked nicely."""
        harness = Harness(bridge=FakeBridge(status=self._working(), cancel_ok=False))
        try:
            harness.running_job(submitted_at=NOW - timedelta(minutes=90))
            harness.created_while_busy()
            observation = harness.adapter.pump(now=NOW)
            self.assertTrue(any("cancel" in error for error in observation.errors))
            self.assertEqual(harness.ledger.snapshot().get("CAP|UI|SKILL").state, q.WORKING)
            self.assertTrue(harness.ledger.snapshot().active_jobs())
        finally:
            harness.cleanup()

    def test_the_timebox_the_job_is_told_is_the_timebox_that_is_enforced(self):
        """One number, stated in the work order and used by the reclaim."""
        source = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
        self.assertIn("timebox_minutes=self.policy.job_timebox_minutes", source)
        self.assertIn("box = self.policy.job_timebox_minutes", source)


class PumpIsTheSameConsumerTest(unittest.TestCase):
    def test_a_pending_record_reaches_the_bridge_with_no_run_behind_it(self):
        """The whole point: a record created while the slot was busy must still arrive."""
        harness = Harness()
        try:
            harness.created_while_busy()
            observation = harness.adapter.pump(now=NOW)
            record = harness.ledger.snapshot().get(PENDING_KEY)
            self.assertEqual(observation.submitted, ("job-1",))
            self.assertEqual(record.state, q.SUBMITTED)
            self.assertEqual(record.job_id, "job-1")
            self.assertEqual(len(harness.bridge.submits), 1)
        finally:
            harness.cleanup()

    def test_the_pump_manufactures_nothing_when_the_queue_is_empty(self):
        """A tick that wrote a row every thirty seconds would bury the real rows."""
        harness = Harness()
        try:
            observation = harness.adapter.pump(now=NOW)
            self.assertEqual(observation.line, "[escalation] nothing to do")
            self.assertEqual(harness.ledger.events(), [])
        finally:
            harness.cleanup()

    def test_the_pump_settles_a_job_that_finished_while_nothing_was_watching(self):
        """Restart recovery: the panel closed, the job finished, the next tick finds it.

        Without this a row stays ``WORKING`` and holds the only concurrency slot --
        which is the stall the consumer exists to remove, arriving by another route.
        """
        status = JobStatus(job_id="job-1", gateway_state="done", verdict=q.DONE,
                           settled=True, detail="finished while the window was closed")
        harness = Harness(bridge=FakeBridge(status=status))
        try:
            harness.adapter._wiring_problems = lambda: 0
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": "CAP|UI|SKILL", "capability": "CAP",
                                   "failure_type": "UI", "skill": "SKILL",
                                   "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": "CAP|UI|SKILL", "job_id": "job-1"})
            harness.ledger.append({"source": "queue", "event": "job_state",
                                   "key": "CAP|UI|SKILL", "state": q.WORKING})

            observation = harness.adapter.pump(now=NOW)
            record = harness.ledger.snapshot().get("CAP|UI|SKILL")
            self.assertEqual(observation.reconciled, ("CAP|UI|SKILL",))
            self.assertIn(record.state, (q.DONE, q.FAILED))
            self.assertEqual(harness.ledger.snapshot().active_jobs(), ())
        finally:
            harness.cleanup()

    def test_a_pump_never_turns_a_stop_reason_into_a_candidate(self):
        """No run means no wall to report: the pump may only consume what is owed."""
        harness = Harness()
        try:
            self.assertNotIn(q.PUMP_STOP_REASON, q.NON_ESCALATABLE_STOP_REASONS)
            self.assertNotIn(q.PUMP_STOP_REASON, q.STOP_REASON_WALLS)
            harness.adapter.pump(now=NOW)
            self.assertEqual(harness.ledger.events(), [])
        finally:
            harness.cleanup()

    def test_the_observation_line_says_what_was_released(self):
        harness = Harness()
        try:
            harness.created_while_busy()
            created = harness.ledger.snapshot().get(PENDING_KEY).first_seen
            (Path(harness.root) / "learning/episodes.jsonl").write_text(json.dumps({
                "skill": "DISPATCH_MARCH",
                "recorded_at": (created + timedelta(minutes=5)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
                "episode_id": "x", "repo_revision": "abc+0",
            }), encoding="utf-8")
            observation = harness.adapter.pump(now=NOW)
            self.assertEqual(observation.released, (PENDING_KEY,))
            self.assertIn("released 1", observation.line)
        finally:
            harness.cleanup()


class QueuePumpStateTest(unittest.TestCase):
    """``control_panel.QueuePump``: the failure and gate behaviour, without a window."""

    @staticmethod
    def _module():
        from tools import control_panel

        return control_panel

    def test_a_disabled_pump_touches_nothing(self):
        """The operator's stop outranks the clock: no adapter, no ledger, no submission."""
        module = self._module()
        pump = module.QueuePump(enabled=lambda: False)
        built = []
        pump._build = lambda: built.append(True)
        state = pump.tick()
        self.assertEqual(built, [], "a gated pump must not even build an adapter")
        self.assertEqual(state["passes"], 0)
        self.assertEqual(state["gated"], "operator stopped")

    def test_a_broken_pass_is_a_reported_state_and_the_next_tick_rebuilds(self):
        module = self._module()
        pump = module.QueuePump()
        broken = mock.Mock()
        broken.pump.side_effect = RuntimeError("gateway exploded")
        pump._build = lambda: broken
        state = pump.tick()
        self.assertEqual(state["errors"], 1)
        self.assertIn("gateway exploded", state["last_error"])
        self.assertIsNone(pump._adapter, "a failed adapter must not be reused")

    def test_a_pass_is_counted_and_quoted(self):
        module = self._module()
        pump = module.QueuePump()
        observation = q.RunObservation(submitted=("job-9",), released=("K",),
                                       reconciled=("J",))
        adapter = mock.Mock()
        adapter.pump.return_value = observation
        pump._build = lambda: adapter
        state = pump.tick()
        self.assertEqual(state["passes"], 1)
        self.assertEqual(state["submitted"], 1)
        self.assertEqual(state["released"], 1)
        self.assertEqual(state["reconciled"], 1)
        self.assertIn("reconciled 1", state["last_line"])

    def test_the_real_ledger_path_is_read_at_tick_time_so_tests_can_redirect_it(self):
        """Same rule as ``PANEL_LOG_PATH``: a test must not be able to write production."""
        module = self._module()
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "learning/workbuddy_escalations.jsonl"
            ledger.parent.mkdir(parents=True)
            (Path(temp) / "knowledge/goals").mkdir(parents=True)
            (Path(temp) / "knowledge/goals/capability_skill_map.json").write_text(
                json.dumps({"goals": []}), encoding="utf-8")
            with mock.patch.object(module, "_ESCALATION_LEDGER_PATH", ledger):
                pump = module.QueuePump()
                adapter = pump._build()
            self.assertEqual(Path(adapter.root), Path(temp))
            self.assertEqual(Path(adapter.ledger.path), ledger)

    def test_the_thread_is_a_daemon_and_stops_on_request(self):
        module = self._module()
        pump = module.QueuePump(interval=0.01)
        pump.tick = lambda: {}          # never touch the real ledger from this test
        pump.start()
        self.assertIsInstance(pump._thread, threading.Thread)
        self.assertTrue(pump._thread.daemon)
        pump.stop()
        pump._thread.join(timeout=3)
        self.assertFalse(pump._thread.is_alive())


class PanelOwnsTheClockTest(unittest.TestCase):
    @staticmethod
    def _module():
        return panel_module()

    def test_the_gate_follows_the_operators_intent(self):
        """Only an explicit stop pauses development; a pause or a gap does not."""
        module = self._module()
        allowed = module.ControlPanel._auto_development_allowed
        self.assertFalse(allowed(SimpleNamespace(operator_intent="STOPPED")))
        self.assertTrue(allowed(SimpleNamespace(operator_intent="RUNNING")))
        self.assertTrue(allowed(SimpleNamespace(operator_intent="PAUSED")))

    def test_a_running_window_really_starts_the_pump(self):
        """The operator's question was "does the GUI start the consumer" -- so pin it."""
        module = self._module()
        try:
            import tkinter as tk
        except Exception as exc:  # noqa: BLE001 - no Tk at all
            self.skipTest(f"tkinter unavailable: {exc}")
        try:
            root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - no display
            self.skipTest(f"no display: {exc}")
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "panel_state.json"
            log = Path(temp) / "panel.log"
            ledger = Path(temp) / "learning/workbuddy_escalations.jsonl"
            ledger.parent.mkdir(parents=True)
            module.ControlPanel._enforce_retention = lambda self: None
            with mock.patch.object(module, "PANEL_STATE_PATH", state), \
                 mock.patch.object(module, "PANEL_LOG_PATH", log), \
                 mock.patch.object(module, "_ESCALATION_LEDGER_PATH", ledger):
                panel = module.ControlPanel(root)
                try:
                    self.assertIsInstance(panel.pump, module.QueuePump)
                    self.assertIsNotNone(panel.pump._thread)
                    self.assertTrue(panel.pump._thread.is_alive())
                    self.assertEqual(panel.pump.state()["passes"], 0)
                finally:
                    panel.probes.stop()
                    panel.pump.stop()
                    root.destroy()


if __name__ == "__main__":
    unittest.main()
