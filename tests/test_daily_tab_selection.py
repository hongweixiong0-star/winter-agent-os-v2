"""The 任务 panel's own tab: the daily skills were reading 章节任务's content.

Origin (2026-09-16).  `OCRPageClassifier` names `Page.DAILY` from the literal string
`每日任务`, which the client draws on the tab **bar** -- so `page is DAILY` has never
meant "the daily tab is showing".  `OPEN_DAILY` lands on the panel's *first* tab
(章节任务), and every daily skill was calibrated on the daily tab.

The cost was measured, not assumed (`tools/probe_daily_tasks_tab.py`, one bounded tap):
with 章节任务 showing, the reading is `{'status': 'AVAILABLE', 'claimable_count': 0}`,
while the daily tab reads `{'status': 'AVAILABLE', 'claimable_count': 0,
'activity': 285}` with three chests at thresholds 80/160/270 **already passed** and
therefore claimable and invisible.

What is pinned here:

1. **The two tab states are distinguishable in the frames themselves** -- unselected is
   a dark blue pill with white text, selected is a light pill with dark text -- and the
   vision layer reports which one is showing.  Measured over all 3490 corpus frames the
   two records match 4 and 1 frames respectively, every one of them a live panel frame
   from that day, so the branch cannot hijack another page.
2. **The brain cannot tap forever.**  One tap per run; if it does not take, the run
   stops honestly instead of burning an action per step (the same shape as the
   beast-card exit and the panel exit).
3. **Real work is not shadowed**: a claimable daily tab is still claimed.

Frames are read from `dataset/truth_audit/`, never `dataset/raw` (that tree is rotated
by the retention pass and a test that depends on it fails the suite).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_daily_tab_selected
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "daily_tasks_tab_20260916"

# The client's own before/after pair, 40 s and one tap apart.
ON_CHAPTER_TAB = ARCHIVE / "01_before_20260916_134609.png"
ON_DAILY_TAB = ARCHIVE / "02_after_tap_20260916_134609.png"

# The 每日任务 pill: x 481..704, y 1091..1173 on the 720x1280 client.
PILL_CENTRE = (592 / 720, 1132 / 1280)


def _semantic() -> SemanticROIVision:
    return SemanticROIVision(MANIFEST)


def _panel(tab: str, status: str = "AVAILABLE", claimable: int = 0) -> WorldState:
    return WorldState(page=Page.DAILY, daily={"tab": tab, "status": status,
                                              "claimable_count": claimable}, confidence=0.99)


class TheTwoTabStatesAreDistinguishableTests(unittest.TestCase):
    def test_the_unselected_pill_is_the_tap_target_and_only_matches_its_own_state(self):
        semantic = _semantic()
        on = semantic.find(ON_CHAPTER_TAB, "BTN_DAILY_TAB_TASKS")
        off = semantic.find(ON_DAILY_TAB, "BTN_DAILY_TAB_TASKS")
        self.assertIsNotNone(on, "the 每日任务 pill must resolve while it is unselected")
        self.assertLessEqual(on.distance, 8)
        self.assertIsNone(off, "the selected pill must not be used as the tap target")

    def test_the_tap_point_lands_on_the_pill(self):
        match = _semantic().find(ON_CHAPTER_TAB, "BTN_DAILY_TAB_TASKS")
        self.assertIsNotNone(match)
        cx, cy = match.center_norm
        # within half the pill's own normalised size of its measured centre
        self.assertLess(abs(cx - PILL_CENTRE[0]), 0.15)
        self.assertLess(abs(cy - PILL_CENTRE[1]), 0.03)

    def test_the_selected_state_is_an_independent_observation(self):
        semantic = _semantic()
        self.assertIsNotNone(semantic.find(ON_DAILY_TAB, "TAB_DAILY_TASKS_SELECTED"))
        self.assertIsNone(semantic.find(ON_CHAPTER_TAB, "TAB_DAILY_TASKS_SELECTED"))

    def test_the_vision_layer_reports_which_tab_is_showing(self):
        vision = SemanticWorldVision(MANIFEST)
        self.assertEqual(vision.observe(ON_CHAPTER_TAB).daily.get("tab"), "NOT_TASKS")
        self.assertEqual(vision.observe(ON_DAILY_TAB).daily.get("tab"), "TASKS")


class TheBrainSwitchesTabsExactlyOnceTests(unittest.TestCase):
    def test_a_panel_on_another_tab_is_switched(self):
        brain = RuleBrain(current_goal="DAILY")
        decision = brain.decide(_panel("NOT_TASKS"), v2_registry())
        self.assertEqual(decision.skill, "SELECT_DAILY_TAB")
        self.assertEqual(decision.reason, "daily_panel_opened_on_another_tab")
        self.assertTrue(brain.daily_tab_switched)

    def test_a_tap_that_did_not_take_is_not_repeated(self):
        brain = RuleBrain(current_goal="DAILY")
        brain.decide(_panel("NOT_TASKS"), v2_registry())
        again = brain.decide(_panel("NOT_TASKS"), v2_registry())
        self.assertNotEqual(again.skill, "SELECT_DAILY_TAB")

    def test_the_daily_tab_is_not_re_tapped_when_it_already_shows(self):
        brain = RuleBrain(current_goal="DAILY")
        decision = brain.decide(_panel("TASKS"), v2_registry())
        self.assertNotEqual(decision.skill, "SELECT_DAILY_TAB")

    def test_a_guardless_goal_also_switches_the_tab(self):
        # HOME has no goal-specific block, so it reaches the page branch.
        brain = RuleBrain(current_goal="HOME")
        self.assertEqual(brain.decide(_panel("NOT_TASKS"), v2_registry()).skill,
                         "SELECT_DAILY_TAB")


class RealWorkIsNotShadowedTests(unittest.TestCase):
    def test_a_claimable_daily_tab_is_still_claimed(self):
        brain = RuleBrain(current_goal="DAILY")
        decision = brain.decide(_panel("TASKS", "CLAIMABLE", 2), v2_registry())
        self.assertEqual(decision.skill, "DAILY_CLAIM_REWARDS")

    def test_a_panel_with_no_tab_read_still_stops_honestly(self):
        # No tab observation (older frames, or the templates did not match): the brain
        # must not invent one and must not tap blind.
        brain = RuleBrain(current_goal="DAILY")
        decision = brain.decide(WorldState(page=Page.DAILY, daily={"status": "AVAILABLE"},
                                           confidence=0.99), v2_registry())
        self.assertNotEqual(decision.skill, "SELECT_DAILY_TAB")

    def test_the_open_daily_step_is_untouched(self):
        brain = RuleBrain(current_goal="DAILY")
        self.assertEqual(brain.decide(WorldState(page=Page.HOME, confidence=0.99),
                                      v2_registry()).skill, "OPEN_DAILY")

    def test_the_new_skill_is_registered_and_dispatchable(self):
        ids = [skill.id for skill in v2_registry().all()]
        self.assertIn("SELECT_DAILY_TAB", ids)
        # A skill without a verifier in VERIFIED_ATOMIC is never dispatched.
        self.assertIs(LiveRuntime.VERIFIED_ATOMIC.get("SELECT_DAILY_TAB"),
                      verify_daily_tab_selected)


class TheVerifierReadsTheDrawnStateTests(unittest.TestCase):
    def test_the_measured_transition_is_proven(self):
        result = verify_daily_tab_selected(_panel("NOT_TASKS"), _panel("TASKS"))
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.reason, "OK")

    def test_a_tap_that_changed_nothing_is_rejected(self):
        result = verify_daily_tab_selected(_panel("NOT_TASKS"), _panel("NOT_TASKS"))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "DAILY_TAB_NOT_SELECTED")

    def test_leaving_the_panel_is_not_a_tab_switch(self):
        result = verify_daily_tab_selected(_panel("NOT_TASKS"),
                                           WorldState(page=Page.HOME, confidence=0.99))
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
