"""A goal's progress must never be decided by comparing two different scales.

``progress_moved`` compares the after-frame's reading with the last one this run actually read.
Two numbers are only comparable when they are the same *kind*, and the module already says so::

    "So the writer records the scale alongside the number.  A remembered value with no matching
     kind was written by the other meter and the honest answer is ``None``."

The writer is ``LiveRuntime._remember_goal_meters``, and it recorded the value and the kind
**separately, on whatever tick happened to run**: the value dict is only overwritten when a meter
exists, while the kind is overwritten whenever one does.  So the two can come from different frames,
and the guard only ever tests the *current* kind -- never the remembered value's.

Measured live 2026-10-09 on the running client: ``CLEAR_INTEL`` dispatched a beast march and then a
hero march -- 17 verified steps, every one SUCCESS -- and recorded ``goal_progress`` **False 9 /
None 8 / True 0**, because the remembered ``-8.0`` (read from a frame that showed the intel board)
was compared with ``1.0`` (the constant ``distance`` on a frame that did not) as ``1.0 < -8.0``.
The goal was then deferred for a no-progress streak of 4: demoted for work it could not report, which
is precisely what ``_observation_meter``'s own note says it exists to prevent.

These tests pin the pairing in both directions, and the honest answer of ``None`` where the scales
differ.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_library  # noqa: E402
from winter_agent_v2.goal_library import (  # noqa: E402
    GoalState,
    GoalStatus,
    meter_kind,
    progress_moved,
)
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402


def _intel(**evidence) -> GoalState:
    """``CLEAR_INTEL`` exactly as the library emits it: a real count, and a constant distance."""
    return GoalState("CLEAR_INTEL", GoalStatus.READY, available_skills=("OPEN_INTEL",),
                     distance=1.0, evidence=evidence)


def _runtime() -> LiveRuntime:
    runtime = object.__new__(LiveRuntime)
    runtime._goal_meters = {}
    return runtime


class TheMeterNeverCrossesScalesTests(unittest.TestCase):

    def setUp(self):
        goal_library._METER_KINDS.clear()
        self.addCleanup(goal_library._METER_KINDS.clear)

    def test_a_board_reading_survives_a_frame_that_did_not_read_the_board(self):
        """The live defect: this used to answer ``False``, i.e. "the goal did not move"."""
        runtime = _runtime()
        runtime._remember_goal_meters([_intel(untried_pins=8)])
        self.assertEqual(runtime._goal_meters["CLEAR_INTEL"], -8.0)
        self.assertEqual(meter_kind(_intel(untried_pins=8)), "observation")

        # the next tick's board does not carry the count
        runtime._remember_goal_meters([_intel()])

        self.assertEqual(runtime._goal_meters["CLEAR_INTEL"], -8.0,
                         "the weaker distance reading must not replace the measured one")
        self.assertEqual(goal_library._METER_KINDS["CLEAR_INTEL"], "observation")
        self.assertIsNone(
            progress_moved(runtime._goal_meters, [_intel()], "CLEAR_INTEL"),
            "a frame that did not read the count is unobserved, not stalled",
        )

    def test_one_pin_fewer_on_a_board_frame_is_still_progress(self):
        runtime = _runtime()
        runtime._remember_goal_meters([_intel(untried_pins=8)])
        runtime._remember_goal_meters([_intel()])
        self.assertIs(
            progress_moved(runtime._goal_meters, [_intel(untried_pins=7)], "CLEAR_INTEL"), True,
        )

    def test_a_scale_change_drops_the_remembered_number_rather_than_comparing_across_it(self):
        """The other direction, so the pairing cannot be fixed on one side only.

        Note what the assertion is *not*: ``progress_moved`` against the very reading the flip
        recorded answers ``False``, and that is right -- the write in ``_remember_goal_meters``
        is the first reading on the new scale, so comparing it with itself means "unchanged".
        The property under test is that no verdict is ever *derived from* mixing the two scales,
        which shows up on the next frame that does not carry the count.
        """
        runtime = _runtime()
        runtime._remember_goal_meters([_intel()])          # distance scale first
        self.assertEqual(goal_library._METER_KINDS["CLEAR_INTEL"], "distance")
        self.assertEqual(runtime._goal_meters["CLEAR_INTEL"], 1.0)

        runtime._remember_goal_meters([_intel(untried_pins=8)])   # then the evidence scale

        self.assertEqual(goal_library._METER_KINDS["CLEAR_INTEL"], "observation")
        self.assertEqual(runtime._goal_meters["CLEAR_INTEL"], -8.0,
                         "the distance value must be replaced, not compared against")
        self.assertIsNone(
            progress_moved(runtime._goal_meters, [_intel()], "CLEAR_INTEL"),
            "a count-less frame is unobserved on this scale, never 'no progress'",
        )
        self.assertIs(
            progress_moved(runtime._goal_meters, [_intel(untried_pins=7)], "CLEAR_INTEL"), True,
        )

    def test_a_goal_with_no_observation_meter_keeps_the_distance_fallback(self):
        """Nothing is taken away where the distance comparison already meant something."""
        from winter_agent_v2.goal_library import GoalState as GS
        runtime = _runtime()
        plain = GS("SOME_GOAL", GoalStatus.READY, distance=3.0)
        runtime._remember_goal_meters([plain])
        self.assertEqual(goal_library._METER_KINDS["SOME_GOAL"], "distance")
        self.assertIs(progress_moved(runtime._goal_meters, [GS("SOME_GOAL", GoalStatus.READY,
                                                              distance=1.0)], "SOME_GOAL"), True)


if __name__ == "__main__":
    unittest.main()
