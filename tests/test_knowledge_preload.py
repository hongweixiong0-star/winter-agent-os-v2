"""Knowledge Preload: read once, store once, reuse many times.

What these tests defend
-----------------------
*Knowledge is an artifact, not a context window* -- a record round-trips through
``knowledge/preload/<CAPABILITY>.json`` with every field the operator listed and a
provenance stamp per value.

*Nothing here can promote a capability* -- this layer stores beliefs about the game.
It has no skill registry, no lifecycle, and no way to write ``LIVE_VERIFIED``; the only
function that raises trust is ``confirm_from_live``, and the reconciler is its only
caller.

*The nine rungs are in the operator's order* -- local rungs are exhausted before any
network call, and "already answered" is a real answer.

*A failed calibration corrects the difference, it does not discard the prior* -- the
old value survives in the notes, because the difference is the finding.

*Persistence is by hook, not by intention* -- every settled bootstrap job re-enters the
loop and names the next capability.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import capability_bootstrap as cb  # noqa: E402
from winter_agent_v2 import escalation_queue as q  # noqa: E402
from winter_agent_v2 import knowledge_preload as kp  # noqa: E402

NOW = datetime(2026, 9, 18, 4, 0, 0, tzinfo=timezone.utc)


def catalog_row(code, *, category="N", implementation="MISSING", lifecycle="MISSING",
                risk="T1", attempts=0, capability_id=""):
    return {
        "capability_id": capability_id or f"CAP-{code[:3]}",
        "code": code, "name_cn": code, "category": category, "description": code,
        "unlock_status": "UNKNOWN", "current_role_available": "UNKNOWN",
        "implementation_status": implementation, "lifecycle": lifecycle, "risk": risk,
        "requires_march": False, "requires_stamina": False, "resource_cost": "UNKNOWN",
        "real_money_cost": "NONE_ALLOWED", "preferred_backend": "MAA",
        "existing_skill": None, "external_reference": "REFERENCE_ONLY",
        "live_attempts": attempts, "live_success": 0, "live_failure": 0,
        "success_rate": None, "last_live_verified": None, "blocked_reason": None,
    }


def full_record(capability="OPEN_ARENA", **overrides):
    """A record with every gate field filled, so tests can subtract one at a time."""
    data = dict(
        capability=capability,
        preconditions="from HOME", navigation="HOME -> ARENA", recognition="BTN_OPEN_ARENA",
        actions="tap the entry", success_state="page is arena", verifier_prior="verify_open_arena",
        recovery_prior="BACK", risk="T1", page_semantics="ArenaPage", failure_states="none",
        resource_rules="free", client_specific_notes="720x1280", source="test",
        source_type=kp.INTERNAL_KNOWLEDGE, source_confidence=0.6, status=kp.UNVERIFIED,
    )
    data.update(overrides)
    return kp.KnowledgeRecord(**data)


class TrustLadder(unittest.TestCase):
    def test_a_prior_can_never_outrank_live_evidence(self):
        self.assertLess(kp.TRUST_RANK[kp.PRIOR], kp.TRUST_RANK[kp.UNVERIFIED])
        self.assertLess(kp.TRUST_RANK[kp.UNVERIFIED], kp.TRUST_RANK[kp.OBSERVED])
        self.assertLess(kp.TRUST_RANK[kp.OBSERVED], kp.TRUST_RANK[kp.CONFIRMED])

    def test_only_seen_or_proven_knowledge_may_skip_a_live_frame(self):
        self.assertFalse(kp.trusted_enough(kp.PRIOR))
        self.assertFalse(kp.trusted_enough(kp.UNVERIFIED))
        self.assertTrue(kp.trusted_enough(kp.OBSERVED))
        self.assertTrue(kp.trusted_enough(kp.CONFIRMED))

    def test_a_record_is_only_as_good_as_its_weakest_field(self):
        record = full_record()
        for name in kp.GATE_FIELDS:
            record.field_status[name] = kp.CONFIRMED
        record.field_status["recovery_prior"] = kp.PRIOR
        self.assertEqual(record.weakest_field_trust(), kp.PRIOR)


class AcquisitionOrder(unittest.TestCase):
    def test_the_nine_rungs_are_the_operators_and_local_ones_come_first(self):
        self.assertEqual(kp.ACQUISITION_ORDER[:5], (
            "LIVE_VERIFIED_ASSET", "INTERNAL_KNOWLEDGE", "EPISODE_EVIDENCE",
            "LEGACY_VERIFIED_ASSET", "FAILURE_PATTERN"))
        self.assertEqual(kp.ACQUISITION_ORDER[5:], (
            "EXTERNAL_MAP", "OPEN_SOURCE_PROJECT", "GAME_WIKI", "SELF_EXPLORATION"))
        self.assertTrue(kp.LOCAL_RUNGS == frozenset(kp.ACQUISITION_ORDER[:5]))

    def test_rank_is_positional_and_unknown_sorts_last(self):
        self.assertEqual(kp.acquisition_rank("LIVE_VERIFIED_ASSET"), 1)
        self.assertEqual(kp.acquisition_rank("SELF_EXPLORATION"), 9)
        self.assertGreater(kp.acquisition_rank("NOT_A_RUNG"), 9)

    def test_a_local_answer_forbids_the_network(self):
        plan = SimpleNamespace(
            facets=(), missing_semantics=(), classes=(), reuse={}, external={},
        )
        check = kp.local_knowledge_check(plan, full_record())
        self.assertTrue(check.enough)
        self.assertFalse(check.network_allowed)
        self.assertIn("禁止重新联网研究", check.why)

    def test_a_gap_names_only_the_missing_questions(self):
        record = full_record(recovery_prior="")
        plan = SimpleNamespace(facets=(), missing_semantics=(), classes=(), reuse={}, external={})
        check = kp.local_knowledge_check(plan, record)
        self.assertFalse(check.enough)
        self.assertTrue(check.network_allowed)
        self.assertEqual(check.missing, ("recovery_prior",))
        self.assertEqual(len(check.questions()), 1)
        self.assertIn("失败后怎么恢复", check.questions()[0])


class SufficiencyGate(unittest.TestCase):
    def test_all_eight_questions_must_have_an_answer(self):
        self.assertTrue(full_record().sufficient)
        for name in kp.GATE_FIELDS:
            self.assertFalse(
                full_record(**{name: ""}).sufficient, f"{name} should be required"
            )

    def test_fields_outside_the_gate_may_still_be_unknown(self):
        record = full_record(page_semantics="", failure_states="")
        enough, missing = kp.sufficiency(record)
        self.assertTrue(enough)
        self.assertEqual(missing, ())

    def test_unknown_text_counts_as_missing_without_the_registry(self):
        self.assertIn("recovery_prior", full_record(recovery_prior="UNKNOWN").missing)


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = kp.KnowledgeStore(self.tmp)

    def test_a_record_round_trips_with_its_provenance(self):
        record = full_record()
        record.field_status["navigation"] = kp.OBSERVED
        record.field_source["navigation"] = "LIVE_CALIBRATION"
        path = self.store.save(record, now=NOW)
        self.assertTrue(path.is_file())
        back = self.store.load("OPEN_ARENA")
        self.assertEqual(back.navigation, record.navigation)
        self.assertEqual(back.field_status["navigation"], kp.OBSERVED)
        self.assertEqual(back.field_source["navigation"], "LIVE_CALIBRATION")
        self.assertEqual(back.source_type, kp.INTERNAL_KNOWLEDGE)

    def test_the_operator_field_list_is_what_gets_written(self):
        self.store.save(full_record(), now=NOW)
        payload = json.loads(self.store.path("OPEN_ARENA").read_text(encoding="utf-8"))
        for name in kp.KNOWLEDGE_FIELDS:
            self.assertIn(name, payload)
        for name in ("source", "source_type", "source_confidence", "observed_date",
                     "live_calibration_status", "capability_id", "conflicts"):
            self.assertIn(name, payload)

    def test_the_index_is_derived_so_it_cannot_disagree(self):
        self.store.save(full_record("A_CAP"), now=NOW)
        self.store.save(full_record("B_CAP", recovery_prior=""), now=NOW)
        path = self.store.write_index(now=NOW)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["records"], 2)
        self.assertEqual(payload["summary"]["sufficient"], 1)
        self.assertEqual(len(payload["records"]), 2)

    def test_a_missing_file_is_not_an_error(self):
        self.assertIsNone(self.store.load("NEVER_WRITTEN"))
        self.assertEqual(self.store.records(), ())


class Freshness(unittest.TestCase):
    """Operator §十: do not re-read the same manual, but do re-read when it changed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = kp.KnowledgeStore(self.tmp)
        record = full_record(question="入口在哪里", game_version="1.20")
        record.status = kp.UNVERIFIED
        self.store.save(record, now=NOW)

    def test_an_answered_question_is_not_asked_again(self):
        needs, why = self.store.needs_research(
            "OPEN_ARENA", question="入口在哪里", source_type=kp.GAME_WIKI)
        self.assertFalse(needs)
        self.assertIn("already answered", why)

    def test_a_different_question_is_researched(self):
        needs, why = self.store.needs_research(
            "OPEN_ARENA", question="成功状态是什么", source_type=kp.GAME_WIKI)
        self.assertTrue(needs)
        self.assertIn("different question", why)

    def test_a_new_game_version_invalidates_the_answer(self):
        needs, why = self.store.needs_research(
            "OPEN_ARENA", question="入口在哪里", source_type=kp.GAME_WIKI,
            game_version="1.21")
        self.assertTrue(needs)
        self.assertIn("version moved", why)

    def test_an_unresolved_conflict_forces_research(self):
        record = kp.mark_conflict(
            self.store.load("OPEN_ARENA"), "navigation",
            prior="HOME -> ARENA", live="HOME -> EVENT", now=NOW)
        self.store.save(record, now=NOW)
        needs, why = self.store.needs_research(
            "OPEN_ARENA", question="入口在哪里", source_type=kp.GAME_WIKI)
        self.assertTrue(needs)
        self.assertIn("conflict", why)

    def test_a_prior_only_answer_is_researched(self):
        record = full_record(question="入口在哪里")
        record.status = kp.PRIOR
        self.store.save(record, now=NOW)
        needs, why = self.store.needs_research(
            "OPEN_ARENA", question="入口在哪里", source_type=kp.GAME_WIKI)
        self.assertTrue(needs)
        self.assertIn("PRIOR", why)

    def test_no_record_at_all_is_the_first_reason(self):
        needs, why = self.store.needs_research(
            "NOT_STORED", question="any", source_type=kp.GAME_WIKI)
        self.assertTrue(needs)
        self.assertIn("no knowledge record", why)


