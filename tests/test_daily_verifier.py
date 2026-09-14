import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_daily_claim, verify_daily_hero_recruit
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class DailyVerifierTests(unittest.TestCase):
    def test_live_free_recruit_daily_cycle(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        names = [
            "live_daily_after_beast.png",
            "live_daily_hero_recruit_navigation.png",
            "live_daily_hero_recruit_result.png",
            "live_daily_hero_recruit_verified.png",
            "live_daily_claim_result.png",
            "live_daily_claim_verified.png",
        ]
        states = [vision.observe(ROOT / "dataset" / "raw" / name) for name in names]
        self.assertEqual(RuleBrain().decide(states[0], v2_registry()).skill, "DAILY_HERO_RECRUIT")
        self.assertTrue(verify_daily_hero_recruit(*states).ok)

    def test_daily_cycle_requires_activity_delta(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        names = ["live_daily_after_beast.png","live_daily_hero_recruit_navigation.png","live_daily_hero_recruit_result.png","live_daily_hero_recruit_verified.png","live_daily_claim_result.png"]
        states = [vision.observe(ROOT / "dataset" / "raw" / name) for name in names]
        self.assertFalse(verify_daily_hero_recruit(*states, states[0]).ok)

    def test_live_multi_task_claim(self) -> None:
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_continue_task_page.png")
        reward = vision.observe(ROOT / "dataset/raw/live_daily_multiclaim_result.png")
        after = vision.observe(ROOT / "dataset/raw/live_daily_multiclaim_after.png")
        self.assertEqual(RuleBrain().decide(before, v2_registry()).skill, "DAILY_CLAIM_REWARDS")
        self.assertTrue(verify_daily_claim(before, reward, after).ok)
