import unittest

from winter_agent_v2.attempt_controller import AttemptState, attempt_priority
from winter_agent_v2.game_understanding import (
    EventAdapter, GoalContribution, Mechanism, ResourcePosition,
    action_utility, missing_mechanism_skills, save_or_spend,
)


class GameUnderstandingTests(unittest.TestCase):
    def test_resource_reserves_are_protected(self):
        position = ResourcePosition("FIRE_CRYSTAL", 100, reserved=20, event_reserved=30, rare_reserved=10)
        self.assertEqual(position.safe_to_spend, 40)
        self.assertTrue(save_or_spend(position, 40).allowed)
        self.assertFalse(save_or_spend(position, 41).allowed)
        self.assertFalse(save_or_spend(position, 1, real_money=True).allowed)

    def test_one_action_can_advance_multiple_goals(self):
        score = action_utility((GoalContribution("TRAIN", 1, 80), GoalContribution("EVENT", 2, 500, 2)),
                               resource_opportunity_cost=20, risk=10, time_cost=5)
        self.assertEqual(score, 2045)

    def test_adapter_reuses_skills_and_reports_only_gaps(self):
        adapter = EventAdapter("BEAR", (Mechanism.RALLY, Mechanism.COOLDOWN_TIMER),
                               {"START_RALLY":{"target":"BEAR"}, "JOIN_RALLY":{"target":"BEAR"}})
        self.assertTrue(adapter.validates(("START_RALLY", "JOIN_RALLY")))
        self.assertEqual(missing_mechanism_skills(adapter.mechanisms, ("START_RALLY", "JOIN_RALLY")), ("READ_TIMER",))

    def test_expiring_free_attempts_outrank_non_expiring(self):
        urgent = attempt_priority(AttemptState("ARENA", 5, 1800))
        normal = attempt_priority(AttemptState("ARENA", 5, 90000))
        self.assertGreater(urgent, normal)


if __name__ == "__main__":
    unittest.main()
