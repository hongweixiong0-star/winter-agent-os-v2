"""The 出征 formation page must be identified by its own anchors, not by a button.

Live defect this file locks down
--------------------------------
Episode ``intel_pins_20260915_000822_nav_01`` recorded
``INTEL_BEAST_START_MARCH`` -> ``INTEL_BEAST_MARCH_NOT_PROVEN`` at
2026-09-15T00:14:13Z.  The tap had in fact opened exactly the right page (the
出征 formation screen with 本次出征胜券在握), but ``state_after`` was
``page=ALLIANCE, alliance={"section":"HOME"}``.

Root cause, measured on the two frames of that one page:

    semantic                    frame A (success)   frame B (this failure)
    BTN_BEAST_DISPATCH          d =  0  MATCH        d = 26  no match
    PAGE_BEAST_MARCH            d =  0  MATCH        d =  0  MATCH
    STATUS_VICTORY_ASSURED      d =  0  MATCH        d =  0  MATCH
    PAGE_ALLIANCE               d =  8  MATCH        d =  8  MATCH

``BTN_BEAST_DISPATCH`` is an animated button, so its perceptual hash drifts
across the default threshold of 8.  When it missed, the next branch that
matched was the ``PAGE_ALLIANCE`` *title strip* (distance 8) and the page was
reported as the alliance home.  The two reviewed anchors that actually belong
to this page -- ``PAGE_BEAST_MARCH`` and ``STATUS_VICTORY_ASSURED``, both
extracted from ``dataset/raw/live_beast_march_selection.png`` -- were present in
the manifest but referenced by no branch at all, so they could not win.

The frames are retained under ``dataset/truth_audit`` because the originals live
in ``dataset/raw/control_panel``, which retention is allowed to rotate.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_intel_beast_march_open
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "beast_formation_page_20260915"
FORMATION_AFTER = ARCHIVE / "01_formation_page_misread_as_alliance_live.png"
TARGET_BEFORE = ARCHIVE / "02_beast_target_card_before_live.png"
REVIEWED_FORMATION = ROOT / "dataset" / "raw" / "live_beast_march_selection.png"
REAL_ALLIANCE_HOME = ROOT / "dataset" / "raw" / "live_alliance_home_2.png"
# A 出征 *configuration* screen (troop ratio preset) that carries the same 出征
# title strip but shows no 本次出征胜券在握 line.  Measured 2026-09-15: it matches
# PAGE_BEAST_MARCH at distance 0 but STATUS_VICTORY_ASSURED at distance 30.
TITLE_ONLY_FORMATION = ROOT / "dataset" / "raw" / "bear_live_20260909" / "auto_join_formation.png"


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST, max_distance=8)


class FormationPageIdentityTests(unittest.TestCase):
    def test_the_formation_page_is_not_reported_as_the_alliance_home(self) -> None:
        state = _vision().observe(FORMATION_AFTER)
        self.assertIs(state.page, Page.MARCH)
        self.assertNotEqual(state.alliance.get("section"), "HOME")

    def test_the_formation_page_asserts_only_the_safety_fact_it_shows(self) -> None:
        state = _vision().observe(FORMATION_AFTER)
        self.assertIs(state.beast.get("victory_assured"), True)
        # The formation page does not display the target's name or level, so
        # claiming either would be an invention.  The neighbouring
        # BTN_BEAST_DISPATCH branch hard-codes 大角鹿/22 and must not be reached
        # for a beast it does not describe.
        self.assertNotIn("name", state.beast)
        self.assertNotIn("level", state.beast)

    def test_the_recovered_pair_satisfies_the_march_verifier(self) -> None:
        before = _vision().observe(TARGET_BEFORE)
        after = _vision().observe(FORMATION_AFTER)
        self.assertIs(before.page, Page.BEAST)
        self.assertEqual(before.beast.get("mission_id"), "INTEL_BEAST_10")
        result = verify_intel_beast_march_open(before, after)
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.reason, "OK")

    def test_the_brain_dispatches_the_intel_march_from_the_recovered_state(self) -> None:
        after = _vision().observe(FORMATION_AFTER)
        decision = RuleBrain(current_goal="INTEL").decide(after, v2_registry())
        self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")


class FormationPageNegativeControlsTests(unittest.TestCase):
    """The new branch must not steal pages it does not own."""

    def test_a_real_alliance_home_is_still_an_alliance_page(self) -> None:
        # live_alliance_home_2.png is the source frame of the PAGE_ALLIANCE
        # title strip.  It legitimately resolves to the alliance GIFTS section,
        # so only the page identity is asserted here -- the point is that it
        # must not become MARCH.
        state = _vision().observe(REAL_ALLIANCE_HOME)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertNotEqual(state.page, Page.MARCH)

    def test_the_reviewed_formation_frame_keeps_its_original_identity(self) -> None:
        # This frame is the source of both anchors.  It already matched the
        # reviewed 麝牛 level-9 branch before this change, and that branch must
        # keep winning: the new branch is a fallback, not a replacement.
        state = _vision().observe(REVIEWED_FORMATION)
        self.assertIs(state.page, Page.MARCH)
        self.assertEqual(state.beast.get("level"), 9)
        self.assertIs(state.beast.get("victory_assured"), True)

    def test_the_title_strip_alone_never_claims_victory_assured(self) -> None:
        # ``victory_assured`` is what authorises a real dispatch, so it may only
        # ever be asserted when the client actually draws the safety line.
        # Measured over the whole corpus on 2026-09-15: of the 83 frames where
        # either anchor matched, 75 already resolved to MARCH (unchanged) and 8
        # to ALLIANCE; only the 5 that matched BOTH anchors are re-decided, and
        # all 5 are the same beast formation page.  This frame is one of the
        # three that match the title strip only, and it must not be promoted.
        state = _vision().observe(TITLE_ONLY_FORMATION)
        self.assertFalse(
            state.page is Page.MARCH and state.beast.get("victory_assured") is True,
            "a 出征 title without the 胜券在握 line must not authorise a dispatch",
        )


class FormationPageBranchOrderTests(unittest.TestCase):
    """Source-level guards: the fix must stay narrow and stay ordered."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "winter_agent_v2" / "vision.py").read_text(encoding="utf-8")

    def test_both_reviewed_anchors_are_required(self) -> None:
        # Requiring only the 出征 title strip would claim the formation page on
        # any screen that shares that title, so the pair must be demanded.
        self.assertIn(
            'if match("PAGE_BEAST_MARCH") and match("STATUS_VICTORY_ASSURED"):',
            self.source,
        )

    def test_the_fallback_is_placed_after_the_verified_button_branch(self) -> None:
        button = self.source.index('if match("BTN_BEAST_DISPATCH"):')
        fallback = self.source.index('if match("PAGE_BEAST_MARCH") and match("STATUS_VICTORY_ASSURED"):')
        alliance = self.source.index('if match("PAGE_ALLIANCE"):')
        self.assertLess(button, fallback, "the live-verified button branch must win when it matches")
        self.assertLess(fallback, alliance, "the formation page must be decided before the alliance title strip")


if __name__ == "__main__":
    unittest.main()
