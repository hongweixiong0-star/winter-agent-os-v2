"""The 登录好礼 day reward: claiming it, and the proof that it was claimed.

Measured live 2026-09-24T14:31 (+08:00) on the real client, 免费 tab of the 超值活动 / 登录好礼
panel the city HUD's 登录好礼 entry opens.  One tap, on the node the client itself highlights:

    14:30:5x  free_tab.png        EVENT/LOGIN_GIFT   highlighted node drawn (crop distance 4)
    14:31:0x  after_00 (+0.25 s)  still drawn (distance 3)
    14:31:0x  after_01 (+0.50 s)  not drawn
    ...       after_02..11        not drawn, and it stays that way
    14:31:1x  claim_final         EVENT/LOGIN_GIFT   the tapped row now shows the client's own
                                                     grey tick -- the mark day 1 already carried

The frame delta steps from 0.0008 to 0.0125 at exactly that moment and holds, and the frame's OCR
tokens changed only by noise -- which is why the verifier is built on the client's drawing rather
than on a caption or a reward count.

What this file does **not** claim: that AUTO drives the loop end to end.  The skill is registered
``CANDIDATE`` and bound to a verifier; a production AUTO run is what would promote it.

The frames live under ``dataset/truth_audit/login_gift_claim_20260924/key`` (screenshots are not in
git; a frame test skips on a machine that does not have them rather than weakening silently).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.live_stack import production_vision  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import (  # noqa: E402
    verify_login_gift_claimed,
    verify_login_gift_panel_open,
)

KEY = ROOT / "dataset/truth_audit/login_gift_claim_20260924/key"
BEFORE = KEY / "01_panel_free_tab_before.png"
AFTER_QUARTER = KEY / "02_claim_after_00_quarter_second.png"
AFTER_HALF = KEY / "03_claim_after_01_half_second.png"
FINAL = KEY / "04_claim_final.png"

EVENT = Page.EVENT


def _panel(*, visible: bool) -> WorldState:
    return WorldState(
        page=EVENT,
        events={"hub": "SUPER_ACTIVITY", "panel": "LOGIN_GIFT", "day_claim_visible": visible},
        confidence=0.99,
    )


class TheVerifierReadsTheClientsTwoMarks(unittest.TestCase):
    """The highlighted node was drawn, and it is not drawn any more, on the same panel."""

    def test_the_measured_pair_is_proven(self) -> None:
        result = verify_login_gift_claimed(_panel(visible=True), _panel(visible=False))
        self.assertTrue(result.ok, result)
        self.assertEqual(result.reason, "OK")

    def test_a_node_that_is_still_drawn_is_not_a_claim(self) -> None:
        """The negative control that matters: a tap that changed nothing must fail."""
        result = verify_login_gift_claimed(_panel(visible=True), _panel(visible=True))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "LOGIN_GIFT_CLAIM_NOT_PROVEN")

    def test_a_node_that_was_never_drawn_is_not_a_claim(self) -> None:
        result = verify_login_gift_claimed(_panel(visible=False), _panel(visible=False))
        self.assertFalse(result.ok)

    def test_a_panel_that_closed_is_not_a_claim(self) -> None:
        """Backing out of the panel is not claiming from it."""
        left = WorldState(page=Page.HOME, confidence=0.99)
        result = verify_login_gift_claimed(_panel(visible=True), left)
        self.assertFalse(result.ok, "leaving the panel must not read as a claim")

    def test_a_frame_with_no_event_state_is_not_a_claim(self) -> None:
        """A state that carries no reading must never be read as "the node is gone"."""
        blind = WorldState(page=EVENT, confidence=0.99)
        self.assertFalse(verify_login_gift_claimed(blind, _panel(visible=False)).ok)


class TheRegisteredSkillCanActuallyBeDispatched(unittest.TestCase):
    """A skill with no ``VERIFIED_ATOMIC`` entry is registered and never run (#45)."""

    def test_it_is_registered_for_the_panel_it_belongs_to(self) -> None:
        skill = next((s for s in v2_registry().all() if s.id == "CLAIM_LOGIN_GIFT"), None)
        self.assertIsNotNone(skill, "CLAIM_LOGIN_GIFT is not in the registry")
        self.assertIs(skill.required_page, EVENT)
        self.assertEqual(skill.action.target, "LOGIN_GIFT_DAY_CLAIM")
        self.assertEqual(skill.verifier, "LOGIN_GIFT_CLAIMED")

    def test_it_has_a_live_loop_verifier(self) -> None:
        self.assertIn("CLAIM_LOGIN_GIFT", LiveRuntime.VERIFIED_ATOMIC)
        self.assertIs(LiveRuntime.VERIFIED_ATOMIC["CLAIM_LOGIN_GIFT"], verify_login_gift_claimed)


class TheNavigationHalfIsWiredToo(unittest.TestCase):
    """The entry tap is a skill the ordinary loop can dispatch, not a tool-only hop.

    Measured reason it was missing: the entry's template lived only in the
    element table, which the ``TAP_SEMANTIC`` resolver never reads, so any skill
    pointing at ``CONTROL[登录好礼]`` answered ``SEMANTIC_TARGET_NOT_VERIFIED``
    and the panel only ever opened from a development tool.
    """

    def test_it_is_registered_for_the_city(self) -> None:
        skill = next((s for s in v2_registry().all() if s.id == "OPEN_LOGIN_GIFT"), None)
        self.assertIsNotNone(skill, "OPEN_LOGIN_GIFT is not in the registry")
        self.assertIs(skill.required_page, Page.HOME)
        self.assertEqual(skill.action.target, "CONTROL[登录好礼]")
        self.assertEqual(skill.verifier, "LOGIN_GIFT_PANEL_OPEN")
        self.assertIn("OPEN_LOGIN_GIFT", LiveRuntime.VERIFIED_ATOMIC)

    def test_the_open_verifier_reads_the_panels_own_identity(self) -> None:
        city = WorldState(page=Page.HOME, events={"login_gift_entry_visible": True}, confidence=0.99)
        opened = verify_login_gift_panel_open(city, _panel(visible=False))
        self.assertTrue(opened.ok, opened)

    def test_an_open_that_changed_nothing_is_not_proven(self) -> None:
        city = WorldState(page=Page.HOME, confidence=0.99)
        self.assertFalse(verify_login_gift_panel_open(city, city).ok)

    def test_an_event_screen_that_is_not_this_panel_is_not_proven(self) -> None:
        """The hub without the 登录好礼 panel must not pass as the panel."""
        city = WorldState(page=Page.HOME, confidence=0.99)
        hub = WorldState(page=EVENT, events={"hub": "SUPER_ACTIVITY"}, confidence=0.99)
        result = verify_login_gift_panel_open(city, hub)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "LOGIN_GIFT_PANEL_NOT_PROVEN")

    def test_a_blind_state_is_not_proven(self) -> None:
        city = WorldState(page=Page.HOME, confidence=0.99)
        blind = WorldState(page=EVENT, confidence=0.99)
        self.assertFalse(verify_login_gift_panel_open(city, blind).ok)


