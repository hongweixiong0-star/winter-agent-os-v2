"""A control this run resolved to nothing is not re-derived for every goal.

Measured 2026-09-23, run ``20260923_140514_506593``: five consecutive ``CLOSE_POPUP`` steps in three
seconds, each recorded against a *different* goal (CLEAR_INTEL, MAIL_ROUTINE, DAILY_ACTIVITY_TARGET,
CLAIM_EXPLORATION_IDLE, AUTO_DISCOVERY) and each the same decision.  The reason is structural rather
than a coincidence of that run: a named popup answers ``blocking_popup`` **before** every goal's own
route (``brain.py``), so whichever goal takes the cycle, the answer is the same step.  Yielding to
another goal therefore bought nothing, and the run only ended when the board ran out of goals.

The runtime already refuses to *tap* a control that failed its verifier twice (§七.3).  This file is
about the other half: a control that resolved to **no point at all** never ran a verifier, so nothing
was holding against it, and the same non-attempt was re-derived once per goal.

Operator directive 2026-09-23 item 3: "同一弹窗连续操作无进展时，记录现场，有界尝试恢复；仍无法处理则让位给
其他任务."  The bound is ``MAX_UNRESOLVED_ATTEMPTS``, the handover is the existing
``_yield_to_next_goal``, and the ending is the resolver's own reason -- no new scheduler, no new
vocabulary.

The brain is **not** stubbed here.  ``RuleBrain.decide`` really does answer ``CLOSE_POPUP`` with
``blocking_popup`` for every goal on this frame, which is the fact the bound exists for; a stubbed
brain would let this test pass while the premise was false.
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

from winter_agent_v2 import control_experience, observation_store  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

#: The two goals whose own route does NOT go through the blocking-popup branch on this frame: they
#: answer ``OPEN_POWER_DETAILS`` instead.  Excluded from the offered board so the scenario under
#: test is the measured one -- every offered goal asking for the same popup dismissal.
OWNS_THE_PANEL = ("KEEP_TRAINING_PRODUCTIVE", "KEEP_RESEARCH_PRODUCTIVE")


class _PopupClient:
    """A client stuck on one popup, with the device and the vision sides the loop asks for."""

    def __init__(self) -> None:
        self.taps: list = []
        self.backs: list = []

    # --- the device the executor drives
    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, *args, **kwargs):
        self.taps.append("swipe")

    # --- the vision the run asks about the frame
    def observe(self, _path):
        return WorldState(page=Page.POPUP, popup="POWER_OVERVIEW", confidence=0.99,
                          march_used=1, march_max=6)

    # --- the semantic vision the executor asks for a point: nothing matches, and no OCR
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


def _offered(runtime, goals, _deferrals):
    """The board, minus the two goals whose route is not the popup dismissal."""
    return [goal for goal in goals
            if goal.goal_id not in OWNS_THE_PANEL
            and goal.goal_id not in runtime._yielded_goals]


class UnresolvedControlTests(unittest.TestCase):
    def _run(self, *, bound: int):
        client = _PopupClient()
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            empty = temp / "observations.json"
            empty.write_text("{}", encoding="utf-8")
            # Two things this fixture has to declare, because it fakes a production run inside a
            # temporary directory: the real ledger must not be read or written (a live
            # ``POPUP|POWER_OVERVIEW|BTN_CLOSE`` entry resolves, which would send this run down the
            # *verifier*-failure path instead of the unresolved one), and the frames here land under
            # the system temp dir, which is the marker of a scratch frame.
            previous_observations = observation_store.STATE_PATH
            previous_ledger = control_experience.STATE_PATH
            observation_store.STATE_PATH = empty
            control_experience.STATE_PATH = temp / "control_experience.json"
            try:
                runtime = LiveRuntime(
                    device=client,
                    vision=client,
                    semantic_vision=client,
                    capture_dir=temp / "captures",
                    sleeper=lambda _seconds: None,
                    episode_store=None,
                )
                runtime.MAX_UNRESOLVED_ATTEMPTS = bound
                with patch.object(LiveRuntime, "_selectable", _offered), \
                     patch.object(control_experience, "measured_on_a_real_frame",
                                  return_value=True):
                    result = runtime.run(
                        max_actions=6,
                        allowed_skills=frozenset({"CLOSE_POPUP", "OPEN_POWER_DETAILS", "BACK"}),
                    )
            finally:
                observation_store.STATE_PATH = previous_observations
                control_experience.STATE_PATH = previous_ledger
        attempts = [step for step in result.steps if step.execution is not None]
        return client, result, attempts

    def test_the_same_non_attempt_is_not_re_derived_for_every_goal(self):
        client, result, attempts = self._run(bound=2)
        self.assertGreaterEqual(len(attempts), 2, "the bound must allow a second try, not one")
        self.assertEqual(len(attempts), 2,
                         f"the bound is 2, so exactly two attempts; it made {len(attempts)}")
        self.assertEqual(result.stop_reason, "SEMANTIC_TARGET_NOT_VERIFIED",
                         "and it ends on the resolver's own reason, which is what happened")
        self.assertEqual(client.taps, [], "nothing was ever tapped: no point was ever resolved")

    def test_without_the_bound_one_goal_after_another_makes_the_same_non_attempt(self):
        """Negative control: this is the measured shape, and it is what the bound removes.

        Run ``20260923_140514_506593`` spent five steps this way, one per goal, in three seconds.
        Each of those recorded an identical failure, so the episode stream showed five problems
        where there was one.
        """
        _client, result, attempts = self._run(bound=10 ** 9)
        self.assertGreater(len(attempts), 2,
                           "an unbounded run re-derives the same control for the next goal")
        self.assertEqual(len({step.decision.skill for step in result.steps}), 1,
                         "and every one of them is the same decision")
        self.assertEqual(len({step.decision.reason for step in result.steps}), 1,
                         "...with the same reason, which is why the repetition carries no news")


if __name__ == "__main__":
    unittest.main()
