"""BEAST_HUNT map-scan branch (2026-09-17 escalation).

Live 2026-09-17: with goal BEAST_HUNT on PAGE_MAP and no verified target in the
viewport, the brain answered SAFE_STOP verified_beast_target_not_visible on the
first observation, the run ended, and no beast was ever dispatched.  The fix is
a bounded viewport pan (SCAN_MAP_FOR_BEAST) before the honest stop.

2026-09-21 -- the order changed, on purpose.  The pan was the first response and
it never converged: its own record says the species templates matched nothing on
23 frames because a pan searches bare snow, and it has no way to *fly* to a
target.  The client ships a better answer -- its own beast search -- so the route
now asks the client first and pans only after the search has been spent:

    SEARCH_RESOURCE (open the panel)
      -> OPEN_BEAST_SEARCH_TAB (select 冰原巨兽)
      -> SUBMIT_BEAST_SEARCH (client locates and centres a beast)
      -> SCAN_MAP_FOR_BEAST x max_beast_scans (the old method, still bounded)
      -> SAFE_STOP verified_beast_target_not_visible

The scan branch itself is unchanged and its budget still bounds it; only what
comes before it moved.  ``_map_without_target`` below therefore now walks the
search hops first, which is what the run does on a bare map.
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


def _search_panel_on_beast_tab() -> WorldState:
    """The frame the 搜索 tap is issued from: panel open, beast tab selected."""
    return WorldState(
        page=Page.MAP,
        march_used=0,
        resource_search_open=True,
        resource_beast_tab=True,
        confidence=0.99,
    )


class BeastScanBranchTests(unittest.TestCase):
    def test_first_observation_without_target_opens_the_clients_search(self):
        """The first move on a bare map is the search, not a pan.

        A pan moves the camera one viewport and cannot know whether the beast is
        nearby; the search asks the client, which does know.  Running the pan
        first would spend the budget on the method with no convergence.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        decision = brain.decide(_map_without_target(), v2_registry())
        self.assertEqual(decision.skill, "SEARCH_RESOURCE")

    def test_the_search_is_walked_before_any_pan(self):
        """Open panel -> beast tab -> submit, and only then the scans."""
        brain = RuleBrain(current_goal="BEAST_HUNT")
        opened = brain.decide(_map_without_target(), v2_registry())
        self.assertEqual(opened.skill, "SEARCH_RESOURCE")

        panel_wrong_tab = WorldState(
            page=Page.MAP, march_used=0, resource_search_open=True, confidence=0.99
        )
        tab = brain.decide(panel_wrong_tab, v2_registry())
        self.assertEqual(tab.skill, "OPEN_BEAST_SEARCH_TAB")

        submit = brain.decide(_search_panel_on_beast_tab(), v2_registry())
        self.assertEqual(submit.skill, "SUBMIT_BEAST_SEARCH")
        self.assertTrue(brain.beast_search_used)

        # Only now does the old pan method get its turn.
        pan = brain.decide(_map_without_target(), v2_registry())
        self.assertEqual(pan.skill, "SCAN_MAP_FOR_BEAST")

    def test_the_search_is_spent_once_and_then_the_pan_budget_bounds(self):
        """Neither the search nor the pan may become an endless loop."""
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.decide(_map_without_target(), v2_registry())
        brain.decide(_search_panel_on_beast_tab(), v2_registry())
        self.assertTrue(brain.beast_search_used)
        # The submit is never issued twice; the pan budget is what runs now.
        for _ in range(brain.max_beast_scans):
            self.assertEqual(
                brain.decide(_map_without_target(), v2_registry()).skill,
                "SCAN_MAP_FOR_BEAST",
            )
        stop = brain.decide(_map_without_target(), v2_registry())
        self.assertEqual(stop.skill, "SAFE_STOP")
        self.assertEqual(stop.reason, "verified_beast_target_not_visible")

    def test_the_panel_is_left_once_before_the_pan_budget_applies(self):
        """搜索 leaves the panel up on the beast tab, so one Back reaches the map.

        The Back must be one-shot: if it did not move the client, repeating it
        would ping-pong between the panel and the map spending an action each way.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.decide(_map_without_target(), v2_registry())
        brain.decide(_search_panel_on_beast_tab(), v2_registry())
        panel_still_up = _search_panel_on_beast_tab()
        self.assertEqual(brain.decide(panel_still_up, v2_registry()).skill, "BACK")
        self.assertTrue(brain.beast_search_panel_left)
        # A second panel frame is never a second Back: the pan budget applies now.
        self.assertEqual(
            brain.decide(panel_still_up, v2_registry()).skill, "SCAN_MAP_FOR_BEAST"
        )

    def test_scan_is_bounded_and_then_stops_with_the_named_reason(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        # Spend the search first, so the pan budget is what this test measures.
        brain.decide(_map_without_target(), v2_registry())
        brain.decide(_search_panel_on_beast_tab(), v2_registry())
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
        # The search ticket is cleared with the pan budget, so a *later* beast in
        # the same run can use the client's search again.
        self.assertFalse(brain.beast_search_used)

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
