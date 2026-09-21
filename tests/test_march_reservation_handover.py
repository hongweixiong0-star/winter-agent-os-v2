"""A reserved march is held *for* the stamina goal, so refusing it must not end the cycle.

Measured live 2026-09-21T03:17:51Z (frames in
``dataset/raw/control_panel/runtime_auto/20260921_111732_651445/``).  The round ran exactly
one action -- ``EXECUTE_INTEL_RESCUE_SURVIVORS``, 187 -> 175 stamina -- and then stopped with
``stop_reason: reserved_march_for_stamina`` after reading the incident frame as:

    page MAP, marches ["GATHERING","RETURNING"], march_used 2, march_max 3, stamina 175

which is ONE free slot: exactly the reserved one, with ``march_policy.reserve_for_stamina = 2``
effective at ``min(2, capacity - 2) = 1``.  So the reservation was doing its job.

Two things then have to be told apart, and only one of them was wrong:

* the *refusal* is correct and stays -- the task in progress may not take the slot;
* the *ending* is not.  ``SAFE_STOP`` ends the run, so one task declining the reserved slot
  stopped every other task, and because nothing moved the client off MAP the next cycle opened
  on the same frame and did it again.

The same frame replayed through the production chain with the production reserve says the
refusal was never aimed at the stamina goal:

    goal=None / GATHER_RESOURCE -> SAFE_STOP reserved_march_for_stamina
    goal=BEAST_HUNT             -> SCAN_MAP_FOR_BEAST   (it would have run)

``BEAST_HUNT`` refuses only at ``idle_marches <= 0``.  These tests pin all of that: the refusal,
the handover, that the stamina route could have used the very slot that was held for it, and
the two bounds that keep the handover from becoming a spin or a lost iteration.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.capability_gate import BLOCKED, Deferral  # noqa: E402
from winter_agent_v2.learning import EpisodeStore  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The production value: ``config/v2.json`` -> ``march_policy.reserve_for_stamina``.
PRODUCTION_RESERVE = 2

#: The incident frame, as the production chain reads it.
INCIDENT = WorldState(
    page=Page.MAP,
    marches=(),                      # the enum members themselves are not what this pins
    march_used=2,
    march_max=3,
    stamina={"current": 175, "source": "MAP_HUD"},
    confidence=0.99,
)

GATHER_ROUTE = frozenset({
    "OPEN_HOME", "OPEN_MAP", "SCAN_MAP_FOR_BEAST", "SEARCH_RESOURCE", "SELECT_RESOURCE",
    "SUBMIT_RESOURCE_SEARCH", "START_GATHER", "DISPATCH_MARCH",
})


class FakeDevice:
    def __init__(self):
        self.taps: list = []
        self.backs: list = []

    def screenshot(self, path):
        Path(path).touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


class FakeVision:
    def __init__(self, states):
        self._states = iter(states)

    def observe(self, _path):
        return next(self._states)


class FakeSemantic:
    """No template resolves, and resource_target is set, so the gather route stays on MAP."""

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def find(self, _path, _semantic):
        return None

    def resource_cell_center_norm(self, _resource):
        return None

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class GateThatDefersAllBut:
    """A gate whose only job is to leave one goal selectable.

    The incident had eight goals discovered on that MAP frame and five of them deferred, one
    of them (``AVOID_STAMINA_WASTE``) by a development job -- which is why the gather goal,
    priority 70, was the best selectable one.  Reproducing that needs the other goals out of
    the way, and the gate is where the scheduler asks that question.
    """

    capabilities: dict = {}

    def __init__(self, allowed: str):
        self.allowed = allowed

    def blocks(self, goal):
        if goal.goal_id == self.allowed:
            return None
        return Deferral(
            goal_id=goal.goal_id,
            state=BLOCKED,
            reason="held out of the way by this test",
            capability="TEST",
        )


class TheReservationRefusesTheSlotTests(unittest.TestCase):
    """The half that was right, and must not be deleted with the half that was wrong."""

    def test_the_task_in_progress_may_not_take_the_last_slot(self):
        decision = RuleBrain(current_goal=None, reserve_marches=PRODUCTION_RESERVE).decide(
            INCIDENT, v2_registry()
        )
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "reserved_march_for_stamina")
        self.assertEqual(decision.expected_result, "stamina_task_slot_preserved")

    def test_the_refusal_needs_the_slot_to_be_free_and_spoken_for(self):
        """Two independent conditions: a free slot, and a reservation that claims it."""
        registry = v2_registry()
        # Nothing out at all: the reservation is not what stops this task.
        wide_open = WorldState(page=Page.MAP, march_used=0, march_max=3, confidence=0.99)
        decision = RuleBrain(current_goal=None, reserve_marches=PRODUCTION_RESERVE).decide(
            wide_open, registry
        )
        self.assertNotEqual(decision.reason, "reserved_march_for_stamina")
        # Capacity 6: the effective reservation is 2 and four slots are free, so again this
        # is not the branch that answers.
        roomy = WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99)
        decision = RuleBrain(current_goal=None, reserve_marches=PRODUCTION_RESERVE).decide(
            roomy, registry
        )
        self.assertNotEqual(decision.reason, "reserved_march_for_stamina")
        # No reservation configured: the last slot is nobody's.
        decision = RuleBrain(current_goal=None, reserve_marches=0).decide(INCIDENT, registry)
        self.assertNotEqual(decision.reason, "reserved_march_for_stamina")

    def test_the_stamina_goal_could_have_used_that_very_slot(self):
        """The reservation is aimed at the gather route, not at the goal it reserves for.

        ``BEAST_HUNT`` refuses only when ``idle_marches <= 0``; with one slot free it goes
        looking for a target.  So nothing about the reservation blocked spending stamina --
        which is why the fix is to hand the cycle over rather than to relax the reservation.
        """
        decision = RuleBrain(
            current_goal="BEAST_HUNT", reserve_marches=PRODUCTION_RESERVE
        ).decide(INCIDENT, v2_registry())
        self.assertNotEqual(decision.reason, "reserved_march_for_stamina")
        self.assertEqual(decision.skill, "SCAN_MAP_FOR_BEAST")


class TheRunHandsTheCycleOverTests(unittest.TestCase):
    def _run(self, *, max_actions: int, states=None):
        states = states or [INCIDENT, INCIDENT, INCIDENT, INCIDENT]
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "episodes.jsonl"
            runtime = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(path),
                capability_gate=GateThatDefersAllBut("KEEP_MARCHES_PRODUCTIVE"),
                brain=RuleBrain(current_goal=None, reserve_marches=PRODUCTION_RESERVE),
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                run = runtime.run(max_actions=max_actions, allowed_skills=GATHER_ROUTE)
            rows = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ] if path.exists() else []
        return device, run, rows, buffer.getvalue()

    def test_refusing_the_reserved_slot_does_not_end_the_run(self):
        """The defect itself: one task declining the slot stopped every other task."""
        _device, run, _rows, output = self._run(max_actions=2)
        self.assertNotEqual(
            run.stop_reason, "reserved_march_for_stamina",
            "the reservation is not an ending -- the run must hand the cycle over",
        )
        self.assertIn("yield KEEP_MARCHES_PRODUCTIVE", output,
                      "the handover must be narrated, not silent")

    def test_the_cycle_that_follows_is_really_spent(self):
        """Not a rename: the run does something after the refusal.

        With every other goal deferred, the pass after the handover has nothing selectable
        and the existing deferral replan hops HOME -- a real, verified step.  Asserted on the
        skills the run actually issued rather than on a step count, because the SAFE_STOP
        itself is recorded as a step and a count would be satisfied without any handover
        (verified: that is exactly how this assertion passed on the unfixed tree).
        """
        _device, run, _rows, _output = self._run(max_actions=2)
        issued = [step.decision.skill for step in run.steps]
        self.assertIn("OPEN_HOME", issued,
                      f"the cycle after the handover must issue a real step; it issued {issued}")

    def test_a_run_with_no_iteration_left_still_stops(self):
        """The guard that keeps this from costing the budget it was meant to save.

        ``index < max_actions`` is load-bearing, exactly as it is on the unexecutable-skill
        path: with no iteration left to re-select in, handing the goal back would spend the
        run and issue nothing.
        """
        _device, run, _rows, _output = self._run(max_actions=1)
        self.assertEqual(run.stop_reason, "reserved_march_for_stamina")

    def test_the_same_goal_is_not_handed_back_twice(self):
        """Bounded: one handover per goal per run, so it cannot become a spin."""
        _device, run, _rows, output = self._run(max_actions=4)
        self.assertEqual(output.count("yield KEEP_MARCHES_PRODUCTIVE"), 1,
                         "the goal was handed back more than once in one run")


if __name__ == "__main__":
    unittest.main()
