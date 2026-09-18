"""The escalation queue: dedup, throttle, budget, model rungs, reconciliation.

What these tests defend, in the operator's words
------------------------------------------------
*Dedup* -- one active WorkBuddy job per ``capability | failure_type | skill``, so a
failure that recurs every six minutes does not summon an agent every six minutes.

*Concurrency* -- ``max_concurrent_jobs = 1``; two agents must never edit this
repository at once.

*Budget and cooldown* -- the repair loop is bounded, and when the budget is spent
the signature goes ``BLOCKED + COOLDOWN`` and AUTO moves to another capability
instead of retrying forever.

*Ordinary weather never escalates* -- an empty mailbox, a busy queue, an event
that has not refreshed.  These are correct observations, and escalating them would
spend a development agent on a working system.

*DONE is not success* -- ``LIVE_VERIFIED`` requires a production episode with
``recorded_at``, ``verifier_ok`` and evidence that appeared after the job was
dispatched.  Code changes and a green wiring gate produce ``TEST_PASS``, and the
explanation says in words that it is not a verified capability.

*The hook cannot hurt the runtime* -- a gateway that is down, or a bridge that
raises, must come back as an observation on the run rather than an exception, and
must never leave AUTO waiting.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import escalation_queue as q  # noqa: E402
from winter_agent_v2.workbuddy_model_router import (  # noqa: E402
    TASK_UI_RECOGNITION,
    VISION_RUNG,
)
from winter_agent_v2 import runtime_reload as reload_mod  # noqa: E402
from winter_agent_v2.workbuddy_bridge import Availability, JobStatus, Submission  # noqa: E402

NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


def failure(failure_type: str, skill: str = "OPEN_INFANTRY_TRAINING", **extra):
    # Bare filenames on purpose: these are synthetic episode rows, not repository
    # evidence, and tests/test_evidence_integrity.py treats any literal containing
    # a path separator as a claim about a real file.
    row = {
        "failure_type": failure_type,
        "skill": skill,
        "goal_id": "KEEP_TRAINING_PRODUCTIVE",
        "before_screenshot": "step_001_before.png",
        "after_screenshot": "step_001_after.png",
        "recorded_at": NOW.isoformat(),
        "state_before": {"page": "HOME"},
    }
    row.update(extra)
    return row


class FakeBridge:
    """A bridge whose HTTP surface is scripted.  Records what it was asked."""

    def __init__(self, *, available=True, reason="OK", status=None, submitted="job-1"):
        self._available = available
        self._reason = reason
        self._status = status
        self._submitted = submitted
        self.submits: list[dict] = []
        self.status_calls: list[str] = []

    def is_available(self):
        return Availability(self._available, self._reason, "http://127.0.0.1:8080")

    def submit(self, context, *, name=None, model=None, effort=None):
        self.submits.append({"capability": context.capability, "name": name, "model": model})
        return Submission(job_id=self._submitted, state="working")

    def status(self, job_id):
        self.status_calls.append(job_id)
        return self._status


class ExplodingBridge(FakeBridge):
    def is_available(self):
        raise RuntimeError("gateway exploded")

    def submit(self, context, **kwargs):
        raise RuntimeError("gateway exploded")

    def status(self, job_id):
        raise RuntimeError("gateway exploded")


class AdapterHarness:
    """An adapter wired to a temp ledger and a scripted bridge."""

    def __init__(self, bridge=None, policy=None, tmp: Path | None = None):
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
            reload_signal=self.signal, policy=policy or q.EscalationPolicy(),
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

    def cleanup(self):
        self._tmp.cleanup()

    def events(self):
        return self.ledger.events()

    def event_kinds(self):
        return [e["event"] for e in self.events()]


# ------------------------------------------------------------------- dedup


class DedupTest(unittest.TestCase):
    def test_a_second_candidate_with_the_same_key_is_not_dispatched_again(self):
        harness = AdapterHarness()
        try:
            candidate = q.EscalationCandidate(
                signature=q.FailureSignature("KEEP_TRAINING", "TRAINING_PAGE_NOT_PROVEN", "OPEN_INFANTRY_TRAINING"),
                condition=q.UNKNOWN_UI, reason="page not proven",
            )
            first = q.decide(candidate, harness.ledger.snapshot(), harness.adapter.policy, now=NOW)
            self.assertTrue(first.should_submit)
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": candidate.signature.key, "condition": candidate.condition})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": candidate.signature.key, "job_id": "job-1"})

            second = q.decide(candidate, harness.ledger.snapshot(), harness.adapter.policy, now=NOW)
            self.assertEqual(second.action, q.DEDUP_SKIP)
            self.assertIn("job-1", second.reason)
        finally:
            harness.cleanup()

    def test_the_key_is_capability_plus_failure_type_plus_skill(self):
        signature = q.FailureSignature("CAP", "TYPE", "SKILL")
        self.assertEqual(signature.key, "CAP|TYPE|SKILL")
        # A different skill is a different key: same reason, different place.
        self.assertNotEqual(
            signature.key, q.FailureSignature("CAP", "TYPE", "OTHER").key
        )

    def test_the_adapter_submits_only_one_job_for_a_recurring_failure(self):
        harness = AdapterHarness()
        try:
            for _ in range(3):
                harness.adapter.observe_run(
                    stop_reason="training_entry_not_verified",
                    failures=[failure("TRAINING_PAGE_NOT_PROVEN")],
                    now=NOW,
                )
            self.assertEqual(len(harness.bridge.submits), 1)
        finally:
            harness.cleanup()

    def test_a_queued_escalation_is_retried_once_the_gateway_returns(self):
        """QUEUED means "decided but never sent", so it must not be deduped.

        Found by tracing the live path: the unattended loop recorded
        ``queued: gateway unavailable`` and, under the first version of the dedup
        rule, had no way back -- an outage would have stranded the key forever
        while no job ever existed.
        """
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition=q.UNKNOWN_UI, reason="queued earlier",
        )
        record = q.EscalationRecord(key=candidate.signature.key, state=q.QUEUED)
        dispatch = q.decide(
            candidate, q.EscalationSnapshot({record.key: record}), q.EscalationPolicy(), now=NOW
        )
        self.assertTrue(dispatch.should_submit, dispatch.reason)

    def test_a_repeated_outage_writes_one_queued_row_per_transition(self):
        harness = AdapterHarness(bridge=FakeBridge(available=False, reason="GATEWAY_UNREACHABLE"))
        try:
            for _ in range(4):
                harness.adapter.observe_run(
                    stop_reason="training_entry_not_verified",
                    failures=[failure("TRAINING_PAGE_NOT_PROVEN")], now=NOW,
                )
            self.assertEqual(harness.event_kinds().count("queued"), 1)
        finally:
            harness.cleanup()


# ------------------------------------------------------------- concurrency


class ConcurrencyTest(unittest.TestCase):
    def test_the_second_distinct_key_waits_for_the_first_job(self):
        harness = AdapterHarness()
        try:
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": "OTHER|TYPE|SKILL", "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": "OTHER|TYPE|SKILL", "job_id": "job-running"})
            candidate = q.EscalationCandidate(
                signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
                condition=q.UNKNOWN_UI, reason="new wall",
            )
            dispatch = q.decide(candidate, harness.ledger.snapshot(), harness.adapter.policy, now=NOW)
            self.assertEqual(dispatch.action, q.CONCURRENCY_WAIT)
            self.assertIn("max_concurrent_jobs=1", dispatch.reason)
        finally:
            harness.cleanup()

    def test_the_adapter_honours_the_cap_across_two_candidates_in_one_run(self):
        harness = AdapterHarness()
        try:
            observation = harness.adapter.observe_run(
                stop_reason="some_real_failure",
                failures=[
                    failure("SEMANTIC_TARGET_NOT_VERIFIED", skill="A"),
                    failure("SEMANTIC_TARGET_NOT_VERIFIED", skill="B"),
                ],
                now=NOW,
            )
            self.assertEqual(len(observation.submitted), 1)
            self.assertTrue(any("CONCURRENCY_WAIT" in why for _, why in observation.skipped))
        finally:
            harness.cleanup()

    def test_the_cap_is_configurable_and_defaults_to_one(self):
        self.assertEqual(q.EscalationPolicy().max_concurrent_jobs, 1)
        harness = AdapterHarness(policy=q.EscalationPolicy(max_concurrent_jobs=2))
        try:
            observation = harness.adapter.observe_run(
                stop_reason="some_real_failure",
                failures=[
                    failure("SEMANTIC_TARGET_NOT_VERIFIED", skill="A"),
                    failure("SEMANTIC_TARGET_NOT_VERIFIED", skill="B"),
                ],
                now=NOW,
            )
            self.assertEqual(len(observation.submitted), 2)
        finally:
            harness.cleanup()


# --------------------------------------------------------- budget & cooldown


def record_with_repairs(key: str, repairs: int, state: str = q.DONE, cooldown_until=None):
    record = q.EscalationRecord(key=key, state=state)
    record.repairs_used = repairs
    record.cooldown_until = cooldown_until
    return record


class BudgetAndCooldownTest(unittest.TestCase):
    def _snapshot(self, record):
        return q.EscalationSnapshot({record.key: record})

    def test_the_budget_stops_the_repair_loop(self):
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition=q.REPEATED_LIVE_FAILURE, reason="again",
        )
        snapshot = self._snapshot(record_with_repairs(candidate.signature.key, 2))
        dispatch = q.decide(candidate, snapshot, q.EscalationPolicy(), now=NOW)
        self.assertEqual(dispatch.action, q.BUDGET_EXHAUSTED)

    def test_the_first_shot_is_free_even_for_a_repeat(self):
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition=q.REPEATED_LIVE_FAILURE, reason="second sighting",
        )
        snapshot = self._snapshot(record_with_repairs(candidate.signature.key, 0))
        self.assertTrue(q.decide(candidate, snapshot, q.EscalationPolicy(), now=NOW).should_submit)

    def test_a_cooldown_is_reported_with_the_remaining_time(self):
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition=q.REPEATED_LIVE_FAILURE, reason="again",
        )
        snapshot = self._snapshot(
            record_with_repairs(candidate.signature.key, 2, state=q.COOLDOWN,
                                cooldown_until=NOW + timedelta(minutes=30))
        )
        dispatch = q.decide(candidate, snapshot, q.EscalationPolicy(), now=NOW)
        self.assertEqual(dispatch.action, q.IN_COOLDOWN)
        self.assertIn("30 min", dispatch.reason)

    def test_an_expired_cooldown_lets_the_capital_try_again_after_the_budget_resets(self):
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition=q.REPEATED_LIVE_FAILURE, reason="again",
        )
        snapshot = self._snapshot(
            record_with_repairs(candidate.signature.key, 1, state=q.COOLDOWN,
                                cooldown_until=NOW - timedelta(minutes=1))
        )
        dispatch = q.decide(candidate, snapshot, q.EscalationPolicy(), now=NOW)
        self.assertTrue(dispatch.should_submit, dispatch.reason)

    def test_spending_the_budget_writes_blocked_then_cooldown(self):
        """The real sequence: one shot already spent, the second just finished badly.

        Reconstructed rather than invented -- ``reconciled`` moves a record out of
        the in-flight states, so the second submission is what the reconciler then
        finds, and the budget is what turns it into BLOCKED + COOLDOWN instead of a
        third dispatch.
        """
        status = JobStatus(job_id="job-2", gateway_state="done", verdict=q.DONE,
                           settled=True, detail="finished without a verified episode")
        harness = AdapterHarness(bridge=FakeBridge(status=status, submitted="job-2"))
        try:
            harness.adapter._wiring_problems = lambda: 0
            key = "CAP|TYPE|SKILL"
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": key, "condition": q.UNKNOWN_UI})
            # First shot: dispatched, finished, spent (no live improvement).
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": key, "job_id": "job-1",
                                   "repo_head": "head1", "repo_dirty": 0})
            harness.ledger.append({"source": "queue", "event": "reconciled",
                                   "key": key, "job_id": "job-1", "job_state": q.DONE,
                                   "outcome": q.NO_IMPROVEMENT, "repair_used": True})
            # Second shot, in flight when reconcile runs.
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": key, "job_id": "job-2",
                                   "repo_head": "head1", "repo_dirty": 0})

            self.assertEqual(harness.ledger.snapshot().get(key).repairs_used, 1)
            with patch.object(q, "repo_revision", return_value=q.RepoRevision("head1", 0, True)):
                settled, errors = harness.adapter.reconcile(now=NOW)

            self.assertEqual(errors, [])
            self.assertEqual(settled, [key])
            kinds = harness.event_kinds()
            self.assertIn("reconciled", kinds)
            self.assertIn("blocked", kinds)
            self.assertIn("cooldown_started", kinds)
            self.assertEqual(harness.ledger.snapshot().get(key).state, q.COOLDOWN)
        finally:
            harness.cleanup()

    def test_a_blocked_signature_stops_being_dispatched(self):
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition=q.STUCK_15_MIN, reason="old",
        )
        record = q.EscalationRecord(key=candidate.signature.key, state=q.COOLDOWN)
        record.repairs_used = 2
        record.cooldown_until = NOW - timedelta(minutes=1)  # expired, but budget spent
        dispatch = q.decide(
            candidate, q.EscalationSnapshot({record.key: record}), q.EscalationPolicy(), now=NOW
        )
        self.assertEqual(dispatch.action, q.BUDGET_EXHAUSTED)


# ------------------------------------------------------- ordinary weather


class OrdinaryWeatherTest(unittest.TestCase):
    def test_the_operators_non_escalatable_reasons_are_all_named(self):
        for stop in ("mail_all_clear", "research_queue_busy", "NOT_REFRESHED",
                     "QUEUE_BUSY", "RESOURCE_SHORTAGE", "EVENT_CLOSED",
                     "RALLY_FULL", "WAITING_FOR_NATURAL_STATE"):
            self.assertIn(stop, q.NON_ESCALATABLE_STOP_REASONS, stop)

    def test_a_step_that_failed_during_an_ordinary_stop_escalates_nothing(self):
        snapshot = q.EscalationSnapshot({})
        candidates = q.candidates_from_run(
            stop_reason="mail_all_clear",
            failures=[failure("SEMANTIC_TARGET_NOT_VERIFIED")],
            snapshot=snapshot, policy=q.EscalationPolicy(), now=NOW, root=ROOT,
        )
        self.assertEqual(candidates, ())

    def test_a_game_tick_is_refused_rather_than_downgraded(self):
        candidate = q.EscalationCandidate(
            signature=q.FailureSignature("CAP", "TYPE", "SKILL"),
            condition="GAME_TICK", reason="routine",
        )
        dispatch = q.decide(candidate, q.EscalationSnapshot({}), q.EscalationPolicy(), now=NOW)
        self.assertEqual(dispatch.action, q.NOT_ESCALATABLE)

    def test_the_adapter_records_nothing_for_an_ordinary_tick(self):
        harness = AdapterHarness()
        try:
            observation = harness.adapter.observe_run(
                stop_reason="daily_no_claimable_rewards",
                failures=[failure("SEMANTIC_TARGET_NOT_VERIFIED")], now=NOW,
            )
            self.assertEqual(observation.submitted, ())
            self.assertEqual(harness.bridge.submits, [])
        finally:
            harness.cleanup()

    def test_an_unknown_failure_shape_gets_no_condition_at_all(self):
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "SOMETHING_NEW", "SKILL"),
            occurrences=1, first_seen=None, now=NOW, policy=q.EscalationPolicy(),
        )
        self.assertIsNone(verdict)

    def test_a_wall_that_only_appears_as_a_stop_reason_is_still_escalated(self):
        # verified_beast_target_not_visible ends most cycles and produces zero
        # failed episodes, because the runtime stops before issuing an action.
        candidates = q.candidates_from_run(
            stop_reason="verified_beast_target_not_visible",
            failures=[], snapshot=q.EscalationSnapshot({}),
            policy=q.EscalationPolicy(), now=NOW, root=ROOT,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].condition, q.UNKNOWN_UI)
        self.assertEqual(candidates[0].signature.skill, "SELECT_BEAST_TARGET")

    def test_a_failed_episode_still_wins_over_the_stop_reason_wall(self):
        candidates = q.candidates_from_run(
            stop_reason="verified_beast_target_not_visible",
            failures=[failure("BEAST_TARGET_CARD_NOT_PROVEN", skill="SELECT_BEAST_TARGET")],
            snapshot=q.EscalationSnapshot({}), policy=q.EscalationPolicy(), now=NOW, root=ROOT,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].signature.failure_type, "BEAST_TARGET_CARD_NOT_PROVEN")

    def test_the_stop_reason_wall_map_is_not_a_blanket_rule(self):
        # Anything not named in it, with no failed episodes, escalates nothing.
        candidates = q.candidates_from_run(
            stop_reason="some_unlisted_stop", failures=[],
            snapshot=q.EscalationSnapshot({}), policy=q.EscalationPolicy(), now=NOW, root=ROOT,
        )
        self.assertEqual(candidates, ())

    def test_ui_unread_matching_is_by_shape_not_by_a_frozen_list(self):
        for reason in ("TRAINING_PAGE_NOT_PROVEN", "MARCH_PAGE_NOT_OPEN",
                       "SEMANTIC_TARGET_NOT_VERIFIED", "RESOURCE_NOT_FOUND",
                       "SOMETHING_BRAND_NEW_NOT_PROVEN"):
            self.assertTrue(q.is_ui_unread(reason), reason)
        self.assertFalse(q.is_ui_unread("SOMETHING_ELSE_ENTIRELY"))
        # gameplay shapes are excluded from the UI family even though the suffix fits
        self.assertIn("DISPATCH_NOT_PROVEN", q.GAMEPLAY_UNKNOWN_FAILURE_TYPES)


class NoGoalProgressDeferralTest(unittest.TestCase):
    """A goal that steps aside must name a capability, not the failure type.

    Measured 2026-09-18 on the real ledger: the no-progress deferral for
    ``AVOID_STAMINA_WASTE`` carried an empty capability field, so the signature
    collapsed to two fields and the queue read ``NO_GOAL_PROGRESS`` -- the failure
    type -- as the capability.  That produced the key
    ``NO_GOAL_PROGRESS|NO_GOAL_PROGRESS|``, a second escalation for a wall already
    on record as ``SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST``,
    and handed a development agent a name no goal can route back to.
    """

    def _deferral(self, signature, **extra):
        row = {
            "goal_id": "AVOID_STAMINA_WASTE",
            "source": "NO_GOAL_PROGRESS",
            "state": "DEFERRED",
            "streak": 3,
            "last_skill": "SCAN_MAP_FOR_BEAST",
            "failure_signature": signature,
        }
        row.update(extra)
        return row

    def _candidates(self, *deferrals):
        return q.candidates_from_run(
            stop_reason="some_unlisted_stop", failures=[],
            snapshot=q.EscalationSnapshot({}), policy=q.EscalationPolicy(), now=NOW,
            root=ROOT, deferrals=list(deferrals),
        )

    def test_a_named_capability_is_what_the_signature_keys_on(self):
        candidates = self._candidates(
            self._deferral("SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST")
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].signature.key,
            "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST",
        )
        self.assertEqual(candidates[0].condition, q.REPEATED_LIVE_FAILURE)
        self.assertEqual(candidates[0].signature.capability, "SPEND_STAMINA_ON_BEAST")
        self.assertEqual(candidates[0].signature.skill, "SCAN_MAP_FOR_BEAST")

    def test_a_missing_capability_field_does_not_become_the_failure_type(self):
        """The old two-field shape must never file ``NO_GOAL_PROGRESS`` as a capability."""
        candidates = self._candidates(self._deferral("NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"))
        self.assertEqual(candidates, ())

    def test_an_explicitly_empty_capability_is_not_filed_either(self):
        """The new positional shape has an empty field, and empty is not a name."""
        candidates = self._candidates(self._deferral("|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"))
        self.assertEqual(candidates, ())


# ------------------------------------------------------- classification


class ClassificationTest(unittest.TestCase):
    def test_an_unimplemented_skill_is_capability_missing(self):
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "ANY", "SKILL"),
            occurrences=1, first_seen=None, now=NOW, policy=q.EscalationPolicy(),
            unimplemented=True,
        )
        self.assertEqual(verdict[0], q.CAPABILITY_MISSING)

    def test_a_repeat_is_labelled_repeated_live_failure(self):
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "SEMANTIC_TARGET_NOT_VERIFIED", "SKILL"),
            occurrences=3, first_seen=None, now=NOW, policy=q.EscalationPolicy(),
        )
        self.assertEqual(verdict[0], q.REPEATED_LIVE_FAILURE)

    def test_a_first_sighting_that_could_not_be_read_is_unknown_ui(self):
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "SEMANTIC_TARGET_NOT_VERIFIED", "SKILL"),
            occurrences=1, first_seen=None, now=NOW, policy=q.EscalationPolicy(),
        )
        self.assertEqual(verdict[0], q.UNKNOWN_UI)

    def test_an_old_signature_becomes_stuck_15_min(self):
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "SOMETHING_NEW", "SKILL"),
            occurrences=1, first_seen=NOW - timedelta(minutes=16), now=NOW,
            policy=q.EscalationPolicy(),
        )
        self.assertEqual(verdict[0], q.STUCK_15_MIN)

    def test_an_old_signature_that_is_still_working_is_left_alone(self):
        # STUCK_15_MIN means "15+ minutes and still no verified episode".  A
        # production episode of the same capability with a passing verifier, after
        # the signature was first seen, makes the condition false -- what happened
        # is a transient AUTO already retried past, not a wall.
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "SOMETHING_NEW", "SKILL"),
            occurrences=1, first_seen=NOW - timedelta(minutes=16), now=NOW,
            policy=q.EscalationPolicy(), verified_episodes=130,
        )
        self.assertIsNone(verdict)

    def test_the_stuck_claim_is_read_from_the_episode_stream_not_the_clock(self):
        """The live 2026-09-17 miss, end to end.

        ``SCAN_MAP_FOR_BEAST|BEAST_SCAN_NOT_PROVEN`` was escalated ``STUCK_15_MIN``
        with the reason "no verified episode" while 130 verifier-passing episodes of
        that skill had been recorded since the failure 74 minutes earlier.  The
        clock alone was asked; the episode stream was not.  Both halves are pinned
        here: with a verified episode the signature yields no candidate, and with
        none it still yields ``STUCK_15_MIN`` -- the gate is narrowed, not removed.

        The record is keyed through the project's own resolver rather than by hand.
        Keying it by hand pinned an accident -- this skill was absent from
        ``capability_skill_map.json``, so it resolved to itself -- and the test then broke
        when an unrelated edit gave the skill a capability, without the gate it exists to
        protect changing at all.  A test may pin a resolution; it must not pin "this skill
        is missing from the map" while claiming to test the episode stream.
        """
        skill = "SCAN_MAP_FOR_BEAST"
        capability = q.capability_for_skill(skill, root=ROOT)
        key = f"{capability}|BEAST_SCAN_NOT_PROVEN|{skill}"
        record = q.EscalationRecord(
            key=key, capability=capability, failure_type="BEAST_SCAN_NOT_PROVEN", skill=skill,
            first_seen=NOW - timedelta(minutes=74),
        )
        snapshot = q.EscalationSnapshot({key: record})
        failed = [failure("BEAST_SCAN_NOT_PROVEN", skill)]

        proven_row = {
            "skill": skill,
            "result": "SUCCESS",
            "verifier_ok": True,
            "recorded_at": (NOW - timedelta(minutes=10)).isoformat(),
            "before_screenshot": "step_001_before.png",
            "after_screenshot": "step_001_after.png",
        }

        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / "episodes.jsonl"
            stream.write_text(json.dumps(proven_row) + "\n", encoding="utf-8")
            proven = q.candidates_from_run(
                stop_reason="", failures=failed, snapshot=snapshot,
                policy=q.EscalationPolicy(), now=NOW, root=ROOT, episodes_path=stream,
            )
            self.assertEqual(proven, ())

            stream.write_text("", encoding="utf-8")
            unproven = q.candidates_from_run(
                stop_reason="", failures=failed, snapshot=snapshot,
                policy=q.EscalationPolicy(), now=NOW, root=ROOT, episodes_path=stream,
            )
        self.assertEqual(len(unproven), 1)
        self.assertEqual(unproven[0].condition, q.STUCK_15_MIN)

    def test_a_gameplay_shaped_failure_is_unknown_game_mechanic(self):
        verdict = q.classify_condition(
            q.FailureSignature("CAP", "DISPATCH_NOT_PROVEN", "SKILL"),
            occurrences=1, first_seen=None, now=NOW, policy=q.EscalationPolicy(),
        )
        self.assertEqual(verdict[0], q.UNKNOWN_GAME_MECHANIC)

    def test_the_interface_conditions_are_not_condition_types(self):
        # The five named conditions are also the interface constants, so a typo
        # in either place cannot silently become a sixth.
        self.assertEqual(
            set(q.AUTO_ESCALATION_CONDITIONS),
            {q.CAPABILITY_MISSING, q.UNKNOWN_UI, q.UNKNOWN_GAME_MECHANIC,
             q.REPEATED_LIVE_FAILURE, q.STUCK_15_MIN},
        )


# ----------------------------------------------------------- model routing


class ModelBoundaryTest(unittest.TestCase):
    """The queue must not know what a model is.

    Model choice is WorkBuddy's strategy, and the operator's architecture puts
    models *below* WorkBuddy as replaceable compute.  The queue delegates to
    workbuddy_model_router and only carries whatever string comes back, which is
    what makes the boundary real rather than promised.  The router's own behaviour
    is tested in tests/test_workbuddy_model_router.py.
    """

    def test_the_queue_does_not_name_a_model(self):
        source = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
        for model in ("deepseek", "glm-", "hy4", "gpt", "claude"):
            self.assertNotIn(model, source.lower(), model)

    def test_the_queue_delegates_to_the_router(self):
        self.assertTrue(callable(q.default_router))

    def test_a_dispatch_carries_the_task_type_the_router_choose(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = q.ModelRouter(q.model_stats_path(tmp))
            candidate = q.EscalationCandidate(
                signature=q.FailureSignature("CAP", "SEMANTIC_TARGET_NOT_VERIFIED", "SKILL"),
                condition=q.UNKNOWN_UI, reason="reason",
            )
            dispatch = q.decide(candidate, q.EscalationSnapshot({}), q.EscalationPolicy(),
                                now=NOW, router=router)
            self.assertTrue(dispatch.should_submit)
            self.assertEqual(dispatch.task_type, TASK_UI_RECOGNITION)
            self.assertTrue(dispatch.model)

    def test_a_vision_shaped_problem_starts_on_the_vision_rung_when_cold(self):
        with tempfile.TemporaryDirectory() as tmp:
            router = q.ModelRouter(q.model_stats_path(tmp))
            candidate = q.EscalationCandidate(
                signature=q.FailureSignature("CAP", "SEMANTIC_TARGET_NOT_VERIFIED", "SKILL"),
                condition=q.UNKNOWN_UI,
                reason="the template crop covers the tutorial finger",
            )
            dispatch = q.decide(candidate, q.EscalationSnapshot({}), q.EscalationPolicy(),
                                now=NOW, router=router)
            self.assertEqual(dispatch.model, VISION_RUNG)

    def test_the_adapter_records_the_model_outcome_for_the_router_to_learn_from(self):
        status = JobStatus(job_id="job-9", gateway_state="done", verdict=q.DONE,
                           settled=True, first_terminal_at=int(NOW.timestamp() * 1000) + 60_000)
        harness = AdapterHarness(bridge=FakeBridge(status=status, submitted="job-9"))
        try:
            harness.adapter._wiring_problems = lambda: 0
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": "K", "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted", "key": "K",
                                   "job_id": "job-9", "model": "some-model",
                                   "task_type": TASK_UI_RECOGNITION,
                                   "repo_head": "h", "repo_dirty": 0})
            with patch.object(q, "repo_revision", return_value=q.RepoRevision("h", 0, True)):
                harness.adapter.reconcile(now=NOW)
            rows = harness.adapter.model_stats.rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["task_type"], TASK_UI_RECOGNITION)
            self.assertIsNone(rows[0]["cost"], "cost is not obtainable and must not be invented")
            self.assertFalse(rows[0]["live_improvement"])
        finally:
            harness.cleanup()


# ----------------------------------------------------------------- folding


class FoldTest(unittest.TestCase):
    def test_bridge_audit_rows_do_not_become_queue_state(self):
        # The bridge writes transport rows into the same file.  Folding those as
        # queue state would invent records for jobs the queue never created.
        events = [
            {"source": "bridge", "event": "submitted", "job_id": "job-x", "capability": "CAP"},
            {"source": "queue", "event": "escalation_created", "key": "K", "condition": q.UNKNOWN_UI},
        ]
        snapshot = q.fold(events)
        self.assertEqual(list(snapshot.records), ["K"])
        self.assertEqual(snapshot.get("K").state, q.NEW)

    def test_replaying_the_same_events_twice_gives_the_same_state(self):
        events = [
            {"source": "queue", "event": "escalation_created", "key": "K", "condition": q.UNKNOWN_UI},
            {"source": "queue", "event": "submitted", "key": "K", "job_id": "j", "attempt": 0},
        ]
        self.assertEqual(q.fold(events).get("K").state, q.fold(events).get("K").state)

    def test_a_job_reaching_a_terminal_state_moves_the_record(self):
        events = [
            {"source": "queue", "event": "escalation_created", "key": "K", "condition": q.UNKNOWN_UI},
            {"source": "queue", "event": "submitted", "key": "K", "job_id": "j"},
            {"source": "queue", "event": "job_state", "key": "K", "state": q.DONE},
        ]
        self.assertEqual(q.fold(events).get("K").state, q.DONE)

    def test_active_jobs_drive_the_concurrency_answer(self):
        events = [
            {"source": "queue", "event": "escalation_created", "key": "K", "condition": q.UNKNOWN_UI},
            {"source": "queue", "event": "submitted", "key": "K", "job_id": "j"},
        ]
        self.assertEqual(len(q.fold(events).active_jobs()), 1)
        self.assertEqual(len(q.fold(events[:1]).active_jobs()), 0)

    def test_a_stopped_job_settles_instead_of_holding_the_slot_forever(self):
        """``STOPPED`` is terminal at the gateway and has to be terminal here too.

        Measured while tracing the operator's P0: the fold settled only DONE/FAILED, so a
        cancelled job stayed ``WORKING`` and held the one concurrency slot -- starving
        every pending escalation behind it, which is the same "nothing ever consumes it"
        failure the consumer exists to remove.
        """
        snapshot = q.fold([
            {"source": "queue", "event": "escalation_created", "key": "K", "condition": q.UNKNOWN_UI},
            {"source": "queue", "event": "submitted", "key": "K", "job_id": "j"},
            {"source": "queue", "event": "job_state", "key": "K", "state": q.WORKING},
            {"source": "queue", "event": "job_state", "key": "K", "state": q.STOPPED,
             "recorded_at": NOW.isoformat()},
        ])
        record = snapshot.get("K")
        self.assertEqual(record.state, q.FAILED)
        self.assertIsNotNone(record.settled_at)
        self.assertEqual(snapshot.active_jobs(), ())

    def test_the_creation_refusal_is_folded_so_a_consumer_can_quote_it(self):
        """``dispatch_reason`` was written at creation and never folded, so it read blank."""
        snapshot = q.fold([{
            "source": "queue", "event": "escalation_created", "key": "K", "condition": q.UNKNOWN_UI,
            "dispatch": q.CONCURRENCY_WAIT, "dispatch_reason": "max_concurrent_jobs=1 is already used",
        }])
        self.assertIn("already used", snapshot.get("K").dispatch_reason)


# ------------------------------------------------- the hook must not hurt AUTO


class HookSafetyTest(unittest.TestCase):
    def test_a_dead_gateway_is_an_observation_not_an_exception(self):
        harness = AdapterHarness(bridge=FakeBridge(available=False, reason="GATEWAY_UNREACHABLE"))
        try:
            observation = harness.adapter.observe_run(
                stop_reason="training_entry_not_verified",
                failures=[failure("TRAINING_PAGE_NOT_PROVEN")], now=NOW,
            )
            self.assertEqual(observation.submitted, ())
            self.assertEqual(observation.errors, ())
            self.assertTrue(observation.skipped, "the candidate must be reported as skipped")
            self.assertIn("queued", harness.event_kinds())
        finally:
            harness.cleanup()

    def test_a_dead_gateway_leaves_the_escalation_queued_not_submitted(self):
        harness = AdapterHarness(bridge=FakeBridge(available=False, reason="GATEWAY_UNREACHABLE"))
        try:
            harness.adapter.observe_run(
                stop_reason="training_entry_not_verified",
                failures=[failure("TRAINING_PAGE_NOT_PROVEN")], now=NOW,
            )
            record = harness.ledger.snapshot().records
            self.assertEqual(len(record), 1)
            self.assertEqual(list(record.values())[0].state, q.QUEUED)
        finally:
            harness.cleanup()

    def test_a_bridge_that_raises_is_reported_and_swallowed(self):
        harness = AdapterHarness(bridge=ExplodingBridge())
        try:
            observation = harness.adapter.observe_run(
                stop_reason="training_entry_not_verified",
                failures=[failure("TRAINING_PAGE_NOT_PROVEN")], now=NOW,
            )
            self.assertTrue(observation.errors)
            self.assertIn("exploded", observation.errors[0])
        finally:
            harness.cleanup()

    def test_a_job_that_is_not_terminal_does_not_make_the_hook_wait(self):
        running = JobStatus(job_id="job-1", gateway_state="working", verdict=q.WORKING)
        harness = AdapterHarness(bridge=FakeBridge(status=running))
        try:
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": "K", "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": "K", "job_id": "job-1"})
            settled, errors = harness.adapter.reconcile(now=NOW)
            self.assertEqual(settled, [])
            self.assertEqual(errors, [])
            self.assertEqual(harness.bridge.status_calls, ["job-1"])
        finally:
            harness.cleanup()

    def test_a_gateway_that_lost_the_job_does_not_leave_it_working_forever(self):
        class GoneBridge(FakeBridge):
            def status(self, job_id):
                raise RuntimeError("404 NOT_FOUND")

        harness = AdapterHarness(bridge=GoneBridge())
        try:
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": "K", "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": "K", "job_id": "job-gone"})
            settled, errors = harness.adapter.reconcile(now=NOW)
            self.assertEqual(settled, [])
            self.assertTrue(errors)
            # Still SUBMITTED in the fold, but the run is not blocked by it for
            # longer than the operator's patience: the error is visible.
            self.assertIn("job-gone", errors[0])
        finally:
            harness.cleanup()

    def test_the_hook_reports_a_line_either_way(self):
        harness = AdapterHarness()
        try:
            observation = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            self.assertTrue(observation.line.startswith("[escalation]"))
        finally:
            harness.cleanup()


# ------------------------------------------------------- pending consumer
#
# Measured 2026-09-18, the operator's P0: two records were created with
# ``dispatch: CONCURRENCY_WAIT`` naming job a7ce58f0 (the one slot was busy) and then sat
# in ``NEW`` for 54 minutes after that job finished, with the gateway healthy and the
# console showing "WorkBuddy 排队".  A candidate is only ever derived from the run that
# produced it, so nothing re-offered them: "created" did not mean "will reach the bridge".

PENDING_KEY = "DISPATCH_GATHER_MARCH|SEMANTIC_TARGET_NOT_VERIFIED|DISPATCH_MARCH"


class PendingConsumerTest(unittest.TestCase):
    def _created_while_busy(self, harness, key=PENDING_KEY):
        """The exact row shape the live ledger has for a record born during CONCURRENCY_WAIT."""
        harness.ledger.append({
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

    def test_a_record_the_device_already_proved_is_released_not_dispatched(self):
        """Measured 2026-09-18 on both records the operator reported stuck.

        DISPATCH_MARCH had four verifier-passing episodes after its record was created --
        two of them on the current tree, minutes earlier -- so "the dispatch button cannot
        be found" was no longer true.  Dispatching a development agent at that point would
        be manufacturing work, and the record would otherwise age into a backlog that is
        not one.
        """
        harness = AdapterHarness()
        try:
            self._created_while_busy(harness)
            created = harness.ledger.snapshot().get(PENDING_KEY).first_seen
            episodes = Path(harness.root) / "learning/episodes.jsonl"
            episodes.write_text(json.dumps({
                "skill": "DISPATCH_MARCH",
                "recorded_at": (created + timedelta(minutes=5)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
                "episode_id": "20260918_090000_000000", "repo_revision": "abc+0",
            }), encoding="utf-8")

            observation = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            record = harness.ledger.snapshot().get(PENDING_KEY)
            self.assertEqual(observation.submitted, ())
            self.assertEqual(observation.released, (PENDING_KEY,))
            self.assertEqual(record.state, q.DONE)
            self.assertEqual(record.outcome, q.LIVE_VERIFIED)
            self.assertFalse(record.repairs_used, "releasing must not spend a repair shot")
            self.assertIn("released 1", observation.line)
        finally:
            harness.cleanup()

    def test_a_record_created_while_the_slot_was_busy_is_submitted_later(self):
        harness = AdapterHarness()
        try:
            self._created_while_busy(harness)
            # No failing episode, no stop-reason wall, no deferral: the run itself says
            # nothing happened.  The record still has to reach the bridge.
            observation = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            record = harness.ledger.snapshot().get(PENDING_KEY)
            self.assertEqual(observation.submitted, ("job-1",))
            self.assertEqual(record.state, q.SUBMITTED)
            self.assertEqual(record.job_id, "job-1")
            self.assertIn("pending_consumed", harness.event_kinds())
        finally:
            harness.cleanup()

    def test_the_consumer_waits_for_the_slot_instead_of_overrunning_it(self):
        """The cap still wins: a busy slot defers the pending record, it does not queue-jump."""
        harness = AdapterHarness()
        try:
            harness.ledger.append({
                "source": "queue", "event": "escalation_created", "key": "OTHER|UI|SKILL",
                "condition": q.UNKNOWN_UI,
            })
            harness.ledger.append({
                "source": "queue", "event": "submitted", "key": "OTHER|UI|SKILL", "job_id": "job-busy",
            })
            harness.ledger.append({
                "source": "queue", "event": "job_state", "key": "OTHER|UI|SKILL", "state": q.WORKING,
            })
            self._created_while_busy(harness)

            first = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            self.assertEqual(first.submitted, ())
            self.assertTrue(
                any(key == PENDING_KEY and q.CONCURRENCY_WAIT in why for key, why in first.skipped),
                first.skipped,
            )
            self.assertEqual(harness.ledger.snapshot().get(PENDING_KEY).state, q.NEW)

            # The holder finishes; the next run must pick the pending record up.
            harness.ledger.append({
                "source": "queue", "event": "job_state", "key": "OTHER|UI|SKILL", "state": q.DONE,
            })
            second = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            self.assertEqual(second.submitted, ("job-1",))
        finally:
            harness.cleanup()

    def test_a_refused_condition_is_not_re_offered(self):
        """Refused on creation for a reason that has not changed -- not re-refused forever."""
        harness = AdapterHarness()
        try:
            harness.ledger.append({
                "source": "queue", "event": "escalation_created", "key": "CAP|QUEUE_BUSY|SKILL",
                "capability": "CAP", "failure_type": "QUEUE_BUSY", "skill": "SKILL",
                "condition": q.NOT_ESCALATABLE,
            })
            observation = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            self.assertEqual(observation.submitted, ())
            self.assertEqual(observation.skipped, ())
        finally:
            harness.cleanup()

    def test_an_already_submitted_record_is_not_sent_twice(self):
        harness = AdapterHarness()
        try:
            self._created_while_busy(harness)
            harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            second = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            self.assertEqual(second.submitted, ())
            self.assertEqual(sum(1 for e in harness.events() if e["event"] == "submitted"), 1)
        finally:
            harness.cleanup()

    def test_a_live_verified_record_is_left_alone(self):
        """Learned means released, not re-dispatched."""
        harness = AdapterHarness()
        try:
            self._created_while_busy(harness)
            harness.ledger.append({
                "source": "queue", "event": "submitted", "key": PENDING_KEY, "job_id": "job-old",
            })
            harness.ledger.append({
                "source": "queue", "event": "job_state", "key": PENDING_KEY, "state": q.DONE,
            })
            harness.ledger.append({
                "source": "queue", "event": "reconciled", "key": PENDING_KEY,
                "job_state": q.DONE, "outcome": q.LIVE_VERIFIED,
            })
            observation = harness.adapter.observe_run(stop_reason="mail_all_clear", now=NOW)
            self.assertEqual(observation.submitted, ())
        finally:
            harness.cleanup()


# --------------------------------------------------------- reconciliation


class ReconciliationTest(unittest.TestCase):
    def _episodes(self, root: Path, rows) -> Path:
        path = root / "learning/episodes.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return path

    def test_a_new_verified_episode_is_the_only_route_to_live_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            self._episodes(root, [{
                "skill": "OPEN_INFANTRY_TRAINING", "recorded_at": (NOW + timedelta(minutes=5)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
                # Ran a tree that differs from the one at dispatch ("a").
                "repo_revision": "b+0", "episode_id": "20260918_090000_000000",
            }])
            outcome, explanation, episodes = q.reconcile_outcome(
                capability="KEEP_TRAINING", skill="OPEN_INFANTRY_TRAINING",
                submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=root,
            )
        self.assertEqual(outcome, q.LIVE_VERIFIED)
        self.assertEqual(len(episodes), 1)
        self.assertIn("verifier_ok", explanation)

    def test_a_concurrent_success_on_the_old_tree_is_not_the_jobs_proof(self):
        """RR-004: AUTO works the same skill while a job runs.

        Measured 2026-09-18: the NAVIGATE_TO_MAP reconciliation counted three verified
        episodes recorded while the job was still WORKING -- i.e. against the code it
        was about to replace.  A passing episode that ran the *dispatch* tree proves
        the old code still works, not that the new code does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            self._episodes(root, [{
                "skill": "OPEN_INFANTRY_TRAINING", "recorded_at": (NOW + timedelta(minutes=5)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
                "repo_revision": "a+0",
            }])
            outcome, explanation, episodes = q.reconcile_outcome(
                capability="KEEP_TRAINING", skill="OPEN_INFANTRY_TRAINING",
                submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=root,
            )
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)
        self.assertEqual(episodes, ())

    def test_an_episode_without_a_revision_cannot_prove_a_version_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            self._episodes(root, [{
                "skill": "OPEN_INFANTRY_TRAINING", "recorded_at": (NOW + timedelta(minutes=5)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
            }])
            outcome, _, _ = q.reconcile_outcome(
                capability="KEEP_TRAINING", skill="OPEN_INFANTRY_TRAINING",
                submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=root,
            )
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)

    def test_an_episode_without_recorded_at_is_history_not_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            self._episodes(root, [{
                "skill": "OPEN_INFANTRY_TRAINING", "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
            }])
            outcome, _, _ = q.reconcile_outcome(
                capability="KEEP_TRAINING", skill="OPEN_INFANTRY_TRAINING",
                submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=root,
            )
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)

    def test_an_episode_before_the_job_is_not_evidence_for_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            self._episodes(root, [{
                "skill": "OPEN_INFANTRY_TRAINING",
                "recorded_at": (NOW - timedelta(hours=1)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
            }])
            outcome, _, _ = q.reconcile_outcome(
                capability="KEEP_TRAINING", skill="OPEN_INFANTRY_TRAINING",
                submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=root,
            )
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)

    def test_an_episode_without_a_failing_verifier_is_not_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            self._episodes(root, [{
                "skill": "OPEN_INFANTRY_TRAINING",
                "recorded_at": (NOW + timedelta(minutes=5)).isoformat(),
                "verifier_ok": False, "result": "FAILURE",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
            }])
            outcome, _, _ = q.reconcile_outcome(
                capability="KEEP_TRAINING", skill="OPEN_INFANTRY_TRAINING",
                submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=root,
            )
        self.assertNotEqual(outcome, q.LIVE_VERIFIED)

    def test_a_code_change_with_a_clean_gate_is_test_pass_and_says_what_it_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome, explanation, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("b", 1, True),
                wiring_problems=0, agent_report="files changed: vision.py, verifier.py",
                root=Path(tmp),
            )
        self.assertEqual(outcome, q.TEST_PASS)
        self.assertIn("NOT a verified capability", explanation)

    def test_a_code_change_with_a_dirty_gate_is_only_code_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome, _, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("b", 1, True),
                wiring_problems=3, root=Path(tmp),
            )
        self.assertEqual(outcome, q.CODE_CHANGED)

    def test_a_job_that_changed_nothing_is_no_improvement(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome, _, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=0, root=Path(tmp),
            )
        self.assertEqual(outcome, q.NO_IMPROVEMENT)

    def test_a_failed_job_with_no_change_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome, _, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="FAILED",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=None, root=Path(tmp),
            )
        self.assertEqual(outcome, q.OUTCOME_BLOCKED)

    def test_a_code_change_raises_the_reload_signal(self):
        status = JobStatus(job_id="job-7", gateway_state="done", verdict=q.DONE, settled=True)
        harness = AdapterHarness(bridge=FakeBridge(status=status, submitted="job-7"))
        try:
            harness.adapter._wiring_problems = lambda: 0
            key = "CAP|TYPE|SKILL"
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": key, "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": key, "job_id": "job-7",
                                   "repo_head": "old", "repo_dirty": 0})
            with patch.object(q, "repo_revision", return_value=q.RepoRevision("new", 1, True)):
                harness.adapter.reconcile(now=NOW)
            pending = harness.signal.pending()
            self.assertIsNotNone(pending)
            self.assertEqual(pending.job_id, "job-7")
            self.assertIn("reload_required", harness.event_kinds())
        finally:
            harness.cleanup()

    def test_no_code_change_raises_no_reload_signal(self):
        status = JobStatus(job_id="job-8", gateway_state="done", verdict=q.DONE, settled=True)
        harness = AdapterHarness(bridge=FakeBridge(status=status, submitted="job-8"))
        try:
            harness.adapter._wiring_problems = lambda: 0
            harness.ledger.append({"source": "queue", "event": "escalation_created",
                                   "key": "K", "condition": q.UNKNOWN_UI})
            harness.ledger.append({"source": "queue", "event": "submitted",
                                   "key": "K", "job_id": "job-8",
                                   "repo_head": "same", "repo_dirty": 0})
            with patch.object(q, "repo_revision", return_value=q.RepoRevision("same", 0, True)):
                harness.adapter.reconcile(now=NOW)
            self.assertIsNone(harness.signal.pending())
        finally:
            harness.cleanup()


