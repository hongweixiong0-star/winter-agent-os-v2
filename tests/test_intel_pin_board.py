"""The Intel board is a pin map - regression guards for the silent-stop bug.

Live 2026-09-15 07:36 (MuMu 720x1280, com.gof.china): the client showed FIVE
mission pins while production reported

    intel = {"status": "NOT_AVAILABLE", "available_count": 0, "list_read": true}

`goal_library` turns NOT_AVAILABLE into ``CLEAR_INTEL = COMPLETE``, so the
agent stopped believing Intel was finished for the day.  Two separate defects
produced that one reading and both are guarded here:

1. ``intel_pins.intel_pin_centers`` dropped the orange pin whose glow halo
   inflates the blob (measured ratio 0.619-0.644 against a 0.65 floor), so the
   detector saw 4 pins and the board was under-reported even before OCR.
2. ``HybridVision`` decided availability from OCR text alone ("has 下次刷新 but
   no 前往查看 -> empty").  On a pin map the mission card does not exist until a
   pin is tapped, so a full board OCRs as nothing but the header.  The same
   frame's header read ``下次刷新:00:23:06`` while five pins were on screen,
   which is why the countdown is not accepted as a signal either.

The second defect had been *encoded as a test*: the frame filed under
``dataset/truth_audit/intel_beast_target_20260914/03_intel_page_empty_list.png``
was asserted to be NOT_AVAILABLE, and it is in fact a full board carrying
thirteen pins.  That file is now named ``03_intel_page_full_board.png`` and the
assertion lives in ``tests/test_beast_target_card.py``.  The practical
consequence is recorded here so nobody re-derives it: **this project still has
no verified empty intel board.** The one negative sample it believed it had was
a mislabel, so ``NOT_AVAILABLE`` remains unproven and is only ever reached when
the pin detector sights nothing at all.
"""

import unittest
from pathlib import Path

from tests.live_stack import production_vision
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.intel_pins import intel_pin_centers
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.verifier import verify_intel_pin_opened

ROOT = Path(__file__).resolve().parents[1]

# Retained live boards that carry the glow-halo orange pin (screenshots are not
# in git, see .gitignore, so the frame-level guards skip on a fresh machine).
LIVE_BOARD = ROOT / "dataset/truth_audit/intel_pin_board_20260915/01_intel_board_5_pins_live.png"
HALO_BOARD = ROOT / "dataset/truth_audit/intel_beast_target_20260914/03_intel_page_full_board.png"
LIVE_BOARDS = (LIVE_BOARD, HALO_BOARD)

# Published (see the .gitignore whitelist), so the #68 guards run on any machine.
COLOUR_BOARD = (
    ROOT / "dataset" / "truth_audit" / "reward_popup_exit_20260920" / "readings"
    / "intel_page_20260920T131907.png"
)


def _first_existing(paths):
    for path in paths:
        if path.exists():
            return path
    return None


def _pin_board(pins: int, mission_type=None) -> WorldState:
    intel = {"status": "AVAILABLE", "available_count": pins, "pins": pins, "list_read": True}
    if mission_type:
        intel["mission_type"] = mission_type
    return WorldState(page=Page.INTEL, intel=intel, confidence=0.99)


class HaloPinRatioGateTests(unittest.TestCase):
    """The glow halo must not hide a real pin."""

    def test_live_board_reports_the_halo_pin(self):
        frame = _first_existing(LIVE_BOARDS)
        if frame is None:
            self.skipTest("no live intel board on this machine")
        pins = intel_pin_centers(frame)
        self.assertTrue(pins, "a board with visible pins must not read as empty")
        orange = [p for p in pins if p.color == "ORANGE"]
        self.assertTrue(
            orange,
            f"the glow-halo orange pin was dropped again; found {[p.color for p in pins]}",
        )
        # Measured halo ratios span 0.521-0.644 across the six boards seen so
        # far, against a floor of 0.5.  The spread is the halo length, so
        # measuring the pin body instead of the blob is the robust follow-up;
        # the floor only has to hold until then.
        self.assertGreaterEqual(len(pins), 5)