class Calibration(unittest.TestCase):
    def test_agreement_produces_no_diff(self):
        record = full_record()
        diffs = kp.prior_vs_live_diff(record, {"navigation": record.navigation})
        self.assertEqual(diffs, ())

    def test_a_difference_is_recorded_with_both_sides(self):
        record = full_record()
        diffs = kp.prior_vs_live_diff(record, {"navigation": "HOME -> EVENT"})
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].prior, "HOME -> ARENA")
        self.assertEqual(diffs[0].observed, "HOME -> EVENT")

    def test_calibration_fixes_the_field_and_keeps_the_old_prior_in_the_notes(self):
        record = full_record()
        diffs = kp.prior_vs_live_diff(record, {"navigation": "HOME -> EVENT"})
        kp.calibrate(record, diffs, confirmed_fields=("actions",), evidence=("frame#7",), now=NOW)
        self.assertEqual(record.navigation, "HOME -> EVENT")
        self.assertEqual(record.field_status["navigation"], kp.OBSERVED)
        self.assertEqual(record.field_status["actions"], kp.OBSERVED)
        self.assertTrue(any("PRIOR_VS_LIVE_DIFF navigation" in note for note in record.notes))
        self.assertIn("frame#7", record.evidence)

    def test_calibration_does_not_wipe_fields_the_client_did_not_contradict(self):
        record = full_record()
        kp.calibrate(record, (), confirmed_fields=("actions",), now=NOW)
        self.assertEqual(record.navigation, "HOME -> ARENA")
        self.assertEqual(record.recovery_prior, "BACK")

    def test_live_success_is_the_only_route_to_confirmed(self):
        record = full_record()
        self.assertEqual(record.status, kp.UNVERIFIED)
        kp.confirm_from_live(record, evidence=("episode:20260918_1",), now=NOW)
        self.assertEqual(record.status, kp.CONFIRMED)
        self.assertEqual(record.live_calibration_status, "CONFIRMED")
        self.assertEqual(record.field_status["navigation"], kp.CONFIRMED)

    def test_a_conflict_is_an_open_question_not_a_low_score(self):
        record = full_record()
        kp.mark_conflict(record, "actions", prior="tap A", live="tap B", now=NOW)
        self.assertEqual(record.status, kp.CONFLICT)
        self.assertTrue(record.conflicts)
        self.assertLess(kp.TRUST_RANK[kp.CONFLICT], kp.TRUST_RANK[kp.PRIOR])


