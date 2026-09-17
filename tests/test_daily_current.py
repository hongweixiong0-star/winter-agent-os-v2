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
        # Since 2026-09-17 the shared 获得奖励 dialog is reported as GENERIC_REWARD,
        # so a daily goal reaches the goal-context dismiss rather than the
        # DAILY_REWARD-specific one.  Same verifier (verify_daily_reward_advanced),
        # which accepts either label as the popup before-state.
        self.assertEqual(RuleBrain(current_goal="DAILY").decide(reward_one, v2_registry()).skill, "DISMISS_DAILY_GENERIC_REWARD")

    def test_open_daily_verifier(self):
        before = self.state("live_20260908_offline_after.png")
        after = self.state("live_20260908_daily_entry.png")
        self.assertEqual(before.page, Page.HOME)
        self.assertTrue(verify_open_daily(before, after).ok)

    def test_daily_panel_goal_does_not_start_unverified_task_actions(self):
        """The panel is read, left, and only then stopped.

        The intent of this test is unchanged -- the brain must not reach for a task
        action it cannot have verified (``DAILY_HERO_RECRUIT`` still has no
        verifier, and is still not chosen) -- but the *shape* of the honest stop
        changed on 2026-09-16.  Stopping while still inside the panel stranded the
        client, so the run now leaves it first (measured DAILY -> HOME, accepted by
        ``verify_safe_back``) and stops on the following decision.  See
        ``tests/test_daily_panel_dead_end_recovery.py``.
        """
        current = self.state("live_20260908_daily_after2.png")
        brain = RuleBrain(current_goal="DAILY")
        first = brain.decide(current, v2_registry())
        self.assertEqual((first.skill, first.reason),
                         ("BACK", "daily_panel_not_actionable_leaving_the_page"))
        home = self.state("live_20260908_offline_after.png")
        self.assertEqual(home.page, Page.HOME)
        second = brain.decide(home, v2_registry())
        self.assertEqual((second.skill, second.reason),
                         ("SAFE_STOP", "daily_panel_already_read_not_actionable"))


if __name__ == "__main__":
    unittest.main()
