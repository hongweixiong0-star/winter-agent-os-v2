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
import os
import subprocess
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


class VersionActivationTest(unittest.TestCase):
    """The operator's §6: a version nothing has loaded cannot be LIVE_VERIFIED.

    The ladder used to read CODE_CHANGED -> TEST_PASS -> LIVE_VERIFIED -> Reload, which
    credits a fix to a process that never loaded it.  The corrected order puts "the new
    version is what is running" between the green gate and the live examination, and the
    measured fact that closes it is an episode recorded *after the job finished* -- each
    cycle is a fresh process that imports the package from disk.
    """

    SETTLED = datetime.now(timezone.utc) - timedelta(minutes=2)

    def _harness(self):
        # ``first_terminal_at`` is milliseconds since epoch, which is what the gateway
        # reports and what ``_duration`` consumes -- not a datetime.
        status = JobStatus(job_id="job-1", gateway_state="done", verdict=q.DONE,
                           settled=True, detail="finished",
                           result="I changed 2 files and committed them",
                           first_terminal_at=int(self.SETTLED.timestamp() * 1000))
        harness = Harness(bridge=FakeBridge(status=status))
        harness.adapter._wiring_problems = lambda: 0
        # A real repository in the temp root: the reconciler measures the tree, and a
        # directory without git reads as "cannot tell", which is a different answer from
        # "nothing changed" and would have made this test vacuous.
        for command in (["init", "-q"], ["add", "-A"],
                        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
            subprocess.run(["git", *command], cwd=harness.root, capture_output=True)
        (Path(harness.root) / "changed.py").write_text("x = 1\n", encoding="utf-8")
        harness.ledger.append({"source": "queue", "event": "escalation_created",
                               "key": "CAP|UI|SKILL", "capability": "CAP",
                               "failure_type": "UI", "skill": "SKILL",
                               "condition": q.UNKNOWN_UI})
        harness.ledger.append({"source": "queue", "event": "submitted", "key": "CAP|UI|SKILL",
                               "job_id": "job-1", "recorded_at":
                               (self.SETTLED - timedelta(minutes=30)).isoformat(),
                               "repo_head": "aaa", "repo_dirty": 0})
        harness.ledger.append({"source": "queue", "event": "job_state", "key": "CAP|UI|SKILL",
                               "job_id": "job-1", "state": q.WORKING})
        return harness

    def _episode(self, when):
        return {
            "skill": "SKILL", "recorded_at": when.isoformat(), "verifier_ok": True,
            "result": "SUCCESS", "goal_progress": True,
            "before_screenshot": "b.png", "after_screenshot": "a.png",
            "episode_id": "e1", "repo_revision": "bbb+1",
        }

    def test_a_changed_tree_with_no_episode_since_the_job_waits_for_activation(self):
        harness = self._harness()
        try:
            harness.adapter.reconcile(now=datetime.now(timezone.utc))
            record = harness.ledger.snapshot().get("CAP|UI|SKILL")
            self.assertEqual(record.outcome, q.VERSION_ACTIVATION_PENDING)
            self.assertEqual(record.state, q.LIVE_VERIFY_PENDING)
            # It must not hold the single agent slot while it waits.
            self.assertEqual(harness.ledger.snapshot().active_jobs(), ())
            # And activation is not a failure, so it may not spend a repair shot.
            self.assertEqual(record.repairs_used, 0)
        finally:
            harness.cleanup()

    def test_a_developed_trace_waits_for_validation_instead_of_settling(self):
        """The shortcut this test used to encode was closed by the operator.

        Renamed from ``..._settles_once_an_episode_has_run_the_new_version``.  The old name
        asserted that a production episode recorded after the settle *settles* the record, and
        that is precisely the credit the operator removed in ``8c4cf08f`` ("a developed trace can
        no longer be certified by a production success"): the episode proves the capability works
        on the tree it ran, not on the version the job produced, and it would exist even if the
        agent had done nothing.  That commit landed *after* this file was last touched, so the
        code began returning ``VERSION_ACTIVATION_PENDING`` here while the assertion kept saying
        ``DONE`` -- and it has been red ever since.  A red test everyone has agreed to ignore is
        where the next real regression hides, which is how the last one got through.

        The boundary this test is actually for is kept, and it is the one the sibling below
        measures from the other side: an episode recorded *after* the job settled is admitted and
        returned as evidence, while the same episode recorded *before* it is not.  What changed is
        only where the record lands -- into the activation ladder, not at a verdict.
        """
        harness = self._harness()
        try:
            harness.adapter.reconcile(now=datetime.now(timezone.utc))
            self.assertEqual(harness.ledger.snapshot().get("CAP|UI|SKILL").state,
                             q.LIVE_VERIFY_PENDING)

            (Path(harness.root) / "learning/episodes.jsonl").write_text(
                json.dumps(self._episode(self.SETTLED + timedelta(minutes=1))), encoding="utf-8")
            harness.adapter.reconcile(now=datetime.now(timezone.utc))

            record = harness.ledger.snapshot().get("CAP|UI|SKILL")
            # Routed into the ladder, not certified: VERSION_ACTIVE -> LIVE_VERIFY_PENDING ->
            # Development Validation -> LIVE_TRIED -> LIVE_VERIFIED.
            self.assertEqual(record.outcome, q.VERSION_ACTIVATION_PENDING)
            self.assertEqual(record.state, q.LIVE_VERIFY_PENDING)
            self.assertNotEqual(record.state, q.DONE)
            # Waiting for a validation cycle is not a failure, so it may not spend a repair shot.
            self.assertEqual(record.repairs_used, 0)
        finally:
            harness.cleanup()

    def test_an_episode_from_before_the_job_finished_is_not_the_new_version(self):
        """The RR-004 shape, now measured on the settled boundary rather than the tree."""
        harness = self._harness()
        try:
            (Path(harness.root) / "learning/episodes.jsonl").write_text(
                json.dumps(self._episode(self.SETTLED - timedelta(minutes=1))), encoding="utf-8")
            harness.adapter.reconcile(now=datetime.now(timezone.utc))
            record = harness.ledger.snapshot().get("CAP|UI|SKILL")
            self.assertEqual(record.outcome, q.VERSION_ACTIVATION_PENDING)
            self.assertEqual(record.state, q.LIVE_VERIFY_PENDING)
        finally:
            harness.cleanup()

    @staticmethod
    def _pending_rows(state):
        return [
            {"source": "queue", "event": "escalation_created", "key": "SPEND_STAMINA_ON_BEAST|UI|SKILL",
             "capability": "SPEND_STAMINA_ON_BEAST", "failure_type": "UI", "skill": "SKILL",
             "condition": q.UNKNOWN_UI},
            {"source": "queue", "event": "submitted", "key": "SPEND_STAMINA_ON_BEAST|UI|SKILL",
             "job_id": "job-1"},
            {"source": "queue", "event": "job_state", "key": "SPEND_STAMINA_ON_BEAST|UI|SKILL",
             "state": q.WORKING},
            {"source": "queue", "event": "live_verify_pending",
             "key": "SPEND_STAMINA_ON_BEAST|UI|SKILL", "job_id": "job-1",
             "reason": "tree changed and nothing has loaded it"},
        ][:3 if state == q.WORKING else 4]

    def _gate(self, rows):
        from winter_agent_v2.capability_gate import CapabilityGate

        return CapabilityGate.load(ROOT, snapshot=q.fold(rows), episodes=[])

    def test_the_gate_allows_the_goal_waiting_for_live_verification(self):
        """Operator §4: refusing here deadlocks -- no executor would ever produce proof."""
        from winter_agent_v2.capability_gate import DEFERRING_STATES

        gate = self._gate(self._pending_rows(q.LIVE_VERIFY_PENDING))
        state = gate.capabilities.get("SPEND_STAMINA_ON_BEAST", ("", "", None))[0]
        self.assertTrue(state, "the capability must be known to the gate")
        self.assertNotIn(state, DEFERRING_STATES,
                         "a version waiting for its examination must not be refused")

    def test_an_in_flight_job_still_owns_its_path(self):
        """The allowance is specific: a job that is still working still defers the goal."""
        from winter_agent_v2.capability_gate import DEFERRING_STATES

        gate = self._gate(self._pending_rows(q.WORKING))
        state = gate.capabilities.get("SPEND_STAMINA_ON_BEAST", ("", "", None))[0]
        self.assertIn(state, DEFERRING_STATES,
                      "a working job must keep the failed path out of gameplay")


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
        return panel_module()

    def setUp(self):
        self.module = panel_module()
        self._tmp = tempfile.TemporaryDirectory()
        self._state_patch = mock.patch.object(
            self.module, "PUMP_STATE_PATH", Path(self._tmp.name) / "pump.json")
        self._state_patch.start()

    def tearDown(self):
        self._state_patch.stop()
        self._tmp.cleanup()

    def test_each_tick_is_written_where_a_reader_outside_the_gui_can_see_it(self):
        """A consumer on a thread inside a window cannot be checked any other way."""
        pump = self.module.QueuePump()
        adapter = mock.Mock()
        adapter.pump.return_value = q.RunObservation(submitted=("job-7",), reconciled=("K",))
        pump._build = lambda: adapter
        pump.tick()
        written = json.loads(Path(self._tmp.name, "pump.json").read_text(encoding="utf-8"))
        self.assertEqual(written["passes"], 1)
        self.assertEqual(written["submitted"], 1)
        self.assertEqual(written["reconciled"], 1)
        self.assertIn("written_at", written)
        self.assertEqual(written["process"], os.getpid())

    def test_a_gated_pump_still_says_so_in_the_file(self):
        """A stale file and a stopped pump must not look the same."""
        pump = self.module.QueuePump(enabled=lambda: False)
        pump.tick()
        written = json.loads(Path(self._tmp.name, "pump.json").read_text(encoding="utf-8"))
        self.assertEqual(written["gated"], "operator stopped")
        self.assertEqual(written["passes"], 0)

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
                 mock.patch.object(module, "PUMP_STATE_PATH", Path(temp) / "pump.json"), \
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
