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


if __name__ == "__main__":
    unittest.main()
