"""The 战力 route that TRAIN and BUILD were both stuck behind, as measured live.

Origin (2026-09-17).  The operator asked for training and building first.  Both
were blocked on one thing, and it was not the reasoning: `brain.py` already routed
the whole chain (lines 243-246, 446-456) and `LiveRuntime.VERIFIED_ATOMIC` already
bound every hop's verifier --

    HOME --[tap power]--> POPUP/POWER_OVERVIEW --[实力详情]--> POPUP/POWER_DETAILS
         --[部队实力 提升]--> HOME (infantry camp focused) --[训练]--> TRAINING

-- but the vision never produced `world.training` on today's client, because every
template that would populate it was cropped from 2026-09-08 frames of a *different
account* (57,083,909 power versus 826,444, a different avatar, and a city camera
zoomed far enough out that buildings the current client does not show were visible).
Measured on the live HOME frame, all five route semantics MISSed.

`tools/probe_power_route.py` walked the route on the live client and
`tools/register_power_route_templates.py` turned those frames into records.  Two
defects were fixed on the way, and both are pinned here:

1. **The power entry was a value-dependent template.**  The 2026-09-08 record's crop
   (x 97..302) contained the power NUMBER, so it could only match the account it was
   cut from.  An icon-only crop measures phash distance 2 between the two accounts
   (a 68x difference in the value) against a gate of 8.
2. **The focused-camp menu carries an ANIMATED overlay** -- a pulsing highlight ring
   and a tutorial pointing hand.  The old crop matched 3 of 7 frames of one run
   (d = 4/8/16, the rest MISS), which cost `NAVIGATE_INFANTRY_CAMP` its whole refresh
   budget (~21 s at 07:41:18/29/39Z); by the time the next step observed, the overlay
   had faded, and the loop re-walked the route (7 steps instead of 4).  The
   replacement crop is centred on the 训练 button and measures 0..8 across the run.

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
BUILDING_FOCUSED = KEY / "04_building_focused.png"
CAMP_FOCUSED = KEY / "05_camp_focused.png"
TRAINING_PAGE = KEY / "06_training_page.png"
CAMP_AFTER_TAP = KEY / "07_camp_focus_after_tap.png"
CAMP_REFRESH_1 = KEY / "08_camp_focus_refresh_1.png"
CAMP_SECOND_PASS = KEY / "09_camp_focus_second_pass.png"
CAMP_LATE = KEY / "10_camp_focus_late_observation.png"
INTEL_REWARD = KEY / "11_intel_reward_popup.png"
OLD_ACCOUNT_HOME = KEY / "12_old_account_home_20260908.png"

CAMP_FRAMES = (CAMP_FOCUSED, CAMP_AFTER_TAP, CAMP_REFRESH_1, CAMP_SECOND_PASS, CAMP_LATE)

# The four records this round added, each of which must be the one that resolves on
# its own frame and must not resolve anywhere else in the route.
ROUTE_OWNERS = {
    "BTN_OPEN_POWER_OVERVIEW": {HOME_PLAIN, OLD_ACCOUNT_HOME, CAMP_FOCUSED, BUILDING_FOCUSED},
    "POPUP_POWER_OVERVIEW": {POWER_OVERVIEW},
    "BTN_OPEN_POWER_DETAILS": {POWER_OVERVIEW},
    "POPUP_POWER_DETAILS": {POWER_DETAILS},
    "BTN_POWER_TROOP_IMPROVE": {POWER_DETAILS},
}

ROUTE_FRAMES = (HOME_PLAIN, POWER_OVERVIEW, POWER_DETAILS, BUILDING_FOCUSED, CAMP_FOCUSED,
                TRAINING_PAGE)

# OCR measured on 03_power_details_panel.png: the 部队实力 row's 提升 button box.
TROOP_IMPROVE_BOX_PX = (569, 631, 642, 676)


def _roi() -> SemanticROIVision:
    return SemanticROIVision(MANIFEST)


class TheRouteReadsCorrectlyOnTheLiveFramesTests(unittest.TestCase):
    def test_the_plain_city_frame_is_home_with_no_training_state(self):
        state = SemanticWorldVision(MANIFEST).observe(HOME_PLAIN)
        self.assertIs(state.page, Page.HOME)
        # The whole route hangs off this being empty: if a plain city frame reported
        # menu_open, the brain would tap the training button's ROI into the city.
        self.assertEqual(state.training, {})

    def test_the_power_entry_opens_the_overview_popup(self):
        state = SemanticWorldVision(MANIFEST).observe(POWER_OVERVIEW)
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "POWER_OVERVIEW")

    def test_the_overview_leads_to_the_details_popup(self):
        state = SemanticWorldVision(MANIFEST).observe(POWER_DETAILS)
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "POWER_DETAILS")

    def test_the_troop_power_improve_focuses_the_infantry_camp(self):
        state = SemanticWorldVision(MANIFEST).observe(CAMP_FOCUSED)
        self.assertIs(state.page, Page.HOME)
        self.assertTrue(state.training.get("menu_open"))

    def test_the_second_pass_frames_still_report_the_camp_menu(self):
        """Every observation of the focused camp reports it, not just the first.

        This is the regression the round exists for: previously the semantic matched
        only some frames of a run, so the loop could not tell whether it had already
        focused the camp.
        """
        world = SemanticWorldVision(MANIFEST)
        for frame in CAMP_FRAMES:
            state = world.observe(frame)
            self.assertIs(state.page, Page.HOME, frame.name)
            self.assertTrue(state.training.get("menu_open"), frame.name)


class EachNewRecordOwnsExactlyItsOwnFrameTests(unittest.TestCase):
    """A record that resolves in the wrong place is a tap in the wrong place.

    `find` takes the minimum distance over a semantic's records and the executor taps
    the winning record's centre, so "it resolved" is not the property that matters --
    "this record resolved" is.
    """

    def test_the_resolution_matrix_is_exactly_as_measured(self):
        vision = _roi()
        for semantic, owners in ROUTE_OWNERS.items():
            for frame in ROUTE_FRAMES:
                match = vision.find(frame, semantic)
                if frame in owners:
                    self.assertIsNotNone(match, f"{semantic} must resolve on {frame.name}")
                else:
                    self.assertIsNone(match, f"{semantic} must not resolve on {frame.name}")

    def test_the_power_entry_is_the_same_control_on_both_accounts(self):
        """The old crop could only ever match the account it was cut from.

        Today's frame carries 826,444 power and the 2026-09-08 frame carries
        57,083,909 -- 68x -- but the fist icon is drawn identically, so an icon-only
        crop resolves on both whereas the old wide crop (which included the number)
        scored 28 against a gate of 8.
        """
        vision = _roi()
        for frame in (HOME_PLAIN, OLD_ACCOUNT_HOME):
            match = vision.find(frame, "BTN_OPEN_POWER_OVERVIEW")
            self.assertIsNotNone(match, frame.name)
            self.assertLessEqual(match.distance, 8, frame.name)

    def test_the_troop_improve_button_is_the_troop_power_row(self):
        """Pin which row the winning ROI points at, not merely that something won.

        The panel lists 建筑/部队/英雄/英雄装备/科技, each with its own 提升 button, and
        the row's y depends on how many categories the account has unlocked: seven on
        2026-09-08 (y 538..608, which is where the old record points, and which today
        is the *building* row) against five today.  Tapping the wrong row focuses the
        wrong building.
        """
        match = _roi().find(POWER_DETAILS, "BTN_POWER_TROOP_IMPROVE")
        self.assertIsNotNone(match)
        cx = match.center_norm[0] * 720
        cy = match.center_norm[1] * 1280
        left, top, right, bottom = TROOP_IMPROVE_BOX_PX
        self.assertLessEqual(left, cx, "the tap must land inside the 提升 button box")
        self.assertLessEqual(cx, right)
        self.assertLessEqual(top, cy)
        self.assertLessEqual(cy, bottom)
        # distance 0, so no other record is even close on this frame
        self.assertEqual(match.distance, 0)


class TheCampMenuGateSeparatesTheTwoPopulationsTests(unittest.TestCase):
    """The gate has to be read off the measurements, not kept at its old value.

    2026-09-08 tuned this semantic to 17: its crop's positives measured 12-16 and live
    Home frames without the menu >=20.  The 2026-09-17 crop sits at 0..8 on the camp
    frames but at **16 on a plain HOME frame**, i.e. inside that gate -- so keeping 17
    would report ``menu_open`` on an ordinary city frame and send the training tap
    into the city.  `tools/probe_camp_menu_gate.py` scanned all 3522 corpus frames and
    spot-checked the <=12 population by OCR (every one carries 盾兵营/详情/训练): the
    negatives that matter are 16 (plain HOME) and 36 (the training page).
    """

    def test_every_camp_frame_resolves_under_the_tightened_gate(self):
        vision = _roi()
        for frame in CAMP_FRAMES:
            match = vision.find(frame, "BTN_OPEN_TRAINING_FROM_CAMP")
            self.assertIsNotNone(match, frame.name)
            self.assertLessEqual(match.distance, 12, frame.name)

    def test_a_plain_city_frame_is_rejected(self):
        self.assertIsNone(_roi().find(HOME_PLAIN, "BTN_OPEN_TRAINING_FROM_CAMP"))

    def test_the_training_page_is_rejected(self):
        """The control is drawn on the city only; on the page it navigates to, the
        crop region holds troop rows instead."""
        self.assertIsNone(_roi().find(TRAINING_PAGE, "BTN_OPEN_TRAINING_FROM_CAMP"))


class TheBuildingPanelIsStillUnrecognisedTests(unittest.TestCase):
    """BUILD's entry is found but not yet landed -- pinned so the gap stays visible.

    Tapping 建筑实力's 提升 focuses 民居1 and opens its furniture panel with an 升级
    button (cost 157.7万 meat against the 16.6万 the account held, so it was disabled
    today).  Nothing reads that panel yet -- `page=UNKNOWN`, no `building` state -- and
    the existing ``BTN_BUILD_UPGRADE`` branch in ``vision.py`` hard-codes
    ``{"id": "STOREHOUSE", "level": 26, "target_level": 27}``, which would fabricate a
    building identity for whatever building is actually focused.  When BUILD is landed
    this test is expected to change.
    """

    def test_the_building_panel_does_not_claim_to_be_a_known_page(self):
        state = SemanticWorldVision(MANIFEST).observe(BUILDING_FOCUSED)
        self.assertIs(state.page, Page.UNKNOWN)
        self.assertEqual(state.building, {})


class TheIntelRewardPopupIsMisreadTests(unittest.TestCase):
    """A separate defect this round exposed, pinned with its measurement.

    The Intel reward feedback is the client's *generic* 获得奖励 dialog (五个奖励格 +
    点击任意位置退出) -- the same artwork other sources use.  The frame resolves
    ``POPUP_GENERIC_REWARD_HEADER`` at distance 12 and neither the daily nor the Intel
    reward title template, yet ``vision.py`` checks ``POPUP_DAILY_REWARD_CURRENT``
    first and that record false-positives here, so the page is reported as
    ``DAILY_REWARD``.  The brain then runs the *daily* dismiss skill, whose verifier
    expects a daily-page transition, and the live Intel run ended

        step 4 DISMISS_DAILY_REWARD  verify=False  DAILY_REWARD_ADVANCE_NOT_PROVEN

    (exit 2, after step 3 ``INTEL_CLAIM_REWARDS`` had verified and actually claimed a
    reward).  The brain already has the goal-context branch that would do the right
    thing -- ``popup == "GENERIC_REWARD"`` plus ``current_goal == "INTEL"`` routes to
    ``DISMISS_INTEL_GENERIC_REWARD`` (brain.py lines 221-232) -- so the repair belongs
    in the vision ordering or in the daily record, and needs the two populations
    (genuine daily reward versus generic) measured first.
    """

    def test_the_generic_header_is_the_signal_that_actually_resolves(self):
        self.assertIsNotNone(_roi().find(INTEL_REWARD, "POPUP_GENERIC_REWARD_HEADER"))

    def test_the_daily_and_intel_reward_titles_do_not_resolve_here(self):
        for semantic in ("POPUP_DAILY_REWARD_TITLE", "POPUP_INTEL_REWARD_TITLE",
                         "POPUP_INTEL_REWARD"):
            self.assertIsNone(_roi().find(INTEL_REWARD, semantic), semantic)


if __name__ == "__main__":
    unittest.main()
