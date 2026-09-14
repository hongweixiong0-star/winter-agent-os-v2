import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import HybridVision, OCRService
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_exploration_claim_confirmed, verify_exploration_claim_feedback, verify_exploration_idle_claim, verify_exploration_reward_dismissed, verify_mail_alliance_tab_selected, verify_mail_claim, verify_mail_claim_feedback, verify_mail_read_or_claim, verify_mail_reward_dismissed, verify_mail_system_tab_selected, verify_open_exploration, verify_open_mail
from winter_agent_v2.vision import ReplayVision, SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]


class RewardClaimVerifierTests(unittest.TestCase):
    def test_mail_context_accepts_shared_known_reward_overlay(self):
        before = WorldState(page=Page.MAIL, mail={"active_tab":"ALLIANCE", "tab_badges":{"ALLIANCE":6}})
        after = WorldState(page=Page.POPUP, popup="DAILY_REWARD", daily={"claim_feedback":True})
        self.assertTrue(verify_mail_claim_feedback(before, after).ok)

    def test_mail_badge_reduction_proves_notification_processing(self):
        before = WorldState(page=Page.MAIL, mail={"status":"CLAIMABLE", "badge_count":8, "tab_badges":{"WAR":3,"ALLIANCE":4,"SYSTEM":1}})
        after = WorldState(page=Page.MAIL, mail={"status":"CLAIMABLE", "badge_count":4, "tab_badges":{"WAR":3,"SYSTEM":1}})
        result = verify_mail_read_or_claim(before, after)
        self.assertTrue(result.ok)
        self.assertFalse(result.evidence["reward_verified"])

    def test_current_alliance_mail_clear_template_rejects_red_badge_state(self):
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        before = vision.observe(ROOT / "dataset/raw/live_20260908_next_batch_current.png")
        after = vision.observe(ROOT / "dataset/raw/live_20260908_next_batch_mail_v2/step_001_after_refresh_2.png")
        self.assertNotEqual(before.mail.get("status"), "CLAIMED")
        self.assertEqual(after.mail.get("status"), "CLAIMED")

    def setUp(self):
        self.vision = ReplayVision(ROOT / "tests/replay/labels.json")

    def state(self, name):
        return self.vision.observe(ROOT / "dataset/raw" / name)

    def test_live_mail_incremental_reward_and_all_tabs_clear(self):
        before = self.state("live_mail_incremental_entry.png")
        reward = self.state("live_mail_incremental_cleared.png")
        after = self.state("live_mail_incremental_all_clear.png")
        result = verify_mail_claim(before, reward, after)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(RuleBrain().decide(before, v2_registry()).skill, "MAIL_CLAIM_REWARDS")

    def test_mail_unread_without_reward_popup_is_not_success(self):
        before = self.state("live_mail_incremental_entry.png")
        after = self.state("live_mail_incremental_all_clear.png")
        self.assertFalse(verify_mail_claim(before, after, after).ok)

    def test_live_exploration_idle_income_cycle(self):
        before = self.state("live_exploration_red_dot.png")
        reward = self.state("live_exploration_claim_verified.png")
        after = self.state("live_exploration_after_claim.png")
        result = verify_exploration_idle_claim(before, reward, after)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(RuleBrain().decide(before, v2_registry()).skill, "EXPLORATION_IDLE_CLAIM")

    def test_exploration_requires_post_claim_disabled_state(self):
        before = self.state("live_exploration_red_dot.png")
        reward = self.state("live_exploration_claim_verified.png")
        self.assertFalse(verify_exploration_idle_claim(before, reward, before).ok)

    def test_current_live_exploration_three_step_claim_flow(self):
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        # 原入口帧在 retention 清理的会话目录里，已改用长期保留的引导帧。
        home = vision.observe(ROOT / "dataset/raw/live_home_after_bootstrap.png")
        opened = vision.observe(ROOT / "dataset/raw/live_deploy_exploration_claim_v3/step_001_before.png")
        dialog = vision.observe(ROOT / "dataset/raw/live_deploy_exploration_claim_v3/step_001_after.png")
        reward = vision.observe(ROOT / "dataset/raw/live_deploy_exploration_claim_v4/step_001_after.png")
        claimed = vision.observe(ROOT / "dataset/raw/live_deploy_exploration_claim_v5/step_001_after_refresh_2.png")
        self.assertTrue(verify_open_exploration(home, opened).ok)
        self.assertTrue(verify_exploration_claim_feedback(opened, dialog).ok)
        self.assertTrue(verify_exploration_claim_confirmed(dialog, reward).ok)
        self.assertTrue(verify_exploration_reward_dismissed(reward, claimed).ok)
        self.assertEqual(RuleBrain(current_goal="EXPLORATION").decide(dialog, v2_registry()).skill, "CONFIRM_EXPLORATION_IDLE_CLAIM")

    def test_live_mail_and_exploration_templates_emit_world_state(self):
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        mail = vision.observe(ROOT / "dataset/raw/live_mail_incremental_entry.png")
        mail_clear = vision.observe(ROOT / "dataset/raw/live_mail_incremental_all_clear.png")
        exploration = vision.observe(ROOT / "dataset/raw/live_exploration_red_dot.png")
        exploration_clear = vision.observe(ROOT / "dataset/raw/live_exploration_after_claim.png")
        self.assertEqual((mail.page.value, mail.mail["status"]), ("MAIL", "CLAIMABLE"))
        self.assertEqual((mail_clear.page.value, mail_clear.mail["status"]), ("MAIL", "CLAIMED"))
        self.assertEqual((exploration.page.value, exploration.exploration["status"]), ("EXPLORATION", "CLAIMABLE"))
        self.assertEqual((exploration_clear.page.value, exploration_clear.exploration["status"]), ("EXPLORATION", "CLAIMED"))

    def test_current_mail_badge_detector_and_planner_clear_each_tab(self):
        class EmptyBackend:
            name = "empty"
            def recognize(self, _image):
                return ()

        semantic = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        vision = HybridVision(semantic, OCRService(EmptyBackend()))
        report = vision.observe(ROOT / "dataset/raw/live_mail_navigation_current_20260907.png")
        after_report = vision.observe(ROOT / "dataset/raw/live_mail_after_report_claim_20260907.png")
        alliance = vision.observe(ROOT / "dataset/raw/live_mail_alliance_before_claim_20260907.png")
        system = vision.observe(ROOT / "dataset/raw/live_mail_system_before_claim_20260907.png")
        clear = vision.observe(ROOT / "dataset/raw/live_mail_all_clear_20260907.png")

        self.assertEqual((report.mail["active_tab"], set(report.mail["tab_badges"])), ("REPORT", {"ALLIANCE", "SYSTEM", "REPORT"}))
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(report, v2_registry()).skill, "MAIL_CLAIM_REWARDS")
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(after_report, v2_registry()).skill, "SELECT_MAIL_ALLIANCE_TAB")
        self.assertTrue(verify_mail_alliance_tab_selected(after_report, alliance).ok)
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(alliance, v2_registry()).skill, "MAIL_CLAIM_REWARDS")
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(system, v2_registry()).skill, "MAIL_CLAIM_REWARDS")
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(clear, v2_registry()).skill, "SAFE_STOP")
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(clear, v2_registry()).reason, "mail_all_clear")

    def test_mail_atomic_navigation_claim_and_dismiss_verifiers(self):
        home = WorldState(page=Page.HOME, confidence=0.99)
        mail = WorldState(page=Page.MAIL, mail={"status":"CLAIMABLE", "active_tab":"SYSTEM", "tab_badges":{"SYSTEM":5}}, confidence=0.99)
        reward = WorldState(page=Page.POPUP, popup="MAIL_REWARD", mail={"claim_feedback":True}, confidence=0.99)
        self.assertTrue(verify_open_mail(home, mail).ok)
        self.assertTrue(verify_mail_system_tab_selected(WorldState(page=Page.MAIL, mail={"tab_badges":{"SYSTEM":5}}), mail).ok)
        self.assertTrue(verify_mail_claim_feedback(mail, reward).ok)
        self.assertTrue(verify_mail_reward_dismissed(reward, mail).ok)
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(home, v2_registry()).skill, "OPEN_MAIL")
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(reward, v2_registry()).skill, "DISMISS_MAIL_REWARD")


if __name__ == "__main__":
    unittest.main()
