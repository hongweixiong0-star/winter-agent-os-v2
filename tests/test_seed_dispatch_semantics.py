"""What the acceptance seed's dispatch must get right, and what it must not silently do.

Two real defects are pinned here.  Both were invisible from the outside, which is why they survived
a green suite:

1. **The seed's origin never reached the ledger.**  ``preload()`` hard-coded ``origin="bootstrap"``
   at both dispatch sites, so a seed was recorded as an ordinary preload.  That is not cosmetic:
   ``acceptance_seed_allowed`` enforces "one seed at a time" by counting records whose origin is
   ``bootstrap_seed``, so the rule could never fire -- the guard read a field nothing ever wrote.
   Measured before the fix: the origin existed as a concept in three files and as a value in none.

2. **The candidate policy did not exist.**  ``BootstrapPlan.actionable`` was ``not in_flight`` and
   ``select()`` had no seed-specific filter, so the first seed was free to be any actionable row.
   It chose ``TROOP_SELECT`` (CAP-G09), whose ``unlocked`` reads OBSERVED only because
   ``_sibling_observed("G")`` found ``RECALL_MARCH`` in the same family.  Nothing had observed
   TROOP_SELECT itself.  A family is not a capability, and the one-shot ticket must not be spent on
   a guess -- so availability evidence is now a per-capability fact with a named ladder.

The third thing pinned here is the *closing* of the ticket: a seed that ended without a reuse must
not quietly become a second seed.  An exception that retries itself is a rule.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import capability_bootstrap as cb  # noqa: E402
from winter_agent_v2 import escalation_queue as q  # noqa: E402

NOW = datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc)


def row(code, *, risk="T1", implementation="MISSING", lifecycle="MISSING",
        existing_skill=None, attempts=0, capability_id="", category="N",
        role="UNKNOWN", money="NONE_ALLOWED", march=False, stamina=False):
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
        "requires_march": march,
        "requires_stamina": stamina,
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


class Availability:
    """Mirrors ``workbuddy_bridge.Availability``: falsy when unavailable, but still carries
    ``reason``.  Both halves matter -- the adapter branches on truthiness *and* then quotes
    ``availability.reason`` into the queued row, so a stub that returns a bare ``None`` makes the
    queue path raise instead of recording why it queued.
    """

    def __init__(self, available: bool, reason: str):
        self.available, self.reason = available, reason

    def __bool__(self) -> bool:
        return self.available


class FakeBridge:
    def __init__(self, *, available=True, reason="OK", submitted="job-seed-1"):
        self._available, self._reason, self._submitted = available, reason, submitted
        self.submits: list[dict] = []

    def is_available(self):
        return Availability(self._available, self._reason)

    def submit(self, context, *, name, model):
        self.submits.append({"name": name, "model": model,
                             "prompt": getattr(context, "prompt", str(context))})
        return SimpleNamespace(job_id=self._submitted)

    def cancel(self, job_id):
        return True


def seedable(root: Path, catalog: list[dict], *, bridge_available=True) -> Path:
    """A root in which every seed condition *other than the candidate* already holds.

    Reproduces the production situation the seed exists for: nothing open, operator running, a live
    panel, a healthy gateway.  Anything missing here would make the seed refuse for the wrong
    reason, and a test that refuses for the wrong reason proves nothing.
    """
    for folder in ("knowledge/game", "knowledge/goals", "knowledge/external", "knowledge/tooling",
                   "dataset/candidate", "learning/control_panel",
                   "learning/knowledge_bootstrap", "config"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "knowledge/game/capability_catalog.json").write_text(
        json.dumps({"schema_version": "1.0", "capabilities": catalog}), encoding="utf-8")
    (root / q.DEFAULT_LEDGER).write_text("", encoding="utf-8")
    (root / "config/control_panel_state.json").write_text(
        json.dumps({"operator_intent": "RUNNING"}), encoding="utf-8")
    (root / "learning/control_panel/pump.json").write_text("{}", encoding="utf-8")
    (root / "learning/control_panel/gateway.json").write_text(
        json.dumps({"available": bridge_available, "reason": "OK"}), encoding="utf-8")
    return root


def make_asset(root: Path, name: str) -> None:
    """A measured artefact whose file name carries every token of a capability code."""
    (root / "dataset/truth_audit").mkdir(parents=True, exist_ok=True)
    (root / "dataset/truth_audit" / name).write_text("{}", encoding="utf-8")


class SeedOriginReachesTheLedger(unittest.TestCase):
    """Defect 1: the seed's origin has to exist as a *value in the ledger*, not as an idea."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        seedable(self.tmp, [
            row("OPEN_ARENA", capability_id="CAP-N01", role="OBSERVED_AVAILABLE"),
        ])
        self.ledger_path = self.tmp / q.DEFAULT_LEDGER
        self.bridge = FakeBridge()

    def _adapter(self, bridge=None):
        return q.EscalationQueueAdapter(
            root=self.tmp, ledger=q.EscalationLedger(self.ledger_path),
            bridge=bridge or self.bridge,
        )

    def _events(self):
        return q.EscalationLedger(self.ledger_path).events()

    def test_the_seed_gate_really_is_the_seed(self):
        """The premise of every test below: without it they would grade a plain preload."""
        armed, reason, _ = cb.arm_state(self.tmp)
        self.assertTrue(armed)
        self.assertEqual(reason, cb.SEED_ARMED)

    def test_the_first_seed_writes_its_own_origin(self):
        observation = self._adapter().preload(now=NOW)
        self.assertEqual(observation.preloaded, ("OPEN_ARENA",))
        created = [e for e in self._events() if e.get("event") == "escalation_created"]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["origin"], "bootstrap_seed")
        # Folded too, because the "one seed at a time" guard reads the folded record.
        record = q.fold(self._events()).get("OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA")
        self.assertIsNotNone(record)
        self.assertEqual(record.origin, "bootstrap_seed")

    def test_the_origin_is_written_when_nothing_was_submitted_either(self):
        """The recorded-but-not-submitted path is a second dispatch site, and it was hard-coded too."""
        adapter = self._adapter(FakeBridge(available=False, reason="GATEWAY_DOWN"))
        observation = adapter.preload(now=NOW)
        self.assertEqual(observation.preloaded, ())
        created = [e for e in self._events() if e.get("event") == "escalation_created"]
        self.assertEqual(created[0]["origin"], "bootstrap_seed")
        self.assertTrue(any(e.get("event") == "queued" for e in self._events()))

    def test_targeted_research_writes_the_same_origin(self):
        """Both knowledge branches must agree, or the mode would depend on the branch it took."""
        self._adapter().preload(now=NOW, mode="TARGETED_RESEARCH", questions=("where is it",))
        created = [e for e in self._events() if e.get("event") == "escalation_created"]
        self.assertEqual(created[0]["origin"], "bootstrap_seed")
        self.assertIn("TARGETED_RESEARCH", created[0]["reason"])

    def test_an_ordinary_preload_still_records_the_ordinary_origin(self):
        """The fix must not rename every preload: "seeded" and "prepared in advance" differ.

        The seed is deliberately checked *before* an operator override, so an ordinary preload is
        produced by breaking a seed condition (here: the operator is not RUNNING) and letting the
        override arm the mechanism -- which is the only way an operator-armed pass can occur.
        """
        other = Path(tempfile.mkdtemp())
        seedable(other, [row("OPEN_ARENA", capability_id="CAP-N01",
                             role="OBSERVED_AVAILABLE")])
        (other / "config/control_panel_state.json").write_text(
            json.dumps({"operator_intent": "STOPPED"}), encoding="utf-8")
        (other / cb.DEFAULT_ARM_PATH).write_text(
            json.dumps({"armed": True, "armed_by": "operator", "reason": "watch it once"}),
            encoding="utf-8")
        ledger_path = other / q.DEFAULT_LEDGER
        q.EscalationQueueAdapter(
            root=other, ledger=q.EscalationLedger(ledger_path), bridge=FakeBridge()
        ).preload(now=NOW)
        created = [e for e in q.EscalationLedger(ledger_path).events()
                   if e.get("event") == "escalation_created"]
        self.assertEqual(created[0]["origin"], "bootstrap")

    def test_the_reason_a_seed_was_spent_is_recorded_next_to_the_seed(self):
        """The ledger is the only place a later reader can check *why* the ticket went here."""
        self._adapter().preload(now=NOW)
        created = [e for e in self._events() if e.get("event") == "escalation_created"][0]
        self.assertIn("P0_ACCEPTANCE_SEED", created["reason"])
        self.assertIn(cb.AVAIL_CATALOG_OBSERVED, created["reason"])


