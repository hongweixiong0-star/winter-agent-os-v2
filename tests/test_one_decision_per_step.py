"""One step, one decision.

`RuleBrain.decide` is not a pure function: it mutates run-scoped state.  The
clearest example is the free-stamina once-per-run check (brain.py:352-363),
which sets `stamina_panel_checked = True` *and* returns OPEN_STAMINA_SOURCES on
the first call, then returns the goal's own action on the second.

`runtime.py` used to make the decision twice for the same frame -- once itself
(to build the backend router) and once inside `Scheduler.tick` (which executed
it).  The two answers disagreed, so the step performed the second decision's
action while the verifier judged it with the first decision's verifier.

Live evidence (2026-09-15T02:31:11Z, goal INTEL, client on the world map):

    action      TAP_SEMANTIC BTN_OPEN_INTEL_WILD_HUD
    before      MAP
    after       INTEL          <- the action worked
    verification ok=false, reason=STAMINA_SOURCES_NOT_OPEN
                 evidence {"before_page": "MAP", "after_popup": null}
    recorded as skill OPEN_INTEL
    stop_reason STAMINA_SOURCES_NOT_OPEN (exit 2)

`STAMINA_SOURCES_NOT_OPEN` is `verify_stamina_sources_open`'s reason and that
evidence dict is its evidence, so a verifier for a skill the step never ran
decided the step.  The free-stamina panel was also never opened even though the
brain had marked it checked for the run.

These tests pin the invariant: the scheduler executes the decision it is given,
so the action, the verifier and the recorded episode all describe one skill.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.executor import Executor
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_open_intel, verify_stamina_sources_open


ROOT = Path(__file__).resolve().parents[1]
AB_ARCHIVE = ROOT / "dataset" / "truth_audit" / "one_decision_per_step_20260915"
AB_RECORDS = AB_ARCHIVE / "live_ab_records.json"

# A world map frame with a readable stamina readout: exactly the precondition
# for the once-per-run free-stamina check.
MAP_WITH_STAMINA = WorldState(
    page=Page.MAP,
    march_used=1,
    march_max=6,
    stamina={"current": 2, "source": "MAP_HUD"},
    resource_search_open=False,
    confidence=0.99,
)


def _brain(goal: str | None = "INTEL") -> RuleBrain:
    return RuleBrain(current_goal=goal, claim_free_stamina=True)


class BrainDecideIsNotIdempotentTests(unittest.TestCase):
    """Documents *why* the invariant is needed, not a wish for it."""

    def test_the_free_stamina_check_changes_the_second_answer(self) -> None:
        brain = _brain()
        registry = v2_registry()

        first = brain.decide(MAP_WITH_STAMINA, registry)
        second = brain.decide(MAP_WITH_STAMINA, registry)

        self.assertEqual(first.skill, "OPEN_STAMINA_SOURCES")
        self.assertEqual(second.skill, "OPEN_INTEL")
        self.assertNotEqual(first.skill, second.skill)

    def test_the_flag_is_set_by_the_decision_not_by_the_action(self) -> None:
        """The mutation happens inside decide(), before anything is executed."""
        brain = _brain()
        self.assertFalse(brain.stamina_panel_checked)
        brain.decide(MAP_WITH_STAMINA, v2_registry())
        self.assertTrue(brain.stamina_panel_checked)


class SchedulerExecutesTheGivenDecisionTests(unittest.TestCase):
    def test_the_given_decision_is_the_one_executed_and_returned(self) -> None:
        brain = _brain()
        registry = v2_registry()
        handed_over = brain.decide(MAP_WITH_STAMINA, registry)
        self.assertEqual(handed_over.skill, "OPEN_STAMINA_SOURCES")

        scheduler = Scheduler(brain, registry, Executor(), None)
        tick = scheduler.tick(MAP_WITH_STAMINA, handed_over)

        self.assertIs(tick.decision, handed_over)
        self.assertEqual(tick.decision.skill, "OPEN_STAMINA_SOURCES")
        # Executor() is a dry run, so the action is planned but not performed;
        # what matters is that the *action* belongs to the handed-over skill.
        self.assertIsNotNone(tick.execution)

    def test_a_recomputed_tick_would_answer_differently(self) -> None:
        """The exact disagreement the runtime used to create."""
        brain = _brain()
        registry = v2_registry()
        handed_over = brain.decide(MAP_WITH_STAMINA, registry)

        recomputed = Scheduler(brain, registry, Executor(), None).tick(MAP_WITH_STAMINA)

        self.assertEqual(handed_over.skill, "OPEN_STAMINA_SOURCES")
        self.assertEqual(recomputed.decision.skill, "OPEN_INTEL")
        self.assertNotEqual(handed_over.skill, recomputed.decision.skill)

    def test_callers_without_a_decision_keep_the_old_behaviour(self) -> None:
        """Backward compatibility: the single-scheduler contract is unchanged."""
        brain = _brain()
        tick = Scheduler(brain, v2_registry(), Executor(), None).tick(MAP_WITH_STAMINA)
        self.assertEqual(tick.decision.skill, "OPEN_STAMINA_SOURCES")


class RuntimePassesOneDecisionTests(unittest.TestCase):
    """A source guard: the runtime must not re-decide through the scheduler."""

    def test_the_runtime_hands_its_decision_to_the_scheduler(self) -> None:
        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn(
            ").tick(before, decision)",
            source,
            "runtime.py must pass its already-made decision to Scheduler.tick",
        )
        self.assertNotIn(
            ").tick(before)\n",
            source,
            "runtime.py must not let the scheduler re-decide for the same frame",
        )

    def test_the_scheduler_accepts_a_decision_and_defaults_to_deciding(self) -> None:
        source = (ROOT / "winter_agent_v2" / "scheduler.py").read_text(encoding="utf-8")
        self.assertIn(
            "def tick(self, world: WorldState, decision: Decision | None = None)",
            source,
        )
        self.assertIn("if decision is None:", source)


def _state(raw: dict) -> WorldState:
    """Rebuild a WorldState from a recorded step's serialized state."""
    data = dict(raw)
    data["page"] = Page(data["page"]) if data.get("page") else Page.UNKNOWN
    data["marches"] = tuple(MarchState(m) for m in data.get("marches") or ())
    data.pop("timestamp", None)
    return WorldState(**data)