class AttributionTest(unittest.TestCase):
    """A tree diff is a fact; whose diff it is, is not.

    The first real escalation proved this the hard way: the reconciler measured a
    changed tree and recorded ``TEST_PASS``, while the agent's own report said "No
    code was changed" -- the diff was the harness editing the escalation queue
    while the job ran.  This project is edited from more than one place at once
    (that is why ``run_live.py`` carries a VERIFIER_MAPPING_CORRUPT guard), so the
    reconciler must corroborate before it credits.
    """

    def test_an_agent_denying_a_change_is_believed_about_that(self):
        for denial in ("No code was changed.", "I did not change any file",
                       "nothing changed in the tree", "the tree is unchanged"):
            self.assertFalse(q.agent_claims_change(denial), denial)

    def test_an_agent_claiming_a_change_is_recognised(self):
        for claim in ("files changed: a.py, b.py", "committed as 19964ec",
                      "I edited vision.py", "patched the verifier"):
            self.assertTrue(q.agent_claims_change(claim), claim)

    def test_an_empty_report_claims_nothing(self):
        self.assertFalse(q.agent_claims_change(""))

    def test_a_tree_diff_the_agent_denies_is_not_credited(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome, explanation, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("b", 1, True),
                wiring_problems=0, agent_report="No code was changed.", root=Path(tmp),
            )
        self.assertEqual(outcome, q.CODE_CHANGED)
        self.assertIn("may not be the agent's", explanation)

    def test_a_tree_diff_the_agent_corroborates_is_test_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcome, explanation, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("b", 1, True),
                wiring_problems=0, agent_report="committed as 19964ec, files changed: 2",
                root=Path(tmp),
            )
        self.assertEqual(outcome, q.TEST_PASS)
        self.assertIn("corroborating", explanation)
        self.assertIn("NOT a verified capability", explanation)

    def test_a_new_verified_episode_outranks_corroboration_entirely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "learning").mkdir(parents=True)
            (root / "learning/episodes.jsonl").write_text(json.dumps({
                "skill": "SKILL", "recorded_at": (NOW + timedelta(minutes=1)).isoformat(),
                "verifier_ok": True, "result": "SUCCESS",
                "before_screenshot": "b.png", "after_screenshot": "a.png",
                # A version that differs from dispatch: the episode is what proves the
                # capability, so the agent's own report cannot outrank it either way.
                "repo_revision": "b+1",
            }), encoding="utf-8")
            outcome, _, _ = q.reconcile_outcome(
                capability="CAP", skill="SKILL", submitted_at=NOW, job_verdict="DONE",
                before=q.RepoRevision("a", 0, True), after=q.RepoRevision("a", 0, True),
                wiring_problems=None, agent_report="I changed nothing", root=root,
            )
        self.assertEqual(outcome, q.LIVE_VERIFIED)


