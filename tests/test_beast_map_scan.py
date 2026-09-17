"""BEAST_HUNT map-scan branch (2026-09-17 escalation).

Live 2026-09-17: with goal BEAST_HUNT on PAGE_MAP and no verified target in the
viewport, the brain answered SAFE_STOP verified_beast_target_not_visible on the
first observation, the run ended, and no beast was ever dispatched.  The fix is
a bounded viewport pan (SCAN_MAP_FOR_BEAST) before the honest stop.
"""
from __future__ import annotations

import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_beast_scan_observed


def _map_without_target() -> WorldState:
    return WorldState(page=Page.MAP, march_used=0, confidence=0.99)


class BeastScanBranchTests(unittest.TestCase):
    def test_first_observation_without_target_pans_instead_of_stopping(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        decision = brain.decide(_map_without_target(), v2_registry())
        self.assertEqual(decision.skill, "SCAN_MAP_FOR_BEAST")
        self.assertEqual(decision.reason, "verified_beast_target_not_visible_scanning_map")

    def test_scan_is_bounded_and_then_stops_with_the_named_reason(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        world = _map_without_target()
        for _ in range(brain.max_beast_scans):
            self.assertEqual(brain.decide(world, v2_registry()).skill, "SCAN_MAP_FOR_BEAST")
        stop = brain.decide(world, v2_registry())
        self.assertEqual(stop.skill, "SAFE_STOP")
        self.assertEqual(stop.reason, "verified_beast_target_not_visible")

    def test_found_target_resets_the_scan_budget(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        world = _map_without_target()
        brain.decide(world, v2_registry())
        target = WorldState(page=Page.MAP, beast={"visible_target": "MUSK_OX", "level": 9, "available": True}, confidence=0.99)
        self.assertEqual(brain.decide(target, v2_registry()).skill, "SELECT_BEAST_TARGET")
        self.assertEqual(brain.beast_scans_used, 0)

    def test_scan_verifier_accepts_only_a_readable_map(self):
        before = _map_without_target()
        self.assertTrue(verify_beast_scan_observed(before, WorldState(page=Page.MAP, march_used=0, confidence=0.99)).ok)
        self.assertFalse(verify_beast_scan_observed(before, WorldState(page=Page.UNKNOWN, confidence=0.0)).ok)
        self.assertFalse(verify_beast_scan_observed(WorldState(page=Page.HOME, confidence=0.98), WorldState(page=Page.MAP, confidence=0.99)).ok)

    def test_scan_skill_is_registered_and_bound_for_live_dispatch(self):
        registry = v2_registry()
        skill = registry.get("SCAN_MAP_FOR_BEAST")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.action.kind, "SWIPE")
        self.assertIs(skill.required_page, Page.MAP)
        self.assertIn("SCAN_MAP_FOR_BEAST", LiveRuntime.VERIFIED_ATOMIC)


if __name__ == "__main__":
    unittest.main()