class TheBrainRoutesThePanelOncePerRun(unittest.TestCase):
    """HOME offers the open once; the panel claims only a client-highlighted node."""

    @staticmethod
    def _city(*, entry: bool) -> WorldState:
        return WorldState(
            page=Page.HOME,
            events={"login_gift_entry_visible": entry},
            confidence=0.99,
        )

    def test_a_city_that_draws_the_entry_opens_it_once(self) -> None:
        brain = RuleBrain()
        first = brain.decide(self._city(entry=True), v2_registry())
        self.assertEqual((first.skill, first.reason),
                         ("OPEN_LOGIN_GIFT", "login_gift_entry_on_the_city_hud_checked_once_per_run"))
        # ...and not again, whatever the panel answered: the check is bounded.
        again = brain.decide(self._city(entry=True), v2_registry())
        self.assertNotEqual(again.skill, "OPEN_LOGIN_GIFT")

    def test_a_city_without_the_entry_stops_asking(self) -> None:
        brain = RuleBrain()
        first = brain.decide(self._city(entry=False), v2_registry())
        self.assertNotEqual(first.skill, "OPEN_LOGIN_GIFT")
        second = brain.decide(self._city(entry=True), v2_registry())
        self.assertNotEqual(second.skill, "OPEN_LOGIN_GIFT",
                            "a run that missed the entry must not reopen the question later")

    def test_a_claimable_panel_is_claimed_not_observed(self) -> None:
        brain = RuleBrain()
        decision = brain.decide(_panel(visible=True), v2_registry())
        self.assertEqual((decision.skill, decision.reason),
                         ("CLAIM_LOGIN_GIFT", "login_gift_day_node_is_free_to_claim"))

    def test_a_panel_without_a_highlighted_node_is_handed_to_observation(self) -> None:
        """Already claimed or not yet unlocked: no tap, the ordinary flow leaves."""
        brain = RuleBrain()
        decision = brain.decide(_panel(visible=False), v2_registry())
        self.assertEqual((decision.skill, decision.reason),
                         ("TRY_ORDINARY_CONTROL",
                          "unclaimed_activity_panel_is_observed_before_any_flow_leaves_it"))


