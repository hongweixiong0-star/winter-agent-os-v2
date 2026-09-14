import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_alliance_help_auto_active, verify_alliance_tech_contribution
from winter_agent_v2.vision import SemanticWorldVision


class AllianceVerifierTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_live_alliance_screens_are_semantically_observed(self):
        vision = SemanticWorldVision(self.ROOT / "dataset/candidate/template_manifest.json")
        before = vision.observe(self.ROOT / "dataset/raw/live_alliance_tech_detail.png")
        result = vision.observe(self.ROOT / "dataset/raw/live_alliance_tech_contribution_result.png")
        help_state = vision.observe(self.ROOT / "dataset/raw/live_alliance_help.png")
        self.assertEqual(before.alliance.get("attempts_remaining"), 25)
        self.assertEqual(result.alliance.get("attempts_remaining"), 24)
        self.assertTrue(help_state.alliance.get("auto_help_active"))

    def test_live_contribution_transition(self):
        before = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"AVAILABLE","personal_contribution":49080,"attempts_remaining":25,"resource":"MEAT","cost":10000}, confidence=0.99)
        result = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"CONTRIBUTED","contribution":240,"attempts_remaining":24}, confidence=0.99)
        after = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"AVAILABLE","personal_contribution":49320,"attempts_remaining":24,"resource":"MEAT","cost":10000}, confidence=0.99)
        self.assertEqual(RuleBrain().decide(before, v2_registry()).skill, "ALLIANCE_TECH_CONTRIBUTE")
        self.assertTrue(verify_alliance_tech_contribution(before, result, after).ok)

    def test_auto_help_is_not_failure(self):
        state = WorldState(page=Page.ALLIANCE, alliance={"section":"HELP","status":"NOT_AVAILABLE","auto_help_active":True}, confidence=0.99)
        decision = RuleBrain().decide(state, v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "alliance_help_auto_active")
        self.assertTrue(verify_alliance_help_auto_active(state).ok)

    def test_contribution_requires_counter_delta(self):
        before = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"AVAILABLE","personal_contribution":49080,"attempts_remaining":25,"resource":"MEAT","cost":10000})
        self.assertFalse(verify_alliance_tech_contribution(before, before, before).ok)

    def test_live_three_consecutive_contributions_include_normal_and_critical_rewards(self):
        attempts = [
            (49080, 25, 240, 49320, 24),
            (49320, 24, 120, 49440, 23),
            (49440, 23, 240, 49680, 22),
        ]
        for contribution_before, attempts_before, reward, contribution_after, attempts_after in attempts:
            before = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"AVAILABLE","personal_contribution":contribution_before,"attempts_remaining":attempts_before,"resource":"MEAT","cost":10000})
            result = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"CONTRIBUTED","contribution":reward,"attempts_remaining":attempts_after})
            after = WorldState(page=Page.ALLIANCE, alliance={"section":"TECHNOLOGY","status":"AVAILABLE","personal_contribution":contribution_after,"attempts_remaining":attempts_after})
            self.assertTrue(verify_alliance_tech_contribution(before, result, after).ok)


if __name__ == "__main__":
    unittest.main()