class ProductionIntelAvailabilityTests(unittest.TestCase):
    """Availability must come from the board, not from header text."""

    def test_live_pin_board_reads_available(self):
        frame = _first_existing(LIVE_BOARDS)
        vision = production_vision()
        if frame is None or vision is None:
            self.skipTest("live board or OCR runtime unavailable")
        state = vision.observe(frame)
        self.assertEqual(state.page, Page.INTEL)
        self.assertEqual(state.intel.get("status"), "AVAILABLE")
        self.assertGreaterEqual(int(state.intel.get("pins") or 0), 1)
        self.assertGreaterEqual(int(state.intel.get("available_count") or 0), 1)

    def test_board_with_pins_does_not_complete_the_goal(self):
        from winter_agent_v2.goal_library import GoalLibrary

        goals = {g.goal_id: g for g in GoalLibrary().discover(_pin_board(5))}
        self.assertNotEqual(goals["CLEAR_INTEL"].status.value, "COMPLETE")


class ColourCoverageTests(unittest.TestCase):
    """The mask list is what the detector can SEE, not what the board DRAWS.

    Open issue #68, live 2026-09-20.  The board carried nine teardrop markers and
    ``intel_pin_centers`` returned four.  Cropped and looked at one by one, the
    missed ones are the same object as the counted ones -- teardrop body, white head
    icon, orange base ring -- and differ only in body colour: two GREEN at (541,399)
    and (210,614), two GREY/silver at (104,593) and (344,765).  (A ninth blob at
    (508,410) passes the same filters but is 35 px from (541,399), so the detector's
    own 45 px neighbourhood rule folds it into that pin.)

    This is the third instance of the class this file's module docstring records: a
    bound that drops a real pin silently makes a full board read as empty, and
    ``goal_library`` turns NOT_AVAILABLE into CLEAR_INTEL = COMPLETE.  The frame is
    whitelisted in .gitignore, so unlike the older guards here this one does not
    skip on a fresh clone.
    """

    def test_the_board_is_not_under_counted_where_it_draws_more_colours(self):
        pins = intel_pin_centers(COLOUR_BOARD)
        self.assertTrue(
            {p.color for p in pins} >= {"GREEN", "GREY"},
            f"green or grey pins were dropped again: {sorted(p.color for p in pins)}",
        )
        self.assertGreaterEqual(len(pins), 8)

    def test_the_page_title_is_not_a_pin(self):
        """The mirror failure of the one above, and why GREY carries two bounds.

        The 情报 page title is a neutral blob with white pixels in it and it is on
        essentially every intel frame, so an unbounded grey mask is a title
        detector: 1-2 blobs on 53 of 60 corpus frames, every one of them the title
        (w 165-166 at y 73-85).  A second neutral false positive sits in the top-left
        HUD at y 38-57 on 23 of 435 frames.  A false positive is not cosmetic either
        -- ``available_count`` staying above zero means CLEAR_INTEL can never
        honestly complete.
        """
        pins = intel_pin_centers(COLOUR_BOARD)
        self.assertFalse([p for p in pins if p.y < 200],
                         "the header band was admitted as a pin")
        self.assertFalse([p for p in pins if p.x > 690],
                         "a right-edge blob was admitted as a pin")

    def test_the_neutral_floor_sits_below_every_real_pin_and_above_the_chrome(self):
        """BOARD_TOP is measured, and it is scoped to the neutral class on purpose.

        Over the 435-frame corpus the topmost real pin of ANY colour is y 261 (PURPLE
        at 354,261), and only the neutral mask produced a tap point above 200 -- so a
        floor at 200 removes both neutral false positives without touching a coloured
        pin that a panned board might place higher.  A floor applied to every class
        would be the wrong trade: missing a real coloured pin is the undercount that
        stops the goal honestly completing.
        """
        from winter_agent_v2 import intel_pins

        self.assertEqual(intel_pins.BOARD_TOP, 200)
        pins = intel_pin_centers(COLOUR_BOARD)
        self.assertTrue(all(p.y >= intel_pins.BOARD_TOP for p in pins))
        # the two grey pins this board carries must survive the floor
        grey = [p for p in pins if p.color == "GREY"]
        self.assertTrue(grey, "the floor cut the grey pins it exists to keep honest")

    def test_the_width_bound_sits_between_the_two_measured_populations(self):
        """130 px, because every real pin measured is w 51-107 and the title 165-166."""
        from winter_agent_v2 import intel_pins

        pins = intel_pin_centers(COLOUR_BOARD)
        widest = max(p.area for p in pins)
        self.assertLess(widest, 14000, "still inside max_area")
        # the bound itself must stay above the widest real pin we have measured
        self.assertGreater(intel_pins.intel_pin_centers.__defaults__[-1], 107,
                           "max_width must not cut into the measured pin population")


