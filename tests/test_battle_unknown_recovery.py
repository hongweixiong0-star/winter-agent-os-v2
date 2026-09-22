"""The unknown-page recovery must not press Back during a live battle.

WB-R19-BATTLE-UNKNOWN-RECOVERY.

The measured risk: runtime.py answers ``SAFE_STOP unknown_page`` by pressing the
system Back key immediately and re-observing, up to ``max_unknown_page_backs``
times per run.  On an ordinary unrecognised screen that is the established
recovery.  On a live battle the effect of Back is UNMEASURED, and the order
forbids manufacturing a battle to measure it.  Evidence that the screen is really
misread this way: the one recorded battle frame
(dataset/raw/control_panel/probe/live_page_20260915_151446.png, 2026-09-15
15:14:46) is judged ``Page.UNKNOWN`` at confidence 0.0, and the next probe 38 s
later reads HOME -- the client clears it unaided.

The change is run-scoped: after a step verifies that a fight has been dispatched,
an unknown screen is waited out instead of backed out of.  Every test here is a
pair, because the acceptance requires the negative control: the ordinary unknown
path must keep behaving exactly as before.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Decision, Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry


class _Status:
    def __init__(self) -> None:
        self.connected = True
        self.resolution = (720, 1280)


class _Device:
    """Records every Back press; the whole point is whether one happens."""

    capture_backend = "TEST_CAPTURE"

    def __init__(self) -> None:
        self.back_presses = 0
        self.taps: list[tuple[int, int]] = []
        self.swipes = 0
        self.screenshots = 0

    def status(self) -> _Status:
        return _Status()

    def press_back(self) -> None:
        self.back_presses += 1

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def swipe(self, *args, **kwargs) -> None:
        self.swipes += 1

    def screenshot(self, path: Path) -> None:
        self.screenshots += 1
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")


class _Vision:
    """Hands out scripted states in order; the last one repeats forever."""

    def __init__(self, states: list[WorldState]) -> None:
        self.states = states
        self.index = 0

    def observe(self, path: Path) -> WorldState:
        state = self.states[min(self.index, len(self.states) - 1)]
        self.index += 1
        return state


class _Match:
    def __init__(self, x: float, y: float) -> None:
        self.center_norm = (x, y)


class _ResolvesAny:
    """Resolves every semantic to a fixed centre.

    What is under test here is when the runtime arms its fight-aware recovery and
    what it then does, not what any particular recogniser reports, and a step that
    never resolves its target never executes and therefore never arms anything.
    """

    def find(self, image_path, semantic):
        return _Match(0.5, 0.5)


UNKNOWN = WorldState(page=Page.UNKNOWN, confidence=0.0)
HOME = WorldState(page=Page.HOME, confidence=0.98)


def _run(
    device: _Device,
    states: list[WorldState],
    max_actions: int = 1,
    prepare=None,
    **kwargs,
):
    """One run against scripted frames.

    ``prepare`` exists so a test can put the runtime into the state a longer run would have
    reached by itself -- the ordinary-control scan being exhausted, for instance -- instead of
    pretending the first decision is already that state.
    """
    with TemporaryDirectory() as temp:
        runtime = LiveRuntime(
            device=device,
            vision=_Vision(states),
            semantic_vision=_ResolvesAny(),
            capture_dir=Path(temp),
            brain=RuleBrain(current_goal="INTEL"),
            sleeper=lambda _seconds: None,
            **kwargs,
        )
        if prepare is not None:
            prepare(runtime)
        return runtime.run(max_actions=max_actions, allowed_skills=set()), runtime


class NegativeControlTests(unittest.TestCase):
    """An ordinary unknown screen must still be backed out of.

    Both tests used to assert ``stop_reason == "unknown_page"`` from a **one-action** run, which was
    true while the brain's first answer on an unnamed screen was already ``SAFE_STOP``.  It is not
    any more, and the change is older than this file's last edit: measured 2026-09-22 by running the
    file against commit ``2c8bd67`` in a separate worktree, where it fails exactly the same way.
    The brain now answers ``TRY_ORDINARY_CONTROL`` first -- 「未知页面自主探索」: a screen nobody can
    name may still have the client's own words on it -- so one action is spent looking for such a
    control before the back-out the test is about can happen.

    What the tests assert now is the guarantee itself, which is **stronger** than the old assertion:
    given the budget to finish, an unnamed screen is still backed out of, bounded, and the run still
    ends on ``unknown_page``.  Nothing about the fallback was relaxed to make this pass, and the
    ordinary attempt it waits for is bounded by the brain's own ``MAX_ORDINARY_ATTEMPTS``.
    """

    #: Enough actions for the bounded ordinary attempt to exhaust itself and hand over to the
    #: back-out.  Measured: the run presses Back twice and stops ``unknown_page`` at 4 actions, and
    #: still exactly twice at 6 -- the fallback does not grow with the budget.
    RECOVERY_BUDGET = 6

    def test_an_ordinary_unknown_screen_still_presses_back(self):
        device = _Device()
        run, _ = _run(device, [UNKNOWN] * 8, max_actions=self.RECOVERY_BUDGET)
        self.assertEqual(run.stop_reason, "unknown_page")
        self.assertGreater(device.back_presses, 0, "the established recovery must not be weakened")
        self.assertLessEqual(device.back_presses, 2, "and it stays bounded")

    def test_the_ordinary_path_recovers_when_back_reaches_a_known_page(self):
        """The recovery itself: twice Back off the unnamed screen, then a normal frame.

        The scan is pre-exhausted here on purpose.  It is the state the runtime reaches by itself
        (the ordinary attempt is bounded, and one that finds nothing exhausts the scan), and setting
        it directly is what lets this test stay about the *recovery* rather than about the attempt
        that precedes it in a fresh run.
        """
        device = _Device()
        run, _ = _run(
            device,
            [UNKNOWN, UNKNOWN, HOME, HOME],
            max_actions=self.RECOVERY_BUDGET,
            prepare=lambda runtime: setattr(runtime.brain, "ordinary_scan_exhausted", True),
        )
        self.assertGreaterEqual(device.back_presses, 1)
        self.assertLessEqual(device.back_presses, 2)
        self.assertNotEqual(run.stop_reason, "unknown_page")
        self.assertTrue(run.steps, "the run still took steps after recovering")


class _ScriptedBrain:
    """Decides a hero dispatch on the squad page and an honest stop on an unknown one.

    A stub rather than RuleBrain so the runtime's arming behaviour is isolated from
    the brain's policy: what is under test is when the runtime arms and what it
    then does, not whether the brain would choose that skill today.
    """

    current_goal = "INTEL"
    next_supply_at = None
    camp_panel_refused = False

    def decide(self, world: WorldState, registry):
        if world.page is Page.UNKNOWN:
            return Decision("SAFE_STOP", "unknown_page", 1.0, "no_action")
        if world.page is Page.MARCH:
            return Decision("INTEL_HERO_DISPATCH", "hero_dispatch_scripted", 0.99, "fight_started")
        return Decision("SAFE_STOP", "goal_page_mismatch", 1.0, "switch_task")


MARCH = WorldState(page=Page.MARCH, confidence=0.99)
MAP = WorldState(page=Page.MAP, confidence=0.99)


class ArmedTests(unittest.TestCase):
    """After a verified dispatch, an unknown screen is waited out, never backed out of."""

    def test_a_dispatched_fight_arms_the_waiter_and_no_back_is_pressed(self):
        device = _Device()
        with TemporaryDirectory() as temp:
            runtime = LiveRuntime(
                device=device,
                vision=_Vision([MARCH, MAP, UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN]),
                semantic_vision=_ResolvesAny(),
                capture_dir=Path(temp),
                brain=_ScriptedBrain(),
                sleeper=lambda _seconds: None,
                max_battle_reobservations=2,
            )
            run = runtime.run(max_actions=2, allowed_skills={"INTEL_HERO_DISPATCH"})

        self.assertEqual(len(run.steps), 2, "the dispatch step must have run")
        self.assertGreaterEqual(len(device.taps), 1, "the dispatch itself still taps")
        self.assertEqual(device.back_presses, 0, "Back during a live battle has an unmeasured effect")
        self.assertEqual(run.stop_reason, "unknown_page", "recovery must not hide the root cause")

    def test_the_wait_is_bounded_and_stops_early_when_the_fight_ends(self):
        device = _Device()
        with TemporaryDirectory() as temp:
            runtime = LiveRuntime(
                device=device,
                vision=_Vision([MARCH, MAP, UNKNOWN, HOME, HOME]),
                semantic_vision=_ResolvesAny(),
                capture_dir=Path(temp),
                brain=_ScriptedBrain(),
                sleeper=lambda _seconds: None,
                max_battle_reobservations=5,
            )
            run = runtime.run(max_actions=2, allowed_skills={"INTEL_HERO_DISPATCH"})

        self.assertEqual(device.back_presses, 0)
        self.assertFalse(runtime._fight_resolving, "arming must not outlive the fight")
        self.assertEqual(run.stop_reason, "MAX_ACTIONS_REACHED")

    def test_the_arming_is_reset_at_the_start_of_every_run(self):
        """Run-scoped, so a previous run's fight cannot silence a later recovery."""
        device = _Device()
        with TemporaryDirectory() as temp:
            runtime = LiveRuntime(
                device=device,
                vision=_Vision([MARCH, MAP]),
                semantic_vision=_ResolvesAny(),
                capture_dir=Path(temp),
                brain=_ScriptedBrain(),
                sleeper=lambda _seconds: None,
            )
            runtime.run(max_actions=1, allowed_skills={"INTEL_HERO_DISPATCH"})
            self.assertTrue(runtime._fight_resolving)
            runtime._vision = _Vision([UNKNOWN, UNKNOWN, UNKNOWN])
            runtime.run(max_actions=1, allowed_skills=set())
        self.assertFalse(runtime._fight_resolving)


class ArmingRuleTests(unittest.TestCase):
    """The arming condition is the verifier, not a hand-written skill list."""

    def test_the_armed_set_is_the_fight_dispatch_verifier(self):
        self.assertIn("INTEL_HERO_DISPATCHED", LiveRuntime.FIGHT_STARTING_VERIFIERS)

    def test_the_registry_really_carries_that_verifier(self):
        registry = v2_registry()
        carriers = [
            skill.id
            for skill in registry.all()
            if skill.verifier in LiveRuntime.FIGHT_STARTING_VERIFIERS
        ]
        self.assertIn("INTEL_HERO_DISPATCH", carriers)
        self.assertLessEqual(
            len(carriers), 2,
            "widening the armed set weakens the ordinary unknown-page recovery, so it needs frames",
        )

    def test_arming_reads_the_verifier_from_the_registry(self):
        source = (Path(__file__).resolve().parent.parent / "winter_agent_v2/runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_skill.verifier in self.FIGHT_STARTING_VERIFIERS", source)


if __name__ == "__main__":
    unittest.main()
