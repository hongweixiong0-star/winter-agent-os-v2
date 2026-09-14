import unittest

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.verifier import verify_popup_closed


class PopupVerifierTests(unittest.TestCase):
    def test_purchase_popup_close_is_verified_without_accepting_purchase(self):
        before = WorldState(page=Page.POPUP, popup="PURCHASE_POPUP", confidence=0.99)
        # 关闭后的落点必须是已知页面。UNKNOWN 不再被当作“关闭成功”，
        # 见 docs/COMMAND_CENTER_UPGRADE_REPORT.md 的 UNKNOWN 验证规则。
        after = WorldState(page=Page.HOME, popup=None, confidence=0.99)
        self.assertTrue(verify_popup_closed(before, after).ok)

    def test_unknown_after_state_does_not_prove_popup_close(self):
        before = WorldState(page=Page.POPUP, popup="PURCHASE_POPUP", confidence=0.99)
        after = WorldState(page=Page.UNKNOWN, popup=None, confidence=0.0)
        self.assertFalse(verify_popup_closed(before, after).ok)

    def test_same_popup_is_not_closed(self):
        state = WorldState(page=Page.POPUP, popup="PURCHASE_POPUP", confidence=0.99)
        self.assertFalse(verify_popup_closed(state, state).ok)

    def test_close_popup_is_in_single_live_verifier_gate(self):
        self.assertIn("CLOSE_POPUP", LiveRuntime.VERIFIED_ATOMIC)


if __name__ == "__main__":
    unittest.main()
