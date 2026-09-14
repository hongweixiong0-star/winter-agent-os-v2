import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_daily_claim_feedback, verify_daily_reward_advanced, verify_open_daily
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]


class CurrentDailyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")

    def state(self, name):
        return self.vision.observe(ROOT / "dataset/raw" / name)

    def test_current_multilayer_reward_flow(self):
        daily = self.state("live_20260908_daily_entry.png")
        reward_one = self.state("live_20260908_daily_reward.png")
        reward_two = self.state("live_20260908_daily_after.png")
        after = self.state("live_20260908_daily_after2.png")
        self.assertTrue(verify_daily_claim_feedback(daily, reward_one).ok)
        self.assertTrue(verify_daily_reward_advanced(reward_one, reward_two).ok)
        self.assertTrue(verify_daily_reward_advanced(reward_two, after).ok)
        self.assertEqual(after.daily.get("activity"), 70)
        self.assertEqual(RuleBrain(current_goal="DAILY").decide(reward_one, v2_registry()).skill, "DISMISS_DAILY_REWARD")

    def test_open_daily_verifier(self):
        before = self.state("live_20260908_offline_after.png")
        after = self.state("live_20260908_daily_entry.png")
        self.assertEqual(before.page, Page.HOME)
        self.assertTrue(verify_open_daily(before, after).ok)

    def test_daily_panel_goal_does_not_start_unverified_task_actions(self):
        current = self.state("live_20260908_daily_after2.png")
        decision = RuleBrain(current_goal="DAILY").decide(current, v2_registry())
        self.assertEqual((decision.skill, decision.reason), ("SAFE_STOP", "daily_no_claimable_rewards"))


if __name__ == "__main__":
    unittest.main()
