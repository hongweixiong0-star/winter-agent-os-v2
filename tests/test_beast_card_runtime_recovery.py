"""REPLAY for the blocked-beast-card recovery: the loop, not just the brain.

Why this is separate from ``test_beast_card_dead_end_recovery.py``
-----------------------------------------------------------------
That file proves ``RuleBrain`` returns BACK and that the real
``verify_safe_back`` accepts BEAST -> MAP.  Both are necessary and neither is
sufficient, because this project has already been burned twice by a fix that was
correct and never reached: ``0as`` (fixed but never reached) and ``0aw`` (a call
site that resolved to no definition, invisible to import/pytest/wiring).  The
question this file answers is the integration one:

    does ``LiveRuntime.run`` actually *dispatch* BACK from ``Page.BEAST``,
    spend no tap doing it, and record a verified step -- rather than
    safe-stopping at step 1 the way it did before the fix?

The frames are synthetic (a replay), so this is REPLAY-class evidence, not LIVE.
Live evidence for the fix on the real client is tracked in the commander result
for WB-0AZ.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from winter_agent_v2 import goal_utility, mode_state
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime

# The live card, field for field: a level-20 master bounty the account cannot
# beat (recommended 189,295,920 against an account around 70,758,484).
BLOCKED_CARD = {
    "name": "大师悬赏",
    "level": 20,
    "available": False,
    "recommended_power": 189295920,
    "stamina_cost_displayed": 10,
    "blocked_reason": "POWER_BELOW_RECOMMENDED",
}


class _FakeMatch:
    center_norm = (0.5, 0.5)


class _FakeSemantic:
    """BACK needs no semantic target; this exists so the runtime can resolve one."""

    def find(self, _path, _semantic):
        return _FakeMatch()

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _FakeVision:
    """Replays a scripted sequence, then keeps repeating the last frame.

    A real device keeps answering screenshots, so an exhausted script must not
    raise StopIteration -- it means the client stopped changing, which is itself
    the situation the ping-pong guard exists for.  Each step costs more than one
    observation (before, then an after-refresh), so the caller lists the
    *transitions* it cares about rather than every frame.
    """

    def __init__(self, states):
        self.states = list(states)

    def observe(self, _path):
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


class _FakeDevice:
    def __init__(self):
        self.taps = []
        self.backs = 0

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs += 1

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


def _card(available: bool = False) -> WorldState:
    beast = dict(BLOCKED_CARD)
    beast["available"] = available
    return WorldState(page=Page.BEAST, beast=beast, confidence=0.99)


def _map() -> WorldState:
    return WorldState(page=Page.MAP, march_used=0, march_max=6, confidence=0.99)


def _run(states, max_actions, allowed):
    """Drive the real loop with every shared input pinned, the way a device test pins its device.

    Measured 2026-10-16, both halves.  The loop reads the mode record fresh every cycle (spec §1),
    so a replay on a machine the operator has taken answers ``manually_owned_by_workbuddy`` with
    ``steps[]`` empty and every assertion an IndexError.  And the fairness ledger is a *shared*
    ranking input: ``test_live_runtime`` already pins it for the same reason ("sharing the repo's
    learning files lets an earlier fake screen change which goal a later test sees"), but this
    file predates that discipline -- its goal selection used to read production's own ranking
    history, so the same scene could pick different goals from one run to the next.
    """
    device = _FakeDevice()
    with TemporaryDirectory() as temp:
        temp_path = Path(temp)
        mode_path = temp_path / "MODE_STATE.json"
        mode_state.switch(mode_state.MODE_AUTO, initiator=mode_state.BY_USER,
                          reason="replay harness owns the mode input", path=mode_path)
        with patch.object(goal_utility, "STATE_PATH", temp_path / "goal_fairness.json"), \
             patch.object(goal_utility, "DECISIONS_PATH", temp_path / "decisions.jsonl"):
            runtime = LiveRuntime(
                device=device,
                vision=_FakeVision(states),
                semantic_vision=_FakeSemantic(),
                capture_dir=temp_path,
                brain=RuleBrain(current_goal="INTEL"),
                sleeper=lambda _seconds: None,
            )
            runtime.mode_state_path = mode_path
            run = runtime.run(max_actions=max_actions, allowed_skills=allowed)
    return device, run


class TheLoopItselfRecoversTests(unittest.TestCase):
    def test_the_first_step_backs_out_and_is_verified(self):
        device, run = _run([_card(), _map()], 1, {"BACK"})

        step = run.steps[0]
        self.assertEqual(step.decision.skill, "BACK")
        self.assertEqual(step.decision.reason, "beast_card_not_actionable_leaving_the_page")
        self.assertTrue(step.execution is not None and step.execution.executed, "BACK was not dispatched")
        self.assertEqual(device.backs, 1, "exactly one BACK should be pressed")
        self.assertEqual(device.taps, [], "the recovery must not tap a game control")
        self.assertTrue(step.verification.ok, step.verification.evidence)

    def test_the_run_does_not_end_on_the_old_dead_end_reason(self):
        # Pre-fix behaviour was stop_reason=beast_not_actionable at step 1, which
        # left the client on the card so the next run hit it again.
        _, run = _run([_card(), _map()], 1, {"BACK"})
        self.assertNotEqual(run.stop_reason, "beast_not_actionable")

    def test_a_back_that_changed_nothing_is_not_repeated(self):
        # Negative control for the ping-pong guard: if BACK lands back on the
        # card, the BEAST recovery must not press it again, and the run must end
        # honestly rather than claim success or fall back to the pre-fix reason.
        #
        # The property is scoped to the beast rule on purpose (updated 2026-10-16).  The
        # older form of this test pinned ``device.backs == 1`` -- "one BACK is spent and
        # the run ends there" -- which was measured when an unproven Back ended the run
        # outright.  The loop has since evolved twice, deliberately and each with its own
        # measurement: an unproven leaving skill is "the first half of a two-step exit"
        # (2026-09-21, max_leave_retries), and a goal that refused on this screen steps
        # aside for the next one (the yield system), so a *second* BACK can come from a
        # *different* goal's own leave rule before the run ends.  What the guard exists
        # for is that the beast recovery itself answers exactly once -- so that is what
        # is asserted, together with the honest ending.
        device, run = _run([_card(), _card()], 3, {"BACK"})

        beast_backs = [
            step for step in run.steps
            if step.decision.reason == "beast_card_not_actionable_leaving_the_page"
        ]
        self.assertEqual(len(beast_backs), 1, "the beast recovery must not repeat")
        self.assertEqual(device.taps, [], "the recovery must not tap a game control")
        self.assertFalse(run.steps[0].verification.ok, "BEAST->BEAST must not verify")
        self.assertEqual(run.steps[0].verification.reason, "SAFE_BACK_NOT_PROVEN")
        self.assertEqual(run.stop_reason, "SAFE_BACK_NOT_PROVEN")
        # It must not fall back to the pre-fix reason, which said nothing happened.
        self.assertNotEqual(run.stop_reason, "beast_not_actionable")
        # And it must not burn the whole budget retrying: the run ends on the unproven
        # transition, before max_actions.
        self.assertLess(len(run.steps), 3)

    def test_an_actionable_card_is_still_marched_on_not_backed_out(self):
        # The recovery must not shadow real work: an available beast is hunted.
        device, run = _run(
            [_card(available=True), WorldState(page=Page.MARCH, confidence=0.99)],
            1,
            {"BEAST_HUNT"},
        )
        self.assertEqual(run.steps[0].decision.skill, "BEAST_HUNT")
        self.assertEqual(device.backs, 0)
        self.assertEqual(len(device.taps), 1)


if __name__ == "__main__":
    unittest.main()