class PermissionDefaultTest(unittest.TestCase):
    def test_only_bypass_permissions_can_execute_measured(self):
        """Four real jobs, one prompt: only one mode ran a shell."""
        measured = {
            "dontAsk": False,
            "acceptEdits": False,
            "auto": False,
            "bypassPermissions": True,
        }
        from winter_agent_v2.workbuddy_bridge import (
            DEFAULT_PERMISSION_MODE,
            WorkBuddyBridge,
        )

        self.assertEqual(DEFAULT_PERMISSION_MODE, "bypassPermissions")
        self.assertTrue(measured[DEFAULT_PERMISSION_MODE])
        self.assertEqual(WorkBuddyBridge().permission_mode, DEFAULT_PERMISSION_MODE)


class CorrectionTest(unittest.TestCase):
    def test_a_correction_overwrites_the_outcome_without_spending_a_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = q.EscalationLedger(Path(tmp) / "ledger.jsonl")
            ledger.append({"source": "queue", "event": "escalation_created",
                           "key": "K", "condition": q.UNKNOWN_UI})
            ledger.append({"source": "queue", "event": "reconciled", "key": "K",
                           "outcome": q.TEST_PASS, "repair_used": True})
            self.assertEqual(ledger.snapshot().get("K").outcome, q.TEST_PASS)
            self.assertEqual(ledger.snapshot().get("K").repairs_used, 1)

            ledger.append({"source": "queue", "event": "reconciled", "correction": True,
                           "key": "K", "outcome": q.NO_IMPROVEMENT, "repair_used": False,
                           "explanation": "corrected by the operator: not the agent's diff"})
            record = ledger.snapshot().get("K")
            self.assertEqual(record.outcome, q.NO_IMPROVEMENT)
            self.assertEqual(record.repairs_used, 1, "a correction is not a new failure")


