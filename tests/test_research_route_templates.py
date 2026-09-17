"""The 科技研究 route: the second BLOCKED goal to become reachable, live verified.

Origin (2026-09-17, same round as the training route).  ``KEEP_RESEARCH_PRODUCTIVE`` is
one of the four BLOCKED goals, and it was blocked the same way TRAIN was -- the route
was already known and half-built, and what was missing was templates that resolve on
today's client plus the decisions that use them.

What already existed, and is deliberately NOT rebuilt here:

* ``knowledge/skills/RESEARCH_RESEARCH.md`` line 38 records the verified route --
  "top power value -> 实力详情 -> scroll to 科技实力 -> 提升 -> Research Center (科研所)" --
  measured 2026-09-04 on the then-current account (Research Center level 30).
* ``skill_factory.GOAL_REQUIREMENTS["KEEP_RESEARCH_PRODUCTIVE"]`` names the two skills
  the goal needs, ``("OPEN_RESEARCH", "RESEARCH")``.
* the ``BTN_OPEN_RESEARCH`` semantic and its 12-distance tolerance already existed;
  ``verify_research_started`` and ``verify_research_queue`` were already bound.

What was wrong, and is what this file pins:

1. **The old ``BTN_OPEN_RESEARCH`` ROI points off the control.**  Both records are
   REPLAY cuts at x 0.68 y 0.596 w 0.13 h 0.12 -- pixels 490..583 x 763..917, centre
   (536, 840) -- while the 研究 button's hexagon measures 435..520 x 855..910, centre
   **(478, 878)** by OCR.  The executor taps the winning record's ROI centre, so even a
   successful match would have tapped ~65 px away.  The replacement is a 340x340 block
   centred on the button, which is also what makes it survive the button's animated
   tutorial hand (the same defect the training camp's menu had).
2. **Nothing read "the research building's menu is open"**, and the RESEARCH goal route
   had no navigation at all: it could only ever stop with
   ``research_entry_not_verified``.  That is now a four-hop route whose every hop has a
   verifier, live-confirmed (exit 0).

Not claimed here: **starting** research.  The 科技研究 page today offers nothing
startable, the node/cost reading does not exist, and ``BTN_START_RESEARCH`` has zero
templates -- so the run ends with ``research_page_no_startable_node``, which is an
honest stop rather than a silent fall-through.  ``RESEARCH_RESEARCH.md`` names the
condition for promoting it: the queue must become free, a node's prerequisite/cost
screen must be inspected, and the transition ``queue_available=true -> IN_PROGRESS +
timer + expected node`` must be observed.

These frames are archived under ``dataset/truth_audit/`` rather than read out of
``dataset/raw``: the raw tree is rotated by the retention pass, and
``test_evidence_integrity`` fails the suite for tests that depend on it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.models import Page
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
KEY = ROOT / "dataset" / "truth_audit" / "power_route_20260917" / "key"

HOME_PLAIN = KEY / "01_home_plain.png"
POWER_OVERVIEW = KEY / "02_power_overview_panel.png"
POWER_DETAILS = KEY / "03_power_details_panel.png"
CAMP_FOCUSED = KEY / "05_camp_focused.png"
TRAINING_PAGE = KEY / "06_training_page.png"
RESEARCH_LAB = KEY / "14_research_lab_focused.png"
RESEARCH_LAB_WALK2 = KEY / "15_research_lab_focused_walk2.png"
RESEARCH_PAGE = KEY / "16_research_page.png"

LAB_FRAMES = (RESEARCH_LAB, RESEARCH_LAB_WALK2)

# The two records this round added, with the frames they must and must not resolve on.
# The population claim behind them is printed by
# tools/register_research_route_templates.py: BTN_OPEN_RESEARCH measures 0/8/8 on three
# walks of the route and misses every negative *and* the research page it navigates to.
ROUTE_OWNERS = {
    "BTN_POWER_RESEARCH_IMPROVE": {POWER_DETAILS},
    "BTN_OPEN_RESEARCH": {RESEARCH_LAB, RESEARCH_LAB_WALK2},
}

ROUTE_FRAMES = (HOME_PLAIN, POWER_OVERVIEW, POWER_DETAILS, CAMP_FOCUSED, TRAINING_PAGE,
                RESEARCH_LAB, RESEARCH_PAGE)

# OCR-measured on the lab frame: the 研究 button's hexagon.
RESEARCH_BUTTON_BOX_PX = (435, 855, 520, 910)


def _roi() -> SemanticROIVision:
    return SemanticROIVision(MANIFEST)


class TheRouteReadsCorrectlyOnTheLiveFramesTests(unittest.TestCase):
    def test_the_focused_lab_is_read_as_home_with_its_menu_open(self):
        state = SemanticWorldVision(MANIFEST).observe(RESEARCH_LAB)
        self.assertIs(state.page, Page.HOME)
        self.assertEqual(state.research.get("building"), "RESEARCH_LAB")
        self.assertTrue(state.research.get("menu_open"))

    def test_the_second_walk_reads_the_same(self):
        """The menu is an animated overlay, so one frame is not evidence.

        Both extra walks of the route reproduce it, and their OCR boxes for 详情/升级
        came back pixel-identical -- which is why the crop is stable enough that the
        verifier passes on its first observation (the training route's first attempt
        did not, and the loop re-walked itself).
        """
        state = SemanticWorldVision(MANIFEST).observe(RESEARCH_LAB_WALK2)
        self.assertIs(state.page, Page.HOME)
        self.assertTrue(state.research.get("menu_open"))

    def test_the_research_page_is_reached(self):
        state = SemanticWorldVision(MANIFEST).observe(RESEARCH_PAGE)
        self.assertIs(state.page, Page.RESEARCH)

    def test_no_queue_is_claimed_from_the_city(self):
        """`menu_open` is a navigation fact, not a queue fact.

        The training branch next door hard-codes `queue_available: True` while the menu
        is open, which is a lie the goal library reads as "this queue is free".  This
        route deliberately does not repeat it.
        """
        state = SemanticWorldVision(MANIFEST).observe(RESEARCH_LAB)
        self.assertNotIn("queue_available", state.research)
        self.assertNotIn("status", state.research)


class EachNewRecordOwnsExactlyItsOwnFrameTests(unittest.TestCase):
    def test_the_resolution_matrix_is_exactly_as_measured(self):
        vision = _roi()
        for semantic, owners in ROUTE_OWNERS.items():
            for frame in ROUTE_FRAMES:
                match = vision.find(frame, semantic)
                if frame in owners:
                    self.assertIsNotNone(match, f"{semantic} must resolve on {frame.name}")
                else:
                    self.assertIsNone(match, f"{semantic} must not resolve on {frame.name}")

    def test_the_research_button_record_resolves_within_its_gate(self):
        """0 on the first walk, 8 on the others, against a default gate of 8.

        Recorded as a number rather than a bare assertion so a future tightening or
        loosening has to come back here and re-measure.
        """
        vision = _roi()
        for frame in LAB_FRAMES:
            match = vision.find(frame, "BTN_OPEN_RESEARCH")
            self.assertIsNotNone(match, frame.name)
            self.assertLessEqual(match.distance, 8, frame.name)

    def test_the_tap_point_lands_on_the_research_button(self):
        """The old ROI's centre was ~65 px away from the control.

        The executor taps `match.center_norm`, so "the semantic resolved" is not enough
        -- the winning record's centre has to be inside the drawn button.
        """
        match = _roi().find(RESEARCH_LAB, "BTN_OPEN_RESEARCH")
        self.assertIsNotNone(match)
        cx = match.center_norm[0] * 720
        cy = match.center_norm[1] * 1280
        left, top, right, bottom = RESEARCH_BUTTON_BOX_PX
        self.assertLessEqual(left, cx, "the tap must land inside the 研究 hexagon")
        self.assertLessEqual(cx, right)
        self.assertLessEqual(top, cy)
        self.assertLessEqual(cy, bottom)

    def test_the_research_page_does_not_resolve_the_button_that_opens_it(self):
        """The page is where this semantic navigates TO; matching there would make the
        step look satisfied without a tap."""
        self.assertIsNone(_roi().find(RESEARCH_PAGE, "BTN_OPEN_RESEARCH"))

    def test_the_technology_row_button_is_value_independent(self):
        """科技实力's numbers sit at x <= 366, left of this crop.

        The 部队实力 record's lesson, applied: a crop that contains the account's values
        can only match the account it was cut from.
        """
        match = _roi().find(POWER_DETAILS, "BTN_POWER_RESEARCH_IMPROVE")
        self.assertIsNotNone(match)
        self.assertEqual(match.distance, 0)
        cx = match.center_norm[0] * 720
        cy = match.center_norm[1] * 1280
        # OCR: 科技实力's row 提升 button is 569..643 x 941..986
        self.assertTrue(569 <= cx <= 643, f"tap x {cx} is not on the 提升 button")
        self.assertTrue(941 <= cy <= 986, f"tap y {cy} is not on the 提升 button")

    def test_the_troop_row_button_does_not_win_the_technology_semantic(self):
        """Both rows draw the same blue 提升 pill, so the ROI is the only thing that
        separates them -- and it does: the 部队实力 row's crop is a different one."""
        vision = _roi()
        technology = vision.find(POWER_DETAILS, "BTN_POWER_RESEARCH_IMPROVE")
        troop = vision.find(POWER_DETAILS, "BTN_POWER_TROOP_IMPROVE")
        self.assertIsNotNone(technology)
        self.assertIsNotNone(troop)
        self.assertNotAlmostEqual(technology.center_norm[1], troop.center_norm[1],
                                  places=2)


if __name__ == "__main__":
    unittest.main()
