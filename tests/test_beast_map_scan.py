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
      -> OPEN_BEAST_SEARCH_TAB (select the client's 野兽 tab, i.e. the ordinary
         solo-attack one -- NOT 冰原巨兽, which is the rally target)
      -> SUBMIT_BEAST_SEARCH (client locates and centres a beast)
      -> SCAN_MAP_FOR_BEAST x max_beast_scans (the old method, still bounded)
      -> SAFE_STOP verified_beast_target_not_visible

The scan branch itself is unchanged and its budget still bounds it; only what
comes before it moved.  ``_map_without_target`` below therefore now walks the
search hops first, which is what the run does on a bare map.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_beast_scan_observed


def _map_without_target() -> WorldState:
    return WorldState(page=Page.MAP, march_used=0, confidence=0.99)


def _search_panel_on_beast_tab() -> WorldState:
    """The frame the 搜索 tap is issued from: panel open, ordinary beast tab read.

    ``resource_beast_tab_norm`` is the label-derived field, and it is what the route keys on.
    The bool ``resource_beast_tab`` is not enough: it is true for a panel showing either monster
    tab, and the rally tab's cards offer no solo 攻击 -- measured on the level-5 mammoth.  The
    fixture carries both so a change that reintroduces the conflated reading fails here.
    """
    return WorldState(
        page=Page.MAP,
        march_used=0,
        resource_search_open=True,
        resource_beast_tab=True,
        resource_tab_kinds=("BEAST", "COAL", "GIANT_BEAST", "MEAT", "WOOD"),
        resource_beast_tab_norm=(0.058, 0.740),
        resource_giant_beast_tab_norm=(0.276, 0.740),
        confidence=0.99,
    )