class RepoRevisionTest(unittest.TestCase):
    def test_a_revision_differs_when_the_head_or_the_dirty_count_moves(self):
        base = q.RepoRevision("a", 0, True)
        self.assertFalse(base.differs_from(q.RepoRevision("a", 0, True)))
        self.assertTrue(base.differs_from(q.RepoRevision("b", 0, True)))
        self.assertTrue(base.differs_from(q.RepoRevision("a", 1, True)))

    def test_an_unavailable_revision_never_claims_a_difference(self):
        self.assertFalse(q.RepoRevision("a", 0, True).differs_from(q.RepoRevision(ok=False)))

    def test_repo_revision_reads_the_real_repository(self):
        revision = q.repo_revision(ROOT)
        self.assertTrue(revision.ok)
        self.assertEqual(len(revision.head), 40)


class CapabilityResolutionTest(unittest.TestCase):
    def test_a_known_skill_resolves_to_its_capability(self):
        self.assertTrue(q.capability_for_skill("OPEN_INTEL", root=ROOT))

    def test_an_unknown_skill_resolves_to_itself_rather_than_a_guess(self):
        self.assertEqual(q.capability_for_skill("NOT_A_REAL_SKILL", root=ROOT), "NOT_A_REAL_SKILL")

    def test_a_skill_can_gain_a_capability_and_thereby_a_new_key(self):
        """The reason the one-job rule is by *capability*, measured on the real map.

        Deliberately not pinned to the capability's name -- the point is not which
        capability ``SCAN_MAP_FOR_BEAST`` belongs to, it is that a skill which once
        resolved to itself can stop doing so after an unrelated map edit, which changes
        the signature key of a wall that did not change.  22 of the 89 skills in the map
        already name two capabilities, and the resolver returns the first match in file
        order, so this is a class of change rather than one occurrence.
        """
        self.assertNotEqual(
            q.capability_for_skill("SCAN_MAP_FOR_BEAST", root=ROOT),
            "SCAN_MAP_FOR_BEAST",
            "this skill now carries a capability: an escalation for it is keyed differently "
            "than it was, which is exactly the re-key the capability-level rule defends against",
        )


