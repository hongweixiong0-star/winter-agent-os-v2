import unittest

from winter_agent_v2.models import Action, Page, SkillState
from winter_agent_v2.semantic_gate import (
    ClaimContext, ClaimDecision, audit_vision_asset, decide_claim,
    semantic_robustness_gate, stable_promotion_allowed,
)
from winter_agent_v2.skills import Skill, v2_registry


class SemanticFirstGateTests(unittest.TestCase):
    def test_unknown_reward_does_not_block_free_claim(self):
        context = ClaimContext(True, True, False, False, False, False, reward_known=False)
        self.assertEqual(decide_claim(context), ClaimDecision.AUTO_CLAIM)

    def test_unknown_cost_blocks_and_choice_routes_to_strategy(self):
        unknown_cost = ClaimContext(True, True, False, False, None, False)
        choice = ClaimContext(True, True, True, False, False, False)
        self.assertEqual(decide_claim(unknown_cost), ClaimDecision.BLOCK_UNKNOWN_ACTION)
        self.assertEqual(decide_claim(choice), ClaimDecision.SELECT_REWARD_OPTION)

    def test_generic_claim_has_complete_semantic_contract(self):
        skill = v2_registry().get("CLAIM_REWARD")
        self.assertTrue(skill.semantic_contract_complete)
        self.assertTrue(semantic_robustness_gate(skill).ok)

    def test_fixed_coordinate_or_click_only_cannot_be_stable(self):
        fragile = Skill("FRAGILE", "bad", Page.HOME, Action("TAP", payload={"x":1,"y":2}),
                        state=SkillState.STABLE, semantic_goal="click",
                        semantic_requirements=("FIXED_COORDINATE_ONLY",),
                        vision_evidence=("SINGLE_TEMPLATE_ONLY",), verifier="CLICK_SUCCESS",
                        recovery=("RETRY",), unknown_policy="guess",
                        ui_change_tolerance=("none",))
        result = stable_promotion_allowed(fragile)
        self.assertFalse(result.ok)
        self.assertIn("STATE_CHANGE_VERIFIER_REQUIRED", result.failures)

    def test_vision_asset_requires_semantic_normalized_roi_and_provenance(self):
        good = {"semantic":"BTN_CLAIM", "roi_norm":{"x_norm":.1,"y_norm":.2,"w_norm":.3,"h_norm":.1}, "source":"LIVE_CLIENT"}
        self.assertTrue(audit_vision_asset(good).ok)
        self.assertFalse(audit_vision_asset({"template_path":"fixed.png", "absolute_coordinate_only":True}).ok)


if __name__ == "__main__":
    unittest.main()