class NothingHereCanPromoteACapability(unittest.TestCase):
    def test_this_layer_owns_no_registry_and_no_lifecycle(self):
        source = (ROOT / "winter_agent_v2/knowledge_preload.py").read_text(encoding="utf-8")
        for forbidden in ("class KnowledgeRegistry", "class SkillRegistry",
                          "class KnowledgeScheduler", "from .skills", "import skills"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("lifecycle", {f for f in kp.KnowledgeRecord.__dataclass_fields__})

    def test_a_record_cannot_claim_a_skill_state(self):
        payload = full_record().as_json()
        self.assertNotIn("lifecycle", payload)
        self.assertEqual(payload["status"], kp.UNVERIFIED)


class Controller(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "knowledge/game").mkdir(parents=True)
        (self.tmp / "knowledge/goals").mkdir(parents=True)
        (self.tmp / "learning").mkdir(parents=True)
        (self.tmp / "knowledge/game/capability_catalog.json").write_text(json.dumps({
            "schema_version": "1.0",
            "capabilities": [
                catalog_row("OPEN_ARENA", category="N", capability_id="CAP-N01"),
                catalog_row("OPEN_VIP", category="N", capability_id="CAP-N03"),
                catalog_row("CHECK_MARCH", category="N", implementation="EXISTING",
                            lifecycle="CANDIDATE", attempts=2, capability_id="CAP-N02"),
            ],
        }), encoding="utf-8")
        self.store = kp.KnowledgeStore(self.tmp)
        self.controller = cb.KnowledgeBootstrapController(self.tmp, store=self.store)

    def test_a_cycle_selects_scans_and_writes_a_state_a_watchdog_can_read(self):
        report = self.controller.cycle(now=NOW, dispatch=False)
        self.assertEqual(report.selected, "OPEN_ARENA")
        self.assertEqual(report.tier, "P1")
        state_path = self.tmp / cb.STATE_PATH
        self.assertTrue(state_path.is_file())
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for question in ("controller", "stage", "learning", "learning_missing",
                         "preloading", "awaiting_calibration", "last_preload_at",
                         "next_capability", "coverage"):
            self.assertIn(question, state)
        self.assertEqual(state["controller"], "RUNNING")

    def test_an_incomplete_capability_becomes_a_targeted_research_request(self):
        report = self.controller.cycle(now=NOW, dispatch=False)
        self.assertEqual(report.decision, cb.DECISION_RESEARCH_QUEUED)
        self.assertTrue(report.questions)
        record = self.store.load("OPEN_ARENA")
        # The plan's fields came from V2's own code, so the record is UNVERIFIED rather
        # than PRIOR -- believed, but not re-proved for this capability.  An external
        # source would be PRIOR; the difference is the point of the ladder.
        self.assertEqual(record.status, kp.UNVERIFIED)
        self.assertEqual(record.source_type, kp.LIVE_VERIFIED_ASSET)
        # The synthetic row's other fields came from the project's own OPEN_ARENA prior,
        # so the one thing still missing is what the research job must ask for.
        self.assertIn("失败后怎么恢复", record.question)
        # A dry run sends nothing, so it claims nothing: no attempt is consumed and the
        # record does not pretend a research job is out.
        self.assertEqual(record.research_attempts, 0)
        self.assertEqual(record.live_calibration_status, "")

    def test_a_dispatched_research_is_recorded_as_pending(self):
        controller = cb.KnowledgeBootstrapController(
            self.tmp, store=self.store, adapter=ScriptedAdapter(job="job-research-1"))
        report = controller.cycle(now=NOW)
        self.assertEqual(report.decision, cb.DECISION_RESEARCH_QUEUED)
        record = self.store.load("OPEN_ARENA")
        self.assertEqual(record.live_calibration_status, cb.PENDING_RESEARCH)
        self.assertEqual(record.research_attempts, 1)

    def test_a_second_cycle_moves_on_instead_of_asking_the_same_question_twice(self):
        """§七: one hard-to-find manual must not stall the whole loop."""
        controller = cb.KnowledgeBootstrapController(
            self.tmp, store=self.store, adapter=ScriptedAdapter(job="job-research-1"))
        first = controller.cycle(now=NOW)
        self.assertEqual(first.selected, "OPEN_ARENA")
        record = self.store.load("OPEN_ARENA")
        report = controller.cycle(now=NOW)
        self.assertEqual(report.selected, "OPEN_VIP", "the loop moved on, it did not stall")
        self.assertTrue(
            any("research already out" in reason for reason in report.skipped),
            report.skipped,
        )
        self.assertEqual(self.store.load("OPEN_ARENA").research_attempts,
                         record.research_attempts)

    def test_a_sufficient_record_goes_to_preload_instead_of_research(self):
        self.store.save(full_record("OPEN_ARENA"), now=NOW)
        report = self.controller.cycle(now=NOW, dispatch=False)
        self.assertEqual(report.decision, cb.DECISION_PRELOADED)
        self.assertEqual(report.stage, "PRELOAD")

    def test_the_loop_always_names_the_next_capability(self):
        report = self.controller.cycle(now=NOW, dispatch=False)
        self.assertEqual(report.next_capability, "OPEN_VIP")

    def test_a_blocked_research_is_skipped_by_the_next_selection(self):
        self.store.save(
            full_record("OPEN_ARENA", recovery_prior="", question="q",
                        live_calibration_status=cb.KNOWLEDGE_BLOCKED, research_attempts=1),
            now=NOW,
        )
        plan, skipped = self.controller.select(self.controller.scan(now=NOW))
        self.assertEqual(plan.code, "OPEN_VIP")
        self.assertTrue(any("research already out" in reason for reason in skipped))

    def test_completion_on_live_success_confirms_the_knowledge(self):
        self.store.save(full_record("OPEN_ARENA"), now=NOW)
        summary = self.controller.completion_hook(
            capability="OPEN_ARENA", outcome="LIVE_VERIFIED",
            evidence=("episode:abc",), now=NOW)
        self.assertIn("CONFIRMED", summary)
        record = self.store.load("OPEN_ARENA")
        self.assertEqual(record.status, kp.CONFIRMED)
        self.assertIn("episode:abc", record.evidence)

    def test_an_external_source_stays_a_prior(self):
        """The one distinction the whole ladder exists for."""
        plan = SimpleNamespace(
            code="OPEN_ARENA", capability_id="CAP-N01",
            facets=(cb.Facet("Navigation", "HOME -> ARENA", "EXTERNAL_MAP", 0.45),),
            missing_semantics=(), classes=("EXTERNAL_PRIOR_UNIMPLEMENTED",),
            reuse={}, external={"capability": "ARENA"},
        )
        record = kp.from_plan(
            plan, source="external card", source_type=kp.EXTERNAL_MAP,
            source_confidence=0.4, now=NOW)
        self.assertEqual(record.status, kp.PRIOR)
        self.assertEqual(kp.acquisition_rank(record.source_type), 6)
        self.assertFalse(kp.trusted_enough(record.status))

    def test_completion_on_failure_asks_for_a_difference_report_not_a_rewrite(self):
        self.store.save(full_record("OPEN_ARENA"), now=NOW)
        self.controller.completion_hook(
            capability="OPEN_ARENA", outcome="BLOCKED", agent_report="could not find the button",
            now=NOW)
        record = self.store.load("OPEN_ARENA")
        self.assertEqual(record.live_calibration_status, cb.CALIBRATION_FAILED)
        self.assertEqual(record.navigation, "HOME -> ARENA")
        self.assertTrue(any("PRIOR_VS_LIVE_DIFF owed" in n for n in record.notes))

    def test_completion_without_a_record_reports_rather_than_guesses(self):
        summary = self.controller.completion_hook(
            capability="NOT_STORED", outcome="LIVE_VERIFIED", now=NOW)
        self.assertIn("no knowledge record", summary)

    def test_coverage_prints_its_denominators(self):
        coverage = self.controller.coverage()
        self.assertEqual(set(coverage), {"unlocked", "all", "knowledge", "definitions"})
        self.assertIn("live_verified_percent", coverage["unlocked"])
        self.assertTrue(coverage["definitions"]["unlocked"])

    def test_a_dry_run_writes_no_ledger_row(self):
        self.controller.cycle(now=NOW, dispatch=False)
        ledger = self.tmp / q.DEFAULT_LEDGER
        self.assertFalse(ledger.exists())


class MergeWithRuntimeGaps(unittest.TestCase):
    """Operator §12: a real failure on a preload job appends evidence, never a 2nd job."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning").mkdir(parents=True)
        self.ledger = self.tmp / q.DEFAULT_LEDGER
        self.bridge = FakeBridge()

    def _adapter(self):
        return q.EscalationQueueAdapter(
            root=self.tmp, ledger=q.EscalationLedger(self.ledger), bridge=self.bridge)

    def _seed_preload_job(self):
        """A preload job that is in flight for OPEN_ARENA."""
        ledger = q.EscalationLedger(self.ledger)
        ledger.append({
            "source": "queue", "event": "escalation_created", "origin": "bootstrap",
            "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA", "capability": "OPEN_ARENA",
            "failure_type": "CAPABILITY_MISSING", "skill": "OPEN_ARENA",
            "condition": "CAPABILITY_MISSING", "recorded_at": NOW.isoformat(),
        })
        ledger.append({
            "source": "queue", "event": "submitted", "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA",
            "job_id": "preload-1", "recorded_at": NOW.isoformat(),
        })

    def test_a_real_failure_is_appended_to_the_preload_job(self):
        self._seed_preload_job()
        before = len(self.bridge.submits)
        observation = self._adapter().observe_run(
            stop_reason="UNKNOWN_PAGE",
            failures=[{
                "failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "skill": "OPEN_ARENA",
                "goal_id": "USE_FREE_ARENA_ATTEMPTS", "before_screenshot": "shot.png",
            }],
            now=NOW,
        )
        self.assertEqual(len(self.bridge.submits), before, "no second job may be created")
        self.assertTrue(
            any("MERGED_INTO_ACTIVE_JOB" in reason for _key, reason in observation.skipped),
            observation.skipped,
        )
        events = q.EscalationLedger(self.ledger).events()
        kinds = [e.get("event") for e in events]
        self.assertIn("evidence_appended", kinds)
        self.assertIn("priority_raised", kinds)
        appended = next(e for e in events if e.get("event") == "evidence_appended")
        self.assertEqual(appended["key"], "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")
        self.assertTrue(appended["evidence"])

    def test_the_merge_raises_the_existing_job_rather_than_making_a_new_one(self):
        self._seed_preload_job()
        self._adapter().observe_run(
            stop_reason="UNKNOWN_PAGE",
            failures=[{"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "skill": "OPEN_ARENA",
                       "goal_id": "USE_FREE_ARENA_ATTEMPTS"}],
            now=NOW,
        )
        snapshot = q.fold(q.EscalationLedger(self.ledger).events())
        self.assertEqual(len(snapshot.records), 1, "one capability, one job")
        record = snapshot.get("OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")
        self.assertEqual(record.origin, "bootstrap")
        self.assertTrue(any("priority raised to P0" in note for note in record.notes))
        self.assertTrue(any("real failure appended" in note for note in record.notes))

    def test_an_unrelated_failure_never_touches_the_preload_job(self):
        self._seed_preload_job()
        self._adapter().observe_run(
            stop_reason="UNKNOWN_PAGE",
            failures=[{"failure_type": "SEMANTIC_TARGET_NOT_VERIFIED", "skill": "OPEN_LABYRINTH",
                       "goal_id": "LABYRINTH_DAILY"}],
            now=NOW,
        )
        events = q.EscalationLedger(self.ledger).events()
        # A first sighting of an unknown-UI shape gets its own record; what matters here
        # is that it did NOT get appended to the preload job for a different capability.
        merged = [e for e in events if e.get("event") == "evidence_appended"]
        self.assertEqual(merged, [])
        record = q.fold(events).get("OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")
        self.assertEqual(record.notes, [])


class ScriptedAdapter:
    """The queue adapter's one method, scripted, so a test can be "dispatched"."""

    def __init__(self, *, job: str = "", note: str = ""):
        self._job, self._note = job, note
        self.calls: list[dict] = []

    def preload(self, *, now=None, plan=None, mode="PRELOAD", questions=()):
        self.calls.append({"plan": getattr(plan, "code", ""), "mode": mode,
                           "questions": tuple(questions)})
        return q.RunObservation(
            preloaded=(getattr(plan, "code", ""),) if self._job else (),
            preload_note=self._note,
        )


class FakeBridge:
    def __init__(self, *, submitted="job-1"):
        self._submitted = submitted
        self.submits: list[dict] = []

    def is_available(self):
        return SimpleNamespace(available=True, reason="OK")

    def submit(self, context, *, name, model):
        self.submits.append({"name": name, "model": model})
        return SimpleNamespace(job_id=self._submitted)

    def cancel(self, job_id):
        return True


class ValidationLease(unittest.TestCase):
    """The device hand-off for a version waiting to be examined (the P0-D link).

    Before this, ``LIVE_VERIFY_PENDING`` existed and the lease protocol existed, and
    nothing ever *asked* for the device -- so the operator's chain (new version -> live
    episode -> verifier -> LIVE_VERIFIED) had no one to take the first step.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning/control_panel").mkdir(parents=True)
        self.ledger = self.tmp / q.DEFAULT_LEDGER
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.bridge = FakeBridge()
        self.heartbeat(NOW)

    def heartbeat(self, when):
        (self.tmp / "learning/control_panel/pump.json").write_text(
            json.dumps({"written_at": when.isoformat(), "process": 4242}), encoding="utf-8")

    def _adapter(self):
        return q.EscalationQueueAdapter(
            root=self.tmp, ledger=q.EscalationLedger(self.ledger), bridge=self.bridge)

    def _seed_waiting_version(self):
        ledger = q.EscalationLedger(self.ledger)
        ledger.append({
            "source": "queue", "event": "escalation_created", "origin": "bootstrap",
            "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA", "capability": "OPEN_ARENA",
            "failure_type": "CAPABILITY_MISSING", "skill": "OPEN_ARENA",
            "condition": "CAPABILITY_MISSING", "goal": "USE_FREE_ARENA_ATTEMPTS",
            "job_id": "job-7", "recorded_at": NOW.isoformat(),
        })
        ledger.append({
            "source": "queue", "event": "live_verify_pending",
            "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA",
            "outcome": "VERSION_ACTIVATION_PENDING", "version_since": NOW.isoformat(),
        })

    def _holder(self):
        from winter_agent_v2.device_lease import DeviceLease

        return DeviceLease(self.tmp).holder(now=NOW)

    def test_it_asks_for_the_device_for_a_version_waiting_to_be_examined(self):
        self._seed_waiting_version()
        observation = self._adapter().pump(now=NOW)
        self.assertEqual(observation.lease_requested_for, "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")
        holder = self._holder()
        self.assertIsNotNone(holder, "the queue must actually take the device")
        self.assertEqual(holder.owner, "DEVELOPMENT_VALIDATION")
        self.assertEqual(holder.trace_id, "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")
        kinds = [e.get("event") for e in q.EscalationLedger(self.ledger).events()]
        self.assertIn("validation_lease_requested", kinds)

    def test_it_never_asks_when_nobody_could_drive_the_validation(self):
        """A device that stands down with nobody to drive it is worse than a wait."""
        self.heartbeat(datetime(2026, 9, 18, 1, 0, 0, tzinfo=timezone.utc))
        self._seed_waiting_version()
        observation = self._adapter().pump(now=NOW)
        self.assertEqual(observation.lease_requested_for, "")
        self.assertIsNone(self._holder())
        events = q.EscalationLedger(self.ledger).events()
        deferred = [e for e in events if e.get("event") == "validation_lease_deferred"]
        self.assertTrue(deferred)
        self.assertIn("nobody to drive", deferred[0]["reason"])

    def test_the_device_goes_back_when_the_examination_finishes(self):
        self._seed_waiting_version()
        adapter = self._adapter()
        adapter.pump(now=NOW)
        self.assertIsNotNone(self._holder())
        released = adapter.release_validation_lease(
            result="LIVE_VERIFIED", reason="examined", expect_key="OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA",
            now=NOW)
        self.assertTrue(released)
        self.assertIsNone(self._holder())

    def test_it_will_not_release_another_records_device(self):
        self._seed_waiting_version()
        adapter = self._adapter()
        adapter.pump(now=NOW)
        released = adapter.release_validation_lease(
            result="LIVE_VERIFIED", reason="wrong record", expect_key="SOME_OTHER_KEY", now=NOW)
        self.assertFalse(released)
        self.assertIsNotNone(self._holder(), "another record's lease must survive")

    def test_nothing_waiting_hands_the_device_straight_back(self):
        self._seed_waiting_version()
        adapter = self._adapter()
        adapter.pump(now=NOW)
        self.assertIsNotNone(self._holder())
        # The record leaves LIVE_VERIFY_PENDING (settled), so the next pass must not keep
        # the device frozen for a version nobody has to examine any more.
        q.EscalationLedger(self.ledger).append({
            "source": "queue", "event": "reconciled",
            "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA",
            "outcome": "LIVE_VERIFIED", "job_state": "DONE", "recorded_at": NOW.isoformat(),
        })
        adapter.pump(now=NOW)
        self.assertIsNone(self._holder())

    def test_the_runtime_is_told_who_owns_the_device_by_the_lease_file(self):
        """No second channel: the runtime reads the same lock everyone else does."""
        self._seed_waiting_version()
        self._adapter().pump(now=NOW)
        payload = json.loads((self.tmp / "learning/DEVICE_LEASE.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["owner"], "DEVELOPMENT_VALIDATION")
        self.assertEqual(payload["trace_id"], "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")


class ResearchComesBack(unittest.TestCase):
    """The half of READ ONCE that was missing: writing the answer down.

    The controller could ask a question -- it could put a work order carrying the
    missing fields onto the one queue -- but nothing put the answer back, so every
    loop re-researched the same capability and the knowledge base never grew.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = kp.KnowledgeStore(self.tmp)

    def _answer(self, name, payload):
        self.store.inbox.mkdir(parents=True, exist_ok=True)
        (self.store.inbox / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _seed(self, **fields):
        record = kp.KnowledgeRecord(capability="TROOP_SELECT", capability_id="CAP-A01")
        for name, value in fields.items():
            setattr(record, name, value)
        self.store.save(record)
        return record

    def test_an_answer_lands_in_the_record_with_its_own_trust(self):
        self._seed()
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{
                "field": "recovery_prior", "value": "失败点 BACK 关掉弹窗",
                "source": "frame probe", "source_type": kp.SELF_EXPLORATION,
            }],
        })
        result = self.store.ingest()
        self.assertEqual(result.accepted, ("TROOP_SELECT.recovery_prior",))
        record = self.store.load("TROOP_SELECT")
        self.assertEqual(record.value("recovery_prior"), "失败点 BACK 关掉弹窗")
        # A real-device look is OBSERVED, never CONFIRMED -- only a live episode can do that.
        self.assertEqual(record.field_trust("recovery_prior"), kp.OBSERVED)

    def test_an_external_answer_can_never_be_more_than_a_prior(self):
        self._seed()
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{
                "field": "navigation", "value": "HOME -> ARMY",
                "source": "wosbot/ui.py:12", "source_type": kp.OPEN_SOURCE_PROJECT,
            }],
        })
        self.store.ingest()
        self.assertEqual(self.store.load("TROOP_SELECT").field_trust("navigation"), kp.PRIOR)

    def test_an_external_answer_may_not_disagree_with_a_confirmed_field(self):
        """The prior loses to the client; the disagreement is kept, not hidden."""
        self._seed(recognition="部队弹窗（真机确认）")
        record = self.store.load("TROOP_SELECT")
        record.field_status["recognition"] = kp.CONFIRMED
        self.store.save(record)
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{
                "field": "recognition", "value": "wiki 说是行军页",
                "source": "wiki", "source_type": kp.GAME_WIKI,
            }],
        })
        result = self.store.ingest()
        self.assertEqual(result.notes and len(result.notes), 1)
        after = self.store.load("TROOP_SELECT")
        self.assertEqual(after.value("recognition"), "部队弹窗（真机确认）")
        self.assertEqual(after.field_trust("recognition"), kp.CONFIRMED)
        self.assertTrue(any("wiki 说是行军页" in note for note in after.notes))

    def test_a_renamed_field_is_refused_by_name(self):
        """The gate reads exact names, so a rename must fail loudly, not silently."""
        self._seed()
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{"field": "recovery", "value": "BACK", "source": "x",
                         "source_type": kp.GAME_WIKI}],
        })
        result = self.store.ingest()
        self.assertEqual(result.accepted, ())
        self.assertTrue(any("unknown field 'recovery'" in r for r in result.rejected))

    def test_a_claim_without_a_known_source_rung_is_refused(self):
        """Trust cannot be assigned to an unknown rung, and guessing it is how a
        prior becomes a fact."""
        self._seed()
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{"field": "actions", "value": "tap", "source": "x",
                         "source_type": "BECAUSE_I_SAID_SO"}],
        })
        result = self.store.ingest()
        self.assertEqual(result.accepted, ())
        self.assertTrue(any("unknown source_type" in r for r in result.rejected))

    def test_an_answer_never_makes_a_holey_record_confirmed(self):
        """Otherwise the research that answered one question would un-schedule the
        capability forever, because ``select()`` refuses CONFIRMED records."""
        record = self._seed()
        record.field_status["preconditions"] = kp.CONFIRMED
        self.store.save(record)
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{"field": "risk", "value": "T0", "source": "frame",
                         "source_type": kp.SELF_EXPLORATION}],
        })
        self.store.ingest()
        after = self.store.load("TROOP_SELECT")
        self.assertTrue(after.missing)
        self.assertNotEqual(after.status, kp.CONFIRMED)

    def test_an_answer_is_kept_for_audit_rather_than_deleted(self):
        self._seed()
        self._answer("a.json", {
            "capability": "TROOP_SELECT",
            "answers": [{"field": "risk", "value": "T0", "source": "frame",
                         "source_type": kp.SELF_EXPLORATION}],
        })
        self.store.ingest()
        self.assertEqual([p.name for p in self.store.pending_research()], [])
        self.assertTrue((self.store.inbox / "done" / "a.json").exists())
        self.assertEqual(self.store.ingest().accepted, (), "ingesting twice must not re-apply")

    def test_an_unreadable_answer_is_set_aside_with_its_reason(self):
        self.store.inbox.mkdir(parents=True, exist_ok=True)
        (self.store.inbox / "broken.json").write_text("{not json", encoding="utf-8")
        result = self.store.ingest()
        self.assertTrue(any("broken.json" in r for r in result.rejected))
        self.assertTrue((self.store.inbox / "rejected" / "broken.json").exists())

    def test_it_reports_zero_accepted_rather_than_looking_healthy(self):
        """An executor that writes nothing must be visible, not quiet."""
        self.assertEqual(self.store.ingest().line, "[ingest] nothing to ingest")
        self.assertEqual(self.store.ingest().accepted, ())


if __name__ == "__main__":
    unittest.main()
