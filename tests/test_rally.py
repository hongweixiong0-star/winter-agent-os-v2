import unittest

from winter_agent_v2.models import WorldState
from winter_agent_v2.rally import (
    BearPhase, BearRole, RallyRow, RallyRowState, RallyTarget, bear_phase,
    choose_bear_operation, choose_rally_operation,
    fastest_joinable_bear, fastest_joinable_for, body_hero_order,
    rally_target_for_goal, read_rally_list_image, select_join_candidates,
)


class Token:
    def __init__(self, text, x, y):
        self.text = text
        self.centre = (x, y)
        self.box = ((x - 20, y - 10), (x + 20, y - 10), (x + 20, y + 10), (x - 20, y + 10))


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

    def test_shared_rally_operation_accepts_an_explicit_target(self):
        polar_row = RallyRow(
            RallyTarget.POLAR_TERROR, "a", RallyRowState.JOINABLE,
            remaining_seconds=45, capacity_used=2, capacity_max=15,
        )
        world = WorldState(normal_idle_slots=1, bear_rally_special_available=True)

        self.assertTrue(polar_row.joinable_for("POLAR_TERROR"))
        self.assertFalse(polar_row.joinable_for(RallyTarget.UNKNOWN))
        self.assertFalse(polar_row.joinable, "legacy Bear-only property must remain scoped to Bear")
        self.assertEqual(fastest_joinable_for((polar_row,), RallyTarget.POLAR_TERROR), polar_row)
        self.assertIsNone(fastest_joinable_bear((polar_row,)))
        self.assertEqual(
            choose_rally_operation(world, BearRole.JOINER, (polar_row,), target=RallyTarget.POLAR_TERROR),
            "JOIN_RALLY",
        )
        self.assertEqual(
            choose_rally_operation(
                world, BearRole.LEADER, (), target=RallyTarget.POLAR_TERROR, start_available=True
            ),
            "START_RALLY",
        )
        self.assertIsNone(
            choose_rally_operation(world, BearRole.LEADER, (), target=RallyTarget.POLAR_TERROR),
            "Bear's special-slot state must not imply that another target can start",
        )

    def test_goal_context_supplies_rally_target_without_guessing_unknown_goals(self):
        self.assertEqual(
            rally_target_for_goal("PARTICIPATE_BEAR", {}),
            RallyTarget.BEAR,
        )
        self.assertEqual(
            rally_target_for_goal("PARTICIPATE_POLAR_TERROR", {"rally_target": "POLAR_TERROR"}),
            RallyTarget.POLAR_TERROR,
        )
        self.assertEqual(
            rally_target_for_goal("JOIN_POLAR_TERROR_RALLY", {}),
            RallyTarget.POLAR_TERROR,
        )
        self.assertIsNone(rally_target_for_goal("UNRELATED_GOAL", {}))
        self.assertIsNone(
            rally_target_for_goal("PARTICIPATE_POLAR_TERROR", {"rally_target": "UNKNOWN"})
        )

    def test_rally_list_reader_keeps_icefield_beast_target_distinct(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (720, 1280), (0, 0, 0))
        ImageDraw.Draw(image).rectangle((610, 250, 665, 305), fill=(0, 255, 0))
        reading = read_rally_list_image(
            image,
            (
                Token("集结中 00:00:45", 200, 200),
                Token("冰原巨兽", 300, 260),
                Token("2/15", 300, 300),
            ),
        )

        self.assertEqual(len(reading.rows), 1)
        row = reading.rows[0]
        self.assertEqual(row.target_type, RallyTarget.POLAR_TERROR)
        self.assertTrue(row.joinable_for(RallyTarget.POLAR_TERROR))
        self.assertEqual(reading.joinable_for(RallyTarget.POLAR_TERROR), (row,))
        self.assertEqual(reading.joinable_bears(), ())
        self.assertEqual(select_join_candidates(reading, RallyTarget.POLAR_TERROR), (row,))
        self.assertEqual(select_join_candidates(reading, RallyTarget.UNKNOWN), ())


if __name__ == "__main__":
    unittest.main()
