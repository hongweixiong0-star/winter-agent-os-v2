import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_alliance_gifts_claim, verify_ally_gift_claim
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class AllianceGiftsVerifierTests(unittest.TestCase):
    def test_live_day1_claim_cycle(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        states = [vision.observe(ROOT / "dataset/raw" / name) for name in (
            "live_alliance_gifts_page.png", "live_alliance_gifts_claim_result.png", "live_alliance_gifts_after.png"
        )]
        result = verify_alliance_gifts_claim(*states)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.evidence["daily_count_delta"], 19)
        self.assertEqual(RuleBrain().decide(states[0], v2_registry()).skill, "ALLIANCE_GIFTS")

    def test_live_day2_claim_cycle_after_reset(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        states = [vision.observe(ROOT / "dataset/raw" / name) for name in (
            "live_alliance_gifts_claim2_victory_recheck.png", "live_alliance_gifts_day2_reward.png", "live_alliance_gifts_day2_after.png"
        )]
        result = verify_alliance_gifts_claim(*states)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.evidence["daily_count_delta"], 61)

    def test_reset_interruption_is_not_success(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_alliance_gifts_new_one.png")
        unrelated = vision.observe(ROOT / "dataset/raw/live_alliance_gifts_claim2_result.png")
        after = vision.observe(ROOT / "dataset/raw/live_alliance_gifts_claim2_victory_recheck.png")
        self.assertFalse(verify_alliance_gifts_claim(before, unrelated, after).ok)

    def test_live_ally_gift_inline_claim(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_alliance_ally_gifts_before.png")
        after = vision.observe(ROOT / "dataset/raw/live_alliance_ally_gift_reward.png")
        result = verify_ally_gift_claim(before, after)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.evidence["progress_delta"], 30)
        self.assertEqual(RuleBrain().decide(before, v2_registry()).skill, "ALLIANCE_ALLY_GIFT_CLAIM")

    def test_live_ally_gift_replenished_list_uses_progress_proof(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_ally_auto_before_3.png")
        after = vision.observe(ROOT / "dataset/raw/live_ally_auto_after_3.png")
        result = verify_ally_gift_claim(before, after)
        self.assertTrue(result.ok, result.evidence)
        self.assertTrue(result.evidence["list_replenished_or_reordered"])

    def test_live_level_three_ally_gift_uses_displayed_120_points(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_ally_auto_before_9.png")
        after = vision.observe(ROOT / "dataset/raw/live_ally_auto_after_9.png")
        result = verify_ally_gift_claim(before, after)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.evidence["progress_delta"], 120)

    def test_unrelated_async_progress_is_not_enough(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        cleared = vision.observe(ROOT / "dataset/raw/live_ally_auto_after_9.png")
        async_progress = type(cleared)(
            page=cleared.page,
            alliance={**cleared.alliance, "gift_progress": 94640, "badge_count": 0},
            confidence=cleared.confidence,
        )
        self.assertFalse(verify_ally_gift_claim(cleared, async_progress).ok)


if __name__ == "__main__":
    unittest.main()
