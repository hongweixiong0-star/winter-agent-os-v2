"""WorkBuddy's model routing, and the boundary that keeps models out of V2.

The operator's architecture has four layers and the model is not one of them:
MAA is the eyes and hands, V2 is the gameplay brain, WorkBuddy is the development
platform, and models are *replaceable development compute*.  Two consequences
follow, and both are tested here rather than asserted in prose.

**V2 must not depend on a model.**  ``winter_agent_v2/workbuddy_model_router.py``
is the only file in the package that names one, so tomorrow's stronger, cheaper or
faster model is a change to that single file and nothing in the brain, scheduler,
skills, verifier or MAA layer moves.  ``ModelBoundaryTest`` enforces it by scanning
the package.

**The floor must not ratchet.**  A task that needed a strong model must not make
every later task expensive.  Selection is derived from *this* task type's record
each time, so a fresh task starts from the cheapest rung again -- which is the
failure mode of every naive "escalate and remember" router.

And the honest limit: the jobs API exposes no token or cost field (measured
2026-09-17), so "lowest cost" is realised as *performance within a known cost
ordering*.  ``cost`` is recorded as ``None`` with a reason rather than estimated.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import workbuddy_model_router as r  # noqa: E402


def outcome(model: str, task_type: str, *, success=True, live=False, duration=None, cost=None):
    return r.ModelOutcome(model=model, task_type=task_type, success=success,
                          live_improvement=live, duration=duration, cost=cost)


def router_with(rows, **kwargs):
    tmp = tempfile.TemporaryDirectory()
    store = r.ModelStatsStore(Path(tmp.name) / "stats.jsonl")
    for row in rows:
        store.append(row)
    return tmp, r.ModelRouter(store, **kwargs)


class ColdStartTest(unittest.TestCase):
    def test_nothing_recorded_starts_on_the_cheapest_rung(self):
        tmp, router = router_with([])
        try:
            choice = router.choose(r.TASK_UI_RECOGNITION)
            self.assertEqual(choice.model, r.SEED_ORDER[0])
            self.assertFalse(choice.from_history)
            self.assertIn("cold start", choice.reason)
        finally:
            tmp.cleanup()

    def test_a_vision_shaped_problem_may_start_higher(self):
        tmp, router = router_with([])
        try:
            self.assertEqual(router.choose(r.TASK_UI_RECOGNITION, needs="vision").model, r.VISION_RUNG)
            self.assertEqual(router.choose(r.TASK_UI_RECOGNITION, needs="logs").model, r.LONG_CONTEXT_RUNG)
        finally:
            tmp.cleanup()

    def test_a_shape_hint_only_applies_before_there_is_evidence(self):
        tmp, router = router_with([outcome(r.SEED_ORDER[0], r.TASK_UI_RECOGNITION) for _ in range(4)])
        try:
            choice = router.choose(r.TASK_UI_RECOGNITION, needs="vision")
            # Evidence about the cheap rung beats a heuristic about the problem shape.
            self.assertEqual(choice.model, r.SEED_ORDER[0])
            self.assertTrue(choice.from_history)
        finally:
            tmp.cleanup()


class WarmSelectionTest(unittest.TestCase):
    def test_a_cheap_rung_with_a_good_record_is_chosen(self):
        rows = [outcome(r.SEED_ORDER[0], r.TASK_REGRESSION_FIX) for _ in range(4)]
        tmp, router = router_with(rows)
        try:
            choice = router.choose(r.TASK_REGRESSION_FIX)
            self.assertEqual(choice.model, r.SEED_ORDER[0])
            self.assertTrue(choice.from_history)
            self.assertIn("clears", choice.reason)
        finally:
            tmp.cleanup()

    def test_a_rung_with_a_poor_record_is_skipped_for_the_next_cheapest(self):
        rows = ([outcome(r.SEED_ORDER[0], r.TASK_REGRESSION_FIX, success=False) for _ in range(4)]
                + [outcome(r.SEED_ORDER[1], r.TASK_REGRESSION_FIX) for _ in range(4)])
        tmp, router = router_with(rows)
        try:
            self.assertEqual(router.choose(r.TASK_REGRESSION_FIX).model, r.SEED_ORDER[1])
        finally:
            tmp.cleanup()

    def test_too_few_samples_is_still_a_cold_start(self):
        rows = [outcome(r.SEED_ORDER[1], r.TASK_REGRESSION_FIX) for _ in range(2)]
        tmp, router = router_with(rows)
        try:
            choice = router.choose(r.TASK_REGRESSION_FIX)
            self.assertEqual(choice.model, r.SEED_ORDER[0], "two jobs is not a record")
            self.assertFalse(choice.from_history)
        finally:
            tmp.cleanup()

    def test_when_every_rung_is_poor_the_cheapest_is_still_tried_first(self):
        rows = [outcome(m, r.TASK_REGRESSION_FIX, success=False) for m in r.SEED_ORDER for _ in range(4)]
        tmp, router = router_with(rows)
        try:
            choice = router.choose(r.TASK_REGRESSION_FIX)
            self.assertEqual(choice.model, r.SEED_ORDER[0])
            self.assertIn("rather than ratcheting the floor", choice.reason)
        finally:
            tmp.cleanup()

    def test_evidence_is_per_task_type_and_does_not_leak_across(self):
        rows = [outcome(r.SEED_ORDER[1], r.TASK_REGRESSION_FIX) for _ in range(4)]
        tmp, router = router_with(rows)
        try:
            self.assertEqual(router.choose(r.TASK_REGRESSION_FIX).model, r.SEED_ORDER[1])
            # A different kind of work knows nothing about that record.
            self.assertEqual(router.choose(r.TASK_GAMEPLAY_MODELING).model, r.SEED_ORDER[0])
        finally:
            tmp.cleanup()


class NoRatchetTest(unittest.TestCase):
    """A spent budget must not raise the price of unrelated work."""

    def test_a_task_that_climbed_does_not_make_the_next_task_expensive(self):
        rows = [outcome(r.SEED_ORDER[0], r.TASK_UI_RECOGNITION) for _ in range(4)]
        tmp, router = router_with(rows)
        try:
            # This task already spent its first shot and climbs...
            climbed = router.choose(r.TASK_UI_RECOGNITION, attempt=1,
                                    previous_model=r.SEED_ORDER[0])
            self.assertEqual(climbed.model, r.SEED_ORDER[1])
            self.assertTrue(climbed.is_escalated)
            self.assertEqual(climbed.escalated_from, r.SEED_ORDER[0])
            # ...and the next task of the same kind starts cheap again.
            self.assertEqual(router.choose(r.TASK_UI_RECOGNITION).model, r.SEED_ORDER[0])
            self.assertEqual(router.choose(r.TASK_STUCK_INVESTIGATION).model, r.SEED_ORDER[0])
        finally:
            tmp.cleanup()

    def test_climbing_is_capped_at_the_top_rung(self):
        tmp, router = router_with([])
        try:
            top = r.SEED_ORDER[-1]
            choice = router.choose(r.TASK_STUCK_INVESTIGATION, attempt=9, previous_model=top)
            self.assertEqual(choice.model, top)
        finally:
            tmp.cleanup()

    def test_every_attempt_climbs_exactly_one_rung(self):
        tmp, router = router_with([])
        try:
            previous = r.SEED_ORDER[0]
            for step in range(1, len(r.SEED_ORDER)):
                choice = router.choose(r.TASK_STUCK_INVESTIGATION, attempt=step, previous_model=previous)
                self.assertEqual(choice.model, r.SEED_ORDER[step])
                self.assertEqual(choice.escalated_from, previous)
                previous = choice.model
        finally:
            tmp.cleanup()

    def test_the_reason_is_always_present(self):
        tmp, router = router_with([])
        try:
            for attempt in (0, 1, 2):
                self.assertTrue(router.choose(r.TASK_UI_RECOGNITION, attempt=attempt).reason.strip())
        finally:
            tmp.cleanup()


class TaskTypeTest(unittest.TestCase):
    def test_each_condition_maps_to_its_own_task_bucket(self):
        self.assertEqual(r.task_type_for("UNKNOWN_UI"), r.TASK_UI_RECOGNITION)
        self.assertEqual(r.task_type_for("CAPABILITY_MISSING"), r.TASK_CAPABILITY_IMPLEMENTATION)
        self.assertEqual(r.task_type_for("UNKNOWN_GAME_MECHANIC"), r.TASK_GAMEPLAY_MODELING)
        self.assertEqual(r.task_type_for("REPEATED_LIVE_FAILURE"), r.TASK_REGRESSION_FIX)
        self.assertEqual(r.task_type_for("STUCK_15_MIN"), r.TASK_STUCK_INVESTIGATION)

    def test_an_unknown_condition_falls_back_rather_than_inventing_a_bucket(self):
        self.assertEqual(r.task_type_for("SOMETHING_NEW"), r.TASK_STUCK_INVESTIGATION)

    def test_every_task_type_has_a_condition_that_reaches_it(self):
        reached = {r.task_type_for(c) for c in
                   ("UNKNOWN_UI", "CAPABILITY_MISSING", "UNKNOWN_GAME_MECHANIC",
                    "REPEATED_LIVE_FAILURE", "STUCK_15_MIN")}
        self.assertEqual(reached, set(r.TASK_TYPES))


class StatsTest(unittest.TestCase):
    def test_folding_counts_jobs_successes_and_live_improvements(self):
        rows = [
            outcome("a", r.TASK_UI_RECOGNITION, success=True, live=True, duration=60.0).as_row(),
            outcome("a", r.TASK_UI_RECOGNITION, success=True, live=False, duration=40.0).as_row(),
            outcome("a", r.TASK_UI_RECOGNITION, success=False, duration=20.0).as_row(),
            outcome("a", r.TASK_GAMEPLAY_MODELING).as_row(),
        ]
        rungs = r.stats_for(rows, r.TASK_UI_RECOGNITION)
        self.assertEqual(rungs["a"].samples, 3)
        self.assertEqual(rungs["a"].successes, 2)
        self.assertEqual(rungs["a"].live_improvements, 1)
        self.assertAlmostEqual(rungs["a"].success_rate, 2 / 3)
        self.assertAlmostEqual(rungs["a"].mean_duration, 40.0)

    def test_a_row_without_a_duration_still_counts_as_a_job(self):
        rows = [outcome("a", r.TASK_UI_RECOGNITION).as_row()]
        rungs = r.stats_for(rows, r.TASK_UI_RECOGNITION)
        self.assertEqual(rungs["a"].samples, 1)
        self.assertIsNone(rungs["a"].mean_duration)

    def test_an_empty_record_describes_itself_as_empty(self):
        self.assertIn("no record", r.Rung(model="a").describe())

    def test_the_store_round_trips_and_ignores_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.jsonl"
            store = r.ModelStatsStore(path)
            store.append(outcome("a", r.TASK_UI_RECOGNITION))
            with path.open("a", encoding="utf-8") as handle:
                handle.write("not json\n")
            self.assertEqual(len(store.rows()), 1)

    def test_a_missing_store_is_empty_not_an_error(self):
        self.assertEqual(r.ModelStatsStore(Path("Z:/nope/stats.jsonl")).rows(), [])


class CostHonestyTest(unittest.TestCase):
    def test_cost_is_recorded_as_null_with_a_reason_rather_than_estimated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.jsonl"
            r.ModelStatsStore(path).append(
                r.ModelOutcome(model="a", task_type=r.TASK_UI_RECOGNITION,
                               cost=None, note="cost unavailable")
            )
            row = r.ModelStatsStore(path).rows()[0]
            self.assertIsNone(row["cost"])
            self.assertIn("cost unavailable", row["note"])

    def test_the_module_says_why_the_cheapest_half_is_the_measurable_one(self):
        doc = r.__doc__ or ""
        self.assertIn("no token or cost field", doc)


class ModelBoundaryTest(unittest.TestCase):
    """The only file in the package that may name a model is the router."""

    MODEL_TOKENS = ("deepseek", "glm-", "hy4", "kimi", "minimax", "gpt-", "claude")

    def test_no_model_literal_appears_outside_the_router(self):
        offenders: list[str] = []
        for source in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            if source.name == "workbuddy_model_router.py":
                continue
            text = source.read_text(encoding="utf-8").lower()
            for token in self.MODEL_TOKENS:
                if token in text:
                    offenders.append(f"{source.name}: {token}")
        self.assertEqual(
            offenders, [],
            "model names must stay in workbuddy_model_router.py so the strategy can "
            "be replaced without touching V2: " + ", ".join(offenders),
        )

    def test_the_escalation_queue_delegates_instead_of_choosing(self):
        source = (ROOT / "winter_agent_v2/escalation_queue.py").read_text(encoding="utf-8")
        self.assertIn("workbuddy_model_router", source)
        self.assertNotIn("SEED_ORDER", source.replace("model_stats_path(root)", ""))

    def test_the_brain_scheduler_skills_and_verifier_do_not_import_the_router(self):
        for name in ("brain.py", "scheduler.py", "skills.py", "verifier.py"):
            text = (ROOT / "winter_agent_v2" / name).read_text(encoding="utf-8")
            self.assertNotIn("workbuddy_model_router", text, name)

    def test_the_seed_order_is_the_operators_cheapest_first_ladder(self):
        self.assertEqual(
            r.SEED_ORDER,
            ("deepseek-v4.1-flash", "glm-5.3-flash", "hy4-preview-f", "deepseek-v4-pro"),
        )

    def test_the_seed_order_is_labelled_a_seed_rather_than_the_answer(self):
        doc = r.__doc__ or ""
        self.assertIn("seed", doc.lower())
        source = (ROOT / "winter_agent_v2/workbuddy_model_router.py").read_text(encoding="utf-8")
        self.assertIn("A **seed**, not the answer", source)


class ReportTest(unittest.TestCase):
    def test_the_report_shows_the_seed_order_and_any_recorded_outcomes(self):
        tmp, router = router_with([outcome(r.SEED_ORDER[0], r.TASK_REGRESSION_FIX) for _ in range(3)])
        try:
            text = router.report()
            self.assertIn(r.SEED_ORDER[0], text)
            self.assertIn(r.TASK_REGRESSION_FIX, text)
        finally:
            tmp.cleanup()

    def test_the_report_says_so_when_nothing_is_recorded(self):
        tmp, router = router_with([])
        try:
            self.assertIn("(none yet)", router.report())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