class PinTapDispatchTests(unittest.TestCase):
    """A board with pins but no open card must produce a tap, not a stop."""

    def test_brain_taps_a_pin_when_the_type_is_unknown(self):
        decision = RuleBrain(current_goal="INTEL").decide(_pin_board(5), v2_registry())
        self.assertEqual(decision.skill, "SELECT_INTEL_PIN")

    def test_read_intel_list_still_used_when_no_pin_was_sighted(self):
        # Regression guard for branch ordering: without a pin sighting the
        # historical candidate read must still be chosen.
        state = WorldState(page=Page.INTEL, intel={"status": "AVAILABLE"}, confidence=0.9)
        self.assertEqual(
            RuleBrain(current_goal="INTEL").decide(state, v2_registry()).skill,
            "READ_INTEL_LIST",
        )

    def test_a_known_mission_type_still_uses_its_reviewed_skill(self):
        decision = RuleBrain(current_goal="INTEL").decide(_pin_board(5, "BEAST"), v2_registry())
        self.assertEqual(decision.skill, "SELECT_INTEL_BEAST_MISSION")

    def test_skill_is_registered_and_dispatchable(self):
        self.assertIsNotNone(v2_registry().get("SELECT_INTEL_PIN"))
        self.assertIn("SELECT_INTEL_PIN", LiveRuntime.VERIFIED_ATOMIC)


class PinOpenedVerifierTests(unittest.TestCase):
    def test_card_opened_is_proven(self):
        after = WorldState(page=Page.POPUP, popup="INTEL_BEAST_MISSION", confidence=0.99)
        self.assertTrue(verify_intel_pin_opened(_pin_board(5), after).ok)

    def test_blocked_card_still_counts_as_opened(self):
        # 大师悬赏 opens with status BLOCKED (power 189M).  The tap did reach
        # the mission; backing out is the brain's decision, not the verifier's.
        after = WorldState(page=Page.POPUP, popup="INTEL_MASTER_BOUNTY", confidence=0.99)
        self.assertTrue(verify_intel_pin_opened(_pin_board(5), after).ok)

    def test_tap_into_snow_is_not_a_success(self):
        after = WorldState(page=Page.INTEL, intel={"status": "AVAILABLE", "pins": 5}, confidence=0.99)
        result = verify_intel_pin_opened(_pin_board(5), after)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "INTEL_PIN_CARD_NOT_OPENED")

    def test_no_pin_sighted_blocks_the_tap(self):
        before = WorldState(page=Page.INTEL, intel={"status": "NOT_AVAILABLE"}, confidence=0.9)
        after = WorldState(page=Page.POPUP, popup="INTEL_BEAST_MISSION", confidence=0.99)
        self.assertFalse(verify_intel_pin_opened(before, after).ok)

    def test_unreviewed_popup_is_not_a_mission_card(self):
        after = WorldState(page=Page.POPUP, popup="INTEL_REWARD", confidence=0.99)
        self.assertFalse(verify_intel_pin_opened(_pin_board(5), after).ok)


if __name__ == "__main__":
    unittest.main()