class PreloadWithoutAPlanStillObeysThePolicy(unittest.TestCase):
    """Defect 2's second half: the no-plan path must not become a third selection authority."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Only sibling-only rows: category N is observed (CAP-N00 is EXISTING), but neither
        # candidate has ever been observed itself.  This is TROOP_SELECT's shape exactly.
        seedable(self.tmp, [
            row("SIBLING_ANCHOR", capability_id="CAP-N00", implementation="EXISTING",
                existing_skill="SIBLING_ANCHOR"),
            row("SIBLING_ONLY", capability_id="CAP-N01", role="UNKNOWN"),
        ])
        self.ledger_path = self.tmp / q.DEFAULT_LEDGER
        self.bridge = FakeBridge()

    def _adapter(self):
        return q.EscalationQueueAdapter(
            root=self.tmp, ledger=q.EscalationLedger(self.ledger_path), bridge=self.bridge)

    def test_the_scanner_really_does_report_it_as_observed(self):
        """The trap being tested: ``unlocked`` says OBSERVED on family evidence alone."""
        plan = [p for p in cb.BootstrapScanner.load(self.tmp).plans()
                if p.code == "SIBLING_ONLY"][0]
        self.assertEqual(plan.unlocked, "OBSERVED")
        self.assertEqual(plan.availability, "")

    def test_a_preload_with_no_plan_refuses_to_spend_the_seed_on_it(self):
        observation = self._adapter().preload(now=NOW)
        self.assertEqual(self.bridge.submits, [], "nothing may be dispatched on a guess")
        self.assertEqual(observation.preloaded, ())
        self.assertIn(cb.DECISION_SEED_NO_ELIGIBLE, observation.preload_note)
        self.assertIn(cb.SEED_NOT_CURRENTLY_OBSERVED, observation.preload_note)

    def test_the_same_catalog_dispatches_the_row_once_it_has_its_own_evidence(self):
        """One variable changed: it now has an artefact of its own."""
        make_asset(self.tmp, "SIBLING_ONLY__live_page.png")
        observation = self._adapter().preload(now=NOW)
        self.assertEqual(observation.preloaded, ("SIBLING_ONLY",))


class SeedEligibilityIsAPerCapabilityFact(unittest.TestCase):
    """Every rung of the policy, and the ones that must stay preferences rather than gates."""

    def _plan(self, catalog, code, *, assets=(), category="N"):
        """A plan for ``code``, in a catalog where its family has been shown at least once.

        The anchor is not decoration: without a row in the same category that is EXISTING or has
        been attempted, ``unlocked`` is UNKNOWN and *every* candidate would be refused by the family
        gate -- so the tests below would pass for the wrong reason and prove nothing about the rule
        they name.
        """
        root = Path(tempfile.mkdtemp())
        anchor = row(f"{category}_ANCHOR", capability_id=f"CAP-{category}00",
                     implementation="EXISTING", existing_skill=f"{category}_ANCHOR",
                     category=category)
        seedable(root, [anchor] + list(catalog))
        for name in assets:
            make_asset(root, name)
        return [p for p in cb.BootstrapScanner.load(root).plans() if p.code == code][0]

    def test_a_sibling_only_capability_is_not_a_seed(self):
        plan = self._plan([
            row("TROOP_SELECT", capability_id="CAP-G09", category="G", role="UNKNOWN"),
        ], "TROOP_SELECT", category="G")
        ok, why, detail = cb.seed_eligible(plan)
        self.assertFalse(ok)
        self.assertEqual(why, cb.SEED_NOT_CURRENTLY_OBSERVED)
        self.assertIn("TROOP_SELECT", detail)
        self.assertEqual(plan.unlocked, "OBSERVED", "the family really is observed")

    def test_its_own_artefact_is_enough(self):
        plan = self._plan([row("OPEN_ARENA", capability_id="CAP-N01")], "OPEN_ARENA",
                          assets=["OPEN_ARENA.json"])
        ok, why, _ = cb.seed_eligible(plan)
        self.assertTrue(ok, why)
        self.assertEqual(plan.availability, cb.AVAIL_PAGE_ASSET)

    def test_a_direct_catalog_observation_outranks_everything_else(self):
        direct = self._plan([row("OPEN_ARENA", capability_id="CAP-N01",
                                 role="OBSERVED_AVAILABLE")], "OPEN_ARENA",
                            assets=["OPEN_ARENA.json"])
        self.assertEqual(direct.availability, cb.AVAIL_CATALOG_OBSERVED)
        self.assertLess(cb.seed_order_key(direct), cb.seed_order_key(
            self._plan([row("OPEN_ARENA", capability_id="CAP-N01")], "OPEN_ARENA",
                       assets=["OPEN_ARENA.json"])))

    def test_risk_real_money_and_forbidden_actions_are_gated(self):
        high_risk = self._plan([row("OPEN_ARENA", capability_id="CAP-N01", risk="T3",
                                    role="OBSERVED_AVAILABLE")], "OPEN_ARENA")
        self.assertEqual(cb.seed_eligible(high_risk)[:2], (False, cb.SEED_RISK_TOO_HIGH))

        money = self._plan([row("OPEN_ARENA", capability_id="CAP-N01", money="FORBIDDEN",
                                role="OBSERVED_AVAILABLE")], "OPEN_ARENA")
        self.assertEqual(cb.seed_eligible(money)[:2], (False, cb.SEED_REAL_MONEY))

        for code in ("ATTACK_CITY", "ACCOUNT_DELETE", "STATE_TRANSFER", "BUY_ITEM"):
            forbidden = self._plan([row(code, capability_id="CAP-BC01",
                                        role="OBSERVED_AVAILABLE")], code)
            self.assertEqual(cb.seed_eligible(forbidden)[:2],
                             (False, cb.SEED_FORBIDDEN_ACTION), code)

        # PvE must not be caught by the same token rule as PvP.
        pve = self._plan([row("ATTACK_BEAST", capability_id="CAP-I03",
                              role="OBSERVED_AVAILABLE")], "ATTACK_BEAST")
        self.assertTrue(cb.seed_eligible(pve)[0], cb.seed_eligible(pve))

    def test_the_operators_preferences_order_candidates_without_gating_them(self):
        """``requires_march`` is phrased "优先", so it must never be the reason a seed is refused."""
        plain = self._plan([row("OPEN_ARENA", capability_id="CAP-N01",
                                role="OBSERVED_AVAILABLE")], "OPEN_ARENA")
        marching = self._plan([row("OPEN_ARENA", capability_id="CAP-N01",
                                   role="OBSERVED_AVAILABLE", march=True)], "OPEN_ARENA")
        self.assertTrue(cb.seed_eligible(marching)[0], "a march is a preference, not a gate")
        self.assertLess(cb.seed_order_key(plain), cb.seed_order_key(marching))

    def test_a_family_that_has_never_been_shown_is_refused_even_with_an_artefact(self):
        # Category AR with no anchor of its own: the artefact is real, the family is not.
        root = Path(tempfile.mkdtemp())
        seedable(root, [row("CLAIM_REWARD", capability_id="CAP-AR06", category="AR")])
        make_asset(root, "CLAIM_REWARD.json")
        plan = [p for p in cb.BootstrapScanner.load(root).plans()
                if p.code == "CLAIM_REWARD"][0]
        self.assertEqual(plan.availability, cb.AVAIL_PAGE_ASSET)
        self.assertEqual(cb.seed_eligible(plan)[:2], (False, cb.SEED_FAMILY_NEVER_SHOWN))


class SeedModeChangesTheSelectionAndNothingElse(unittest.TestCase):
    """One selector, two modes: the seed's policy may not leak into ordinary bootstrap."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        seedable(self.tmp, [
            row("SIBLING_ANCHOR", capability_id="CAP-G00", implementation="EXISTING",
                existing_skill="SIBLING_ANCHOR", category="G"),
            row("TROOP_SELECT", capability_id="CAP-G09", category="G", role="UNKNOWN"),
        ])
        self.controller = cb.KnowledgeBootstrapController(self.tmp)
        self.scanner = self.controller.scan(now=NOW)

    def test_without_the_seed_the_ranking_is_untouched(self):
        plan, _ = self.controller.select(self.scanner)
        self.assertEqual(plan.code, "TROOP_SELECT",
                         "the ordinary bootstrap path keeps its own ranking")

    def test_under_the_seed_it_is_skipped_and_not_blocked(self):
        plan, skipped = self.controller.select(self.scanner, arm_reason=cb.SEED_ARMED)
        self.assertIsNone(plan)
        self.assertTrue(
            any("TROOP_SELECT" in reason and cb.SEED_NOT_CURRENTLY_OBSERVED in reason
                for reason in skipped),
            skipped,
        )

    def test_a_seed_that_cannot_close_is_reported_as_such_not_as_nothing_to_do(self):
        """``NOTHING_TO_DO`` and "the free ticket was refused by policy" are different facts."""
        report = self.controller.cycle(now=NOW, dispatch=False)
        self.assertEqual(report.decision, cb.DECISION_SEED_NO_ELIGIBLE)

    def test_the_real_catalog_is_never_seeded_on_family_evidence_alone(self):
        """Against the live 522-row catalog, as a rule rather than a fixed answer.

        Asserting "the seed is X" would break every time the catalog is rebuilt.  The invariant
        that must hold whatever the data says: whichever capability is chosen in seed mode carries
        evidence of its *own*, and anything the policy refused is reported with its reason.
        """
        controller = cb.KnowledgeBootstrapController(ROOT)
        scanner = controller.scan(now=NOW)
        plan, skipped = controller.select(scanner, arm_reason=cb.SEED_ARMED)
        troop = [p for p in scanner.plans() if p.code == "TROOP_SELECT"]
        if troop:
            ok, why, _ = cb.seed_eligible(troop[0])
            if not ok:
                self.assertNotEqual(
                    getattr(plan, "code", None), "TROOP_SELECT",
                    "a capability that failed seed_eligible must not be dispatched as the seed",
                )
                self.assertEqual(why, cb.SEED_NOT_CURRENTLY_OBSERVED)
        if plan is not None:
            self.assertTrue(plan.availability, "a seed must carry its own availability evidence")
            self.assertIn(plan.risk, cb.SEED_RISKS)
            self.assertEqual(plan.real_money_cost, "NONE_ALLOWED")
        else:
            self.assertTrue(skipped, "refusing every row must name at least one reason")


