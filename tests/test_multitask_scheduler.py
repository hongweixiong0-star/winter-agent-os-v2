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
        scheduler = Scheduler(RuleBrain(), v2_registry(), Executor())
        daily = scheduler.tick(WorldState(page=Page.DAILY, daily={"status":"UNKNOWN"}, confidence=0.9))
        alliance = scheduler.tick(WorldState(page=Page.ALLIANCE, alliance={"status":"UNKNOWN"}, confidence=0.9))
        self.assertEqual(daily.decision.skill, "SAFE_STOP")
        self.assertEqual(alliance.decision.skill, "SAFE_STOP")

    def test_all_unavailable_has_explicit_result(self):
        scheduler = Scheduler(RuleBrain(), v2_registry(), Executor())
        selection = scheduler.select_next((WorldState(), WorldState(page=Page.ALLIANCE, alliance={"status":"UNKNOWN"})))
        self.assertIsNone(selection.index)
        self.assertEqual(selection.decision.reason, "all_tasks_unavailable")


if __name__ == "__main__":
    unittest.main()
