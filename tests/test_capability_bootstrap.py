"""Capability Bootstrap / Preload: prepare the lesson before the wall.

What these tests defend
-----------------------
*Bootstrap is not LIVE_VERIFIED* -- the mechanism has a ceiling, and the ceiling is
a function (``lifecycle_allowed``) rather than a paragraph, so a later contributor
who tries to promote a capability from a brief fails a test instead of shipping.

*Never a duplicate* -- ``WORKING`` / ``DEVELOPMENT_PENDING`` / ``CANDIDATE`` /
``LIVE_VERIFY_PENDING`` / ``LIVE_VERIFIED`` are refused by name.  The operator's
reason is concrete: two agents must not work the same capability, and a preload that
re-briefs something already in the pipeline is manufacturing work.

*It yields to everything ranked above it* -- a real gap the device already hit, an
agent holding the single slot, a development validation owning the device, a V2 in a
REALTIME activity, and a main loop that has not been proven once.  Five named
refusals, because "we were busy" is not checkable but ``GATE_REAL_GAP_WAITING`` is.

*It is not a second pipeline* -- the preload pass goes through the same adapter, the
same ledger and the same throttle, and writes ``origin=bootstrap`` so a reader can
tell "we were blocked here" from "we prepared this in advance".

*Honest fields* -- a field with no source stays ``UNKNOWN``, unknown fields block the
design state, and a near-match draft never makes a brief look designed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import capability_bootstrap as cb  # noqa: E402
from winter_agent_v2 import escalation_queue as q  # noqa: E402

NOW = datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc)


def row(code, *, risk="T1", implementation="MISSING", lifecycle="MISSING",
        existing_skill=None, attempts=0, capability_id="", category="X",
        role="UNKNOWN", money="NONE_ALLOWED"):
    return {
        "capability_id": capability_id or f"CAP-{code[:3]}",
        "code": code,
        "name_cn": code,
        "category": category,
        "description": code,
        "unlock_status": "UNKNOWN",
        "current_role_available": role,
        "implementation_status": implementation,
        "lifecycle": lifecycle,
        "risk": risk,
        "requires_march": False,
        "requires_stamina": False,
        "resource_cost": "UNKNOWN",
        "real_money_cost": money,
        "preferred_backend": "MAA",
        "existing_skill": existing_skill,
        "external_reference": "REFERENCE_ONLY",
        "live_attempts": attempts,
        "live_success": 0,
        "live_failure": 0,
        "success_rate": None,
        "last_live_verified": None,
        "blocked_reason": None,
    }


def prior(*, entry=("HOME",), target=("ARENA",), semantics=(), steps=("TAP",),
          success=("opened",), skill_id="OPEN_ARENA"):
    """The shape ``skill_factory.OperationPrior`` has, without importing it."""
    return SimpleNamespace(
        entry_pages=entry, target_pages=target, required_semantics=semantics,
        execute_steps=steps, success_conditions=success, skill_id=skill_id,
    )


def card(name="Arena", *, v2="CAP-N01", reuse="ADAPT_PATTERN", license_="AGPL-3.0-only"):
    """One ``external_capability_map.json`` row, as the index actually shapes it."""
    return {
        "capability": name, "repo": "wosbot", "v2_equivalent": v2,
        "navigation": "tap the entry then the panel", "recognition": "template",
        "action": "tap", "verification": "none in the source", "recovery": "reschedule",
        "reuse_level": reuse, "license": license_,
        "source_files": ["modules/tasks/src/main/java/ArenaRoutine.java"],
        "current_gap": "V2 has no entry",
    }


def scanner(**overrides):
    """A scanner over synthetic inputs -- the classification is what is under test."""
    base = dict(
        root=".",
        catalog=(row("OPEN_ARENA", capability_id="CAP-N01"),),
        priors={},
        registry_states={},
        registry_ids=(),
        cards=(),
        drafts={},
        verifier_bindings=(),
        registered_semantics=(),
        asset_names=(),
        ledger_index={},
        episodes_attempts={},
        tools={"tools": [{"tool_id": "MAA_FRAMEWORK"}, {"tool_id": "OCR_RAPID"}]},
        now=NOW,
    )
    base.update(overrides)
    return cb.BootstrapScanner(**base)


class TheCeiling(unittest.TestCase):
    def test_a_bootstrap_can_never_promote_a_capability(self):
        self.assertTrue(cb.lifecycle_allowed("CANDIDATE"))
        self.assertTrue(cb.lifecycle_allowed(cb.READY_FOR_LIVE_VERIFY))
        for forbidden in cb.FORBIDDEN_LIFECYCLES:
            self.assertFalse(cb.lifecycle_allowed(forbidden), forbidden)

    def test_the_ceiling_is_read_write_ready_not_verified(self):
        self.assertEqual(cb.BOOTSTRAP_MAX_LIFECYCLE, "READY_FOR_LIVE_VERIFY")

    def test_the_ladders_are_the_operators_and_in_his_order(self):
        self.assertEqual(cb.KNOWLEDGE_LADDER, (
            "V2_EVIDENCE", "LEGACY_ASSET", "EXTERNAL_MAP",
            "OPEN_SOURCE_UNINDEXED", "GAME_DB_WIKI", "SELF_EXPLORATION"))
        self.assertEqual(cb.PRIORITY_LADDER, (
            "REAL_GAP", "UNLOCKED_MISSING", "HIGH_FREQ_FREE_VALUE",
            "OTHER_UNLOCKED", "NEAR_UNLOCK", "FUTURE_LOCKED"))
        self.assertEqual(
            [cb.PRIORITY_TIER[name] for name in cb.PRIORITY_LADDER],
            ["P0", "P1", "P2", "P3", "P4", "P5"],
        )

    def test_the_seven_fields_are_the_operators_seven(self):
        self.assertEqual(cb.FACET_NAMES, (
            "Preconditions", "Navigation", "Recognition", "Action",
            "Verifier", "Recovery", "Risk"))


class Classification(unittest.TestCase):
    def test_a_capability_with_nothing_anywhere_is_missing(self):
        plan = scanner().plans()[0]
        self.assertIn(cb.CLASS_MISSING, plan.classes)
        self.assertEqual(plan.plan_state, cb.NEEDS_LIVE_FRAME)

    def test_implemented_but_never_attempted_is_never_tried(self):
        plan = scanner(catalog=(row("CHECK_MARCH", implementation="EXISTING",
                                    lifecycle="CANDIDATE", existing_skill="CHECK_MARCH",
                                    attempts=0),)).plans()[0]
        self.assertIn(cb.CLASS_NEVER_TRIED, plan.classes)

    def test_a_draft_without_an_implementation_is_defined_but_unimplemented(self):
        plan = scanner(priors={"OPEN_ARENA": prior()}).plans()[0]
        self.assertIn(cb.CLASS_DEFINED_NO_IMPLEMENTATION, plan.classes)

    def test_an_external_prior_is_named_as_such(self):
        plan = scanner(cards=(card(),),
                       catalog=(row("OPEN_ARENA", capability_id="CAP-N01"),)).plans()[0]
        self.assertIn(cb.CLASS_EXTERNAL_PRIOR_UNIMPLEMENTED, plan.classes)
        self.assertEqual(plan.external["reuse_level"], "ADAPT_PATTERN")
        self.assertEqual(plan.external["license"], "AGPL-3.0-only")

    def test_an_unwired_internal_asset_is_named(self):
        plan = scanner(
            asset_names=("arena_route_step_001_before.png", "OPEN_ARENA.json"),
        ).plans()[0]
        self.assertIn(cb.CLASS_LEGACY_ASSET_UNWIRED, plan.classes)

    def test_a_bag_of_tokens_is_not_an_asset(self):
        """Every token must live in ONE name, or "an asset exists" means nothing."""
        plan = scanner(asset_names=("open.png", "arena_notes.md")).plans()[0]
        self.assertNotIn(cb.CLASS_LEGACY_ASSET_UNWIRED, plan.classes)


class NeverADuplicate(unittest.TestCase):
    """The five states the operator listed, each refused with its own sentence."""

    def _in_flight(self, **kw):
        return scanner(**kw).plans()[0]

    def test_a_registered_candidate_is_refused(self):
        plan = self._in_flight(registry_states={"OPEN_ARENA": "CANDIDATE"})
        self.assertEqual(plan.in_flight, "CANDIDATE")
        self.assertFalse(plan.actionable)

    def test_a_live_verified_skill_is_refused(self):
        plan = self._in_flight(registry_states={"OPEN_ARENA": "VERIFIED"})
        self.assertEqual(plan.in_flight, "LIVE_VERIFIED")

    def test_a_working_job_is_refused(self):
        plan = self._in_flight(ledger_index={"OPEN_ARENA": ("DEVELOPMENT_PENDING", "job 1234")})
        self.assertEqual(plan.in_flight, "DEVELOPMENT_PENDING")

    def test_a_version_waiting_for_the_device_is_refused(self):
        plan = self._in_flight(ledger_index={
            "OPEN_ARENA": ("RUNNABLE", "new version waiting for live verification (job=x)")})
        self.assertEqual(plan.in_flight, "LIVE_VERIFY_PENDING")

    def test_a_capability_the_device_already_proved_is_refused(self):
        plan = self._in_flight(ledger_index={"OPEN_ARENA": ("LIVE_VERIFIED", "episode after the job")})
        self.assertEqual(plan.in_flight, "LIVE_VERIFIED")

    def test_a_settled_but_unproven_job_does_not_block_a_fresh_preload(self):
        """DONE/FAILED without a live proof is not one of the five states."""
        plan = self._in_flight(ledger_index={"OPEN_ARENA": ("RUNNABLE", "job settled as TEST_PASS")})
        self.assertEqual(plan.in_flight, "")
        self.assertTrue(plan.actionable)

    def test_the_refusal_is_reported_not_silent(self):
        plan = self._in_flight(registry_states={"OPEN_ARENA": "CANDIDATE"})
        self.assertTrue(plan.in_flight_reason)
        self.assertIn("OPEN_ARENA", plan.in_flight_reason)


class ThePriorityLadder(unittest.TestCase):
    def test_the_tier_gap_outranks_every_bonus(self):
        """A locked, well-known capability must still rank below an unlocked bare one."""
        observed = row("CHECK_MARCH", category="Z", implementation="EXISTING", attempts=2)
        locked = scanner(catalog=(row("OPEN_ARENA", category="L"), observed)).plans()[0]
        unlocked = scanner(
            catalog=(row("OPEN_ARENA", category="Z"), observed),
            asset_names=("OPEN_ARENA_route.json",),
            verifier_bindings=("OPEN_ARENA",),
            drafts={"OPEN_ARENA": {"lifecycle": "CANDIDATE", "preconditions": ["x"]}},
        ).plans()[0]
        self.assertEqual(locked.priority, cb.PRIO_FUTURE_LOCKED)
        self.assertEqual(unlocked.priority, cb.PRIO_UNLOCKED_MISSING)
        self.assertGreater(unlocked.score, locked.score)

    def test_an_observed_family_is_unlocked_evidence_not_a_guess(self):
        observed = scanner(catalog=(
            row("OPEN_ARENA", category="N"),
            row("START_ARENA", category="N", implementation="EXISTING", attempts=4),
        )).plans()[0]
        self.assertEqual(observed.unlocked, "OBSERVED")
        self.assertNotEqual(observed.priority, cb.PRIO_FUTURE_LOCKED)

    def test_free_low_risk_value_sits_above_other_unlocked_work(self):
        observed = row("CHECK_MARCH", category="B", implementation="EXISTING", attempts=2)
        free = scanner(catalog=(
            row("CLAIM_VIP_DAILY", category="B", risk="T0",
                implementation="EXISTING", attempts=3), observed)).plans()[0]
        spend = scanner(catalog=(
            row("PROMOTE_TROOPS", category="B", risk="T2",
                implementation="EXISTING", attempts=3), observed)).plans()[0]
        self.assertEqual(free.priority, cb.PRIO_HIGH_FREQ_FREE_VALUE)
        self.assertEqual(spend.priority, cb.PRIO_OTHER_UNLOCKED)
        self.assertGreater(free.score, spend.score)

    def test_a_missing_capability_outranks_an_implemented_free_one(self):
        """Rung 2 beats rung 3: "the role can use it and V2 cannot do it at all"."""
        observed = row("CHECK_MARCH", category="B", implementation="EXISTING", attempts=2)
        missing = scanner(catalog=(row("CLAIM_VIP_DAILY", category="B", risk="T0"), observed)).plans()[0]
        free = scanner(catalog=(
            row("CLAIM_MAIL", category="B", risk="T0",
                implementation="EXISTING", attempts=3), observed)).plans()[0]
        self.assertEqual(missing.priority, cb.PRIO_UNLOCKED_MISSING)
        self.assertEqual(free.priority, cb.PRIO_HIGH_FREQ_FREE_VALUE)
        self.assertGreater(missing.score, free.score)

    def test_a_row_that_costs_real_money_is_never_free_value(self):
        observed = row("CHECK_MARCH", category="B", implementation="EXISTING", attempts=2)
        plan = scanner(catalog=(row("BUY_BUNDLE", category="B", risk="T1", money="REAL_MONEY",
                                    implementation="EXISTING", attempts=2), observed)).plans()[0]
        self.assertEqual(plan.priority, cb.PRIO_OTHER_UNLOCKED)

    def test_an_unobserved_family_is_future_work_and_says_so(self):
        plan = scanner(catalog=(row("REGISTER_CANYON", category="AA"),)).plans()[0]
        self.assertEqual(plan.unlocked, "UNKNOWN")
        self.assertEqual(plan.priority, cb.PRIO_FUTURE_LOCKED)


class TheKnowledgeLadder(unittest.TestCase):
    def _plan(self, **kw):
        return scanner(**kw).plans()[0]

    def test_a_draft_outranks_an_external_card(self):
        with_draft = self._plan(
            priors={"OPEN_ARENA": prior()},
            drafts={"OPEN_ARENA": {"lifecycle": "CANDIDATE", "preconditions": ["from HOME"]}},
            cards=(card(),),
        )
        with_card = self._plan(cards=(card(),))
        self.assertEqual(with_draft.knowledge_source, cb.SRC_V2_EVIDENCE)
        self.assertEqual(with_card.knowledge_source, cb.SRC_EXTERNAL_MAP)
        self.assertGreater(with_draft.score, with_card.score)

    def test_in_project_game_knowledge_is_rung_five(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "knowledge/game").mkdir(parents=True)
        (tmp / "knowledge/game/open_arena.json").write_text("{}", encoding="utf-8")
        plan = scanner(root=tmp, catalog=(row("OPEN_ARENA"),)).plans()[0]
        self.assertEqual(plan.knowledge_source, cb.SRC_GAME_DB_WIKI)
        self.assertTrue(any("先读项目内知识" in note for note in plan.notes))

    def test_with_no_rung_at_all_the_last_resort_is_a_live_frame(self):
        plan = scanner(root=tempfile.mkdtemp(), catalog=(row("OPEN_ARENA"),)).plans()[0]
        self.assertEqual(plan.knowledge_source, cb.SRC_SELF_EXPLORATION)
        self.assertTrue(any("最后手段" in note for note in plan.notes))

    def test_a_field_with_no_source_is_unknown_and_blocks_the_design(self):
        plan = self._plan()
        self.assertIn("Action", plan.unknown_fields)
        self.assertEqual(plan.plan_state, cb.NEEDS_LIVE_FRAME)
        self.assertEqual(plan.targeted_test["verdict"], "NOT_PROVEN")

    def test_a_near_match_draft_never_makes_a_brief_look_designed(self):
        """``CLAIM_REWARD`` may read ``CLAIM_FREE_REWARD``; that is a hypothesis."""
        plan = self._plan(priors={"CLAIM_FREE_REWARD": prior(skill_id="CLAIM_FREE_REWARD")},
                          catalog=(row("CLAIM_REWARD"),))
        self.assertEqual(plan.plan_state, cb.NEEDS_LIVE_FRAME)
        self.assertTrue(any("相近技能" in note for note in plan.notes))

    def test_a_missing_semantic_is_named_as_the_reason_a_frame_is_needed(self):
        plan = self._plan(
            priors={"SELECT_ARENA_OPPONENT": prior(semantics=("ARENA_OPPONENT_CARD",),
                                                   skill_id="SELECT_ARENA_OPPONENT")},
            drafts={"SELECT_ARENA_OPPONENT": {"lifecycle": "CANDIDATE",
                                              "preconditions": ["from HOME"],
                                              "recovery": ["BACK"]}},
            catalog=(row("SELECT_ARENA_OPPONENT"),),
        )
        self.assertEqual(plan.missing_semantics, ("ARENA_OPPONENT_CARD",))
        self.assertIn("ARENA_OPPONENT_CARD", plan.targeted_test["detail"])

    def test_a_registered_semantic_and_a_bound_verifier_make_it_ready(self):
        """A complete design is still not a live try -- it is READY_FOR_LIVE_VERIFY."""
        plan = self._plan(
            priors={"OPEN_ARENA": prior(semantics=("BTN_OPEN_ARENA",))},
            registered_semantics=("BTN_OPEN_ARENA",),
            verifier_bindings=("OPEN_ARENA",),
            cards=(card(),),
        )
        self.assertEqual(plan.missing_semantics, ())
        self.assertTrue(plan.has_verifier)
        self.assertNotIn("Recovery", plan.unknown_fields)
        self.assertEqual(plan.plan_state, cb.READY_FOR_LIVE_VERIFY)

    def test_a_complete_design_that_is_already_a_candidate_is_refused(self):
        """The converse, and the reason the refusal exists: a finished design *is*
        the candidate the pipeline already owns, so re-briefing it is duplicate work."""
        plan = self._plan(
            priors={"OPEN_ARENA": prior(semantics=("BTN_OPEN_ARENA",))},
            drafts={"OPEN_ARENA": {"lifecycle": "CANDIDATE", "preconditions": ["from HOME"],
                                   "recovery": ["BACK"]}},
            registered_semantics=("BTN_OPEN_ARENA",),
            verifier_bindings=("OPEN_ARENA",),
        )
        self.assertEqual(plan.in_flight, "CANDIDATE")
        self.assertFalse(plan.actionable)

    def test_an_external_prior_is_never_copied_only_adapted(self):
        plan = self._plan(cards=(card(reuse="LICENSE_BLOCKED"),))
        self.assertEqual(plan.external.get("reuse_level"), "LICENSE_BLOCKED")
        self.assertTrue(any("不复制" in note for note in plan.notes))

    def test_the_verifier_field_quotes_the_binding_when_one_exists(self):
        plan = self._plan(verifier_bindings=("OPEN_ARENA",))
        verifier = next(f for f in plan.facets if f.name == "Verifier")
        self.assertIn("VERIFIED_ATOMIC[OPEN_ARENA]", verifier.value)


class TheGate(unittest.TestCase):
    """The four things the operator forbade disturbing, as five named refusals."""

    def _gate(self, **kw):
        base = dict(armed=True, arm_reason="MAIN_LOOP_P0_PASS", arm_detail="",
                    active_jobs=0, pending_records=0, lease_holder="", runtime={}, actionable=1)
        base.update(kw)
        return cb.preload_gate(**base)

    def test_a_disarmed_mechanism_says_why_and_names_no_other_reason(self):
        gate = self._gate(armed=False, arm_reason=cb.GATE_NOT_ARMED, arm_detail="P0-D not proven")
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, cb.GATE_NOT_ARMED)

    def test_a_real_gap_owed_to_the_queue_comes_first(self):
        gate = self._gate(pending_records=2, active_jobs=1, lease_holder="DEVELOPMENT_VALIDATION",
                          runtime={"current_goal": "PARTICIPATE_BEAR"})
        self.assertEqual(gate.reason, cb.GATE_REAL_GAP_WAITING)

    def test_the_single_agent_slot_is_not_stolen(self):
        gate = self._gate(active_jobs=1)
        self.assertEqual(gate.reason, cb.GATE_AGENT_SLOT_BUSY)

    def test_the_device_is_not_disturbed(self):
        gate = self._gate(lease_holder="DEVELOPMENT_VALIDATION")
        self.assertEqual(gate.reason, cb.GATE_DEVICE_LEASED)

    def test_a_realtime_activity_is_not_loaded(self):
        gate = self._gate(runtime={"current_goal": "PARTICIPATE_BEAR"})
        self.assertEqual(gate.reason, cb.GATE_REALTIME_ACTIVITY)
        gate = self._gate(runtime={"current_skill": "JOIN_RALLY"})
        self.assertEqual(gate.reason, cb.GATE_REALTIME_ACTIVITY)

    def test_nothing_to_do_is_a_state_not_an_error(self):
        gate = self._gate(actionable=0)
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, cb.GATE_NOTHING_TO_DO)

    def test_an_idle_system_lets_it_run(self):
        gate = self._gate(runtime={"current_goal": "KEEP_MARCHES_PRODUCTIVE"})
        self.assertTrue(gate.allowed)
        self.assertEqual(gate.reason, cb.GATE_OK)


class Arming(unittest.TestCase):
    def _root(self, payload=None, override=None):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "config").mkdir()
        (tmp / "dataset/truth_audit/p0_loop_20260918").mkdir(parents=True)
        if payload is not None:
            (tmp / cb.DEFAULT_P0_PATH).write_text(json.dumps(payload), encoding="utf-8")
        if override is not None:
            (tmp / cb.DEFAULT_ARM_PATH).write_text(json.dumps(override), encoding="utf-8")
        return tmp

    def test_a_missing_artifact_is_honestly_not_complete(self):
        armed, reason, detail = cb.arm_state(self._root())
        self.assertFalse(armed)
        self.assertEqual(reason, cb.GATE_NOT_ARMED)
        self.assertIn("no main-loop status artifact", detail)

    def test_a_partial_ladder_does_not_arm_it(self):
        payload = {"stages": {"P0-A gate -> job": {"verdict": "PARTIAL"},
                              "P0-D live": {"verdict": "NOT PROVEN"}}}
        armed, reason, detail = cb.arm_state(self._root(payload))
        self.assertFalse(armed)
        self.assertIn("P0-A=PARTIAL", detail)
        self.assertIn("P0-D=NOT PROVEN", detail)

    def test_every_stage_at_pass_arms_it_automatically(self):
        payload = {"stages": {"P0-A": {"verdict": "PASS"}, "P0-F": {"verdict": "PASS"}}}
        armed, reason, _ = cb.arm_state(self._root(payload))
        self.assertTrue(armed)
        self.assertEqual(reason, "MAIN_LOOP_P0_PASS")

    def test_an_operator_override_is_explicit_and_never_silent(self):
        root = self._root({"stages": {"P0-A": {"verdict": "PARTIAL"}}},
                          {"armed": True, "armed_by": "operator", "reason": "watch it once"})
        armed, reason, detail = cb.arm_state(root)
        self.assertTrue(armed)
        self.assertEqual(reason, "OPERATOR_OVERRIDE")
        self.assertIn("operator", detail)


class PreloadIsOneProducerForTheOneQueue(unittest.TestCase):
    """The end-to-end behaviour: same adapter, same ledger, one record, one origin."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "knowledge/game").mkdir(parents=True)
        (self.tmp / "knowledge/external").mkdir(parents=True)
        (self.tmp / "knowledge/tooling").mkdir(parents=True)
        (self.tmp / "knowledge/goals").mkdir(parents=True)
        (self.tmp / "dataset/candidate").mkdir(parents=True)
        (self.tmp / "learning").mkdir(parents=True)
        (self.tmp / "config").mkdir(parents=True)
        (self.tmp / cb.DEFAULT_ARM_PATH).write_text(
            json.dumps({"armed": True, "armed_by": "test", "reason": "unit test"}), encoding="utf-8")
        (self.tmp / "knowledge/game/capability_catalog.json").write_text(json.dumps({
            "schema_version": "1.0",
            "capabilities": [
                row("OPEN_ARENA", capability_id="CAP-N01", category="N", risk="T1"),
                row("CLAIM_VIP_DAILY", capability_id="CAP-B09", category="N", risk="T0"),
            ],
        }), encoding="utf-8")
        self.ledger_path = self.tmp / q.DEFAULT_LEDGER
        self.bridge = FakeBridge()

    def _adapter(self):
        return q.EscalationQueueAdapter(
            root=self.tmp,
            ledger=q.EscalationLedger(self.ledger_path),
            bridge=self.bridge,
        )

    def _events(self):
        return q.EscalationLedger(self.ledger_path).events()

    def test_one_pass_dispatches_one_prepared_capability(self):
        observation = self._adapter().preload(now=NOW)
        self.assertEqual(len(self.bridge.submits), 1)
        self.assertEqual(len(observation.preloaded), 1)
        created = [e for e in self._events() if e.get("event") == "escalation_created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["origin"], "bootstrap")
        self.assertEqual(created[0]["condition"], q.CAPABILITY_MISSING)

    def test_the_brief_reaches_the_bridge_as_evidence_and_as_text(self):
        self._adapter().preload(now=NOW)
        submit = self.bridge.submits[0]
        notes = json.dumps(submit, ensure_ascii=False)
        self.assertIn("PRELOAD BRIEF", notes)
        self.assertIn("CEILING", notes)
        self.assertIn("Do not claim LIVE_TRIED / LIVE_VERIFIED / STABLE", notes)
        brief = Path(self.tmp) / "learning/capability_bootstrap/briefs/OPEN_ARENA.json"
        self.assertTrue(brief.is_file())
        payload = json.loads(brief.read_text(encoding="utf-8"))
        self.assertEqual(payload["max_lifecycle"], cb.BOOTSTRAP_MAX_LIFECYCLE)
        self.assertEqual(payload["must_not_claim"], list(cb.FORBIDDEN_LIFECYCLES))
        self.assertIn("LIVE_VERIFY_PENDING", payload["next_flow"])

    def test_the_origin_is_folded_so_a_reader_can_tell_where_it_came_from(self):
        self._adapter().preload(now=NOW)
        snapshot = q.fold(self._events())
        record = list(snapshot.records.values())[0]
        self.assertEqual(record.origin, "bootstrap")

    def test_a_second_pass_does_not_brief_the_same_capability_again(self):
        adapter = self._adapter()
        adapter.preload(now=NOW)
        self.assertEqual(len(self.bridge.submits), 1)
        # The job is now in flight, so the gate yields and nothing else is offered.
        second = adapter.preload(now=NOW)
        self.assertEqual(len(self.bridge.submits), 1)
        self.assertEqual(second.preloaded, ())
        self.assertTrue(second.preload_note)

    def test_a_running_job_stops_a_preload_before_it_reaches_the_bridge(self):
        ledger = q.EscalationLedger(self.ledger_path)
        ledger.append({"source": "queue", "event": "escalation_created", "key": "OTHER|UNKNOWN_UI|X",
                       "capability": "OTHER", "failure_type": "UNKNOWN_UI", "skill": "X",
                       "condition": "UNKNOWN_UI", "recorded_at": NOW.isoformat()})
        ledger.append({"source": "queue", "event": "submitted", "key": "OTHER|UNKNOWN_UI|X",
                       "job_id": "live-1", "recorded_at": NOW.isoformat()})
        observation = self._adapter().preload(now=NOW)
        self.assertEqual(self.bridge.submits, [])
        self.assertIn(cb.GATE_AGENT_SLOT_BUSY, observation.preload_note)

    def test_a_disarmed_mechanism_reaches_no_bridge_at_all(self):
        (self.tmp / cb.DEFAULT_ARM_PATH).write_text(json.dumps({"armed": False}), encoding="utf-8")
        (self.tmp / cb.DEFAULT_P0_PATH).unlink(missing_ok=True)
        (self.tmp / "dataset/truth_audit/p0_loop_20260918").mkdir(parents=True)
        observation = self._adapter().preload(now=NOW)
        self.assertEqual(self.bridge.submits, [])
        self.assertIn(cb.GATE_NOT_ARMED, observation.preload_note)

    def test_a_preload_pass_never_raises(self):
        """A background pass that raises would take the panel's tick with it."""
        broken = q.EscalationQueueAdapter(
            root=self.tmp, ledger=q.EscalationLedger(self.ledger_path), bridge=ExplodingBridge())
        observation = broken.preload(now=NOW)
        self.assertIsInstance(observation, q.RunObservation)

    def test_the_observation_line_says_what_it_preloaded(self):
        observation = self._adapter().preload(now=NOW)
        self.assertIn("preloaded 1", observation.line)


class TheReport(unittest.TestCase):
    def test_the_report_states_its_own_ceiling(self):
        payload = scanner().report()
        self.assertEqual(payload["policy"]["max_lifecycle"], cb.BOOTSTRAP_MAX_LIFECYCLE)
        self.assertEqual(payload["policy"]["never_from_a_bootstrap"], list(cb.FORBIDDEN_LIFECYCLES))
        self.assertEqual(payload["policy"]["fields"], list(cb.FACET_NAMES))

    def test_writing_the_report_is_a_report_not_a_registry(self):
        tmp = Path(tempfile.mkdtemp())
        json_path, md_path = cb.write_report(tmp, scanner(), limit=5)
        self.assertTrue(json_path.is_file() and md_path.is_file())
        self.assertIn("Bootstrap 完成 ≠ LIVE_VERIFIED", md_path.read_text(encoding="utf-8"))

    def test_a_refused_row_is_still_in_the_report(self):
        payload = scanner(registry_states={"OPEN_ARENA": "CANDIDATE"}).report()
        self.assertEqual(payload["summary"]["in_flight"], 1)
        self.assertEqual(payload["summary"]["actionable"], 0)


class FakeBridge:
    def __init__(self, *, available=True, reason="OK", submitted="job-preload-1"):
        self._available, self._reason, self._submitted = available, reason, submitted
        self.submits: list[dict] = []

    def is_available(self):
        return SimpleNamespace(available=self._available, reason=self._reason)

    def submit(self, context, *, name, model):
        self.submits.append(json.loads(json.dumps({
            "name": name, "model": model, "prompt": getattr(context, "prompt", str(context)),
        })))
        return SimpleNamespace(job_id=self._submitted)

    def cancel(self, job_id):
        return True


class ExplodingBridge(FakeBridge):
    def is_available(self):
        raise RuntimeError("gateway exploded")


class ThePanelClock(unittest.TestCase):
    """The window owns the only long-lived process, so the preload lives there.

    On its *own* slower cadence, sharing the adapter with the consumer: an order of
    magnitude rarer, because the operator's rule is that a preload is background work
    that must not disturb anything else the same thread is already doing.
    """

    def setUp(self):
        from tools import control_panel

        self.module = control_panel
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "learning").mkdir(parents=True)
        # A catalog row so the pass reaches the gate rather than stopping at "nothing to
        # scan": the arm refusal is what this fixture is about.
        (self.tmp / "knowledge/game").mkdir(parents=True)
        (self.tmp / "knowledge/game/capability_catalog.json").write_text(json.dumps({
            "schema_version": "1.0",
            "capabilities": [{
                "capability_id": "CAP-Z01", "code": "OPEN_ARENA", "name_cn": "竞技场",
                "category": "N", "description": "OPEN_ARENA", "unlock_status": "UNKNOWN",
                "current_role_available": "UNKNOWN", "implementation_status": "MISSING",
                "lifecycle": "MISSING", "risk": "T1", "requires_march": False,
                "requires_stamina": False, "resource_cost": "UNKNOWN",
                "real_money_cost": "NONE_ALLOWED", "preferred_backend": "MAA",
                "existing_skill": None, "external_reference": "REFERENCE_ONLY",
                "live_attempts": 0, "live_success": 0, "live_failure": 0,
                "success_rate": None, "last_live_verified": None, "blocked_reason": None,
            }],
        }), encoding="utf-8")
        self.ledger = self.tmp / "learning/workbuddy_escalations.jsonl"
        self.state_file = self.tmp / "learning/pump.json"

    def _pump(self, **kw):
        patches = [
            mock.patch.object(self.module, "_ESCALATION_LEDGER_PATH", self.ledger),
            mock.patch.object(self.module, "PUMP_STATE_PATH", self.state_file),
            mock.patch.object(self.module, "ROOT", self.tmp),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return self.module.QueuePump(**kw)

    def test_it_runs_on_its_own_slower_cadence(self):
        pump = self._pump(preload_every=2)
        pump.tick()
        self.assertEqual(pump.state()["preload_ticks"], 1)
        self.assertEqual(pump.state()["preloads"], 0)
        pump.tick()
        state = pump.state()
        self.assertEqual(state["preload_ticks"], 2)
        self.assertEqual(state["passes"], 2)
        self.assertTrue(state["preload_last"])

    def test_a_refusal_is_recorded_rather_than_being_an_absence(self):
        """The mechanism is not armed here, and the file has to say so."""
        pump = self._pump(preload_every=1)
        state = pump.tick()
        self.assertIn(cb.GATE_NOT_ARMED, state["preload_note"])
        self.assertEqual(state["preloads"], 0)

    def test_a_stopped_window_does_not_preload(self):
        pump = self._pump(enabled=lambda: False, preload_every=1)
        state = pump.tick()
        self.assertEqual(state["preload_ticks"], 0)
        self.assertEqual(state["preload_note"], "")

    def test_the_note_reaches_a_reader_outside_the_gui(self):
        pump = self._pump(preload_every=1)
        pump.tick()
        payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertIn("preload_note", payload)
        self.assertIn("preload_every", payload)

    def test_switching_it_off_is_a_parameter_not_an_edit(self):
        pump = self._pump(preload_every=0)
        for _ in range(3):
            pump.tick()
        self.assertEqual(pump.state()["preload_ticks"], 3)
        self.assertEqual(pump.state()["preload_last"], "")


if __name__ == "__main__":
    unittest.main()
