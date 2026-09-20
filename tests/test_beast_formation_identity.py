"""The 出征 formation page must not invent the beast it is about to attack.

Defect, proven with pixels on 2026-09-15
----------------------------------------
``Page.MARCH`` is shared by the map wilderness beast and the intel beast target.
``SemanticWorldVision`` reported a *different* beast name and level for the same
page depending on which template happened to match:

    semantic                          parent frame                  roi (y, h)
    BTN_BEAST_DISPATCH_MUSK_OX_9      beast9_round3_march           (0.912, 0.070)
    BTN_BEAST_DISPATCH                live_beast_march_selection    (0.914, 0.070)
    STATUS_VICTORY_ASSURED_MUSK_OX_9  beast9_round3_march           (0.450, 0.045)
    STATUS_VICTORY_ASSURED            live_beast_march_selection    (0.455, 0.045)

Those four are crops of *the same* 出征 button and *the same* 本次出征胜券在握
line, taken from two different live frames.  Measured with
``tools/probe_beast_formation_identity.py``, **all four match both frames at
distance 0** -- the 0.002 ROI difference is under the perceptual-hash
resolution.  So the reported identity was decided by branch order, i.e. by
nothing:

    dataset/raw/live_beast_march_selection.png
        -> page=MARCH beast={'name': '麝牛', 'level': 9, ...}
    dataset/raw/stamina_emergency/beast6_march.png
        -> page=MARCH beast={'name': '麝牛', 'level': 9, ...}   # it is a 北极狼

The second line is the whole defect: a 北极狼 (Arctic Wolf) formation was
reported as 麝牛 level 9, and ``verify_beast_dispatch`` -- which required exactly
that name and level -- would then have *passed* on an invented identity.

The page does display the target, in the title bar
--------------------------------------------------
The classifier never looked there.  OCR of the title strip (x 0.08-0.50,
y 0.004-0.066) separates the two populations cleanly:

    wilderness  目标：麝牛 / 目标：北极狼 / 目标：雪豹     (4/4 frames)
    intel       出征                                      (2/2 frames)

So the honest fix is to read the field the client actually draws instead of
inferring it from duplicate button templates, and to let the template layer
assert only the fact its templates evidence (the 胜券在握 line).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.live_stack import production_vision
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import (
    verify_beast_dispatch,
    verify_beast_march_open,
)
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "beast_formation_page_20260915"

# frame -> (target name shown in the title, victory_assured)
WILDERNESS_FORMATIONS = {
    "dataset/raw/stamina_emergency/beast9_round3_march.png": ("麝牛", True),
    "dataset/raw/stamina_emergency/beast9_march.png": ("麝牛", True),
    "dataset/raw/stamina_emergency/beast6_march.png": ("北极狼", True),
    "dataset/raw/stamina_emergency/beast_march.png": ("雪豹", False),
}
INTEL_FORMATIONS = (
    "dataset/raw/live_beast_march_selection.png",
    "dataset/truth_audit/beast_formation_page_20260915/"
    "01_formation_page_misread_as_alliance_live.png",
)
ALL_FORMATIONS = tuple(WILDERNESS_FORMATIONS) + INTEL_FORMATIONS

# The duplicate pair that decided the identity.
DUPLICATE_ANCHORS = (
    "BTN_BEAST_DISPATCH_MUSK_OX_9",
    "BTN_BEAST_DISPATCH",
    "STATUS_VICTORY_ASSURED_MUSK_OX_9",
    "STATUS_VICTORY_ASSURED",
)


def _vision() -> SemanticWorldVision:
    return SemanticWorldVision(MANIFEST, max_distance=8)


def _path(relative: str) -> Path:
    return ROOT / relative


class FormationIdentityIsNotInventedTests(unittest.TestCase):
    """The template layer asserts only what its own templates evidence."""

    def test_no_formation_frame_claims_a_beast_identity(self) -> None:
        vision = _vision()
        for relative in ALL_FORMATIONS:
            with self.subTest(frame=relative):
                state = vision.observe(_path(relative))
                self.assertIs(state.page, Page.MARCH)
                self.assertNotIn(
                    "name",
                    state.beast,
                    "the formation page does not draw the target name; it must be read, not guessed",
                )
                self.assertNotIn(
                    "level",
                    state.beast,
                    "the formation page does not draw the target level at all",
                )

    def test_the_victory_assured_line_is_still_asserted_when_drawn(self) -> None:
        vision = _vision()
        for relative, (_name, assured) in WILDERNESS_FORMATIONS.items():
            with self.subTest(frame=relative):
                state = vision.observe(_path(relative))
                self.assertIs(state.beast.get("victory_assured"), assured)

    def test_the_archived_intel_formation_keeps_its_verifier_green(self) -> None:
        # ``verify_intel_beast_march_open`` reads the identity from the BEAST
        # side (mission id) and only the safety line from this page, so removing
        # the invented name/level must not change its verdict.
        from winter_agent_v2.verifier import verify_intel_beast_march_open

        before = _vision().observe(
            ARCHIVE / "02_beast_target_card_before_live.png"
        )
        after = _vision().observe(
            ARCHIVE / "01_formation_page_misread_as_alliance_live.png"
        )
        self.assertEqual(before.beast.get("mission_id"), "INTEL_BEAST_10")
        result = verify_intel_beast_march_open(before, after)
        self.assertTrue(result.ok, result.evidence)


class TheAnchorsReallyAreDuplicatesTests(unittest.TestCase):
    """Proof that this cannot be fixed by preferring the other template.

    Scoped to the two frames the templates were cut from, which is exactly what
    ``tools/probe_beast_formation_identity.py`` measured: on
    ``live_beast_march_selection.png`` (intel) and ``beast9_round3_march.png``
    (wilderness) all four anchors sit at distance 0.  A first version of this
    test demanded a match on *every* formation frame and failed on three
    frame/anchor pairs -- the duplicates overlap heavily, they are not
    universally interchangeable, and claiming more than was measured is the
    same error this whole file is about.
    """

    PARENT_FRAMES = (
        "dataset/raw/live_beast_march_selection.png",
        "dataset/raw/stamina_emergency/beast9_round3_march.png",
    )

    def test_every_identity_anchor_matches_both_parent_frames(self) -> None:
        # Measured distances (tools/probe_beast_formation_identity.py):
        #   live_beast_march_selection.png : 0, 0, 4, 0
        #   beast9_round3_march.png        : 0, 0, 0, 0
        # The single 4 is the musk-ox victory strip on the intel frame -- still
        # far inside the threshold of 8, which is why it was able to decide the
        # identity there.
        matcher = SemanticROIVision(MANIFEST, max_distance=8)
        for relative in self.PARENT_FRAMES:
            for anchor in DUPLICATE_ANCHORS:
                with self.subTest(frame=relative, anchor=anchor):
                    found = matcher.find(_path(relative), anchor)
                    self.assertIsNotNone(
                        found,
                        f"{anchor} must match {relative} too -- the pair are crops of one control",
                    )
                    self.assertLessEqual(
                        found.distance,
                        4,
                        "measured at distance 0-4 on both parent frames",
                    )


class FormationTitleIsReadTests(unittest.TestCase):
    """The one structured field that only exists as text is read as text."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()
        if cls.vision is None:
            raise unittest.SkipTest("OCR runtime unavailable")

    def test_wilderness_titles_supply_the_target_name(self) -> None:
        for relative, (name, assured) in WILDERNESS_FORMATIONS.items():
            with self.subTest(frame=relative):
                state = self.vision.observe(_path(relative))
                self.assertIs(state.page, Page.MARCH)
                self.assertEqual(state.beast.get("name"), name)
                self.assertEqual(state.beast.get("target_kind"), "WILDERNESS")
                self.assertIs(state.beast.get("victory_assured"), assured)

    def test_intel_titles_are_recognised_as_intel(self) -> None:
        for relative in INTEL_FORMATIONS:
            with self.subTest(frame=relative):
                state = self.vision.observe(_path(relative))
                self.assertIs(state.page, Page.MARCH)
                self.assertEqual(state.beast.get("target_kind"), "INTEL")
                self.assertNotIn("name", state.beast)

    def test_the_arctic_wolf_is_never_reported_as_the_musk_ox(self) -> None:
        # The exact fabrication: beast6_march.png is a 北极狼 formation that the
        # old duplicate-template race reported as 麝牛 level 9.
        state = self.vision.observe(
            _path("dataset/raw/stamina_emergency/beast6_march.png")
        )
        self.assertEqual(state.beast.get("name"), "北极狼")
        self.assertNotEqual(state.beast.get("name"), "麝牛")