def _search_panel_on_the_rally_tab_only() -> WorldState:
    """The client's other monster tab, with no ordinary 野兽 tab drawn.

    Measured 2026-09-21: this is the layout the archived ``beast_tab.png`` frames actually
    have -- 冰原巨兽 leftmost and no 野兽 tab at all.  Its targets are the rally ones, so the
    route must decline rather than tap it and search for something it cannot solo.
    """
    return WorldState(
        page=Page.MAP,
        march_used=0,
        resource_search_open=True,
        resource_beast_tab=True,
        resource_tab_kinds=("COAL", "GIANT_BEAST", "IRON", "MEAT", "WOOD"),
        resource_giant_beast_tab_norm=(0.066, 0.740),
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


class TheSearchActuallyReachesADispatchTests(unittest.TestCase):
    """The search is only worth walking if a found beast is then hunted.

    The operator's requirement is a *real dispatch* that keeps going afterwards --
    "完成一次真实出征后继续下一次，不得首次成功即停止" -- so it is not enough for
    the search hops to be right in isolation.  This walks the whole route on the
    frames the client actually produces:

        bare map -> SEARCH_RESOURCE -> OPEN_BEAST_SEARCH_TAB -> SUBMIT_BEAST_SEARCH
                 -> the client centres a beast -> SELECT_BEAST_TARGET_LABELLED
                 -> the card's own verdict -> the march

    and then shows a second beast in the same run takes the same route again.
    """

    def _beast_now_on_the_map(self) -> WorldState:
        """What the frame looks like after the client's search succeeded.

        A level-25 mammoth, which is what the live search returned -- deliberately
        not the pre-approved level-9 musk ox, because the whole point of the labelled
        route is that a species nobody cut a sprite for is still attackable.

        ``visible_target`` carries the species the *frame* named, which is the field the
        route keys identity on (``may_evaluate`` requires it; a bare ``name`` is not
        enough).  The label read is what fills it on a real frame.
        """
        return WorldState(
            page=Page.MAP,
            march_used=0,
            march_max=6,
            stamina={"current": 120, "source": "MAP_HUD"},
            beast={"visible_target": "MAMMOTH", "name": "猛犸象", "level": 25, "available": True},
            confidence=0.99,
        )

    def test_the_search_hands_a_found_beast_to_the_labelled_route(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        # Bare map: the search chain.
        self.assertEqual(brain.decide(_map_without_target(), v2_registry()).skill, "SEARCH_RESOURCE")
        self.assertEqual(brain.decide(WorldState(page=Page.MAP, resource_search_open=True, resource_beast_tab=False, confidence=0.99), v2_registry()).skill, "OPEN_BEAST_SEARCH_TAB")
        self.assertEqual(brain.decide(_search_panel_on_beast_tab(), v2_registry()).skill, "SUBMIT_BEAST_SEARCH")
        # The search found something: the labelled route takes it, not a stop.
        decision = brain.decide(self._beast_now_on_the_map(), v2_registry())
        self.assertEqual(decision.skill, "SELECT_BEAST_TARGET_LABELLED")
        self.assertEqual(decision.reason, "beast_labelled_on_the_map_reading_the_clients_own_verdict")

    def test_a_second_beast_in_the_same_run_still_takes_the_route(self):
        """One success must not close the goal.

        ``beast_search_used`` and the pan budget are cleared when a target is found,
        precisely so the route can be walked again rather than ending on the first
        dispatch.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.decide(_map_without_target(), v2_registry())
        brain.decide(_search_panel_on_beast_tab(), v2_registry())
        brain.decide(self._beast_now_on_the_map(), v2_registry())
        self.assertFalse(brain.beast_search_used, "a found target must return the search ticket")

        # A second bare map in the same run starts the search again from the top.
        brain.beast_search_panel_left = False
        self.assertEqual(brain.decide(_map_without_target(), v2_registry()).skill, "SEARCH_RESOURCE")
        self.assertEqual(brain.decide(_search_panel_on_beast_tab(), v2_registry()).skill, "SUBMIT_BEAST_SEARCH")

    def test_a_target_found_behind_the_still_open_panel_is_selected_not_backed_out_of(self):
        """The panel stays up when the search succeeds, so this is the real frame.

        Measured 2026-09-21 on ``beast5_found.png``: after 搜索 the panel is still
        open on the beast tab and the result card is drawn over it.  The panel-exit
        branch and the target branches therefore both match the same frame, and the
        order between them decides whether the hunt happens at all -- with the exit
        first, the run answers Back and the labelled route that actually opens the
        card and spends the stamina is never reached.  Standing on the panel is fine
        when there is a target to tap; leaving is only right when there is not.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.beast_search_used = True  # the search has been spent
        found = self._beast_now_on_the_map()
        found = WorldState(
            page=Page.MAP,
            march_used=0,
            march_max=6,
            stamina={"current": 120, "source": "MAP_HUD"},
            resource_search_open=True,
            resource_beast_tab=True,
            beast=dict(found.beast),
            confidence=0.99,
        )
        decision = brain.decide(found, v2_registry())
        self.assertEqual(decision.skill, "SELECT_BEAST_TARGET_LABELLED",
                         "a search that found something must not be backed out of")
        self.assertFalse(brain.beast_search_panel_left,
                         "the panel was never left, so a later bare map can still use it")

    def test_a_spent_search_with_nothing_to_show_still_leaves_the_panel(self):
        """The negative control: the exit is still taken when there is no target."""
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.beast_search_used = True
        empty_panel = WorldState(
            page=Page.MAP, march_used=0, resource_search_open=True,
            resource_beast_tab_norm=(0.058, 0.740), confidence=0.99,
        )
        decision = brain.decide(empty_panel, v2_registry())
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.reason, "close_resource_search_for_beast_goal")
        self.assertTrue(brain.beast_search_panel_left)


class OnlyTheOrdinaryBeastTabIsSearchedTests(unittest.TestCase):
    """The two monster tabs are not interchangeable, and the route must not conflate them.

    Measured 2026-09-21: the archived ``beast_tab.png`` frames -- the ones the beast-search
    templates were cut from -- have 冰原巨兽 leftmost and draw no 野兽 tab at all, while the
    live client that day had 野兽 leftmost.  A route whose purpose is a solo kill must target
    ``BEAST``, because the measured level-5 mammoth card on the rally tab offered only 集结.
    """

    def test_the_rally_tab_alone_is_refused_rather_than_searched(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        decision = brain.decide(_search_panel_on_the_rally_tab_only(), v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(
            decision.reason,
            "only_the_rally_beast_tab_is_offered_no_solo_attack_entry",
        )
        self.assertFalse(
            brain.beast_search_used,
            "a refusal must not spend the search ticket: another frame may still offer 野兽",
        )

    def test_a_panel_with_both_tabs_searches_the_ordinary_one(self):
        brain = RuleBrain(current_goal="BEAST_HUNT")
        decision = brain.decide(_search_panel_on_beast_tab(), v2_registry())
        self.assertEqual(decision.skill, "SUBMIT_BEAST_SEARCH")

    def test_the_open_tab_skill_taps_where_the_label_was_read(self):
        """The tap comes from this frame's own label, not a position-pinned template.

        Asserted through the runtime's own resolver, because that is what the executor taps:
        a coordinate that is read off the frame cannot follow the client when the strip
        reorders, and a template pinned to a slot silently taps the wrong tab instead.
        """
        from winter_agent_v2.runtime import LiveRuntime

        panel = _search_panel_on_beast_tab()
        runtime = LiveRuntime(
            device=object(), vision=object(), semantic_vision=object(),
            capture_dir=Path("."), brain=RuleBrain(current_goal="BEAST_HUNT"),
            sleeper=lambda _s: None,
        )
        point = runtime._resolve_semantic_target("BEAST_SEARCH_TAB", panel)
        self.assertEqual(point, panel.resource_beast_tab_norm)
        # The giant-beast tab is a different place, so the two cannot be tapped interchangeably.
        self.assertNotEqual(panel.resource_beast_tab_norm, panel.resource_giant_beast_tab_norm)

    def test_the_resolver_refuses_when_the_panel_is_not_open(self):
        """A stale point must not be reused on a frame that is not showing the strip."""
        from winter_agent_v2.runtime import LiveRuntime

        brain = RuleBrain(current_goal="BEAST_HUNT")
        runtime = LiveRuntime(
            device=object(), vision=object(), semantic_vision=object(),
            capture_dir=Path("."), brain=brain, sleeper=lambda _s: None,
        )
        bare = WorldState(page=Page.MAP, march_used=0, confidence=0.99)
        self.assertIsNone(runtime._resolve_semantic_target("BEAST_SEARCH_TAB", bare))

    def test_the_label_reader_maps_both_monster_tabs_apart(self):
        from winter_agent_v2.ocr import RESOURCE_TAB_LABEL_TO_KIND

        self.assertEqual(RESOURCE_TAB_LABEL_TO_KIND["野兽"], "BEAST")
        self.assertEqual(RESOURCE_TAB_LABEL_TO_KIND["冰原巨兽"], "GIANT_BEAST")
        self.assertNotEqual(
            RESOURCE_TAB_LABEL_TO_KIND["野兽"],
            RESOURCE_TAB_LABEL_TO_KIND["冰原巨兽"],
        )


if __name__ == "__main__":
    unittest.main()