class LiveClientABTests(unittest.TestCase):
    """Replay the two live step-1 records that bracket the fix.

    Both runs: goal INTEL, client on the world map, stamina 0 spent.  Only the
    verifier applied to the step differs.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = json.loads(AB_RECORDS.read_text(encoding="utf-8"))

    def test_the_fixture_is_a_live_client_ab(self) -> None:
        self.assertEqual(self.records["_provenance"]["kind"], "LIVE_CLIENT_AB")
        self.assertEqual(self.records["_provenance"]["goal"], "INTEL")
        self.assertEqual(self.records["_provenance"]["stamina_spent"], 0)
        for name in self.records["_provenance"]["frames"].values():
            self.assertTrue((AB_ARCHIVE / name).is_file(), name)

    def test_both_runs_performed_the_same_action_and_transition(self) -> None:
        before = self.records["before_fix"]["step"]
        after = self.records["after_fix"]["step"]
        for step in (before, after):
            self.assertEqual(step["decision"]["skill"], "OPEN_INTEL")
            self.assertEqual(
                step["execution"]["action"]["target"], "BTN_OPEN_INTEL_WILD_HUD"
            )
            self.assertEqual(step["before"]["page"], "MAP")
            self.assertEqual(step["after"]["page"], "INTEL")
        self.assertEqual(
            before["execution"]["action"], after["execution"]["action"]
        )

    def test_before_the_fix_a_stamina_verifier_judged_an_intel_step(self) -> None:
        step = self.records["before_fix"]["step"]
        before = _state(step["before"])
        after = _state(step["after"])

        # The action really worked ...
        self.assertTrue(verify_open_intel(before, after).ok)

        # ... but this is the verification the step was recorded with, and it is
        # reproducible from the other verifier: same reason, same evidence.
        recorded = step["verification"]
        self.assertFalse(recorded["ok"])
        self.assertEqual(recorded["reason"], "STAMINA_SOURCES_NOT_OPEN")
        wrong = verify_stamina_sources_open(before, after)
        self.assertEqual(recorded["reason"], wrong.reason)
        self.assertEqual(recorded["evidence"], wrong.evidence)
        self.assertEqual(self.records["before_fix"]["stop_reason"], wrong.reason)

    def test_after_the_fix_the_intel_verifier_judges_the_intel_step(self) -> None:
        step = self.records["after_fix"]["step"]
        before = _state(step["before"])
        after = _state(step["after"])

        recorded = step["verification"]
        right = verify_open_intel(before, after)
        self.assertTrue(recorded["ok"])
        self.assertEqual(recorded["reason"], right.reason)
        self.assertEqual(recorded["evidence"], right.evidence)
        self.assertEqual(recorded["evidence"]["after_intel"], True)
        self.assertEqual(self.records["after_fix"]["stop_reason"], "MAX_ACTIONS_REACHED")


if __name__ == "__main__":
    unittest.main()
