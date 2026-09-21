"""A goal that cannot run says only that THAT goal must step aside.

Measured live twice on 2026-09-21, both times a whole cycle ending on one goal's
refusal:

  * 03:17:51Z, ``stop_reason 'reserved_march_for_stamina'``.  The round had run one
    action (EXECUTE_INTEL_RESCUE_SURVIVORS, 187 -> 175 stamina) and then stopped,
    after reading ``marches=["GATHERING","RETURNING"], march_used=2, march_max=3``
    -- exactly one free slot, which is exactly the reserved one, so the reservation
    was doing its job.  Replayed through the production chain on that frame with the
    production reserve, ``goal=BEAST_HUNT`` gave ``SCAN_MAP_FOR_BEAST``: the
    reservation never blocked the stamina goal, the stop blocked everything.

  * 03:44:56Z, ``stop_reason 'alliance_state_unknown'``, page ALLIANCE -- a panel
    that plainly showed 联盟科技 carrying a 25 badge.  Nothing moved the client off
    the panel, so the next cycle opened on the same screen.

The operator's rule is that neither proves the work cycle is over, and the runtime
already owned the mechanism that says so (``_yield_to_next_goal``, the same Rule A
hop the unexecutable-skill path uses), so the fix was to stop scoping it to one
reason and let the project's own ``is_fatal_stop`` decide: only FATAL_/ACCOUNT_/
PAYMENT_ reasons end a run, everything else hands the cycle over.

These tests drive the real runtime and the real brain.  The one thing stubbed is
``_selectable``, and the reason is measured rather than convenient: the production
answer comes from the capability gate, which reads ``knowledge/**`` -- and the
running AUTO rewrites that between test runs, which is precisely why
``test_live_runtime.py::test_verified_action_repeats_then_safe_stops`` answers
differently at different times of day (#63 records that set as moving; verified
2026-09-21 by running it on an untouched HEAD checkout and watching it fail there
too).  Pinning the scenario here makes the assertion about the refusal instead of
about whatever the gate happened to say that minute.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import GoalState, GoalStatus  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.runtime_snapshot import is_fatal_stop  # noqa: E402

#: The single goal the stubbed selector offers.  ALLIANCE_ROUTINE is the one whose
#: brain answer turns on the frame's own content, so the same state can produce both
#: a refusal and a real action without stubbing the brain.  ``available_skills`` is
#: not decoration: ``GoalLibrary.best`` drops any goal that declares none, so a
#: scenario without it silently selects nothing and tests the wrong branch.
ONLY_GOAL = GoalState(
    goal_id="ALLIANCE_ROUTINE",
    status=GoalStatus.READY,
    available_skills=("ALLIANCE_GIFTS", "ALLIANCE_ALLY_GIFT_CLAIM"),
)


class _FakeMatch:
    center_norm = (0.84, 0.50)


class _FakeSemantic:
    def find(self, _path, semantic):
        return _FakeMatch() if semantic in {"BTN_ALLY_GIFT_CLAIM", "PAGE_MAP", "BTN_OPEN_HOME"} else None

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _FakeVision:
    def __init__(self, states):
        self.states = iter(states)

    def observe(self, _path):
        return next(self.states)


class _FakeDevice:
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


def alliance_gift(status: str, buttons: int, claimed: int, progress: int = 130) -> WorldState:
    """The alliance gifts panel in one of the two states the live frames show."""
    return WorldState(
        page=Page.ALLIANCE,
        alliance={
            "section": "GIFTS",
            "tab": "ALLY_GIFT",
            "status": status,
            "gift_progress": progress,
            "gift_progress_target": 150000,
            "badge_count": buttons,
            "visible_claim_buttons": buttons,
            "visible_claimed": claimed,
        },
        confidence=0.99,
    )


def already_claimed() -> WorldState:
    """What the panel reads once everything on it has been collected.

    This is the state whose brain answer is ``SAFE_STOP alliance_action_not_needed``
    -- a correct refusal that used to end the run.
    """
    return alliance_gift("CLAIMED", buttons=0, claimed=2, progress=250)


def has_something_to_claim() -> WorldState:
    return alliance_gift("CLAIMABLE", buttons=1, claimed=1)


class TheRefusalHandsOverTheCycleTests(unittest.TestCase):
    def _selectable_stub(self, goal):
        """Offer ``goal`` until it is held back, then offer nothing.

        The filtering is the point rather than boilerplate: a stub that kept offering
        the goal would re-derive the same route on the next pass and quietly test
        nothing.  This mirrors what ``_selectable`` does with ``_yielded_goals`` while
        dropping only the capability-gate half.
        """

        def stub(runtime, _goals, _deferrals):
            if goal is None or goal.goal_id in runtime._yielded_goals:
                return []
            return [goal]

        return stub

    def _run(self, states, max_actions=4, goal=ONLY_GOAL):
        device = _FakeDevice()
        with TemporaryDirectory() as temp:
            with patch.object(LiveRuntime, "_selectable", self._selectable_stub(goal)):
                run = LiveRuntime(
                    device=device,
                    vision=_FakeVision(states),
                    semantic_vision=_FakeSemantic(),
                    capture_dir=Path(temp),
                    sleeper=lambda _seconds: None,
                ).run(max_actions=max_actions)
        return device, run

    def test_a_refusal_does_not_end_the_cycle(self):
        """The core fix, and the shape of the two live incidents.

        Frame 1 is a panel with nothing left to collect, so the brain refuses --
        correctly.  Before the fix that refusal was the end of the run and the device
        was never touched.  Now the goal steps aside, the next pass re-observes, and
        the work that was still on the screen actually happens.
        """
        device, run = self._run([
            already_claimed(),
            has_something_to_claim(),
            already_claimed(),
            already_claimed(),
        ])
        self.assertEqual(len(device.taps), 1,
                         "the cycle must reach the work the refusal was hiding")
        self.assertEqual(run.stop_reason, "alliance_action_not_needed",
                         "...and end honestly once there is genuinely nothing left")

    def test_the_handover_is_bounded_and_does_not_spin(self):
        """Yielding costs an iteration, so it must stop when there is nobody to hand to.

        The stubbed selector offers one goal; once it has been held back there is
        nothing else, and the refusal becomes the honest end of the cycle.  Without
        this the fix would turn a stop into a spin.
        """
        device, run = self._run([already_claimed()] * 6)
        self.assertEqual(device.taps, [])
        self.assertEqual(run.stop_reason, "alliance_action_not_needed")
        self.assertEqual(len(run.steps), 1, "one honest step, not four attempts at the same screen")

    def test_the_handover_needs_an_iteration_to_hand_over_in(self):
        """A run with no budget left must stop rather than spend its last slot yielding.

        Same guard as the unexecutable-skill path, and the same measured reason: a
        one-action run that yields finishes with zero steps, which is strictly worse
        than the stop it replaced.
        """
        device, run = self._run([already_claimed()] * 6, max_actions=1)
        self.assertEqual(device.taps, [])
        self.assertEqual(run.stop_reason, "alliance_action_not_needed")

    def test_a_fatal_reason_still_ends_the_run(self):
        """The project's own line, not a new one: only FATAL_/ACCOUNT_/PAYMENT_ stop.

        Guarded here because the change moved the decision from a hand-written reason
        list to ``is_fatal_stop``, and the property worth keeping is that the fatal
        ones were never inside it.
        """
        self.assertTrue(is_fatal_stop("FATAL_ADB_LOST"))
        self.assertTrue(is_fatal_stop("ACCOUNT_SUSPENDED"))
        self.assertTrue(is_fatal_stop("PAYMENT_REQUIRED"))


class TheOperatorNamedReasonsAllQualifyTests(unittest.TestCase):
    """Every reason the operator listed is a refusal, not an ending.

    Pinned as a table because the fix's whole claim is that these hand the cycle over
    rather than stopping it, and a future reader adding a new stop reason needs to see
    where the line is.  ``camp_menu_never_drawn`` is in here deliberately even though
    it is absent from NON_FATAL_STOPS: it qualifies by shape (no FATAL_ prefix), and
    writing that down is what stops someone "fixing" it by adding it to a list.
    """

    NAMED = (
        "reserved_march_for_stamina",
        "no_idle_march",
        "camp_menu_never_drawn",
        "training_queue_busy",
        "research_queue_busy",
        "verified_beast_target_not_visible",
        "alliance_state_unknown",
    )

    def test_none_of_them_is_fatal(self):
        for reason in self.NAMED:
            with self.subTest(reason=reason):
                self.assertFalse(is_fatal_stop(reason),
                                 f"{reason} must hand the cycle over, not end it")

    def test_the_safe_stop_branch_consults_is_fatal_stop_rather_than_a_reason_list(self):
        """The shape of the fix, asserted where it lives.

        A hand-written list here would drift the moment a new reason appears, which is
        exactly how 'reserved_march_for_stamina' came to be the only one that yielded.
        """
        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("not is_fatal_stop(decision.reason)", source,
                      "the SAFE_STOP branch must ask the project's fatal line")
        self.assertNotIn('decision.reason == "reserved_march_for_stamina"', source,
                         "the single-reason special case must be gone, not duplicated")


if __name__ == "__main__":
    unittest.main()
