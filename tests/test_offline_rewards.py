import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_offline_rewards_claimed
from winter_agent_v2.vision import SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]


class OfflineRewardsTests(unittest.TestCase):
    def test_live_welcome_back_popup_is_actionable(self):
        state = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").observe(ROOT / "dataset/raw/live_20260908_current.png")
        self.assertEqual((state.page, state.popup, state.daily.get("offline_rewards")), (Page.POPUP, "WELCOME_BACK_OFFLINE", "CLAIMABLE"))
        self.assertEqual(RuleBrain().decide(state, v2_registry()).skill, "CLAIM_OFFLINE_REWARDS")

    def test_live_popup_to_home_is_verified(self):
        before = WorldState(page=Page.POPUP, popup="WELCOME_BACK_OFFLINE", daily={"offline_rewards":"CLAIMABLE"}, confidence=0.99)
        after = WorldState(page=Page.HOME, confidence=0.98)
        self.assertTrue(verify_offline_rewards_claimed(before, after).ok)


if __name__ == "__main__":
    unittest.main()
