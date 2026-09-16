import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.executor import Executor
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class MultiTaskSchedulerTests(unittest.TestCase):
    def test_skips_live_busy_and_auto_states_then_selects_daily(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        states = (
            vision.observe(ROOT / "dataset/raw/live_research_queue_busy.png"),
            WorldState(page=Page.TRAINING, training={"all_queues_busy":True}),
            vision.observe(ROOT / "dataset/raw/live_alliance_help.png"),
            vision.observe(ROOT / "dataset/raw/live_daily_after_beast.png"),
        )
        selection = Scheduler(RuleBrain(), v2_registry(), Executor()).select_next(states)
        self.assertEqual(selection.index, 3)
        self.assertEqual(selection.decision.skill, "DAILY_HERO_RECRUIT")
        self.assertEqual([item.reason for item in selection.skipped], ["research_queue_busy","all_training_queues_busy","alliance_help_auto_active"])

    def test_unknown_daily_and_alliance_never_fall_through_to_registry(self):
        """The scheduler answers with a decision of its own, never a registry default.

        The guard this test exists for is unchanged: an unknown state on these pages
        must not fall through to ``registry.ready(world)[0]``, whose first entry is the
        ``WAIT`` placeholder and would park the loop silently.  What changed on
        2026-09-16 is the shape of the answer for the daily panel -- an unknown or
        empty panel is now left with a verified Back (measured DAILY -> HOME,
        accepted by ``verify_safe_back``) instead of being stopped from inside, which
        stranded the client for every following run.  Alliance is untouched.
        """
        scheduler = Scheduler(RuleBrain(), v2_registry(), Executor())
        daily = scheduler.tick(WorldState(page=Page.DAILY, daily={"status":"UNKNOWN"}, confidence=0.9))
        alliance = scheduler.tick(WorldState(page=Page.ALLIANCE, alliance={"status":"UNKNOWN"}, confidence=0.9))
        self.assertEqual(daily.decision.skill, "BACK")
        self.assertEqual(daily.decision.reason, "daily_panel_not_actionable_leaving_the_page")
        # Not a registry fall-through: the placeholder the guard is about is WAIT.
        self.assertNotEqual(daily.decision.skill, "WAIT")
        self.assertEqual(alliance.decision.skill, "SAFE_STOP")

    def test_all_unavailable_has_explicit_result(self):
        scheduler = Scheduler(RuleBrain(), v2_registry(), Executor())
        selection = scheduler.select_next((WorldState(), WorldState(page=Page.ALLIANCE, alliance={"status":"UNKNOWN"})))
        self.assertIsNone(selection.index)
        self.assertEqual(selection.decision.reason, "all_tasks_unavailable")


if __name__ == "__main__":
    unittest.main()
