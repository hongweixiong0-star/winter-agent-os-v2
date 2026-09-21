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

import json
import unittest
from dataclasses import replace
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime

ROOT = Path(__file__).resolve().parents[1]
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_beast_scan_observed


def _map_without_target() -> WorldState:
    return WorldState(page=Page.MAP, march_used=0, confidence=0.99)


def _search_panel_on_beast_tab() -> WorldState:
    """The frame the 搜索 tap is issued from: panel open, ordinary beast tab *anchored*.

    ``resource_selected_tab`` is what the route keys on, and it is the anchor rather than the
    label.  ``resource_beast_tab_norm`` is not enough on its own: measured live 2026-09-21, a
    freshly opened panel draws all five tabs so that field is already non-``None`` while the
    client has **生肉** bracketed, and a gate keyed on it submitted the search without ever
    switching tabs.  The bool ``resource_beast_tab`` is not enough either: it is true for a panel
    showing either monster tab, and the rally tab's cards offer no solo 攻击 -- measured on the
    level-5 mammoth.  The fixture carries all three so a change that reintroduces the conflated
    reading fails here.
    """
    return WorldState(
        page=Page.MAP,
        march_used=0,
        resource_search_open=True,
        resource_beast_tab=True,
        resource_tab_kinds=("BEAST", "COAL", "GIANT_BEAST", "MEAT", "WOOD"),
        resource_beast_tab_norm=(0.058, 0.740),
        resource_giant_beast_tab_norm=(0.276, 0.740),
        resource_selected_tab="BEAST",
        confidence=0.99,
    )


