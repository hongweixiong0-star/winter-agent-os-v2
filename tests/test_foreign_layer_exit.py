"""A layer that ignores a Back must still not cost the cycle its work.

Measured live on 2026-09-21, and the measurement is the whole argument.

``KEEP_TRAINING_PRODUCTIVE`` opened on the alliance chest layer -- page ALLIANCE, a
sub-page with its own X in the top-right corner -- and the sweep's one leave-a-foreign-page
hop is a Back:

    before  page ALLIANCE  ->  PRESS_BACK  ->  after  page ALLIANCE  (confidence 0.98)
    verifier  SAFE_BACK_NOT_PROVEN

Two costs, and the second is the one that mattered.  The first is that the run ended, which
is the defect the SAFE_STOP handover already fixes elsewhere.  The second is that
``foreign_page_left`` had already been set on the way past, so from that run onward the
training route answered ``training_entry_not_verified`` without even trying: one unmovable
layer cost the cycle its training work PERMANENTLY, across every following run, until a
human noticed.

The fix is an ordered pair inside the existing hop -- Back, which is correct on every panel
measured so far and cheap; then the close the client itself draws, bound to its own verifier
-- and it is deliberately bounded at two, so a layer that answers neither still falls
through to an honest stop rather than becoming a spin.

These tests pin the shape of that sequence and the verifier that judges it.  What they
cannot prove is that the client answers the close; only a live frame can, and that is what
the truth-audit directory is for.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.verifier import verify_left_foreign_layer  # noqa: E402


def _alliance_layer() -> WorldState:
    """The frame the Back did not move: a definite, known, non-POPUP page."""
    return WorldState(page=Page.ALLIANCE, confidence=0.98)


def _known(page: Page) -> WorldState:
    return WorldState(page=page, confidence=0.99)


class ThePairIsOrderedAndBounded(unittest.TestCase):
    def test_back_comes_first_then_the_close(self) -> None:
        brain = RuleBrain(current_goal="TRAIN")
        world = _alliance_layer()

        first = brain._leave_foreign_page_once(world, owner="TRAIN")
        self.assertIsNotNone(first)
        self.assertEqual(first.skill, "BACK")

        second = brain._leave_foreign_page_once(world, owner="TRAIN")
        self.assertIsNotNone(second, "the layer ignored the Back; the close is the second try")
        self.assertEqual(second.skill, "LEAVE_FOREIGN_LAYER")

    def test_a_third_call_gives_up_rather_than_spinning(self) -> None:
        brain = RuleBrain(current_goal="TRAIN")
        world = _alliance_layer()

        self.assertIsNotNone(brain._leave_foreign_page_once(world, owner="TRAIN"))
        self.assertIsNotNone(brain._leave_foreign_page_once(world, owner="TRAIN"))
        self.assertIsNone(
            brain._leave_foreign_page_once(world, owner="TRAIN"),
            "a layer that answers neither exit must fall through to the caller's honest stop",
        )

    def test_the_close_is_told_apart_from_the_back_by_its_reason(self) -> None:
        """The two decisions must not be reported as the same event.

        The operator reads these lines; "leaves_a_panel" and "closes_a_layer_a_back_did_not_move"
        are different statements, and collapsing them would hide which exit was needed.
        """
        brain = RuleBrain(current_goal="TRAIN")
        world = _alliance_layer()

        first = brain._leave_foreign_page_once(world, owner="TRAIN")
        second = brain._leave_foreign_page_once(world, owner="TRAIN")
        self.assertNotEqual(first.reason, second.reason)
        self.assertIn("leaves_a_panel", first.reason)
        self.assertIn("closes_a_layer", second.reason)
        self.assertIn("train", first.reason)
        self.assertIn("train", second.reason)


class TheVerifierJudgesTheRightThing(unittest.TestCase):
    def test_leaving_the_layer_is_proven_by_a_different_known_page(self) -> None:
        result = verify_left_foreign_layer(_alliance_layer(), _known(Page.HOME))
        self.assertTrue(result.ok, result.reason)

    def test_an_unmoved_client_is_not_proven(self) -> None:
        result = verify_left_foreign_layer(_alliance_layer(), _alliance_layer())
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "FOREIGN_LAYER_NOT_LEFT")

    def test_a_page_that_could_not_be_read_afterwards_is_not_proof(self) -> None:
        """UNKNOWN after is evidence of nothing, and calling it success is how a loop forms."""
        after = WorldState(page=Page.UNKNOWN, confidence=0.0)
        result = verify_left_foreign_layer(_alliance_layer(), after)
        self.assertFalse(result.ok)

    def test_two_unknowns_do_not_satisfy_it(self) -> None:
        """Without a definite start, ``after.page is not before.page`` would be free."""
        result = verify_left_foreign_layer(
            WorldState(page=Page.UNKNOWN, confidence=0.0), _known(Page.HOME)
        )
        self.assertFalse(result.ok)

    def test_a_popup_start_is_left_to_the_popup_verifier(self) -> None:
        """POPUP closings already have a verifier; this one is for pages that are not."""
        before = WorldState(page=Page.POPUP, popup="SOMETHING", confidence=0.99)
        result = verify_left_foreign_layer(before, _known(Page.HOME))
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
