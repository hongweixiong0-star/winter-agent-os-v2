"""The client's refusal of a camp fight is a route, not the end of the run.

Measured live 2026-09-15T03:51:37Z (``tools/run_live.py --goal INTEL``): the
client sat on a Hero Journey camp panel showing 探险 ⚡10 with stamina 8.  The
camp panel's stamina ROI read *nothing* on that frame -- the gauge digit had
drifted left of ``HUD_STAMINA_ROI``, which reads 19 of 25 corpus frames and
whose misses the whole-frame fallback rescues 0 of -- so RuleBrain's predictive
affordability gate could not fire, the tap went out, and the client answered
with ``POPUP / GET_MORE_STAMINA``.  Because ``runtime.py`` returns on the first
failed verification, the run died one step short of the free-stamina check.

A wider ROI was measured and rejected for this job: it lifted readability to
25/26 but returned *different* numbers on 6 frames (18->188, 36->136, and a
known 9 read as 6) by catching adjacent glyphs.  A wrong reading would
mis-authorise spending, so the read stays conservative and the refusal is used
instead -- it is the client's own affordability verdict and needs no OCR.

These tests pin both halves: the runtime keeps going and lands on the
free-stamina check, and the brain treats a recorded refusal as ground truth so
the panel is never tapped a second time.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime

CAMP_COST = 10


class FakeMatch:
    center_norm = (0.84, 0.50)


class FakeSemantic:
    """Return a target for every semantic: this file is about routing, not aiming."""

    def find(self, _path, _semantic):
        return FakeMatch()

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None
    # The map gauge's measured spot (vision.py: 49,110 on 720x1280); the
    # runtime refuses to tap it unless the gauge was read on this frame.
    stamina_gauge_center = (49.0 / 720.0, 110.0 / 1280.0)

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class FakeVision:
    def __init__(self, states):
        self.states = iter(states)

    def observe(self, _path):
        return next(self.states)


class FakeDevice:
    def __init__(self):
        self.taps = []
        self.backs = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


def camp_panel(stamina: dict | None = None) -> WorldState:
    """The Hero Journey camp panel: an EXPLORATION page that displays a cost."""
    return WorldState(
        page=Page.EXPLORATION,
        exploration={"stamina_cost_displayed": CAMP_COST},
        stamina=dict(stamina or {}),
        confidence=0.99,
    )


def stamina_panel(free: bool, current: int = 8) -> WorldState:
    return WorldState(
        page=Page.POPUP,
        popup="GET_MORE_STAMINA",
        stamina={"current": current, "free_claim_available": free},
        confidence=0.99,
    )


def world_map(current: int = 8) -> WorldState:
    return WorldState(
        page=Page.MAP,
        march_used=1,
        march_max=6,
        stamina={"current": current},
        confidence=0.99,
    )


class TheRefusalOutranksTheGaugeTests(unittest.TestCase):
    """The brain half: a recorded refusal needs no reading at all."""

    def test_a_refused_panel_is_unaffordable_even_when_the_gauge_is_unreadable(self):
        # This is the exact shape of the 03:51:37Z miss: stamina is *empty*
        # because the ROI read nothing.  Without the refusal signal the brain
        # would tap again; with it the panel is known to be unpayable.
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
        brain.camp_panel_refused = True
        decision = brain.decide(camp_panel(stamina=None), None)
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.reason, "camp_fight_unaffordable_go_get_free_stamina")

    def test_the_refusal_does_not_silence_the_free_stamina_check(self):
        # ``stamina_panel_checked`` gates the map's free-gift check, so the
        # gate must not set it -- otherwise it cancels the very step it routes
        # to.  A separate loop guard exists for that reason.
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
        brain.camp_panel_refused = True
        brain.decide(camp_panel(stamina=None), None)
        self.assertFalse(brain.stamina_panel_checked)
        self.assertTrue(brain.unaffordable_camp_panel_left)

    def test_the_refusal_does_not_route_to_the_free_gift_twice(self):
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
        brain.camp_panel_refused = True
        brain.unaffordable_camp_panel_left = True
        decision = brain.decide(camp_panel(stamina=None), None)
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "camp_fight_unaffordable_and_free_gift_already_checked")

    def test_a_refusal_without_the_operator_directive_still_stops(self):
        # The gate is only allowed to spend actions on the free gift when the
        # operator asked for it; a refusal must not invent that permission.
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=False)
        brain.camp_panel_refused = True
        decision = brain.decide(camp_panel(stamina=None), None)
        self.assertEqual(decision.skill, "SAFE_STOP")

    def test_an_affordable_panel_is_still_attacked(self):
        # The refusal flag must not leak into a panel we can pay for.
        brain = RuleBrain(current_goal="INTEL")
        decision = brain.decide(camp_panel(stamina={"current": 150}), None)
        self.assertEqual(decision.skill, "INTEL_HERO_START_MARCH")


class TheRefusedFightIsRecoverableTests(unittest.TestCase):
    """The runtime half: a refusal continues the run instead of ending it."""

    def _run(self, states, **kwargs):
        device = FakeDevice()
        # ``claim_free_stamina=True`` is the operator directive that
        # config/v2.json sets (the free 丰盛的招待 gift must be claimed).  It is
        # what lets the route end on the free-stamina check instead of falling
        # through to the intel board.
        brain = RuleBrain(current_goal="INTEL", claim_free_stamina=True)
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(list(states)),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                brain=brain,
                sleeper=lambda _seconds: None,
                # Zero retries: every step then consumes exactly one before and
                # one after state, so the state list reads as the run itself.
                # The retry loop is orthogonal to routing and is covered by
                # tests/test_live_runtime.py.
                observation_retries=0,
                **kwargs,
            ).run(
                max_actions=3,
                allowed_skills={"INTEL_HERO_START_MARCH", "BACK", "OPEN_STAMINA_SOURCES"},
            )
        return run, device, brain

    def _refusal_then_free_stamina_check(self):
        # Each step observes twice (before, after), so the list is the run:
        # 1: camp panel, gauge unreadable  -> tap   -> client refuses
        # 2: the refusal's own popup       -> Back  -> map
        # 3: map, gift not checked yet     -> open the stamina panel
        return [
            camp_panel(stamina=None), stamina_panel(free=False),
            stamina_panel(free=False), world_map(),
            world_map(), stamina_panel(free=False),
        ]

    def test_a_refused_camp_fight_does_not_end_the_run(self):
        run, device, _brain = self._run(self._refusal_then_free_stamina_check())
        self.assertEqual(len(run.steps), 3, "the run must survive the refusal")
        # Honest record: the tap was refused, so it is not a success.
        self.assertFalse(run.steps[0].verification.ok)
        self.assertEqual(run.steps[0].verification.reason, "INTEL_HERO_MARCH_REFUSED_FOR_STAMINA")
        self.assertEqual(run.steps[0].decision.skill, "INTEL_HERO_START_MARCH")
        # The camp-fight tap went out before the refusal was known, and the
        # only other tap in the run is the map gauge that opens the free-gift
        # panel -- the run never taps the camp panel twice.  The executor
        # rounds the normalised centre to whole pixels.
        self.assertEqual(device.taps, [(605, 640), (49, 110)])

    def test_the_run_reaches_the_free_stamina_check_after_a_refusal(self):
        # The counterfactual: without this route the run returns at step 1 and
        # never opens the panel that holds the +150 gift.
        run, _device, _brain = self._run(self._refusal_then_free_stamina_check())
        self.assertEqual(run.steps[1].decision.skill, "BACK")
        self.assertTrue(run.steps[1].verification.ok)
        self.assertEqual(run.steps[2].decision.skill, "OPEN_STAMINA_SOURCES")
        self.assertEqual(run.steps[2].decision.reason, "free_stamina_gift_not_yet_checked_this_run")
        self.assertTrue(run.steps[2].verification.ok)
        self.assertEqual(run.stop_reason, "MAX_ACTIONS_REACHED")

    def test_the_refusal_is_recorded_on_the_brain_as_ground_truth(self):
        _run, _device, brain = self._run(self._refusal_then_free_stamina_check())
        self.assertTrue(brain.camp_panel_refused)

    def test_the_refusal_is_bounded_per_run(self):
        # With the bound at zero the route must not exist at all: the run ends
        # on the refusal instead of continuing, which is the honest fallback if
        # the recovery itself ever turns out to be wrong.
        run, _device, brain = self._run(
            self._refusal_then_free_stamina_check(), max_stamina_refusals=0
        )
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.stop_reason, "INTEL_HERO_MARCH_REFUSED_FOR_STAMINA")
        self.assertFalse(brain.camp_panel_refused)

    def test_the_popup_is_answered_by_the_brain_not_the_runtime(self):
        # The recovery must not press anything itself: the refusal leaves
        # POPUP/GET_MORE_STAMINA on screen and RuleBrain owns that popup.
        run, device, _brain = self._run(self._refusal_then_free_stamina_check())
        self.assertEqual(run.steps[1].decision.skill, "BACK")
        self.assertEqual(run.steps[1].decision.reason, "stamina_panel_without_a_free_gift")
        self.assertEqual(len(device.backs), 1, "exactly one Back, and it was the brain's")

    def test_a_claimable_gift_is_taken_instead_of_backing_out(self):
        # If the refusal arrives while the gift is claimable, the recovery
        # hands the popup to the brain, which claims it -- this is the path
        # that has never been live-executed (CLAIM_FREE_STAMINA: 0 records).
        states = [
            camp_panel(stamina=None),
            stamina_panel(free=True),
            stamina_panel(free=True),
            world_map(),
        ]
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                brain=RuleBrain(current_goal="INTEL", claim_free_stamina=True),
                sleeper=lambda _seconds: None,
                observation_retries=0,
            ).run(
                max_actions=2,
                allowed_skills={"INTEL_HERO_START_MARCH", "CLAIM_FREE_STAMINA"},
            )
        self.assertEqual(run.steps[1].decision.skill, "CLAIM_FREE_STAMINA")
        self.assertEqual(len(device.backs), 0, "the free gift needs no Back")


if __name__ == "__main__":
    unittest.main()
