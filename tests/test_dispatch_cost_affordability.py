"""An unaffordable dispatch is a spending decision, not a lost control.

Origin (2026-09-15).  Four recorded beast dispatches failed with
``SEMANTIC_TARGET_NOT_VERIFIED`` on the formation page.  That reason means "the
executor's target resolver returned nothing", and it had twice sent earlier
sessions hunting a stale template or a wrong coordinate.  It was neither.  The
出征 control was on screen and plainly visible in all four frames; its stamina
cost was painted **red** because the account could not pay, and a red digit is
what moved the reviewed template off its match:

    ===========  ===  ===============  =============  ===========
    result         n  phash distance   strong red px  client says
    ===========  ===  ===============  =============  ===========
    success       25  0 (identical)    0              affordable
    failure        4  26 (identical)   452            unaffordable
    ===========  ===  ===============  =============  ===========

The threshold is 8, so 26 is not a near miss -- it is a different picture, and
the same picture four times.  The affordable frames match at distance 0.

The same red/white signal already gates the hero camp panel
(``tests/test_cost_colour_verdict.py``); this file covers the other cost-bearing
control, and pins down the two things that matter: Vision must record the
client's verdict on the formation page, and the brain must refuse to pay it --
while never reading an unmeasured verdict as a refusal.

Frames are real live-client captures copied into ``dataset/truth_audit`` because
``dataset/raw`` is machine-local and not in git.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.image_hash import hamming, phash
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.ocr import unaffordable_cost_pixels
from winter_agent_v2.runtime_snapshot import is_fatal_stop
from winter_agent_v2.skills import v2_registry

from tests.live_stack import production_vision

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "dataset/truth_audit/beast_dispatch_cost_colour_20260915"

# The registered ROI Vision reads the verdict from, and the reviewed template the
# dispatches used to be matched against.
ROI = {"x_norm": 0.56, "y_norm": 0.914, "w_norm": 0.405, "h_norm": 0.07}
TEMPLATE = ROOT / "dataset/candidate/templates/btn_beast_dispatch__live_beast_march_selection__2.png"
MATCH_THRESHOLD = 8

UNAFFORDABLE = tuple(sorted((EVIDENCE).glob("*_unaffordable_*.png")))
AFFORDABLE = tuple(sorted((EVIDENCE).glob("*_affordable_*.png")))

# The frames themselves are machine-local: .gitignore keeps
# ``dataset/truth_audit/**/*.png`` out of the repository (a recorded project
# limitation -- live evidence is not portable).  The structured record *is*
# committed.  So the pixel tests skip where the frames cannot exist, instead of
# reporting a regression that has nothing to do with the code.
FRAMES_PRESENT = (
    len(UNAFFORDABLE) == 4 and len(AFFORDABLE) == 2 and TEMPLATE.is_file()
)
REQUIRES_FRAMES = unittest.skipUnless(FRAMES_PRESENT, "live evidence frames not on this machine")


def _records() -> dict:
    return json.loads((EVIDENCE / "live_ab_records.json").read_text(encoding="utf-8"))


def _formation(**stamina) -> WorldState:
    """The intel beast formation page with the measured safety strip."""
    return WorldState(
        page=Page.MARCH,
        beast={"victory_assured": True, "target_kind": "INTEL"},
        stamina=dict(stamina),
        confidence=0.99,
    )


def _gather_formation(**stamina) -> WorldState:
    return WorldState(
        page=Page.MARCH,
        resource_target="COAL",
        stamina=dict(stamina),
        confidence=0.99,
    )


@REQUIRES_FRAMES
class TheEvidenceIsTheRealThingTests(unittest.TestCase):
    def test_the_archive_carries_both_populations(self):
        self.assertEqual(len(UNAFFORDABLE), 4, UNAFFORDABLE)
        self.assertEqual(len(AFFORDABLE), 2, AFFORDABLE)
        self.assertTrue(TEMPLATE.is_file(), TEMPLATE)


class TheRecordedMeasurementTests(unittest.TestCase):
    """The committed record must keep saying what was measured."""

    def test_the_recorded_groups_are_the_recorded_groups(self):
        payload = _records()
        self.assertEqual(payload["measured"]["UNAFFORDABLE"]["n"], 4)
        self.assertEqual(payload["measured"]["AFFORDABLE"]["n"], 25)
        kinds = {r["kind"] for r in payload["records"]}
        self.assertEqual(kinds, {"UNAFFORDABLE", "AFFORDABLE"})

    def test_the_measurement_still_says_red_rather_than_missing(self):
        measured = _records()["measured"]
        self.assertEqual(measured["UNAFFORDABLE"]["helper_unaffordable_cost_pixels"], True)
        self.assertEqual(measured["AFFORDABLE"]["helper_unaffordable_cost_pixels"], False)
        self.assertGreater(measured["UNAFFORDABLE"]["phash_distance"], measured["threshold_phash"])
        self.assertLessEqual(measured["AFFORDABLE"]["phash_distance"], measured["threshold_phash"])


@REQUIRES_FRAMES
class TheRedDigitIsWhyTheTargetWentMissingTests(unittest.TestCase):
    """The mechanism, measured -- not the reason string we were reporting."""

    def test_the_unaffordable_frames_really_are_unaffordable(self):
        for path in UNAFFORDABLE:
            with self.subTest(frame=path.name):
                self.assertIs(unaffordable_cost_pixels(path, ROI), True)

    def test_the_affordable_frames_contain_no_red_at_all(self):
        for path in AFFORDABLE:
            with self.subTest(frame=path.name):
                self.assertIs(unaffordable_cost_pixels(path, ROI), False)

    def test_the_red_digit_is_what_pushes_the_template_out_of_range(self):
        """Distance 26 vs 0 is the whole story, so pin it to the frames."""
        from PIL import Image

        with Image.open(TEMPLATE) as template:
            template_hash = phash(template)
        for path in UNAFFORDABLE:
            with self.subTest(frame=path.name):
                with Image.open(path) as image:
                    width, height = image.size
                    bounds = (
                        round(ROI["x_norm"] * width),
                        round(ROI["y_norm"] * height),
                        round((ROI["x_norm"] + ROI["w_norm"]) * width),
                        round((ROI["y_norm"] + ROI["h_norm"]) * height),
                    )
                    distance = hamming(phash(image.crop(bounds)), template_hash)
                self.assertGreater(distance, MATCH_THRESHOLD)
        for path in AFFORDABLE:
            with self.subTest(frame=path.name):
                with Image.open(path) as image:
                    width, height = image.size
                    bounds = (
                        round(ROI["x_norm"] * width),
                        round(ROI["y_norm"] * height),
                        round((ROI["x_norm"] + ROI["w_norm"]) * width),
                        round((ROI["y_norm"] + ROI["h_norm"]) * height),
                    )
                    distance = hamming(phash(image.crop(bounds)), template_hash)
                self.assertLessEqual(distance, MATCH_THRESHOLD)


@REQUIRES_FRAMES
@unittest.skipUnless(production_vision() is not None, "OCR runtime unavailable")
class TheFormationPageReportsTheVerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()

    def test_an_unaffordable_formation_page_reports_the_client_verdict(self):
        state = self.vision.observe(UNAFFORDABLE[-1])
        self.assertEqual(state.page.value, "MARCH")
        self.assertIs(state.stamina.get("cost_affordable"), False)
        self.assertEqual(state.stamina.get("cost_verdict_source"), "DISPATCH_COST_COLOUR")

    def test_an_affordable_formation_page_reports_that_too(self):
        state = self.vision.observe(AFFORDABLE[-1])
        self.assertEqual(state.page.value, "MARCH")
        self.assertIs(state.stamina.get("cost_affordable"), True)

    def test_the_dispatch_verdict_does_not_hijack_the_camp_panel(self):
        # The camp panel is a different page with its own cost control and its
        # own verdict source; the formation-page rule must not overwrite it.
        camp = (
            ROOT / "dataset/truth_audit/camp_panel_stamina_gate_20260915"
            / "01_camp_panel_stamina_read_live.png"
        )
        if not camp.is_file():
            self.skipTest("camp panel frame not on this machine")
        state = self.vision.observe(camp)
        self.assertEqual(state.page.value, "EXPLORATION")
        if "cost_verdict_source" in state.stamina:
            self.assertEqual(state.stamina["cost_verdict_source"], "BUTTON_COST_COLOUR")


class TheBrainRefusesToPayAnUnaffordableDispatchTests(unittest.TestCase):
    def _decide(self, world, goal="INTEL", **kwargs):
        brain = RuleBrain(current_goal=goal, **kwargs)
        return brain, brain.decide(world, v2_registry())

    def test_a_red_cost_stops_the_intel_beast_dispatch(self):
        _, decision = self._decide(_formation(cost_affordable=False))
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "dispatch_unaffordable_for_stamina")

    def test_a_red_cost_stops_the_gathering_dispatch_too(self):
        # Both dispatch buttons are the same control on the same page.  The
        # gather formation is reached with the gathering goal: under the INTEL
        # goal an empty-beast MARCH page is the hero squad page by definition
        # and takes the branch above the guard.
        _, decision = self._decide(_gather_formation(cost_affordable=False), goal="GATHER_RESOURCE")
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "dispatch_unaffordable_for_stamina")

    def test_an_affordable_formation_still_dispatches(self):
        _, decision = self._decide(_formation(cost_affordable=True))
        self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")

    def test_an_unmeasured_verdict_does_not_block_a_payable_march(self):
        # ``None`` means "not measured" and must never be read as "red"; the
        # client stays the authority on affordability.
        for value in (None,):
            with self.subTest(cost_affordable=value):
                _, decision = self._decide(_formation(cost_affordable=value))
                self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")

    def test_the_verdict_outranks_a_wrong_gauge_reading(self):
        _, decision = self._decide(
            _formation(current=300, max=200, cost_affordable=False)
        )
        self.assertEqual(decision.skill, "SAFE_STOP")

    def test_the_hero_squad_page_is_deliberately_out_of_scope(self):
        # A different screen draws that control, and the ROI above has not been
        # measured against it, so the guard must not reach in.
        squad = WorldState(
            page=Page.MARCH,
            beast={},
            stamina={"cost_affordable": False},
            confidence=0.99,
        )
        _, decision = self._decide(squad)
        self.assertEqual(decision.skill, "INTEL_HERO_DISPATCH")

    def test_the_stop_is_a_normal_one_not_a_fatal_one(self):
        # Ordinary failures must not halt AUTO; this is a normal end of run.
        _, decision = self._decide(_formation(cost_affordable=False))
        self.assertFalse(is_fatal_stop(decision.reason))

    def test_a_march_page_with_idle_capacity_is_unaffected(self):
        # Guard against the branch swallowing unrelated map behaviour.
        _, decision = self._decide(
            WorldState(page=Page.MAP, march_used=3, march_max=6,
                       marches=(MarchState.GATHERING,), confidence=0.99)
        )
        self.assertNotEqual(decision.reason, "dispatch_unaffordable_for_stamina")


if __name__ == "__main__":
    unittest.main()