def _search_panel_opened_on_the_meat_tab() -> WorldState:
    """The frame the panel actually opens on, measured live 2026-09-21.

    All five tabs are drawn -- so ``resource_beast_tab_norm`` is non-``None`` and the old gate
    declared the tab switch unnecessary -- but the bracket is on **生肉** and ``resource_selected``
    reads ``MEAT``.  The route must open the 野兽 tab from here rather than submit the search:
    the measured failure is that 搜索 then hit a gatherable node behind the panel and the run
    went ``MAP -> RESOURCE_DETAIL`` on a 等级6 废弃畜牧场 card.
    """
    return WorldState(
        page=Page.MAP,
        march_used=0,
        resource_search_open=True,
        resource_beast_tab=True,
        resource_tab_kinds=("BEAST", "COAL", "GIANT_BEAST", "MEAT", "WOOD"),
        resource_beast_tab_norm=(0.0576, 0.7398),
        resource_giant_beast_tab_norm=(0.2764, 0.7394),
        resource_selected="MEAT",
        resource_selected_tab="MEAT",
        resource_level=6,
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
        resource_selected_tab="GIANT_BEAST",
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

        # The panel as the client actually opens it: 生肉 anchored, 野兽 drawn but not
        # selected.  This is the state measured live 2026-09-21 and it is the one the
        # switch exists for -- a panel with no tab reading at all proves nothing either way.
        panel_wrong_tab = _search_panel_opened_on_the_meat_tab()
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
        # The panel's own opening state: 野兽 drawn, 生肉 anchored.
        self.assertEqual(brain.decide(_search_panel_opened_on_the_meat_tab(), v2_registry()).skill, "OPEN_BEAST_SEARCH_TAB")
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

    def test_the_panel_the_client_opens_on_meat_switches_tab_first(self):
        """The measured live defect: a readable 野兽 label is not a selected 野兽 tab.

        Measured 2026-09-21 on
        ``live_runtime_step_002_after_20260921T103154681030.png``: the client opens the panel
        with all five tabs drawn and **生肉** bracketed, so ``resource_beast_tab_norm`` was
        already ``(0.0576, 0.7398)``.  The gate keyed on that field and went straight to the
        search, and the 搜索 tap hit a gatherable node behind the panel -- the run recorded
        ``page MAP -> RESOURCE_DETAIL`` and ``BEAST_SEARCH_NOT_SUBMITTED``.

        The route must open the 野兽 tab from this exact frame, and must not spend the search
        ticket doing it, because nothing has been searched yet.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        decision = brain.decide(_search_panel_opened_on_the_meat_tab(), v2_registry())
        self.assertEqual(decision.skill, "OPEN_BEAST_SEARCH_TAB")
        self.assertFalse(
            brain.beast_search_used,
            "switching tabs is not searching: spending the ticket here would forbid the search",
        )

    def test_a_panel_already_anchored_on_the_beast_tab_does_not_switch(self):
        """The other half: when the anchor is already 野兽 the route must submit directly.

        Without this the switch could be re-issued forever, which is the loop the older
        ``resource_selected == 'BEAST'`` gate produced and why that signal was rejected.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        decision = brain.decide(_search_panel_on_beast_tab(), v2_registry())
        self.assertEqual(decision.skill, "SUBMIT_BEAST_SEARCH")
        self.assertTrue(brain.beast_search_used)

    def test_the_open_tab_skill_taps_where_the_label_was_read(self):
        """The tap follows the frame, not a position-pinned template.

        Asserted through the runtime's own resolver, because that is what the executor taps:
        a coordinate read off the frame cannot follow the client when the strip reorders, and
        a template pinned to a slot silently taps the wrong tab instead.

        This fixture carries no frame path, so the resolver has no strip geometry to consult
        and falls back to the label box it read -- which is the branch under test here.  The
        geometry branch has its own test below.
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

    def test_the_anchor_is_read_through_the_composite_vision(self):
        """The semantic layer hangs off ``template_vision``, and the first live run proved it.

        The opening live run of this change crashed inside ``observe`` with
        ``AttributeError: 'HybridVision' object has no attribute 'semantic'`` -- the composite
        exposes the semantic layer as ``template_vision.semantic`` (see ``_semantic_roi``), and
        reading it under the shorter name works for a bare ``SemanticROIVision`` and fails for
        the object production actually builds.  This test constructs the real composite, so the
        shorter name cannot creep back in.
        """
        from winter_agent_v2.ocr import (
            HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend,
        )
        from winter_agent_v2.vision import SemanticWorldVision

        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        if not manifest.exists():
            self.skipTest("the template manifest is not in this checkout")
        try:
            composite = HybridVision(
                SemanticWorldVision(manifest),
                OCRService(ResilientOCRBackend(RapidOCRBackend())),
            )
        except Exception as error:                      # pragma: no cover - backend missing
            self.skipTest(f"the OCR backend is unavailable here: {error}")
        semantic = getattr(getattr(composite, "template_vision", None), "semantic", None)
        self.assertIsNotNone(
            semantic,
            "the anchor read reaches the semantic layer through template_vision",
        )
        self.assertTrue(hasattr(semantic, "anchored_tab_kind"))

    def test_a_clipped_tab_is_refused_and_the_swipe_is_what_reveals_it(self):
        """Measured end to end: tapping a clipped 野兽 picks its neighbour instead.

        On ``live_runtime_step_002_after_20260921T103154681030.png`` the strip sits at offset
        196.5, putting 野兽's cell left at -30.5 and its centre at 42.0 -- the client draws a
        sliver of the cell and the whole 野兽 label.  Tapping that sliver was measured to do the
        wrong thing: on ``live_runtime_step_001_after_20260921T105247039793.png`` the tap at
        x=42 left **冰原巨兽** anchored, because the client selects the neighbouring cell rather
        than the one showing a sliver of itself.  The verifier's honest
        ``BEAST_SEARCH_TAB_NOT_PROVEN`` is what stopped the run from searching the wrong tab.

        So the resolver must refuse the clipped point (leaving the runtime's scroll branch to
        reveal the cell), the anchor must read the neighbour that the tap actually selected, and
        the client's own swipe amount must be the small positive drag that fixes it.  The
        controlled swipe of +34 px was measured to move the strip to offset 237.5 and put 野兽's
        cell left on a bracket stroke at 10.5 -- the exact nominal position -- after which the
        same frame reads ``anchored_tab_kind == "BEAST"``.
        """
        from pathlib import Path as _Path

        from winter_agent_v2.vision import SemanticROIVision

        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        clipped = (
            ROOT / "dataset" / "raw" / "live_runtime"
            / "live_runtime_step_002_after_20260921T103154681030.png"
        )
        if not clipped.exists() or not manifest.exists():
            self.skipTest("the measured live frame is not in this checkout")
        vision = SemanticROIVision(_Path(manifest))
        vision.selected_resource(clipped)
        self.assertEqual(
            vision.anchored_tab_kind(clipped), "MEAT",
            "the panel opens on 生肉, which is why the switch is needed at all",
        )
        self.assertIsNone(
            vision.resource_cell_center_norm("BEAST"),
            "a clipped cell has no confirmed centre, so the resolver must refuse it",
        )
        swipe = vision.resource_tab_swipe_for("BEAST")
        self.assertIsNotNone(swipe, "the reveal amount is derivable from the strip geometry")
        self.assertGreater(
            swipe, 0.0,
            "野兽 clips on the LEFT edge, so the drag that reveals it is positive",
        )

    def test_the_neighbour_is_what_a_clipped_tap_actually_selected(self):
        """The frame the wrong tap produced, read back through the same anchor."""
        from pathlib import Path as _Path

        from winter_agent_v2.vision import SemanticROIVision

        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        tapped = (
            ROOT / "dataset" / "raw" / "live_runtime"
            / "live_runtime_step_001_after_20260921T105247039793.png"
        )
        if not tapped.exists() or not manifest.exists():
            self.skipTest("the measured live frame is not in this checkout")
        vision = SemanticROIVision(_Path(manifest))
        self.assertEqual(
            vision.anchored_tab_kind(tapped), "GIANT_BEAST",
            "the tap at 野兽's clipped sliver left the rally tab anchored, not 野兽",
        )

    def test_the_swipe_is_what_makes_the_beast_tab_anchored(self):
        """The controlled experiment: after the +34 swipe the anchor really is 野兽."""
        from pathlib import Path as _Path

        from winter_agent_v2.vision import SemanticROIVision

        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        revealed = ROOT / "dataset" / "raw" / "live_runtime" / "probe_swipe_right34.png"
        if not revealed.exists() or not manifest.exists():
            self.skipTest("the controlled-experiment frame is not in this checkout")
        vision = SemanticROIVision(_Path(manifest))
        self.assertEqual(
            vision.anchored_tab_kind(revealed), "BEAST",
            "the revealed 野兽 tab is the anchored one",
        )
        self.assertIsNotNone(
            vision.resource_cell_center_norm("BEAST"),
            "once revealed, the cell has a confirmed centre and is tappable",
        )

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


class TheSubmitButtonIsTheOneMeasuredOnLiveFramesTests(unittest.TestCase):
    """The submit control is the same blue 搜索 pill under two names.

    Measured live 2026-09-21 on ``live_runtime_step_002_after_20260921T102557043132.png``,
    a frame of the beast search panel with 野兽 selected:

        BTN_RESOURCE_SEARCH_SUBMIT   d=0   (six independent records, all d=0)
        BTN_SUBMIT_BEAST_SEARCH      d=12  (threshold 8 -> NO MATCH)

    On the archived ``beast_search_exploration/beast_tab.png`` -- the frame the beast
    template was cut from -- the same comparison is d=0 versus d=4, i.e. the beast record
    matches only the screen it was cut from, 23 px above where the live client draws the
    button.  Two live runs failed this hop with SEMANTIC_TARGET_NOT_VERIFIED.

    This is the same defect class as the 野兽 tab above: a control registered against an
    archived frame rather than against the client the run drives.  What is asserted is the
    binding, because that is what the executor taps.
    """

    def test_the_submit_skill_taps_the_measured_control(self):
        skill = v2_registry().get("SUBMIT_BEAST_SEARCH")
        self.assertEqual(skill.action.target, "BTN_RESOURCE_SEARCH_SUBMIT")

    def test_the_measured_control_resolves_on_the_live_panel_frame(self):
        """A binding is only as good as the frame it resolves on.

        The panel frame is a real live capture, so this asserts the same thing the run
        needed: on the screen the beast search actually produces, the control the skill
        names is found.  A green test here and a NO MATCH at runtime is exactly the
        contradiction the two failed runs exposed, so the frame is the load-bearing part.
        """
        from winter_agent_v2.vision import SemanticROIVision

        frame = ROOT / "dataset/raw/live_runtime/live_runtime_step_002_after_20260921T102557043132.png"
        if not frame.exists():
            self.skipTest("the live beast-panel frame is not in this checkout")
        target = v2_registry().get("SUBMIT_BEAST_SEARCH").action.target
        match = SemanticROIVision(ROOT / "dataset/candidate/template_manifest.json").find(frame, target)
        self.assertIsNotNone(match, f"{target} must resolve on the live beast-search panel")

    def test_the_archived_record_matches_the_client_that_drew_it(self):
        """And the record it replaced is kept explained, not silently deleted.

        ``BTN_SUBMIT_BEAST_SEARCH`` still matches the archive at d=4 -- that is why it
        looked correct when it was registered.  Pinning that keeps the next reader from
        "repairing" the binding by cutting a fresh crop of the same archived screen.
        """
        import json

        from PIL import Image

        from winter_agent_v2.image_hash import hamming, phash

        frame = ROOT / "dataset/raw/beast_search_exploration/beast_tab.png"
        if not frame.exists():
            self.skipTest("the archived beast-tab frame is not in this checkout")
        rows = json.loads((ROOT / "dataset/candidate/template_manifest.json").read_text(encoding="utf-8"))
        rec = [r for r in rows["records"] if r["semantic"] == "BTN_SUBMIT_BEAST_SEARCH"][0]
        roi = rec["roi_norm"]
        with Image.open(frame) as im, Image.open(ROOT / rec["template_path"]) as t:
            width, height = im.size
            box = (round(roi["x_norm"] * width), round(roi["y_norm"] * height),
                   round((roi["x_norm"] + roi["w_norm"]) * width),
                   round((roi["y_norm"] + roi["h_norm"]) * height))
            self.assertLessEqual(hamming(phash(im.crop(box)), phash(t)), 8,
                                 "the archived record must still match the frame it was cut from")


class TheSearchResultCardIsReadFromItsOwnWordsTests(unittest.TestCase):
    """The successful search produces a card no template matches, but its words read.

    Measured live 2026-09-21 on
    ``live_runtime_step_001_after_refresh_2_20260921T105832480183.png``: the search found a
    **等级10 麝牛**, and on that frame ``BTN_BEAST_CARD_ATTACK`` (cut from a world-map card)
    and every ``TARGET_BEAST_*`` sprite scored NO MATCH, while the card's own text read at
    0.88-1.00.  The old ``beast_search_submitted`` was ``resource_beast_tab and
    beacon_beast`` -- a NO-MATCH template and a map-nameplate reader that returned ``{}`` --
    so a search that visibly succeeded was reported as not submitted.

    The load-bearing distinction is 攻击 vs 集结, which is what keeps a rally target from
    being attempted as a normal attack: the measured level-5 mammoth card offered 集结 and
    no 攻击, this one offers 攻击 and no 集结.
    """

    @staticmethod
    def _card_reader():
        from winter_agent_v2.ocr import (
            OCRService, RapidOCRBackend, ResilientOCRBackend, read_beast_search_result_card,
        )
        try:
            config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
            ocr = OCRService(
                ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
            )
        except Exception as error:                      # pragma: no cover - backend missing
            raise unittest.SkipTest(f"the OCR backend is unavailable here: {error}")
        return read_beast_search_result_card, ocr

    def test_the_found_beast_card_offers_a_solo_attack(self):
        reader, ocr = self._card_reader()
        frame = (
            ROOT / "dataset" / "raw" / "live_runtime"
            / "live_runtime_step_001_after_refresh_2_20260921T105832480183.png"
        )
        if not frame.exists():
            self.skipTest("the measured result-card frame is not in this checkout")
        card = reader(frame, ocr, frame_size=(720, 1280))
        self.assertTrue(card, "the successful search frame must read as a result card")
        self.assertEqual(card["title_level"], 10)
        self.assertTrue(card["has_attack"], "this card carries the 攻击 control")
        self.assertFalse(card["has_rally"], "and it does not carry 集结, so it is a solo target")
        self.assertTrue(card["solo_attack"])

    def test_the_open_panel_is_not_a_result_card(self):
        """The negative control: the panel before 搜索 must not read as a result."""
        reader, ocr = self._card_reader()
        frame = (
            ROOT / "dataset" / "raw" / "live_runtime"
            / "live_runtime_step_001_before_20260921T105747410273.png"
        )
        if not frame.exists():
            self.skipTest("the measured panel frame is not in this checkout")
        self.assertEqual(
            reader(frame, ocr, frame_size=(720, 1280)), {},
            "an open panel with no result drawn is not a result card",
        )

    def test_the_verifier_accepts_the_card_and_still_refuses_the_panel(self):
        """The hop's verdict, on the two measured frames, through the real verifier."""
        from winter_agent_v2.ocr import (
            HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend,
        )
        from winter_agent_v2.verifier import verify_beast_search_submitted
        from winter_agent_v2.vision import SemanticWorldVision

        try:
            config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
            vision = HybridVision(
                SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
                OCRService(
                    ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
                ),
            )
        except Exception as error:                      # pragma: no cover - backend missing
            raise unittest.SkipTest(f"the OCR backend is unavailable here: {error}")
        panel = (
            ROOT / "dataset" / "raw" / "live_runtime"
            / "live_runtime_step_001_before_20260921T105747410273.png"
        )
        card = (
            ROOT / "dataset" / "raw" / "live_runtime"
            / "live_runtime_step_001_after_refresh_2_20260921T105832480183.png"
        )
        if not panel.exists() or not card.exists():
            self.skipTest("the measured frames are not in this checkout")
        before = vision.observe(panel)
        after = vision.observe(card)
        result = verify_beast_search_submitted(before, after)
        self.assertTrue(
            result.ok,
            "a search that drew the result card must pass this hop: " + str(result.evidence),
        )


class _EnumerationDevice:
    """A device that is never touched: this test resolves a target, it does not act.

    Present because ``LiveRuntime`` takes one, and a resolver asserting on a *read*
    must not be able to accidentally reach the hardware if it fell through.
    """

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()


class _NoMatchSemantic:
    """A semantic layer that matches nothing.

    Used where the point under test is *read off the frame's state* rather than found
    by a template: the resolver must not be able to fall through to a match, because
    then the assertion would pass without the reading having been used at all.
    """

    resource_tab_offset = None
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)

    def find(self, _path, _semantic):
        return None

    def resource_cell_center_norm(self, _resource):
        return None

    def resource_tab_swipe_for(self, _resource):
        return 0.0

    def selected_resource(self, _path):
        return None


