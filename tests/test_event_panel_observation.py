"""The 登录好礼 panel: it must be *named*, and a just-opened screen must be observed.

Two live defects, both measured on 2026-09-24 on the real client, and both fixed here.

1. The panel had no identity.  The city HUD's 登录好礼 entry opens the 超值活动 hub with the
   登录好礼 panel on it, and every frame of a six-second burst was called ``ALLIANCE`` at
   confidence 0.98 -- ``tools/diagnose_page_match.py`` named the culprit:
   ``PAGE_ALLIANCE_TECH``, a *title strip*, matching the panel's own header band at distance 8
   (exactly the threshold) while the panel's real content matched nothing.  That was not
   cosmetic: ``brain`` answers ``<goal>_leaves_a_panel_it_does_not_own`` with ``BACK`` for a page
   the running goal does not own, and this project's own episode stream holds 91 such steps --
   including 2026-09-24T03:29:15Z with ``state_before.page=ALLIANCE, state_after.page=HOME`` --
   so the AUTO closed a panel it had never identified, on the strength of a fiction.

2. Even correctly named, the panel was closed one step after it opened.  Measured live
   2026-09-24T06:01:18Z in the AUTO's own episode stream:

       skill BACK   EVENT -> HOME   reason first_ready_p0_skill

   ``before.page`` is EVENT, so the page model was right and the bug was not a misreading:
   ``registry.ready()`` offers the generic BACK for *any* page, it wins as "first ready P0
   skill", and the panel goes away.  Operator directive §三 is explicit -- a screen that has just
   appeared is observed and verified before any flow is allowed to change it, and an unclaimed
   screen is handed to the frame's own controls rather than to a Back.

The frames are the client's own captures from that session, copied into the tracked
``dataset/truth_audit/login_gift_entry_20260924/key`` tree (screenshots are not in git; a frame
test skips rather than silently weakening when the machine does not have them).
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
from winter_agent_v2.models import Decision, Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

KEY = ROOT / "dataset/truth_audit/login_gift_entry_20260924/key"

#: The panel itself, twice: the frame the 免费 tab was read on, and the frame taken right after
#: the entry tap.  Both must be the same page, or the identity is a one-frame accident.
PANEL_FRAMES = (
    KEY / "login_gift_PANEL_FREE_TAB_20260924T055924.png",
    KEY / "login_gift_PANEL_JUST_OPENED_20260924T055924.png",
)
#: The two screens the identity must never claim, both captured in the same session: the city
#: HUD the entry sits on, and the world map with the panel closed.
CITY_FRAME = KEY / "login_gift_CITY_BEFORE_ENTRY_20260924T055934.png"
MAP_FRAME = KEY / "map_hud_panel_closed_20260924T040458.png"

OBSERVATION_REASON = "unclaimed_activity_panel_is_observed_before_any_flow_leaves_it"


def _require(*paths: Path) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise unittest.SkipTest("live frames not captured on this machine: " + ", ".join(missing))


def _vision():
    vision = production_vision()
    if vision is None:
        raise unittest.SkipTest("OCR runtime unavailable")
    return vision


def _decide(goal: str | None, world: WorldState, brain: RuleBrain | None = None) -> Decision:
    return (brain or RuleBrain(current_goal=goal)).decide(world, v2_registry())


class ThePanelHasItsOwnIdentity(unittest.TestCase):
    """Defect 1: the page model must name the panel, not a title strip that resembles it."""

    @classmethod
    def setUpClass(cls) -> None:
        _require(*PANEL_FRAMES, CITY_FRAME, MAP_FRAME)
        cls.vision = _vision()

    def test_the_login_gift_panel_is_named_event_with_its_panel(self) -> None:
        for frame in PANEL_FRAMES:
            state = self.vision.observe(frame)
            self.assertIs(state.page, Page.EVENT, f"{frame.name} -> {state.page}")
            self.assertEqual(
                dict(state.events or {}).get("panel"),
                "LOGIN_GIFT",
                f"{frame.name} named the hub but not the panel: {state.events}",
            )

    def test_the_city_and_the_map_are_not_the_panel(self) -> None:
        """The negative control.  A header-shaped crop must not claim either screen.

        The panel's branch is guarded by the project's own map/city discriminator
        (``BTN_OPEN_HOME`` and ``PAGE_MAP`` must both be absent), so these two frames are the
        control that the guard really is doing work rather than decorating the branch.
        """
        city = self.vision.observe(CITY_FRAME)
        self.assertIs(city.page, Page.HOME, f"city frame -> {city.page}")
        world_map = self.vision.observe(MAP_FRAME)
        self.assertIs(world_map.page, Page.MAP, f"map frame -> {world_map.page}")


class AJustOpenedPanelIsObservedFirst(unittest.TestCase):
    """Defect 2: the first step on the panel is an observation, whoever holds the cycle.

    2026-09-24 refinement, measured on the same client: the observation is not the
    *end* of the story, it is the front of it.  A panel the client marks with its
    gold claim ring is free to act on -- the first answer is the claim skill, for
    every goal, exactly as the observation guard intended ("observed and verified
    before any flow is allowed to change it", and then acted on).  The property
    below therefore runs on BOTH panel states: the claimable one, and the claimed
    one (04_claim_final, ring gone) which has nothing to act on and must be
    observed and left, never tapped a second time.
    """

    CLAIMED_FRAME = (
        ROOT / "dataset/truth_audit/login_gift_claim_20260924/key/04_claim_final.png"
    )

    @classmethod
    def setUpClass(cls) -> None:
        _require(*PANEL_FRAMES, cls.CLAIMED_FRAME)
        vision = _vision()
        cls.panel = vision.observe(PANEL_FRAMES[0])
        assert cls.panel.page is Page.EVENT, "the identity test above must pass first"
        assert dict(cls.panel.events or {}).get("day_claim_visible") is True, (
            "the claimable fixture must carry the client's own claim ring; if this frame "
            "no longer draws one, the fixture frame is stale and must be re-measured"
        )
        cls.claimed_panel = vision.observe(cls.CLAIMED_FRAME)
        assert cls.claimed_panel.page is Page.EVENT
        assert dict(cls.claimed_panel.events or {}).get("day_claim_visible") is False, (
            "the claimed fixture must NOT draw the ring; the day was claimed 2026-09-24"
        )

    def test_a_claimable_panel_is_claimed_by_whatever_holds_the_cycle(self) -> None:
        for goal in (None, "MAIL", "DAILY_ACTIVITY_TARGET", "ALLIANCE_ROUTINE", "TRAIN"):
            with self.subTest(goal=goal):
                decision = _decide(goal, self.panel)
                self.assertEqual(decision.skill, "CLAIM_LOGIN_GIFT", f"goal={goal}")

    def test_no_goal_may_leave_the_panel_on_the_first_step(self) -> None:
        """The measured production failure -- and the committed-goal variant of it.

        The episode that produced this file carried ``reason=first_ready_p0_skill``, i.e. the
        goal-less fallback.  The same panel is also closed by a *committed* goal's own branch
        (measured here: ``BACK / mail_goal_leaves_a_panel_it_does_not_own``), so the guard has to
        answer for every goal rather than for the fallback alone.  Run on the CLAIMED panel:
        a panel with nothing to claim is the one the guard exists for.
        """
        for goal in (None, "MAIL", "DAILY_ACTIVITY_TARGET", "ALLIANCE_ROUTINE", "TRAIN"):
            with self.subTest(goal=goal):
                decision = _decide(goal, self.claimed_panel)
                self.assertEqual(
                    decision.skill,
                    "TRY_ORDINARY_CONTROL",
                    f"goal={goal} left a just-opened panel with {decision.skill}/"
                    f"{decision.reason}",
                )
                self.assertEqual(decision.reason, OBSERVATION_REASON)

    def test_the_observation_is_bounded_to_one_step_per_run(self) -> None:
        """One observation, not a loop: the next step is the ordinary flow's own answer.

        With nothing else to do and no goal claiming the panel, that answer is the honest leave
        the client's own Back produces -- what must not happen is the observation repeating for
        ever on a panel that has nothing to act on.
        """
        brain = RuleBrain(current_goal=None)
        first = brain.decide(self.claimed_panel, v2_registry())
        second = brain.decide(self.claimed_panel, v2_registry())
        third = brain.decide(self.claimed_panel, v2_registry())
        self.assertEqual(first.reason, OBSERVATION_REASON)
        self.assertNotEqual(second.reason, OBSERVATION_REASON, "the observation repeated")
        self.assertEqual(second.reason, third.reason, "the flow settled differently each step")
        self.assertEqual(second.skill, "BACK")

    def test_the_claim_is_also_bounded_to_one_step_per_run(self) -> None:
        """A claimable panel is claimed once; the flag is consumed either way."""
        brain = RuleBrain(current_goal=None)
        first = brain.decide(self.panel, v2_registry())
        second = brain.decide(self.panel, v2_registry())
        self.assertEqual(first.skill, "CLAIM_LOGIN_GIFT")
        self.assertNotEqual(second.skill, "CLAIM_LOGIN_GIFT",
                            "the claim repeated on the same run")

    def test_a_fresh_run_observes_again(self) -> None:
        """The flag is per run, so the next AUTO round still looks before it leaves."""
        self.assertEqual(_decide(None, self.claimed_panel).reason, OBSERVATION_REASON)
        self.assertEqual(_decide(None, self.claimed_panel).reason, OBSERVATION_REASON)

    def test_the_guard_does_not_touch_a_page_no_one_opened(self) -> None:
        """``Page.EVENT`` is the trigger; every other page keeps its own answer."""
        mail = WorldState(page=Page.MAIL, confidence=0.99)
        decision = _decide("MAIL", mail)
        self.assertNotEqual(decision.reason, OBSERVATION_REASON)


if __name__ == "__main__":
    unittest.main()