class FormationRouteTests(unittest.TestCase):
    """Routing reads the measured target kind, never the invented level."""

    @staticmethod
    def _march(beast: dict) -> WorldState:
        return WorldState(page=Page.MARCH, beast=beast, confidence=0.99)

    def test_a_measured_wilderness_name_routes_to_the_wilderness_dispatch(self) -> None:
        state = self._march({"name": "麝牛", "target_kind": "WILDERNESS", "victory_assured": True})
        decision = RuleBrain(current_goal="HOME").decide(state, v2_registry())
        self.assertEqual(decision.skill, "DISPATCH_BEAST")

    def test_a_measured_intel_title_routes_to_the_intel_dispatch(self) -> None:
        state = self._march({"target_kind": "INTEL", "victory_assured": True})
        decision = RuleBrain(current_goal="HOME").decide(state, v2_registry())
        self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")

    def test_the_intel_goal_still_routes_to_the_intel_dispatch(self) -> None:
        state = self._march({"victory_assured": True})
        decision = RuleBrain(current_goal="INTEL").decide(state, v2_registry())
        self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")

    def test_the_invented_level_no_longer_decides_the_route(self) -> None:
        # A state carrying only the old fabricated level (22 = 大角鹿) and no
        # measured evidence must not be routed by it.  The wilderness route
        # requires positive evidence, so this falls to the default.
        state = self._march({"name": "麝牛", "level": 22, "victory_assured": True})
        decision = RuleBrain(current_goal="HOME").decide(state, v2_registry())
        self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")

    def test_an_unread_title_takes_the_route_that_cannot_report_a_false_failure(self) -> None:
        # Both dispatch buttons are the same control, so either tap lands, but
        # the verifiers differ: verify_beast_dispatch demands the measured name
        # 麝牛 and would record a correct action as a FAILURE for a formation
        # whose identity was never read.  The default must therefore be the
        # intel route, which asserts only facts true of both pages.
        for goal in ("HOME", "BEAST_HUNT", None):
            with self.subTest(goal=goal):
                state = self._march({"victory_assured": True})
                decision = RuleBrain(current_goal=goal).decide(state, v2_registry())
                self.assertEqual(decision.skill, "DISPATCH_INTEL_BEAST")

    def test_low_win_probability_still_never_dispatches(self) -> None:
        state = self._march({"name": "雪豹", "target_kind": "WILDERNESS", "victory_assured": False})
        decision = RuleBrain(current_goal="HOME").decide(state, v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")


class FormationVerifierTests(unittest.TestCase):
    """The verifiers bind the identity where it is actually displayed."""

    BEAST_TARGET = WorldState(
        page=Page.BEAST,
        beast={"name": "麝牛", "level": 9, "available": True},
        confidence=0.99,
    )
    MAP_MARCHING = WorldState(
        page=Page.MAP,
        marches=(MarchState.MARCHING,),
        march_used=6,
        march_max=6,
        confidence=0.99,
    )

    def test_the_measured_name_proves_the_march_open(self) -> None:
        after = WorldState(page=Page.MARCH, beast={"name": "麝牛", "target_kind": "WILDERNESS", "victory_assured": True})
        result = verify_beast_march_open(self.BEAST_TARGET, after)
        self.assertTrue(result.ok, result.evidence)

    def test_a_formation_page_without_the_measured_name_is_not_proven(self) -> None:
        after = WorldState(page=Page.MARCH, beast={"victory_assured": True})
        result = verify_beast_march_open(self.BEAST_TARGET, after)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "BEAST_MARCH_NOT_PROVEN")

    def test_a_different_beast_is_never_accepted_as_the_musk_ox(self) -> None:
        """The musk-ox verifier is species-bound; the generic one is bound by the client's verdict.

        REVISED 2026-09-20.  The second assertion used to hold too, because ``verify_beast_dispatch``
        required ``target.dispatchable`` -- a per-species pre-approval.  北极狼 carries a *recorded*
        green assessment (``本次出征胜券在握``) but its status is REVIEWED, not VERIFIED, so the old
        inference refused it: a beast the client had already graded winnable could never be
        recorded as dispatched.  The operator's rule is the opposite of that ("as long as we can beat
        it, we may hit it"), and the evidence for "we can beat it" IS the frame's own victory strip,
        which is what ``victory_assured`` here is.

        So the species-bound half stays exactly as it was -- ``verify_beast_march_open`` is the
        musk-ox verifier and must not accept another animal -- and the generic half is now pinned on
        the three things that must still refuse.
        """
        after = WorldState(page=Page.MARCH, beast={"name": "北极狼", "target_kind": "WILDERNESS", "victory_assured": True})
        self.assertFalse(verify_beast_march_open(self.BEAST_TARGET, after).ok,
                         "the musk-ox route's verifier must stay species-bound")

        before = WorldState(page=Page.MARCH, beast={"name": "北极狼", "target_kind": "WILDERNESS", "victory_assured": True})
        self.assertTrue(verify_beast_dispatch(before, self.MAP_MARCHING).ok,
                        "a client-graded winnable target may be dispatched whatever species it is")

        # The three refusals that carry the safety: no readable name, no verdict, and a target the
        # client has already been seen turning down.
        nameless = WorldState(page=Page.MARCH, beast={"victory_assured": True})
        self.assertFalse(verify_beast_dispatch(nameless, self.MAP_MARCHING).ok)
        no_verdict = WorldState(page=Page.MARCH, beast={"name": "北极狼"})
        self.assertFalse(verify_beast_dispatch(no_verdict, self.MAP_MARCHING).ok)
        refused = WorldState(page=Page.MARCH, beast={"name": "雪豹", "victory_assured": True})
        self.assertFalse(verify_beast_dispatch(refused, self.MAP_MARCHING).ok,
                         "the leopard's row records a measured red assessment")

    def test_the_measured_name_proves_the_dispatch(self) -> None:
        before = WorldState(page=Page.MARCH, beast={"name": "麝牛", "target_kind": "WILDERNESS", "victory_assured": True})
        result = verify_beast_dispatch(before, self.MAP_MARCHING)
        self.assertTrue(result.ok, result.evidence)


if __name__ == "__main__":
    unittest.main()