class OneCapabilityOneJobTest(unittest.TestCase):
    """The operator's §九: two agents must never edit one capability.

    A signature key is per-*failure*, and the resolver that builds it is order-dependent
    (see ``CapabilityResolutionTest``), so key equality cannot answer "is someone already
    working on this capability".  Capability identity can.
    """

    def _sibling(self, state: str, capability: str = "SPEND_STAMINA_ON_BEAST"):
        return q.EscalationRecord(
            key=f"{capability}|NO_GOAL_PROGRESS|SELECT_BEAST_TARGET", state=state,
            capability=capability, skill="SELECT_BEAST_TARGET", job_id="job-live",
        )

    def _candidate(self, capability: str = "SPEND_STAMINA_ON_BEAST"):
        return q.EscalationCandidate(
            signature=q.FailureSignature(capability, "BEAST_SCAN_NOT_PROVEN", "SCAN_MAP_FOR_BEAST"),
            condition=q.UNKNOWN_UI, reason="the client showed something V2 could not read",
        )

    def test_a_second_key_for_the_same_capability_is_refused(self):
        sibling = self._sibling(q.WORKING)
        dispatch = q.decide(
            self._candidate(), q.EscalationSnapshot({sibling.key: sibling}),
            q.EscalationPolicy(), now=NOW,
        )
        self.assertEqual(dispatch.action, q.DEDUP_SKIP)
        self.assertIn("job-live", dispatch.reason)
        self.assertIn("must not have two jobs", dispatch.reason)

    def test_a_settled_sibling_does_not_block_the_next_escalation(self):
        # The same capability may be escalated again once the previous job is over --
        # otherwise a capability could be developed at most once, ever.  Iterating the
        # real set rather than a hand list, so a terminal state added later is covered.
        for settled in sorted(q.TERMINAL_STATES) + [q.LIVE_VERIFIED]:
            with self.subTest(state=settled):
                sibling = self._sibling(settled)
                dispatch = q.decide(
                    self._candidate(), q.EscalationSnapshot({sibling.key: sibling}),
                    q.EscalationPolicy(), now=NOW,
                )
                self.assertNotEqual(dispatch.action, q.DEDUP_SKIP)

    def test_another_capability_is_left_alone(self):
        sibling = self._sibling(q.WORKING, capability="SOMETHING_ELSE")
        dispatch = q.decide(
            self._candidate(), q.EscalationSnapshot({sibling.key: sibling}),
            q.EscalationPolicy(), now=NOW,
        )
        self.assertNotEqual(dispatch.action, q.DEDUP_SKIP)

    def test_a_real_failure_is_appended_to_a_running_job_rather_than_resubmitted(self):
        """§12, generalised: any active job owning the capability, not only a preload.

        Before this, the merge matched ``origin == "bootstrap"`` -- so a runtime job and a
        re-keyed signature produced *two* records for one capability and relied on the
        concurrency cap (1) to avoid two agents.  A cap is luck; this is a rule.
        """
        harness = AdapterHarness()
        try:
            sibling = q.EscalationRecord(
                key="SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SELECT_BEAST_TARGET",
                state=q.WORKING, capability="SPEND_STAMINA_ON_BEAST",
                skill="SPEND_STAMINA_ON_BEAST", job_id="job-live",
            )
            harness.ledger.append({
                "source": "queue", "event": "escalation_created", "key": sibling.key,
                "capability": sibling.capability, "failure_type": "NO_GOAL_PROGRESS",
                "skill": sibling.skill, "condition": q.STUCK_15_MIN, "job_id": "job-live",
            })
            harness.ledger.append({
                "source": "queue", "event": "submitted", "key": sibling.key, "job_id": "job-live",
            })

            harness.adapter.observe_run(
                stop_reason="", now=NOW,
                failures=[failure("BEAST_SCAN_NOT_PROVEN", "SPEND_STAMINA_ON_BEAST")],
            )

            kinds = harness.event_kinds()
            self.assertIn("evidence_appended", kinds)
            self.assertEqual(harness.bridge.submits, [], "a second job was opened")
            self.assertEqual(kinds.count("escalation_created"), 1, "a second record was opened")
            appended = [e for e in harness.events() if e["event"] == "evidence_appended"][0]
            self.assertEqual(appended["key"], sibling.key)
            self.assertNotEqual(appended["from_key"], sibling.key)
            # Only a preload job has a priority to raise; a runtime escalation is P0 already.
            self.assertNotIn("priority_raised", kinds)
        finally:
            harness.cleanup()


