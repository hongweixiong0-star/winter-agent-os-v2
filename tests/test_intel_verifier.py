import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.verifier import verify_intel_beast_dispatch, verify_intel_beast_march_open, verify_intel_claim, verify_intel_claim_feedback, verify_intel_mission_selected, verify_intel_rescue_selected, verify_intel_rescue_started, verify_intel_rescue_target_open, verify_intel_reward_dismissed, verify_intel_target_open
from winter_agent_v2.vision import ReplayVision, SemanticWorldVision
from winter_agent_v2.skills import v2_registry


ROOT = Path(__file__).resolve().parents[1]


class IntelVerifierTests(unittest.TestCase):
    def test_live_intel_claim_cycle(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        before = vision.observe(ROOT / "dataset" / "raw" / "live_intel_lighthouse_selected.png")
        reward = vision.observe(ROOT / "dataset" / "raw" / "live_intel_claim_result.png")
        after = vision.observe(ROOT / "dataset" / "raw" / "live_intel_after_claim.png")
        decision = RuleBrain().decide(before, v2_registry())
        self.assertEqual(decision.skill, "INTEL_CLAIM_REWARDS")
        self.assertTrue(verify_intel_claim(before, reward, after).ok)

    def test_intel_claim_requires_reward_feedback(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        before = vision.observe(ROOT / "dataset" / "raw" / "live_intel_lighthouse_selected.png")
        after = vision.observe(ROOT / "dataset" / "raw" / "live_intel_after_claim.png")
        self.assertFalse(verify_intel_claim(before, after, after).ok)

    def test_atomic_live_runtime_claim_requires_reward_popup(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        before = vision.observe(ROOT / "dataset" / "raw" / "live_intel_lighthouse_selected.png")
        reward = vision.observe(ROOT / "dataset" / "raw" / "live_intel_claim_result.png")
        self.assertTrue(verify_intel_claim_feedback(before, reward).ok)
        self.assertFalse(verify_intel_claim_feedback(before, before).ok)

    def test_reward_overlay_uses_dedicated_safe_dismiss_and_requires_intel_page(self) -> None:
        reward = WorldState(page=Page.POPUP, popup="INTEL_REWARD", intel={"claim_feedback": True}, confidence=0.99)
        intel = WorldState(page=Page.INTEL, intel={"status": "AVAILABLE", "stamina": 200}, confidence=0.99)
        decision = RuleBrain().decide(reward, v2_registry())
        self.assertEqual(decision.skill, "DISMISS_INTEL_REWARD")
        self.assertTrue(verify_intel_reward_dismissed(reward, intel).ok)
        self.assertFalse(verify_intel_reward_dismissed(reward, WorldState(page=Page.UNKNOWN)).ok)

    def test_current_client_intel_beast_chain_is_verifier_gated(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
        available = vision.observe(ROOT / "dataset" / "raw" / "live_intel_beast10_claim_runtime" / "step_003_before.png")
        dialog = vision.observe(ROOT / "dataset" / "raw" / "live_intel_mission_probe.png")
        target = vision.observe(ROOT / "dataset" / "raw" / "live_intel_beast10_target_current.png")
        march = vision.observe(ROOT / "dataset" / "raw" / "live_intel_beast10_march_current.png")
        dispatched = ReplayVision(ROOT / "tests" / "replay" / "labels.json").observe(ROOT / "dataset" / "raw" / "live_beast_marching.png")
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(available, v2_registry()).skill, "SELECT_INTEL_BEAST_MISSION")
        self.assertTrue(verify_intel_mission_selected(available, dialog).ok)
        self.assertTrue(verify_intel_target_open(dialog, target).ok)
        self.assertTrue(verify_intel_beast_march_open(target, march).ok)
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(march, v2_registry()).skill, "DISPATCH_INTEL_BEAST")
        self.assertTrue(verify_intel_beast_dispatch(march, dispatched).ok)

    def test_special_intel_dialogs_cannot_enter_ordinary_beast_flow(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
        hero = vision.observe(ROOT / "dataset" / "raw" / "live_intel_purple_axes_probe.png")
        bounty = vision.observe(ROOT / "dataset" / "raw" / "live_intel_orange_rabbit_probe.png")

        self.assertEqual((hero.popup, hero.intel.get("mission_type")), ("INTEL_HERO_JOURNEY", "HERO_JOURNEY"))
        self.assertEqual((bounty.popup, bounty.intel.get("mission_type")), ("INTEL_MASTER_BOUNTY", "MASTER_BOUNTY"))
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(hero, v2_registry()).skill, "BACK")
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(bounty, v2_registry()).skill, "BACK")

    def test_current_client_firebeast_chain_has_distinct_semantics(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
        available = vision.observe(ROOT / "dataset" / "raw" / "live_intel_claw4_claim_20260907" / "step_003_after.png")
        dialog = vision.observe(ROOT / "dataset" / "raw" / "live_intel_orange_goat_probe_20260907.png")
        target = vision.observe(ROOT / "dataset" / "raw" / "live_intel_blazing_behemoth_target_20260907.png")
        march = vision.observe(ROOT / "dataset" / "raw" / "live_intel_blazing_behemoth_dispatch_20260907" / "step_002_before.png")

        self.assertEqual((available.page, available.intel.get("mission_type")), (Page.INTEL, "FIREBEAST"))
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(available, v2_registry()).skill, "SELECT_INTEL_FIREBEAST_MISSION")
        self.assertEqual((dialog.popup, dialog.intel.get("mission_id")), ("INTEL_BEAST_MISSION", "INTEL_FIREBEAST_10"))
        self.assertEqual((target.page, target.beast.get("name"), target.beast.get("recommended_power")), (Page.BEAST, "炽红巨兽", 1467020))
        self.assertTrue(verify_intel_mission_selected(available, dialog).ok)
        self.assertTrue(verify_intel_target_open(dialog, target).ok)
        self.assertTrue(verify_intel_beast_march_open(target, march).ok)

    def test_firebeast_card_does_not_replace_ordinary_beast_or_master_bounty(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
        ordinary = vision.observe(ROOT / "dataset" / "raw" / "live_intel_beast10_target_current.png")
        bounty = vision.observe(ROOT / "dataset" / "raw" / "live_intel_master_bounty_target_probe.png")
        self.assertEqual(ordinary.beast.get("mission_id"), "INTEL_BEAST_10")
        self.assertEqual(bounty.intel.get("mission_type"), "MASTER_BOUNTY")

    def test_live_rescue_survivors_chain_is_structured_and_verified(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
        available = vision.observe(ROOT / "dataset" / "raw" / "live_intel_firebeast2_claim_20260907" / "step_004_before.png")
        dialog = vision.observe(ROOT / "dataset" / "raw" / "live_intel_orange_tent_probe_20260907.png")
        target = vision.observe(ROOT / "dataset" / "raw" / "live_intel_rescue_survivors_target_20260907.png")
        active = vision.observe(ROOT / "dataset" / "raw" / "live_intel_rescue_survivors_execute_20260907.png")

        self.assertEqual(RuleBrain(current_goal="INTEL").decide(available, v2_registry()).skill, "SELECT_INTEL_RESCUE_SURVIVORS")
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(dialog, v2_registry()).skill, "OPEN_INTEL_RESCUE_SURVIVORS_TARGET")
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(target, v2_registry()).skill, "EXECUTE_INTEL_RESCUE_SURVIVORS")
        self.assertEqual(active.intel.get("status"), "IN_PROGRESS")
        self.assertTrue(verify_intel_rescue_selected(available, dialog).ok)
        self.assertTrue(verify_intel_rescue_target_open(dialog, target).ok)
        self.assertTrue(verify_intel_rescue_started(target, active).ok)

    def test_master_bounty_power_gate_and_hero_failure_are_live_facts(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json")
        bounty = vision.observe(ROOT / "dataset" / "raw" / "live_intel_master_bounty_target_probe.png")
        failed = vision.observe(ROOT / "dataset" / "raw" / "live_intel_hero_journey_progress.png")

        self.assertEqual(bounty.page, Page.BEAST)
        self.assertFalse(bounty.beast.get("available"))
        self.assertEqual(bounty.beast.get("blocked_reason"), "POWER_BELOW_RECOMMENDED")
        self.assertEqual(failed.page, Page.MAP)
        self.assertEqual(failed.intel.get("failure"), "BATTLE_FAILED")
