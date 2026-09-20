"""The species-agnostic beast hop: tap what the client labelled, let the client judge it.

Added 2026-09-20 for the operator's P0 ("intel is finished, spend the stamina that is left").
The route could not act on any beast the table had not pre-approved, and the measured cost was
that on a live frame the client printed 霜鳞避役 beside its 20 badge, the label read at 0.89, the
table resolved it to a row -- and the route recorded nothing, then went back to panning the map.

The chain this file pins, and where each half is proven:

    MAP   the client's label names a beast      -> SELECT_BEAST_TARGET_LABELLED
          (identity is enough; no spend happens)
    BEAST the card's own 攻击 control opens     -> verify_beast_card_opened
    MARCH the client's 胜券在握 strip is on it   -> verify_beast_dispatch (spend proven here)

The safety line is unchanged and is the whole point of the design: no stamina moves on identity
alone.  It moves when the client's own printed verdict says the fight is winnable, which is also
how an unsafe target (the level-29 leopard, whose row records a measured red assessment) gets
read and refused instead of being invisible.

Two of these tests assert against source text rather than behaviour: the resolver and the
binding table are closures and dicts inside `LiveRuntime`, and the property that matters is that
the wiring *exists* -- a skill with no `VERIFIED_ATOMIC` entry is never dispatched, and a resolver
case that is missing returns None for the rest of time.  Behaviour alone cannot tell those apart
from "nothing happened to be on screen".
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.beast_targets import GREEN_ASSESSMENT  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import verify_beast_card_opened, verify_beast_dispatch  # noqa: E402

# The frame the whole change came from, archived under dataset/truth_audit and whitelisted in
# .gitignore so this guard runs on any machine -- a guard that only passes on the one box with
# the raw capture is not a guard.
LABELLED_FRAME = (
    ROOT / "dataset" / "truth_audit" / "beast_labelled_selection_20260920" / "key"
    / "01_map_frame_labelled_beast_20260919T144336.png"
)

# Measured on that frame: the nameplate's box maps to (0.2687, 0.6551) of a 720x1280 frame.
LABELLED_BEAST = {
    "visible_target": "FROST_SCALED_RUNNER",
    "level": 20,
    "available": True,
    "source": "BEAST_LABEL",
    "label_confidence": 0.893,
    "tap_norm": (0.2687, 0.6551),
}


def labelled_map() -> WorldState:
    return WorldState(page=Page.MAP, beast=dict(LABELLED_BEAST), confidence=0.99)


class TheRouteReachesALabelledBeastTests(unittest.TestCase):
    def test_the_route_taps_what_the_label_named(self):
        """The decision that used to be impossible: an unmeasured species is acted on."""
        decision = RuleBrain(current_goal="BEAST_HUNT").decide(labelled_map(), v2_registry())
        self.assertEqual(decision.skill, "SELECT_BEAST_TARGET_LABELLED")
        self.assertEqual(decision.expected_result, "beast_target_dialog_open")

    def test_it_is_reached_before_the_blind_pan(self):
        """Ordering matters: the pan has no convergence criterion (see the failure-pattern file).

        The scan counter is also reset by this branch, because naming a beast *is* progress and
        a budget shared with the pan would stop the route after three labelled taps.
        """
        brain = RuleBrain(current_goal="BEAST_HUNT")
        brain.beast_scans_used = brain.max_beast_scans - 1
        decision = brain.decide(labelled_map(), v2_registry())
        self.assertEqual(decision.skill, "SELECT_BEAST_TARGET_LABELLED")
        self.assertEqual(brain.beast_scans_used, 0, "a labelled target resets the pan budget")

    def test_a_pre_cleared_species_keeps_its_own_hop(self):
        """The LIVE_VERIFIED musk ox and the mammoth route must not be rerouted."""
        musk_ox = WorldState(page=Page.MAP, confidence=0.99,
                             beast={"visible_target": "MUSK_OX", "level": 9, "available": True})
        self.assertEqual(
            RuleBrain(current_goal="BEAST_HUNT").decide(musk_ox, v2_registry()).skill,
            "SELECT_BEAST_TARGET",
        )
        mammoth = WorldState(page=Page.MAP, confidence=0.99,
                             beast={"visible_target": "MAMMOTH", "level": 5, "available": True})
        self.assertEqual(
            RuleBrain(current_goal="BEAST_HUNT").decide(mammoth, v2_registry()).skill,
            "SELECT_BEAST_TARGET_MAMMOTH",
        )

    def test_a_refused_target_is_not_tapped(self):
        """The leopard's row records a measured red assessment, so it is not a target at all."""
        leopard = WorldState(page=Page.MAP, confidence=0.99,
                             beast={"visible_target": "SNOW_LEOPARD", "level": 29, "available": True})
        decision = RuleBrain(current_goal="BEAST_HUNT").decide(leopard, v2_registry())
        self.assertNotEqual(decision.skill, "SELECT_BEAST_TARGET_LABELLED")