class ReloadSignalTest(unittest.TestCase):
    def test_a_fresh_marker_defers_the_next_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            signal = reload_mod.ReloadSignal(reload_mod.default_path(tmp))
            signal.request("job-1", "code changed")
            deferral = signal.evaluate(now=datetime.now(timezone.utc))
            self.assertTrue(deferral.defer)
            self.assertIn("settle", deferral.reason)

    def test_a_recent_write_keeps_deferring_past_the_marker_age(self):
        """The wait follows the tree, not the marker.

        Measured 2026-09-18: the panel logged the identical deferral every five
        seconds from a marker that was already 103 seconds old, because the thing
        that was still happening was the agent writing, not the marker ageing.
        """
        with tempfile.TemporaryDirectory() as tmp:
            signal = reload_mod.ReloadSignal(reload_mod.default_path(tmp))
            signal.request("job-1", "code changed")
            now = datetime.now(timezone.utc) + timedelta(seconds=reload_mod.SETTLE_SECONDS + 5)
            deferral = signal.evaluate(now=now, newest_write_at=now - timedelta(seconds=2))
            self.assertTrue(deferral.defer)
            self.assertIn("written 2s ago", deferral.reason)

    def test_an_active_job_alone_never_holds_auto_off(self):
        """The operator's §七: 禁止等待 Job 完成才继续 AUTO.

        Waiting on "a job is active" was the first version of this policy, and it
        held the game off for up to ``max_defer_seconds`` whenever an agent was
        working.  The job is still reported -- the operator asked to see it -- but
        it is not a reason to stop playing.
        """
        with tempfile.TemporaryDirectory() as tmp:
            signal = reload_mod.ReloadSignal(reload_mod.default_path(tmp))
            signal.request("job-1", "code changed")
            now = datetime.now(timezone.utc) + timedelta(seconds=reload_mod.SETTLE_SECONDS + 5)
            deferral = signal.evaluate(active_jobs=1, now=now, newest_write_at=now - timedelta(minutes=10))
            self.assertFalse(deferral.defer, "an active job must not stall AUTO")
            self.assertIn("not held for it", deferral.reason)

    def test_the_ceiling_stops_deferring_so_a_hung_agent_cannot_stall_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            signal = reload_mod.ReloadSignal(reload_mod.default_path(tmp))
            signal.request("job-1", "code changed")
            deferral = signal.evaluate(active_jobs=5, now=datetime.now(timezone.utc)
                                       + timedelta(seconds=reload_mod.MAX_DEFER_SECONDS + 1))
            self.assertFalse(deferral.defer)
            self.assertIn("ceiling", deferral.reason)

    def test_no_marker_never_defers(self):
        with tempfile.TemporaryDirectory() as tmp:
            signal = reload_mod.ReloadSignal(reload_mod.default_path(tmp))
            self.assertFalse(signal.evaluate().defer)

    def test_a_broken_marker_is_treated_as_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = reload_mod.default_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            signal = reload_mod.ReloadSignal(path)
            self.assertIsNone(signal.pending())
            self.assertFalse(signal.evaluate().defer)

    def test_a_marker_of_another_kind_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = reload_mod.default_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"kind": "SOMETHING_ELSE"}), encoding="utf-8")
            self.assertIsNone(reload_mod.ReloadSignal(path).pending())

    def test_clear_removes_the_marker_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            signal = reload_mod.ReloadSignal(reload_mod.default_path(tmp))
            signal.request("job-1", "code changed")
            self.assertTrue(signal.clear())
            self.assertFalse(signal.clear())
            self.assertIsNone(signal.pending())


class CredentialHygieneTest(unittest.TestCase):
    def test_the_queue_never_writes_a_credential_to_its_ledger(self):
        # The queue shares the bridge's ledger, and the bridge redacts; this pins
        # the property at the queue level too, because the queue is what builds the
        # payload that carries the environment.
        source = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
        for forbidden in ("CODEBUDDY_GATEWAY_PASSWORD", "gateway_password"):
            self.assertNotIn(forbidden, source, forbidden)


if __name__ == "__main__":
    unittest.main()
