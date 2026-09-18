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
        self.assertEqual(record.live_calibration_status, cb.PENDING_RESEARCH)
        # The synthetic row's other fields came from the project's own OPEN_ARENA prior,
        # so the one thing still missing is what the research job must ask for.
        self.assertIn("失败后怎么恢复", record.question)

    def test_a_second_cycle_moves_on_instead_of_asking_the_same_question_twice(self):
        """§七: one hard-to-find manual must not stall the whole loop."""
        first = self.controller.cycle(now=NOW, dispatch=False)
        self.assertEqual(first.selected, "OPEN_ARENA")
        record = self.store.load("OPEN_ARENA")
        report = self.controller.cycle(now=NOW, dispatch=False)
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
            any("MERGED_INTO_PRELOAD_JOB" in reason for _key, reason in observation.skipped),
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


if __name__ == "__main__":
    unittest.main()