class TheCardProvesTheTargetNotTheActionTests(unittest.TestCase):
    def test_the_card_opening_is_the_proof(self):
        before = labelled_map()
        after = WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99)
        result = verify_beast_card_opened(before, after)
        self.assertTrue(result.ok, result.reason)

    def test_a_tap_that_did_not_open_a_card_is_a_failure(self):
        before = labelled_map()
        after = WorldState(page=Page.MAP, confidence=0.99)
        self.assertFalse(verify_beast_card_opened(before, after).ok)

    def test_an_identity_that_was_not_read_from_the_client_is_not_enough(self):
        """A template/other source cannot claim this hop -- only a read label can."""
        before = WorldState(page=Page.MAP, confidence=0.99,
                            beast={k: v for k, v in LABELLED_BEAST.items() if k != "source"})
        after = WorldState(page=Page.BEAST, beast={"attack_card": True}, confidence=0.99)
        self.assertFalse(verify_beast_card_opened(before, after).ok)


class TheSpendStillNeedsTheClientsVerdictTests(unittest.TestCase):
    def test_a_verdict_backed_dispatch_is_accepted_for_an_unmeasured_species(self):
        """The generalisation: the client's strip is the evidence, not a pre-approval flag."""
        before = WorldState(page=Page.MARCH, confidence=0.99,
                            beast={"name": "霜鳞避役", "victory_assured": True})
        after = WorldState(page=Page.MAP, confidence=0.99, march_used=1,
                           marches=("MARCHING",))
        result = verify_beast_dispatch(before, after)
        self.assertTrue(result.ok, result.reason)

    def test_the_verdict_is_still_required(self):
        before = WorldState(page=Page.MARCH, confidence=0.99, beast={"name": "霜鳞避役"})
        after = WorldState(page=Page.MAP, confidence=0.99, march_used=1, marches=("MARCHING",))
        self.assertFalse(verify_beast_dispatch(before, after).ok)

    def test_an_unnameable_target_is_refused(self):
        before = WorldState(page=Page.MARCH, confidence=0.99, beast={"victory_assured": True})
        after = WorldState(page=Page.MAP, confidence=0.99, march_used=1, marches=("MARCHING",))
        self.assertFalse(verify_beast_dispatch(before, after).ok)

    def test_the_pre_cleared_row_still_works_unchanged(self):
        before = WorldState(page=Page.MARCH, confidence=0.99,
                            beast={"name": "麝牛", "victory_assured": True})
        after = WorldState(page=Page.MAP, confidence=0.99, march_used=1, marches=("MARCHING",))
        self.assertTrue(verify_beast_dispatch(before, after).ok)


class TheWiringExistsTests(unittest.TestCase):
    def test_the_skill_is_registered_for_its_own_page(self):
        skill = v2_registry().get("SELECT_BEAST_TARGET_LABELLED")
        self.assertIsNotNone(skill)
        self.assertIs(skill.required_page, Page.MAP)
        self.assertEqual(skill.action.target, "BEAST_ON_MAP")

    def test_it_is_bound_to_a_verifier(self):
        """A skill with no VERIFIED_ATOMIC entry is never dispatched -- issue #45's failure mode."""
        self.assertIs(
            LiveRuntime.VERIFIED_ATOMIC["SELECT_BEAST_TARGET_LABELLED"], verify_beast_card_opened
        )

    def test_the_executor_can_resolve_the_dynamic_target(self):
        """The tap point lives in the world state, so the resolver has to read it from there."""
        source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
        self.assertIn('if semantic == "BEAST_ON_MAP":', source)
        block = source.split('if semantic == "BEAST_ON_MAP":', 1)[1].split('if semantic ==', 1)[0]
        self.assertIn("before.page is not Page.MAP", block,
                      "a stale tap_norm must not be usable on another page")
        self.assertIn('before.beast.get("tap_norm")', block)

    def test_the_frame_this_came_from_is_still_in_the_repo(self):
        self.assertTrue(LABELLED_FRAME.exists(),
                        f"the evidence frame moved: {LABELLED_FRAME}")

    def test_the_real_frame_reads_through_the_production_chain(self):
        """Not a stub: the archived live frame through HybridVision, the way production sees it.

        This is the measurement the change rests on, so it is asserted rather than described --
        the label at its real confidence, the row it resolves to, the tap point in frame
        coordinates, and the brain actually choosing the new hop.  Skipped (visibly, with a
        reason) when RapidOCR is not installed, because a silent pass would be indistinguishable
        from a working chain.
        """
        try:
            from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend
            from winter_agent_v2.vision import SemanticWorldVision
            ocr = OCRService(RapidOCRBackend())
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"RapidOCR unavailable: {type(exc).__name__}: {exc}")

        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        state = HybridVision(SemanticWorldVision(manifest), ocr).observe(LABELLED_FRAME)

        self.assertIs(state.page, Page.MAP)
        self.assertEqual(state.beast.get("source"), "BEAST_LABEL")
        self.assertEqual(state.beast.get("visible_target"), "FROST_SCALED_RUNNER")
        self.assertEqual(state.beast.get("level"), 20)
        self.assertGreater(state.beast.get("label_confidence", 0), 0.8,
                           "the read has to clear the reader's own confidence floor")
        tap = state.beast.get("tap_norm")
        self.assertIsNotNone(tap, "a labelled beast must carry where to tap it")
        # Measured on this frame: the nameplate's box centre is (193, 838) in 720x1280.
        self.assertAlmostEqual(tap[0], 193 / 720, places=2)
        self.assertAlmostEqual(tap[1], 838 / 1280, places=2)
        self.assertEqual(
            RuleBrain(current_goal="BEAST_HUNT").decide(state, v2_registry()).skill,
            "SELECT_BEAST_TARGET_LABELLED",
        )


if __name__ == "__main__":
    unittest.main()