class TheSeedTicketIsSpentOnce(unittest.TestCase):
    """The closing rules, including the case where the first seed simply failed to prove anything."""

    def setUp(self):
        self.root = seedable(Path(tempfile.mkdtemp()), [])
        self.ledger_path = self.root / q.DEFAULT_LEDGER

    def _seed_record(self, state: str) -> None:
        """A seed whose folded state is ``state``, written with the ledger's own vocabulary."""
        ledger = q.EscalationLedger(self.ledger_path)
        ledger.append({
            "source": "queue", "event": "escalation_created", "origin": "bootstrap_seed",
            "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA", "capability": "OPEN_ARENA",
            "failure_type": "CAPABILITY_MISSING", "skill": "OPEN_ARENA",
            "condition": "CAPABILITY_MISSING", "recorded_at": NOW.isoformat(),
        })
        if state != "NEW":
            # A *reconciled* event carrying ``job_state`` is the only path fold() takes a terminal
            # state from; a standalone ``job_state`` row is not folded into ``record.state``.
            ledger.append({
                "source": "queue", "event": "reconciled", "key":
                    "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA", "job_state": state,
                "outcome": state, "recorded_at": NOW.isoformat(),
            })

    def test_an_open_seed_refuses_a_second_and_says_which_record_is_in_the_way(self):
        self._seed_record("NEW")
        ok, why = cb.acceptance_seed_allowed(self.root)
        self.assertFalse(ok)
        self.assertIn("bootstrap_seed", why)
        self.assertIn("同时只允许一个", why)

    def test_a_terminal_seed_that_proved_nothing_is_not_silently_replaced(self):
        self._seed_record("DONE")
        ok, why = cb.acceptance_seed_allowed(self.root)
        self.assertFalse(ok)
        self.assertIn("不得静默补发", why)
        self.assertIn("OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA", why)
        # "Not silently" has to mean something a reader can find, not just a refusal string.
        chain = json.loads((self.root / cb.SEED_CHAIN_PATH).read_text(encoding="utf-8"))
        entry = [g for g in chain["generations"]
                 if g.get("predecessor") == "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA"]
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry[0]["outcome"], "NO_PRODUCTION_REUSE")
        self.assertIsNone(entry[0]["supersedes_allowed_by"])

    def test_recording_the_refusal_is_idempotent(self):
        self._seed_record("DONE")
        for _ in range(3):
            cb.acceptance_seed_allowed(self.root)
        chain = json.loads((self.root / cb.SEED_CHAIN_PATH).read_text(encoding="utf-8"))
        self.assertEqual(len(chain["generations"]), 1)

    def test_an_explicit_supersede_is_what_opens_the_next_seed(self):
        self._seed_record("DONE")
        cb.write_seed_supersede(self.root, predecessor="OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA",
                                by="operator", note="first seed hit a closed event window")
        ok, why = cb.acceptance_seed_allowed(self.root)
        self.assertTrue(ok, why)

    def test_generations_are_bounded(self):
        self._seed_record("DONE")
        predecessor = "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA"
        cb.write_seed_supersede(self.root, predecessor=predecessor, by="operator", note="retry")
        chain = json.loads((self.root / cb.SEED_CHAIN_PATH).read_text(encoding="utf-8"))
        while len(chain["generations"]) < cb.SEED_MAX_GENERATIONS:
            chain["generations"].append({"predecessor": predecessor, "outcome": "SUPERSEDED",
                                         "supersedes_allowed_by": "operator"})
        (self.root / cb.SEED_CHAIN_PATH).write_text(
            json.dumps(chain, ensure_ascii=False), encoding="utf-8")
        ok, why = cb.acceptance_seed_allowed(self.root)
        self.assertFalse(ok)
        self.assertIn("用满", why)

    def test_a_real_reuse_still_closes_it_permanently(self):
        self._seed_record("DONE")
        q.EscalationLedger(self.ledger_path).append({
            "source": "queue", "event": "production_reuse",
            "key": "OPEN_ARENA|CAPABILITY_MISSING|OPEN_ARENA", "capability": "OPEN_ARENA",
            "production_reuse_episode_id": "ep-1", "recorded_at": NOW.isoformat(),
        })
        ok, why = cb.acceptance_seed_allowed(self.root)
        self.assertFalse(ok)
        self.assertIn("永久关闭", why)
        self.assertTrue((self.root / cb.PROVEN_ONCE_PATH).exists())


class TheGateDoesNotLieAboutTheSeed(unittest.TestCase):
    """Cheap guards against the two ways this fix could rot."""

    def test_the_fresh_heartbeat_requirement_is_not_weakened_by_this_change(self):
        root = seedable(Path(tempfile.mkdtemp()), [])
        stale = time.time() - 600
        import os
        os.utime(root / "learning/control_panel/pump.json", (stale, stale))
        ok, why = cb.acceptance_seed_allowed(root)
        self.assertFalse(ok)
        self.assertIn("面板心跳已过期", why)

    def test_a_candidate_rule_never_grants_the_seed_by_itself(self):
        """The two halves are independent: a perfect candidate in a disarmed system is still no seed."""
        root = seedable(Path(tempfile.mkdtemp()),
                        [row("OPEN_ARENA", capability_id="CAP-N01",
                             role="OBSERVED_AVAILABLE")])
        (root / "config/control_panel_state.json").write_text(
            json.dumps({"operator_intent": "STOPPED"}), encoding="utf-8")
        armed, reason, _ = cb.arm_state(root)
        self.assertFalse(armed)
        self.assertNotEqual(reason, cb.SEED_ARMED)


if __name__ == "__main__":
    unittest.main()
