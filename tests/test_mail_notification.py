import unittest
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_mail_read_or_claim, verify_mail_claim_feedback


class MailNotificationTests(unittest.TestCase):
    def test_read_notification_does_not_prove_reward(self):
        before = WorldState(page=Page.MAIL, mail={"active_tab":"REPORT", "tab_badges":{"REPORT":1}})
        after = WorldState(page=Page.MAIL, mail={"status":"CLAIMED", "tab_badges":{}, "badge_count":0})
        result = verify_mail_read_or_claim(before, after)
        self.assertTrue(result.ok)
        self.assertFalse(result.evidence["reward_verified"])
        self.assertFalse(verify_mail_claim_feedback(before, after).ok)

    def test_unknown_or_remaining_badge_is_not_read_success(self):
        before = WorldState(page=Page.MAIL, mail={"active_tab":"REPORT", "tab_badges":{"REPORT":1}})
        for after in (WorldState(), before, WorldState(page=Page.MAIL, mail={"status":"CLAIMED"})):
            self.assertFalse(verify_mail_read_or_claim(before, after).ok)

    def test_mail_goal_claims_contextual_generic_reward_feedback(self):
        before = WorldState(page=Page.MAIL, mail={"active_tab":"REPORT", "tab_badges":{"REPORT":64}})
        reward = WorldState(page=Page.POPUP, popup="INTEL_REWARD", intel={"claim_feedback":True})
        self.assertTrue(verify_mail_read_or_claim(before, reward).ok)
        self.assertEqual(RuleBrain(current_goal="MAIL").decide(reward, v2_registry()).skill, "DISMISS_MAIL_GENERIC_REWARD")
