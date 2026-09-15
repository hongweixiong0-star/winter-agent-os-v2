"""The Alliance home page must not be reported as the gifts section.

Live defect this file locks down
--------------------------------
Measured 2026-09-15 on the live client: the Alliance home page (联盟, with the
eight entry tiles 联盟战争 / 联盟宝箱 / 联盟领地 / 据点争夺 / 联盟商店 / 联盟科技 /
实力排行 / 联盟互助) was reported as

    page=ALLIANCE   alliance={"section": "GIFTS", "status": "UNKNOWN",
                              "tab": "VICTORY_LOOT", "visible_claim_buttons": 0}

so ``RuleBrain`` always answered ``SAFE_STOP alliance_state_unknown`` for the
ALLIANCE goal -- and the live page carried an unclaimed-gift badge of **99+**
that therefore never got claimed.

Two independent causes had to be fixed.  Neither fix alone is sufficient, and
this file asserts both.

1. Template layer (``SemanticROIVision``).  ``PAGE_ALLIANCE_GIFTS`` matched the
   home page at distance 6 (threshold is the default 8) and was tested *before*
   ``PAGE_ALLIANCE``, so the home page never reached the HOME branch at all.
   Measured over 2757 live frames: ``PAGE_ALLIANCE`` is d=0 on every home frame
   but d>=12 on the gifts / technology / help pages, while
   ``BTN_OPEN_ALLIANCE_GIFTS`` (the 联盟宝箱 entry tile) is d=2 on home and
   d=24-34 on the others.  ``PAGE_ALLIANCE`` alone is not usable -- it also
   matches 79 出征 frames at d=8 -- hence the pair.

2. OCR layer (``OCRPageClassifier``).  It set ``section=GIFTS`` whenever the
   exact text ``联盟宝箱`` was present, and ``联盟宝箱`` is *also* an entry tile
   on the home page: measured, it is an exact token on all 5 home frames AND on
   all 3 gifts frames, so on its own it identifies no page at all.
   ``HybridVision`` then merged the OCR answer *over* the template answer, so
   even a correct template result was overwritten.

Why fix 1 alone is not enough: the template layer itself said GIFTS.
Why fix 2 alone is not enough: OCR overwrote the corrected template answer.

Frames are retained under ``dataset/truth_audit`` because the 2026-09-15 probe
frame was captured into ``dataset/raw/control_panel``, which retention is
allowed to rotate.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import HybridVision
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import (
    verify_alliance_gifts_claimed,
    verify_open_alliance_gifts,
)
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "alliance_gifts_chain_20260915"

HOME_FRAME = ARCHIVE / "01_alliance_home_live_20260915.png"
GIFTS_FRAME = ARCHIVE / "02_alliance_gifts_page_live.png"
TECH_FRAME = ARCHIVE / "03_alliance_tech_page_live.png"
HELP_FRAME = ARCHIVE / "04_alliance_help_page_live.png"
# A 出征 troop-ratio configuration screen: the negative control proving the new
# alliance-home branch does not steal a formation page (it matches
# PAGE_ALLIANCE at d=8 but no alliance entry tile).
FORMATION_FRAME = ARCHIVE / "05_formation_page_negative_control.png"

VISION_SOURCE = ROOT / "winter_agent_v2" / "vision.py"
OCR_SOURCE = ROOT / "winter_agent_v2" / "ocr.py"

HOME_BRANCH = 'if match("PAGE_ALLIANCE") and (match("BTN_OPEN_ALLIANCE_GIFTS") or match("BTN_ALLIANCE_HELP")):'


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST, max_distance=8)


class _StubOCR:
    """Stands in for OCRService: the stub classifier ignores its result."""

    def recognize(self, image_path, roi=None):  # noqa: ANN001 - test double
        return None


class _GiftsClassifier:
    """Reports the wrong section on purpose, exactly as OCR did live.

    The fields it returns are the ones the live OCR layer really produced for
    the home page, so the merge behaviour under test is the real one.
    """

    def classify(self, result):  # noqa: ANN001 - test double
        return WorldState(
            page=Page.ALLIANCE,
            alliance={
                "section": "GIFTS",
                "status": "UNKNOWN",
                "tab": "VICTORY_LOOT",
                "visible_claimed": 0,
                "visible_claim_buttons": 0,
            },
            confidence=0.99,
        )


def _hybrid() -> HybridVision:
    return HybridVision(_vision(), _StubOCR(), _GiftsClassifier())


class AllianceHomeIdentityTests(unittest.TestCase):
    """Cause 1: the template layer must call the home page HOME."""

    def test_the_alliance_home_is_reported_as_home(self) -> None:
        state = _vision().observe(HOME_FRAME)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance.get("section"), "HOME")

    def test_the_gifts_page_is_still_the_gifts_section(self) -> None:
        state = _vision().observe(GIFTS_FRAME)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance.get("section"), "GIFTS")

    def test_the_technology_page_is_unchanged(self) -> None:
        state = _vision().observe(TECH_FRAME)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance.get("section"), "TECHNOLOGY")

    def test_the_help_page_is_unchanged(self) -> None:
        state = _vision().observe(HELP_FRAME)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(state.alliance.get("section"), "HELP")

    def test_the_formation_page_is_not_stolen_by_the_alliance_pair(self) -> None:
        # The negative control for the new branch: this page matches
        # PAGE_ALLIANCE at distance 8, so the branch must require an entry tile
        # as well, or the 出征 page would be reported as the alliance home --
        # the exact regression fixed on 2026-09-15 for a different anchor.
        state = _vision().observe(FORMATION_FRAME)
        self.assertIsNot(state.page, Page.ALLIANCE)
        self.assertIs(state.page, Page.MARCH)

    def test_the_branch_requires_both_the_strip_and_an_entry_tile(self) -> None:
        source = VISION_SOURCE.read_text(encoding="utf-8")
        self.assertIn(HOME_BRANCH, source)

    def test_the_branch_precedes_the_weak_title_strips(self) -> None:
        source = VISION_SOURCE.read_text(encoding="utf-8")
        home = source.index(HOME_BRANCH)
        gifts = source.index('if match("PAGE_ALLIANCE_GIFTS"):')
        tech = source.index('if match("PAGE_ALLIANCE_TECH"):')
        fallback = source.index('if match("PAGE_ALLIANCE"):\n            return WorldState(page=Page.ALLIANCE, alliance={"section": "HOME"}, confidence=0.98)')
        self.assertLess(home, gifts, "the home branch must win before PAGE_ALLIANCE_GIFTS")
        self.assertLess(home, tech, "the home branch must win before PAGE_ALLIANCE_TECH")
        self.assertLess(home, fallback)


class AllianceOcrMergeTests(unittest.TestCase):
    """Cause 2: OCR may enrich fields but must not overwrite the section."""

    def test_ocr_may_not_override_the_template_section(self) -> None:
        state = _hybrid().observe(HOME_FRAME)
        self.assertIs(state.page, Page.ALLIANCE)
        self.assertEqual(
            state.alliance.get("section"),
            "HOME",
            "OCRPageClassifier reads the 联盟宝箱 entry tile as the gifts page; "
            "it must not be allowed to overwrite the template layer's section",
        )

    def test_ocr_still_fills_the_fields_the_template_layer_lacks(self) -> None:
        state = _hybrid().observe(HOME_FRAME)
        # The template layer only knows {"section": "HOME"}; the counters come
        # from OCR and must still arrive, otherwise the fix would have thrown
        # away the very fields the gift chain needs.
        self.assertEqual(state.alliance.get("tab"), "VICTORY_LOOT")
        self.assertEqual(state.alliance.get("visible_claim_buttons"), 0)
        self.assertEqual(state.alliance.get("status"), "UNKNOWN")

    def test_a_gifts_page_still_merges_ocr_over_the_template(self) -> None:
        state = _hybrid().observe(GIFTS_FRAME)
        self.assertEqual(state.alliance.get("section"), "GIFTS")
        self.assertEqual(state.alliance.get("tab"), "VICTORY_LOOT")

    def test_the_merge_keeps_a_template_section_when_ocr_disagrees(self) -> None:
        source = OCR_SOURCE.read_text(encoding="utf-8")
        self.assertIn('if primary.alliance.get("section"):', source)
        self.assertIn('alliance["section"] = primary.alliance["section"]', source)


class AllianceBrainTests(unittest.TestCase):
    def test_the_home_page_dispatches_open_alliance_gifts(self) -> None:
        state = _vision().observe(HOME_FRAME)
        decision = RuleBrain(current_goal="ALLIANCE").decide(state, v2_registry())
        self.assertEqual(decision.skill, "OPEN_ALLIANCE_GIFTS")
        self.assertEqual(decision.reason, "alliance_gifts_badge_visible")

    def test_the_gifts_page_dispatches_the_claim_skill(self) -> None:
        state = _vision().observe(GIFTS_FRAME)
        state = WorldState(
            page=state.page,
            alliance={**state.alliance, "status": "CLAIMABLE"},
            confidence=state.confidence,
        )
        decision = RuleBrain(current_goal="ALLIANCE").decide(state, v2_registry())
        self.assertEqual(decision.skill, "ALLIANCE_GIFTS")


class AllianceGiftChainVerifierTests(unittest.TestCase):
    def test_open_alliance_gifts_passes_across_the_corrected_frames(self) -> None:
        before = _vision().observe(HOME_FRAME)
        after = _vision().observe(GIFTS_FRAME)
        result = verify_open_alliance_gifts(before, after)
        self.assertTrue(result.ok, result.evidence)

    def test_open_alliance_gifts_still_rejects_a_home_before_frame(self) -> None:
        # Before the fix the home page never satisfied `before.section == HOME`,
        # so this verifier could not pass however well the tap worked.
        before = WorldState(page=Page.ALLIANCE, alliance={"section": "GIFTS"}, confidence=0.98)
        after = _vision().observe(GIFTS_FRAME)
        result = verify_open_alliance_gifts(before, after)
        self.assertFalse(result.ok)

    def test_alliance_gifts_has_a_registered_verifier(self) -> None:
        # A skill without a verifier is never dispatched by the live loop, which
        # is why the last step of this chain had never run.
        self.assertIn("ALLIANCE_GIFTS", LiveRuntime.VERIFIED_ATOMIC)

    def test_a_daily_counter_increase_proves_the_claim(self) -> None:
        before = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "GIFTS", "status": "CLAIMABLE", "daily_claimed": 444,
                      "daily_limit": 500, "gift_progress": 71636, "visible_claim_buttons": 4},
            confidence=0.99,
        )
        after = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "GIFTS", "status": "CLAIMABLE", "daily_claimed": 448,
                      "daily_limit": 500, "gift_progress": 71876, "visible_claim_buttons": 0},
            confidence=0.99,
        )
        result = verify_alliance_gifts_claimed(before, after)
        self.assertTrue(result.ok, result.evidence)

    def test_a_reward_overlay_after_the_claim_is_accepted(self) -> None:
        # The client may answer a claim-all with a reward overlay instead of
        # resolving in place; rejecting that would score a real claim as a
        # failure and poison the success rate.
        before = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "GIFTS", "status": "CLAIMABLE", "daily_claimed": 444,
                      "daily_limit": 500, "gift_progress": 71636, "visible_claim_buttons": 4},
            confidence=0.99,
        )
        after = WorldState(page=Page.POPUP, popup="ALLIANCE_GIFT_REWARD", confidence=0.99)
        result = verify_alliance_gifts_claimed(before, after)
        self.assertTrue(result.ok, result.evidence)

    def test_an_unrelated_popup_does_not_prove_a_claim(self) -> None:
        before = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "GIFTS", "status": "CLAIMABLE", "daily_claimed": 444,
                      "daily_limit": 500, "gift_progress": 71636, "visible_claim_buttons": 4},
            confidence=0.99,
        )
        after = WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)
        result = verify_alliance_gifts_claimed(before, after)
        self.assertFalse(result.ok)

    def test_an_unchanged_gifts_page_proves_nothing(self) -> None:
        before = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "GIFTS", "status": "CLAIMABLE", "daily_claimed": 444,
                      "daily_limit": 500, "gift_progress": 71636, "visible_claim_buttons": 4},
            confidence=0.99,
        )
        result = verify_alliance_gifts_claimed(before, before)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "ALLIANCE_GIFTS_CLAIM_NOT_PROVEN")

    def test_a_home_page_before_frame_is_rejected(self) -> None:
        before = WorldState(page=Page.ALLIANCE, alliance={"section": "HOME"}, confidence=0.98)
        after = _vision().observe(GIFTS_FRAME)
        result = verify_alliance_gifts_claimed(before, after)
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