class TheSearchResultIsWhatTheRouteMarchesOnTests(unittest.TestCase):
    """The hop the route was missing: a solo card found by the search is attacked.

    Measured live 2026-09-21 (run at 11:07Z, revision ``af4235e``): the search was submitted
    and verified, the client drew a **等级10 麝牛** card carrying an orange 攻击 control --
    and the run then went to ``BACK`` and rescanned the map, because nothing in the route
    could see that card.  ``world.beast`` stayed empty (no template matched it), so neither
    ``attack_card`` nor ``is_dispatchable`` could fire, and the beast the run had just found
    was dropped.  These tests pin the hop that spends it.
    """

    def _solo_card_world(self):
        return WorldState(
            page=Page.MAP,
            confidence=0.99,
            resource_search_open=True,
            resource_selected_tab="BEAST",
            beast_search_submitted=True,
            beast_search_result={
                "title_level": 10,
                "title_text": "蔚牛",
                "has_attack": True,
                "has_rally": False,
                "solo_attack": True,
                "attack_centre_norm": (0.5007, 0.4688),
                "title_centre_norm": (0.4993, 0.2977),
            },
        )

    def test_a_card_offering_attack_and_not_rally_is_marched_on(self):
        decision = RuleBrain(current_goal="BEAST_HUNT").decide(
            self._solo_card_world(), v2_registry()
        )
        self.assertEqual(decision.skill, "ATTACK_BEAST_CARD")
        self.assertEqual(decision.reason, "solo_attack_card_found_by_the_clients_own_search")

    def test_a_card_offering_rally_is_never_entered_as_an_ordinary_attack(self):
        """The user's rule, as a guard rather than a convention: 集结 is not 攻击.

        The measured level-5 mammoth card offers 集结 with no 攻击; that card must not
        reach the ordinary-attack skill, whatever else is true of the frame.
        """
        rally = replace(
            self._solo_card_world(),
            beast_search_result={
                "title_level": 5,
                "title_text": "猛犸象",
                "has_attack": False,
                "has_rally": True,
                "solo_attack": False,
            },
        )
        decision = RuleBrain(current_goal="BEAST_HUNT").decide(rally, v2_registry())
        self.assertNotEqual(decision.skill, "ATTACK_BEAST_CARD")

    def test_the_attack_point_is_read_off_the_card_and_guarded_by_it(self):
        """The resolver returns the card's own measured point, and only for that card."""
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp:
            runtime = LiveRuntime(
                device=_EnumerationDevice(),
                vision=lambda _path: (_ for _ in ()).throw(AssertionError("vision is not used here")),
                semantic_vision=_NoMatchSemantic(),
                capture_dir=Path(temp),
            )
            world = self._solo_card_world()
            point = runtime._resolve_semantic_target("BTN_BEAST_CARD_ATTACK", world)
            self.assertEqual(point, (0.5007, 0.4688))

            # No card on screen: the point is a fragment of the frame it was measured on,
            # so it must not survive onto a frame that no longer shows that card.
            without = replace(self._solo_card_world(), beast_search_result={})
            self.assertIsNone(runtime._resolve_semantic_target("BTN_BEAST_CARD_ATTACK", without))

            # A rally card is not this route's control either.
            rally = replace(
                self._solo_card_world(),
                beast_search_result={
                    "title_level": 5, "title_text": "猛犸象",
                    "has_attack": False, "has_rally": True, "solo_attack": False,
                },
            )
            self.assertIsNone(runtime._resolve_semantic_target("BTN_BEAST_CARD_ATTACK", rally))

            # And a point that is not on the frame is refused rather than tapped.
            off_frame = replace(
                self._solo_card_world(),
                beast_search_result={
                    "title_level": 10, "title_text": "蔚牛",
                    "has_attack": True, "has_rally": False, "solo_attack": True,
                    "attack_centre_norm": (1.4, 0.4688),
                },
            )
            self.assertIsNone(runtime._resolve_semantic_target("BTN_BEAST_CARD_ATTACK", off_frame))

    def test_the_march_verifier_binds_the_search_card_the_same_as_the_map_card(self):
        """A verified card is a verified card: both are the 攻击 control, measured two ways."""
        from winter_agent_v2.verifier import verify_beast_card_march_open

        march = WorldState(page=Page.MARCH, beast={"victory_assured": True}, confidence=0.99)

        # the card the client's own search drew (read from its words)
        result = verify_beast_card_march_open(self._solo_card_world(), march)
        self.assertTrue(result.ok, result.evidence)

        # the world-map card (matched by template) must still verify
        map_card = WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99)
        result = verify_beast_card_march_open(map_card, march)
        self.assertTrue(result.ok, result.evidence)

        # and neither half may be satisfied by a frame with no card at all
        blank = WorldState(page=Page.MAP, confidence=0.99)
        self.assertFalse(verify_beast_card_march_open(blank, march).ok)

        # opening a formation is not the spend: the after half still has to show it
        self.assertFalse(verify_beast_card_march_open(self._solo_card_world(), blank).ok)


    def test_the_panel_is_not_closed_while_it_is_showing_a_target(self):
        """The measured regression: BACK fired on the one frame that had the beast.

        The panel is left when the search is spent, which is right when the search found
        nothing.  But the result card is read into ``beast_search_result`` and not into
        ``world.beast`` -- it matches no reviewed template -- so the branch's existing
        predicate (``is_dispatchable`` or ``may_evaluate``) could not see it and pressed
        BACK over a verified 等级10 麝牛.
        """
        world = self._solo_card_world()
        decision = RuleBrain(current_goal="BEAST_HUNT").decide(world, v2_registry())
        self.assertNotEqual(
            decision.reason,
            "close_resource_search_for_beast_goal",
            "a panel holding a verified solo target must not be torn down",
        )

        # A panel whose search found nothing is still left, exactly as before.
        empty = replace(
            self._solo_card_world(),
            beast_search_submitted=True,
            beast_search_result={},
        )
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.beast_search_used = True
        decision = brain.decide(empty, v2_registry())
        self.assertEqual(decision.reason, "close_resource_search_for_beast_goal")

        # And a rally card does not hold it open for a route that cannot use it.
        rally = replace(
            self._solo_card_world(),
            beast_search_result={
                "title_level": 5, "title_text": "猛犸象",
                "has_attack": False, "has_rally": True, "solo_attack": False,
            },
        )
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.beast_search_used = True
        decision = brain.decide(rally, v2_registry())
        self.assertEqual(decision.reason, "close_resource_search_for_beast_goal")


if __name__ == "__main__":
    unittest.main()