class TheLiveFramesCarryTheClaim(unittest.TestCase):
    """Read the client's own four frames through the production stack."""

    @classmethod
    def setUpClass(cls) -> None:
        for frame in (BEFORE, AFTER_QUARTER, AFTER_HALF, FINAL):
            if not frame.is_file():
                raise unittest.SkipTest(f"live frame not captured on this machine: {frame.name}")
        cls.vision = production_vision()
        if cls.vision is None:
            raise unittest.SkipTest("OCR runtime unavailable")

    def test_the_highlighted_node_disappears_half_a_second_after_the_tap(self) -> None:
        marks = {
            "before": self.vision.observe(BEFORE),
            "after_quarter": self.vision.observe(AFTER_QUARTER),
            "after_half": self.vision.observe(AFTER_HALF),
            "final": self.vision.observe(FINAL),
        }
        for name, state in marks.items():
            self.assertIs(state.page, EVENT, f"{name}: the panel is not named EVENT ({state.page})")
            self.assertEqual(dict(state.events or {}).get("panel"), "LOGIN_GIFT", name)

        self.assertTrue(marks["before"].events.get("day_claim_visible"),
                        "the frame the tap was issued from must draw the highlighted node")
        # The client's response is ~0.75 s long (measured for another control too), so the very next
        # 0.25 s frame still carries the node.  Asserting it stays *does not* belong here: what the
        # reading must be is "present before, absent after", and the pair below is exactly that.
        self.assertTrue(marks["after_quarter"].events.get("day_claim_visible"))
        self.assertFalse(marks["after_half"].events.get("day_claim_visible"))
        self.assertFalse(marks["final"].events.get("day_claim_visible"))

        proven = verify_login_gift_claimed(marks["before"], marks["after_half"])
        self.assertTrue(proven.ok, proven)
        proven_final = verify_login_gift_claimed(marks["before"], marks["final"])
        self.assertTrue(proven_final.ok, proven_final)
        # ...and the ordinary control: a tap that changed nothing must not pass.
        self.assertFalse(verify_login_gift_claimed(marks["before"], marks["before"]).ok)


class TheCityFrameDrawsTheEntry(unittest.TestCase):
    """The production vision stack reads the entry flag off the client's own city frames."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.city = ROOT / "dataset/truth_audit/login_gift_entry_20260924/key/login_gift_CITY_BEFORE_ENTRY_20260924T055934.png"
        cls.panel = FINAL
        for frame in (cls.city, cls.panel):
            if not frame.is_file():
                raise unittest.SkipTest(f"live frame not captured on this machine: {frame.name}")
        cls.vision = production_vision()
        if cls.vision is None:
            raise unittest.SkipTest("OCR runtime unavailable")

    def test_the_city_says_the_entry_is_there_and_the_panel_does_not(self) -> None:
        state = self.vision.observe(self.city)
        self.assertIs(state.page, Page.HOME, f"city frame -> {state.page}")
        self.assertTrue(
            (state.events or {}).get("login_gift_entry_visible"),
            "the frame the probe tapped the entry from must read the entry as visible",
        )
        panel_state = self.vision.observe(self.panel)
        self.assertFalse(
            (panel_state.events or {}).get("login_gift_entry_visible", False),
            "the open panel draws no entry; a True here would let the brain reopen it forever",
        )


if __name__ == "__main__":
    unittest.main()
