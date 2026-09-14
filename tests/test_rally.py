import unittest

from winter_agent_v2.models import WorldState
from winter_agent_v2.rally import (
    BearPhase, BearRole, RallyRow, RallyRowState, RallyTarget, bear_phase,
    body_hero_order, choose_bear_operation, fastest_joinable_bear,
)


class RallyPolicyTests(unittest.TestCase):
    def test_bear_start_uses_special_slot_even_when_normal_slots_busy(self):
        world = WorldState(march_used=6, march_max=6, normal_march_slots=6,
                           normal_idle_slots=0, bear_rally_special_slot=True,
                           bear_rally_special_available=True)
        self.assertEqual(choose_bear_operation(world, BearRole.LEADER, ()), "START_RALLY")

    def test_join_requires_normal_idle_slot_and_skips_full(self):
        full = RallyRow(RallyTarget.BEAR, "a", RallyRowState.FULL, 5, 15, 15)
        open_row = RallyRow(RallyTarget.BEAR, "b", RallyRowState.JOINABLE, 7, 10, 15)
        self.assertIsNone(choose_bear_operation(WorldState(normal_idle_slots=0), BearRole.JOINER, (open_row,)))
        self.assertEqual(choose_bear_operation(WorldState(normal_idle_slots=1), BearRole.JOINER, (full, open_row)), "JOIN_RALLY")
        self.assertEqual(fastest_joinable_bear((full, open_row)), open_row)

    def test_body_hero_falls_back_to_no_hero(self):
        self.assertEqual(body_hero_order([]), ("NO_HERO",))
        self.assertEqual(body_hero_order(["JASSER", "JESSIE"]), ("JESSIE", "JASSER", "NO_HERO"))

    def test_bear_deadline_phases(self):
        self.assertEqual(bear_phase(None, 601, None), BearPhase.SCHEDULED)
        self.assertEqual(bear_phase(None, 600, None), BearPhase.PREPARING)
        self.assertEqual(bear_phase(None, 120, None), BearPhase.READY)
        self.assertEqual(bear_phase("ACTIVE", None, 900), BearPhase.ACTIVE)
        self.assertEqual(bear_phase("COOLDOWN", None, 0), BearPhase.FINISHED)


if __name__ == "__main__":
    unittest.main()
