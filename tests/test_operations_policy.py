import unittest

from winter_agent_v2.operations_policy import (
    choose_healing, choose_resource_balanced, choose_shield,
    choose_stamina_goal, choose_troop_rotation, operational_priority, reward_candidates,
)


class OperationsPolicyTests(unittest.TestCase):
    def test_four_resource_balance_uses_deficit_then_history(self):
        self.assertEqual(choose_resource_balanced({"MEAT": 8, "WOOD": 9, "COAL": 2, "IRON": 7}).parameters["resource"], "COAL")
        self.assertEqual(choose_resource_balanced({}, {"MEAT": 2, "WOOD": 2, "COAL": 1, "IRON": 2}).parameters["resource"], "COAL")

    def test_three_troop_rotation_skips_busy_and_balances(self):
        result = choose_troop_rotation({"INFANTRY": True}, {"LANCER": 20, "MARKSMAN": 5})
        self.assertEqual(result.parameters["troop_type"], "MARKSMAN")

    def test_stamina_intel_then_giant_then_beast(self):
        self.assertEqual(choose_stamina_goal(31, "AVAILABLE", True, True).goal, "INTEL")
        self.assertEqual(choose_stamina_goal(31, "NOT_AVAILABLE", True, True).goal, "GIANT_BEAST")
        self.assertEqual(choose_stamina_goal(31, "NOT_AVAILABLE", False, True).goal, "BEAST_HUNT")
        self.assertEqual(choose_stamina_goal(30, "AVAILABLE", True, True).goal, "NONE")

    def test_shield_requires_verified_attack_and_free_inventory(self):
        self.assertEqual(choose_shield(True, 100001, {"8H": 1, "2H": 1}).parameters["duration"], "8H")
        self.assertTrue(choose_shield(True, 100001, {}).blocked)
        self.assertEqual(choose_shield(False, 999999, {"8H": 1}).goal, "NONE")

    def test_healing_batches_and_red_dot_is_not_authority(self):
        heal = choose_healing(6000, 100000)
        self.assertEqual(heal.goal, "HEAL_BATCH")
        self.assertGreaterEqual(heal.parameters["batch"], 500)
        self.assertLessEqual(heal.parameters["batch"], 1000)
        self.assertEqual(reward_candidates(["MAIL", "UNKNOWN", "EVENT"], {"MAIL", "EVENT"}), ("MAIL", "EVENT"))

    def test_single_scheduler_priority_defense_then_heal_then_stamina(self):
        shield = operational_priority("ACTIVATE_SHIELD", defense={"incoming_attack": True, "incoming_troops": 100001}, hospital={}, stamina={})
        heal = operational_priority("HEAL_BATCH", defense={}, hospital={"wounded": 6000, "capacity": 100000}, stamina={})
        stamina = operational_priority("INTEL", defense={}, hospital={}, stamina={"current": 200})
        self.assertGreater(shield, heal)
        self.assertGreater(heal, stamina)


if __name__ == "__main__":
    unittest.main()
