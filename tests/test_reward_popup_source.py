"""The client's shared 获得奖励 dialog must not be labelled by its contents.

Defect (measured 2026-09-16T23:53Z and 2026-09-17T00:26Z).  Two live Intel runs
claimed a reward successfully and then failed on the *dismiss* step:

    step 3  INTEL_CLAIM_REWARDS  INTEL -> POPUP  verifier OK   (a reward was claimed)
    step 4  DISMISS_DAILY_REWARD -> INTEL        verifier FALSE
            DAILY_REWARD_ADVANCE_NOT_PROVEN                     (exit 2)

The cause was not the tap: the tap worked and returned to the Intel page.  It was
the label.  ``vision.py`` tested ``POPUP_DAILY_REWARD_CURRENT`` before the generic
banner, and that record's ROI is the whole reward-GRID area
(x 0.08 y 0.20 w 0.84 h 0.40), so it answers "do these items look like the ones I
was cut from" -- a content question -- instead of "who produced this dialog".  It
matched 8 of 8 production frames that carried a reward popup over a non-daily
page, so a reward popup over the Intel page read ``DAILY_REWARD``, the brain
routed it to the *daily* dismiss, and that verifier -- which requires the DAILY
page afterwards -- rejected a dismissal that had actually worked.

What the artwork can and cannot say, measured over 103 labelled production
frames (65 GENERIC_REWARD / 18 INTEL_REWARD / 12 EXPLORATION_REWARD /
8 labelled DAILY_REWARD):

    semantic                          DAILY  EXPLOR  GENERIC  INTEL
    BTN_DISMISS_INTEL_REWARD (footer)    8/8   12/12    65/65  17/18
    POPUP_GENERIC_REWARD_HEADER          5/8    8/12    64/65   1/18
    POPUP_INTEL_REWARD_TITLE (gate 22)   6/8   10/12    58/65  17/18
    POPUP_DAILY_REWARD_CURRENT           8/8    0/12     0/65   0/18
    POPUP_EXPLORATION_REWARD             7/8   12/12     1/65   0/18

Only the footer is present on essentially every one of them (102/103 at
distance <= 2).  Neither the banner nor any grid template identifies a source --
the same dialog is simply drawn for all of them, which is why
``verifier.py`` already carries the comment "the source is therefore proven by
the *before* state ... any reward popup counts as the feedback" and why
``REWARD_POPUPS`` deliberately omits ``DAILY_REWARD``.

So ``vision.py`` now reports the goal-neutral label from the source-independent
signals and lets the brain choose the dismiss from goal context, which is what
every ``*_reward_dismissed`` verifier was already written to accept.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.image_hash import hamming, phash
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_daily_reward_advanced, verify_intel_reward_dismissed
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
KEY = ROOT / "dataset" / "truth_audit" / "reward_popup_source_20260917" / "key"

# One frame per source, all three the same dialog.
DAILY_POPUP = KEY / "01_daily_reward_popup_163338.png"
INTEL_POPUP_RUN1 = KEY / "02_intel_reward_popup_run1.png"
INTEL_POPUP_RUN2 = KEY / "03_intel_reward_popup_run2.png"
POPUPS = (DAILY_POPUP, INTEL_POPUP_RUN1, INTEL_POPUP_RUN2)

# The footer that is drawn on every one of them.  Its manifest name mentions
# Intel because it was registered from an Intel frame; the measurement above is
# what shows the name is a misnomer.
FOOTER = "BTN_DISMISS_INTEL_REWARD"
BANNER = "POPUP_GENERIC_REWARD_HEADER"
GRID = "POPUP_DAILY_REWARD_CURRENT"

FOOTER_BOX = (214, 1135, 510, 1175)
BANNER_BOX = (180, 215, 545, 310)


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST)


def _decide(world: WorldState, goal: str):
    return RuleBrain(current_goal=goal).decide(world, v2_registry())


class TheSharedDialogIsLabelledByItsSignalsNotItsContentsTests(unittest.TestCase):
    def test_every_source_reads_the_shared_label(self):
        """A daily popup and an Intel popup are the same dialog, so they agree."""
        vision = _vision()
        for frame in POPUPS:
            with self.subTest(frame=frame.name):
                state = vision.observe(frame)
                self.assertIs(state.page, Page.POPUP)
                self.assertEqual(state.popup, "GENERIC_REWARD")

    def test_the_footer_is_drawn_on_all_of_them(self):
        """It is the one signal present whatever produced the dialog."""
        vision = _vision()
        for frame in POPUPS:
            with self.subTest(frame=frame.name):
                match = vision.semantic.find(frame, FOOTER)
                self.assertIsNotNone(match)
                self.assertLessEqual(match.distance, 2)

    def test_the_grid_template_is_what_used_to_mislabel_them(self):
        """Pin the defect itself, not only its repair.

        ``POPUP_DAILY_REWARD_CURRENT`` answers a content question -- "do these
        items look like the ones I was cut from" -- so it matched the Intel
        popups a live run produced, and it was tested before the generic banner.
        It does not even match the genuine daily popup in this directory, which is
        the tell that it was never a source detector at all.
        """
        vision = _vision()
        self.assertIsNone(
            vision.semantic.find(DAILY_POPUP, GRID),
            "the record named after the daily reward does not match a daily reward",
        )
        for frame in (INTEL_POPUP_RUN1, INTEL_POPUP_RUN2):
            with self.subTest(frame=frame.name):
                self.assertIsNotNone(
                    vision.semantic.find(frame, GRID),
                    "it matched the Intel popups instead -- the false positive",
                )

    def test_the_artwork_cannot_name_the_source(self):
        """The footer and banner regions are the same drawing in both frames.

        This is why the repair is goal-context rather than a better crop: there
        is no region of this dialog that differs by source.
        """
        from PIL import Image

        daily = Image.open(DAILY_POPUP).convert("RGB")
        intel = Image.open(INTEL_POPUP_RUN2).convert("RGB")
        footer = hamming(
            phash(daily.crop(FOOTER_BOX)), phash(intel.crop(FOOTER_BOX))
        )
        banner = hamming(
            phash(daily.crop(BANNER_BOX)), phash(intel.crop(BANNER_BOX))
        )
        self.assertLessEqual(footer, 6, "the 点击任意位置退出 bar is identical")
        self.assertLessEqual(banner, 8, "the 获得奖励 banner is the same artwork")


class TheBrainChoosesTheDismissFromGoalContextTests(unittest.TestCase):
    """The label is goal-neutral, so the goal has to select the dismiss."""

    def _reward(self) -> WorldState:
        return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)

    def test_an_intel_run_uses_the_intel_dismiss(self):
        decision = _decide(self._reward(), "INTEL")
        self.assertEqual(decision.skill, "DISMISS_INTEL_GENERIC_REWARD")

    def test_a_daily_run_uses_the_daily_dismiss(self):
        decision = _decide(self._reward(), "DAILY")
        self.assertEqual(decision.skill, "DISMISS_DAILY_GENERIC_REWARD")

    def test_the_other_three_goals_that_share_the_dialog_are_covered(self):
        for goal, skill in (("MAIL", "DISMISS_MAIL_GENERIC_REWARD"),
                            ("EXPLORATION", "DISMISS_EXPLORATION_GENERIC_REWARD"),
                            ("ALLIANCE", "DISMISS_ALLIANCE_GENERIC_REWARD")):
            with self.subTest(goal=goal):
                self.assertEqual(_decide(self._reward(), goal).skill, skill)

    def test_without_goal_context_it_stops_rather_than_guessing(self):
        """Documented, not hidden: this is the pre-existing shape.

        Every goal that can produce this dialog is named above; a goal that
        cannot (TRAIN, GATHER, ...) refuses to guess which page it should return
        to.  It already behaved this way for the 64 frames that read
        GENERIC_REWARD before this change.
        """
        decision = _decide(self._reward(), "TRAIN")
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "generic_reward_without_goal_context")


class TheDismissVerifiersAlreadyAcceptTheSharedLabelTests(unittest.TestCase):
    def _reward(self) -> WorldState:
        return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)

    def test_the_intel_dismiss_is_proved_by_the_page_it_returns_to(self):
        intel = WorldState(page=Page.INTEL, popup=None, confidence=0.99)
        self.assertTrue(verify_intel_reward_dismissed(self._reward(), intel).ok)

    def test_the_intel_dismiss_rejects_returning_to_the_wrong_page(self):
        """The exact 2026-09-16 failure: a working dismissal, rejected.

        The daily verifier was run against a popup that sat over the Intel page,
        so it demanded the DAILY page and failed even though the popup was gone.
        """
        daily_page = WorldState(page=Page.DAILY, popup=None, confidence=0.99)
        intel_dismiss = verify_intel_reward_dismissed(self._reward(), daily_page)
        self.assertFalse(intel_dismiss.ok)
        self.assertEqual(intel_dismiss.evidence["after_page"], "DAILY")
        # And the old pairing is exactly what produced DAILY_REWARD_ADVANCE_NOT_PROVEN.
        daily_dismiss = verify_daily_reward_advanced(self._reward(), WorldState(
            page=Page.INTEL, popup=None, confidence=0.99))
        self.assertFalse(daily_dismiss.ok)
        self.assertEqual(daily_dismiss.reason, "DAILY_REWARD_ADVANCE_NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
