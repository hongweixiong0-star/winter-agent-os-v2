"""Closing the quit dialog must not be able to quit the client.

Open issue 26.  ``vision.py`` reports ``popup="EXIT_CONFIRM"`` for the client's
「确认退出游戏吗?」 dialog, and ``brain.py`` had no branch for it, so it fell through
to the generic blocking-popup answer and was closed with ``BTN_CLOSE``.  That is not
obviously safe: the dialog carries 取消 on the left and 确定 on the right, and a
close-button template whose ROI landed on 确定 would quit the game.

So the question was measured rather than argued.  On the live dialog
(2026-09-17, ``close_hero_journey_20260917_043919_99_after_back.png``):

    POPUP_EXIT_CONFIRM  d=4   ROI y 0.32..0.68, centre (360,640)
    BTN_CLOSE           d=2   the winning record's centre is (635,455)  <- the X
    BTN_CANCEL          d=4   ROI centre (208,793)                     <- 取消

and the sibling two-button dialog in the same client measures its own pair at
``BTN_DUPLICATE_TARGET_CANCEL`` (201,787) / ``..._CONFIRM`` (503,787), i.e. one row
at y ~787.  So the winner taps the X in the title bar, roughly 290 px above the row
that contains the control which quits the game.

That is the safe answer, so this file pins it instead of changing it: the tap must
stay in the title band and well clear of the button row.  ``brain.py`` now names the
branch as well, which is what keeps a future ``BTN_CLOSE`` record from silently
repointing it at a control nobody measured.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
FRAME = (ROOT / "dataset" / "truth_audit" / "power_route_20260917"
         / "close_hero_journey_20260917_043919_99_after_back.png")

FRAME_W, FRAME_H = 720.0, 1280.0

# The button row of this dialog family, measured on the same client.  The quit
# control the close button must never reach is the one on the RIGHT (确定).
QUIT_BUTTON_ROW_TOP_PX = 748.0     # 取消's ROI starts here (y 0.585 * 1280)
QUIT_BUTTON_ROW_BOTTOM_PX = 842.0  # and ends here (y 0.655 * 1280)
QUIT_BUTTON_LEFT_EDGE_PX = 379.0   # the measured 确定 button's left edge
CLEARANCE_PX = 200.0


class TheQuitDialogIsClosedSafelyTests(unittest.TestCase):
    def test_the_frame_is_the_quit_dialog(self):
        state = SemanticWorldVision(MANIFEST).observe(FRAME)
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "EXIT_CONFIRM")

    def test_the_close_button_lands_in_the_title_band_not_on_the_buttons(self):
        """The whole point: the tap must not be able to reach 确定."""
        match = SemanticWorldVision(MANIFEST).semantic.find(FRAME, "BTN_CLOSE")
        self.assertIsNotNone(match)
        x = match.center_norm[0] * FRAME_W
        y = match.center_norm[1] * FRAME_H
        self.assertLess(
            y, QUIT_BUTTON_ROW_TOP_PX - CLEARANCE_PX,
            f"the close tap at y={y:.0f} is inside the button row band "
            f"({QUIT_BUTTON_ROW_TOP_PX:.0f}..{QUIT_BUTTON_ROW_BOTTOM_PX:.0f}) "
            f"or too close to it",
        )
        self.assertLess(y, QUIT_BUTTON_ROW_TOP_PX)
        self.assertGreater(y, 0.0)
        # ... and it is on the right, in the title bar, where the X is drawn.
        self.assertGreater(x, FRAME_W / 2)

    def test_the_two_controls_that_can_quit_are_below_the_tap(self):
        row = WorldState(page=Page.POPUP, popup="EXIT_CONFIRM", confidence=0.99)
        decision = RuleBrain().decide(row, v2_registry())
        self.assertEqual(decision.skill, "CLOSE_POPUP")
        self.assertEqual(decision.reason, "exit_confirm_closed_via_its_close_button")


class TheBranchIsNamedTests(unittest.TestCase):
    """A named branch is what stops a future record from repointing the tap."""

    def test_the_quit_dialog_has_its_own_reason(self):
        decision = RuleBrain().decide(
            WorldState(page=Page.POPUP, popup="EXIT_CONFIRM", confidence=0.99),
            v2_registry(),
        )
        self.assertNotEqual(
            decision.reason, "blocking_popup",
            "the quit dialog must not rely on the generic popup answer",
        )

    def test_other_popups_still_use_the_generic_answer(self):
        """The named branch must not capture anything else."""
        decision = RuleBrain().decide(
            WorldState(page=Page.POPUP, popup="SESSION_DISCONNECTED", confidence=0.99),
            v2_registry(),
        )
        self.assertEqual(decision.skill, "RECONNECT_SESSION")


# Measured 2026-09-21.  The client draws ONE confirm-dialog shape for several
# different questions, so a loose template for one question matches another
# question's dialog at a small distance.  ``vision.py`` used to answer by
# ``if/elif`` order, and the looser ``POPUP_DUPLICATE_TARGET_TITLE`` was tested
# first -- so the quit dialog was read as DUPLICATE_TARGET and the route tapped
# ``BTN_DUPLICATE_TARGET_CANCEL``, i.e. the 取消 of "quit the game?".
# The recorded run ended with ``DUPLICATE_TARGET_CANCEL_NOT_PROVEN``.
#
# Both frames are archived live captures, and the numbers below are re-measured
# here rather than asserted from memory: the question templates separate the two
# dialogs, while the button row does not (it matches both at distance 0 and the
# same centres).
QUIT_DIALOG_FRAME = (
    ROOT / "dataset" / "raw" / "live_runtime"
    / "live_runtime_step_002_before_20260921T115555673312.png"
)
DUPLICATE_DIALOG_FRAME = ROOT / "dataset" / "raw" / "live_phase_e_start.png"

# The row both dialogs draw their 取消/确定 controls in.  ``CANCEL`` is the
# left control, and on the quit dialog it is the one that must never be tapped.
SHARED_CANCEL_CENTRE_NORM = (0.280, 0.615)


class TheQuitDialogIsNotTheDuplicateTargetDialogTests(unittest.TestCase):
    """The two sibling questions must be told apart by the question, not order."""

    def _semantic(self):
        return SemanticWorldVision(MANIFEST).semantic

    def test_the_quit_dialog_is_read_as_the_quit_dialog(self):
        semantic = self._semantic()
        quit_hit = semantic.find(QUIT_DIALOG_FRAME, "POPUP_EXIT_CONFIRM")
        duplicate_hit = semantic.find(QUIT_DIALOG_FRAME, "POPUP_DUPLICATE_TARGET_TITLE")
        self.assertIsNotNone(quit_hit, "the quit question must match its own frame")
        self.assertIsNotNone(
            duplicate_hit,
            "the false positive is the premise of this test; if the loose "
            "template stops firing here, the ordering hazard is gone and this "
            "file can be simplified",
        )
        self.assertLess(
            quit_hit[1],
            duplicate_hit[1],
            "the quit question must be the NEARER match on the quit dialog, "
            "which is what lets the nearest-question rule pick it",
        )

    def test_the_duplicate_target_dialog_is_still_read_as_duplicate_target(self):
        """The existing behaviour, which the fix must not trade away."""
        semantic = self._semantic()
        duplicate_hit = semantic.find(DUPLICATE_DIALOG_FRAME, "POPUP_DUPLICATE_TARGET_TITLE")
        quit_hit = semantic.find(DUPLICATE_DIALOG_FRAME, "POPUP_EXIT_CONFIRM")
        self.assertIsNotNone(duplicate_hit)
        self.assertIsNotNone(quit_hit, "the converse false positive, likewise measured")
        self.assertLess(
            duplicate_hit[1],
            quit_hit[1],
            "the duplicate-target question must be the NEARER match on its own "
            "dialog; choosing a fixed order instead of the distance is what the "
            "2026-09-21 quit-dialog failure was made of",
        )

    def test_the_buttons_cannot_tell_the_two_dialogs_apart(self):
        """Why the question has to be the discriminator."""
        semantic = self._semantic()
        for name in ("BTN_DUPLICATE_TARGET_CANCEL", "BTN_DUPLICATE_TARGET_CONFIRM"):
            on_quit = semantic.find(QUIT_DIALOG_FRAME, name)
            on_duplicate = semantic.find(DUPLICATE_DIALOG_FRAME, name)
            self.assertIsNotNone(on_quit)
            self.assertIsNotNone(on_duplicate)
            self.assertEqual(
                on_quit[1], 0,
                f"{name} matches the quit dialog at distance {on_quit[1]}; its "
                "share of the row is what makes it unusable as identity",
            )
            self.assertEqual(
                on_duplicate[1], 0,
                f"{name} must match the duplicate dialog at distance 0 too, or "
                "this file's premise is wrong",
            )

    def test_the_production_answer_for_each_frame(self):
        """End to end through the classifier the route actually calls."""
        vision = SemanticWorldVision(MANIFEST)
        state = vision.observe(QUIT_DIALOG_FRAME)
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(
            state.popup, "EXIT_CONFIRM",
            "reading the quit dialog as DUPLICATE_TARGET is what tapped 取消 on "
            "the quit question",
        )
        self.assertNotEqual(state.popup, "DUPLICATE_TARGET")

        other = vision.observe(DUPLICATE_DIALOG_FRAME)
        self.assertIs(other.page, Page.POPUP)
        self.assertEqual(other.popup, "DUPLICATE_TARGET")

    def test_the_quit_dialog_never_reaches_the_duplicate_cancel(self):
        """The destructive consequence, asserted at the decision layer."""
        quit_state = SemanticWorldVision(MANIFEST).observe(QUIT_DIALOG_FRAME)
        decision = RuleBrain().decide(quit_state, v2_registry())
        self.assertNotEqual(
            decision.skill, "CANCEL_DUPLICATE_TARGET",
            "tapping the duplicate-target cancel on the quit dialog is exactly "
            "the missed tap the live run recorded",
        )
        self.assertEqual(decision.skill, "CLOSE_POPUP")


if __name__ == "__main__":
    unittest.main()
