from __future__ import annotations

import unittest

from winter_agent_v2.models import Action
from winter_agent_v2.policy import SafetyPolicy
from winter_agent_v2.recovery import FailureType, Recovery, RecoveryAction


class FailureMatrixTests(unittest.TestCase):
    def test_all_required_failures_have_bounded_recovery(self) -> None:
        for failure in FailureType:
            recovery = Recovery(max_retries=2)
            first = recovery.decide("GATHER_RESOURCE", failure)
            second = recovery.decide("GATHER_RESOURCE", failure)
            third = recovery.decide("GATHER_RESOURCE", failure)
            self.assertLessEqual(second.retry_count, 2)
            self.assertTrue(third.blocked or first.blocked)

    def test_qwen_busy_falls_back_before_block(self) -> None:
        recovery = Recovery()
        self.assertEqual(recovery.decide("GATHER_RESOURCE", FailureType.QWEN_BUSY).action, RecoveryAction.FALLBACK_RULE)

    def test_no_march_switches_task_immediately(self) -> None:
        result = Recovery().decide("GATHER_RESOURCE", FailureType.NO_MARCH)
        self.assertTrue(result.blocked)
        self.assertEqual(result.action, RecoveryAction.SWITCH_TASK)

    def test_hard_safety_actions_are_blocked(self) -> None:
        policy = SafetyPolicy()
        for kind in SafetyPolicy.BLOCKED_KINDS:
            self.assertFalse(policy.evaluate(Action(kind)).allowed)

    def test_game_resources_are_allowed(self) -> None:
        policy = SafetyPolicy()
        for kind in ("SPEND_GEMS", "SPEND_ITEM", "SPEND_SPEEDUP", "SPEND_ADVANCED_RESOURCE"):
            self.assertTrue(policy.evaluate(Action(kind)).allowed)

    def test_real_money_purchase_is_blocked(self) -> None:
        action = Action("PURCHASE", payload={"currency":"CNY", "amount":30})
        self.assertFalse(SafetyPolicy().evaluate(action).allowed)
