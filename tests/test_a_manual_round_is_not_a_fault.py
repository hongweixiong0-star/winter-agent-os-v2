"""A round that ended because the machine belongs to WorkBuddy is not a system fault.

Measured on the real root, 2026-10-06 07:24 UTC, three rows out of three in
``learning/auto_uptime.jsonl``:

    stop_reason=manually_owned_by_workbuddy   healthy=false

and the panel log read 「本轮被判定为系统故障：manually_owned_by_workbuddy」.  The operator
taking their own machine back was being recorded as a fault, because the reason the runtime
emits was never declared in ``runtime_snapshot``'s table and fell through to SYSTEM_FAILURE.

Two properties have to hold at once, and they pull in opposite directions -- which is why
this is a test and not a one-line edit:

* **healthy** -- the round yielded, nothing broke, so the uptime ledger must not count it as
  a fault (otherwise every Manual session silently poisons the acceptance metric);
* **halted** -- and yet the cycle must not continue, because the next round would hit the
  runtime's mode guard on its first tick and the panel and the runtime would spin against
  each other.

A test that only checks the first would let the spin back in.  Both are pinned here.
"""

from __future__ import annotations

import unittest

from tools import control_panel
from winter_agent_v2 import mode_state
from winter_agent_v2.runtime_snapshot import (
    AgentState,
    StopCategory,
    classify_stop_reason,
    state_for_stop_reason,
)


class ManualOwnershipIsNotAFault(unittest.TestCase):
    def test_the_reason_is_declared_so_it_does_not_fall_through(self) -> None:
        category = classify_stop_reason(mode_state.MANUAL_STOP_REASON)
        self.assertIs(StopCategory.EXPECTED_NO_ACTION, category)
        self.assertIsNot(StopCategory.SYSTEM_FAILURE, category)

    def test_the_agent_state_is_not_degraded(self) -> None:
        """A Manual round yields; it is not a degraded system."""
        _category, state = state_for_stop_reason(mode_state.MANUAL_STOP_REASON)
        self.assertIs(AgentState.IDLE, state)
        self.assertIsNot(AgentState.DEGRADED, state)

    def test_the_cycle_still_halts(self) -> None:
        """The half that pulls the other way: healthy, and still no next round."""
        self.assertFalse(control_panel.should_continue_auto_cycle(
            healthy=True, reason=mode_state.MANUAL_STOP_REASON,
            continuous=True, stop_requested=False, paused=False, fatal=False,
        ))

    def test_the_halt_says_manual_instead_of_system_fault(self) -> None:
        """The operator must not be told their own choice was a failure."""
        why = control_panel.auto_halt_reason(
            healthy=True, reason=mode_state.MANUAL_STOP_REASON,
            continuous=True, stop_requested=False, paused=False, fatal=False,
        )
        self.assertTrue(why, "a Manual round must halt, and must say why")
        self.assertIn("Manual", why)
        self.assertNotIn("系统故障", why)

    def test_a_real_fault_still_reads_as_a_fault(self) -> None:
        """The declaration must not widen into excusing genuine failures."""
        self.assertIs(StopCategory.SYSTEM_FAILURE,
                      classify_stop_reason("SOMETHING_BROKE_NOBODY_DECLARED"))
        why = control_panel.auto_halt_reason(
            healthy=False, reason="SOMETHING_BROKE_NOBODY_DECLARED",
            continuous=True, stop_requested=False, paused=False, fatal=False,
        )
        self.assertIn("系统故障", why)

    def test_the_runtime_emits_the_shared_constant(self) -> None:
        """Three modules agree on this string; a literal in any of them drifts."""
        self.assertEqual(mode_state.MANUAL_STOP_REASON, "manually_owned_by_workbuddy")


if __name__ == "__main__":
    unittest.main()
