"""The client states affordability by the colour of the cost itself.

Measured 2026-09-15 (``tools/probe_cost_colour.py``): a stamina cost is drawn
**white** when it can be paid and **red** when it cannot, on three different
cost-bearing buttons.  Red pixels appear on exactly the frames where stamina is
below the displayed cost, and the affordable frames contain *zero* red pixels:

    ================================  =======  ====  =======
    frame                             stamina  cost  red px
    ================================  =======  ====  =======
    beast dispatch (live 04:11:16Z)   0        10    452
    hero camp panel                   7        10    220
    hero camp panel                   16       10    0
    hero squad page (dispatched)      10       10    0
    beast dispatch (template source)  payable  10    0
    ================================  =======  ====  =======

Why this matters: the HUD gauge OCR is *not* available in exactly these cases.
Its ROI reads only 19 of 25 camp-panel frames, and a genuine ``0`` -- the most
important case, because that is when the free gift matters most -- reads nothing
at all at any padding or scale (``tools/probe_stamina_zero.py``: best confidence
0.73, flipping between '0' and 'O').  The colour needs no OCR and no arithmetic.

These tests read real frames through the production stack, because a synthetic
pixel cannot show that the client really does this.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import unaffordable_cost_pixels
from winter_agent_v2.skills import v2_registry

from tests.live_stack import production_vision

ROOT = Path(__file__).resolve().parents[1]

CAMP_BLOCKED = ROOT / "dataset/truth_audit/camp_panel_stamina_gate_20260915/03_camp_panel_unaffordable_live.png"
CAMP_AFFORDABLE = ROOT / "dataset/truth_audit/camp_panel_stamina_gate_20260915/01_camp_panel_stamina_read_live.png"
DISPATCH_BLOCKED = (
    ROOT / "dataset/raw/live_zero_stamina_claim_20260915"
    / "live_zero_stamina_claim_20260915_step_007_before_20260915T041114783780.png"
)

CAMP_COST = 10
CAMP_FIGHT_ROI = {"x_norm": 0.3542, "y_norm": 0.4648, "w_norm": 0.2986, "h_norm": 0.0602}


def _camp_panel(stamina: dict | None = None, cost: int = CAMP_COST) -> WorldState:
    return WorldState(
        page=Page.EXPLORATION,
        exploration={"stamina_cost_displayed": cost},
        stamina=dict(stamina or {}),
        confidence=0.99,
    )


class TheClientReallyDoesColourTheCostTests(unittest.TestCase):
    def test_a_cost_that_cannot_be_paid_is_drawn_red(self):
        for path, stamina in ((CAMP_BLOCKED, 7), (DISPATCH_BLOCKED, 0)):
            with self.subTest(frame=path.name, stamina=stamina):
                self.assertTrue(path.is_file(), f"evidence frame missing: {path}")
                roi = CAMP_FIGHT_ROI if path is CAMP_BLOCKED else {
                    "x_norm": 0.56, "y_norm": 0.914, "w_norm": 0.405, "h_norm": 0.07,
                }
                self.assertIs(unaffordable_cost_pixels(path, roi), True)

    def test_a_cost_that_can_be_paid_has_no_red_at_all(self):
        # Not "mostly white" -- zero red pixels, in both camp panels we own.
        self.assertIs(unaffordable_cost_pixels(CAMP_AFFORDABLE, CAMP_FIGHT_ROI), False)

    def test_an_out_of_frame_roi_never_looks_affordable(self):
        # A verdict that cannot be read must not authorise spending.
        for roi in ({"x_norm": 0.98, "y_norm": 0.98, "w_norm": 0.5, "h_norm": 0.5},
                    {"x_norm": 0.0, "y_norm": 0.0, "w_norm": 0.0, "h_norm": 0.0}):
            with self.subTest(roi=roi):
                self.assertIsNone(unaffordable_cost_pixels(CAMP_BLOCKED, roi))


@unittest.skipUnless(production_vision() is not None, "OCR runtime unavailable")
class TheCampPanelReportsTheVerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()

    def test_the_unaffordable_panel_reports_it_without_any_gauge_read(self):
        state = self.vision.observe(CAMP_BLOCKED)
        self.assertEqual(state.page.value, "EXPLORATION")
        self.assertEqual(state.exploration.get("stamina_cost_displayed"), CAMP_COST)
        self.assertIs(state.stamina.get("cost_affordable"), False)
        self.assertEqual(state.stamina.get("cost_verdict_source"), "BUTTON_COST_COLOUR")

    def test_the_affordable_panel_reports_that_too(self):
        state = self.vision.observe(CAMP_AFFORDABLE)
        self.assertIs(state.stamina.get("cost_affordable"), True)


class TheBrainObeysTheColourTests(unittest.TestCase):
    def _decide(self, world, **kwargs):
        kwargs.setdefault("claim_free_stamina", True)
        brain = RuleBrain(current_goal="INTEL", **kwargs)
        return brain, brain.decide(world, v2_registry())

    def test_a_red_cost_blocks_even_when_the_gauge_could_not_be_read(self):
        # This is the case the gauge could never cover: no number at all.
        brain, decision = self._decide(_camp_panel({"cost_affordable": False}))
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.reason, "camp_fight_unaffordable_go_get_free_stamina")
        self.assertTrue(brain.unaffordable_camp_panel_left)

    def test_a_white_cost_never_blocks_a_payable_fight(self):
        _, decision = self._decide(
            _camp_panel({"current": 150, "source": "CAMP_PANEL_HUD", "cost_affordable": True})
        )
        self.assertEqual(decision.skill, "INTEL_HERO_START_MARCH")

    def test_an_unmeasured_verdict_does_not_block(self):
        # ``None`` means "not measured" -- it must not be read as "red".
        for value in (None, True):
            with self.subTest(cost_affordable=value):
                _, decision = self._decide(
                    _camp_panel({"current": 150, "source": "CAMP_PANEL_HUD", "cost_affordable": value})
                )
                self.assertEqual(decision.skill, "INTEL_HERO_START_MARCH")

    def test_the_colour_outranks_a_wrong_gauge_reading(self):
        # If the gauge were misread high, the colour is still the client's own
        # verdict and must win: tapping here would be refused.
        _, decision = self._decide(_camp_panel({"current": 300, "cost_affordable": False}))
        self.assertEqual(decision.skill, "BACK")


if __name__ == "__main__":
    unittest.main()
