"""The router must say why it chose the hop the step ran, not only that it failed.

Measured 2026-10-14: the ledger's largest failure cluster is
``GIANT_BEAST_SEARCH_NOT_PROVEN`` (164 of 206 attempts), produced by
``SUBMIT_GIANT_BEAST_SEARCH`` -- which ``operations_policy.choose_stamina_goal`` reaches
only as the **fallback after INTEL**.  So the first question the cluster raises is "why
GIANT_BEAST and not INTEL this time", and that is a question about a route decision the
episode did not record: ``_stamina_route`` computed it, wrote it into the goal's own
evidence, and it never reached disk (the field appeared **0 times** in the whole stream).

The recorder is also the trap.  ``_stamina_route`` has three callers and two of them walk
the whole goal board, so a recorder *inside* the method would have stamped whichever goal
happened to be last in the loop.  These tests pin both halves: the value is read from the
goal that was chosen, and a goal with no decision reads empty rather than guessed.
"""

from __future__ import annotations

import unittest
from dataclasses import asdict

from winter_agent_v2.learning import Episode
from winter_agent_v2.runtime import _stamina_route_reason


class TheStaminaRouteRecordsItsOwnChoiceTest(unittest.TestCase):
    def test_the_sink_and_its_reason_are_read_off_the_goal(self):
        sink, reason = _stamina_route_reason({
            "stamina_sink": "GIANT_BEAST",
            "stamina_sink_reason": "intel_unavailable_use_verified_giant_beast",
        })
        self.assertEqual(sink, "GIANT_BEAST")
        self.assertEqual(reason, "intel_unavailable_use_verified_giant_beast")

    def test_the_answer_comes_from_the_goal_it_was_handed(self):
        """The loop trap, stated as a test.

        ``_stamina_route`` is called for every goal while the board is re-ranked, so the
        recorder must answer per-goal.  If it ever reads run-scoped state instead, these
        two calls return the same thing and the ledger starts blaming the wrong goal.
        """
        chosen = {"stamina_sink": "GIANT_BEAST", "stamina_sink_reason": "fallback"}
        other = {"stamina_sink": "INTEL", "stamina_sink_reason": "stamina_at_or_above_floor_intel_first"}
        self.assertNotEqual(_stamina_route_reason(chosen), _stamina_route_reason(other))
        self.assertEqual(_stamina_route_reason(chosen)[0], "GIANT_BEAST")
        self.assertEqual(_stamina_route_reason(other)[0], "INTEL")

    def test_a_goal_with_no_decision_reads_empty_rather_than_guessed(self):
        """Empty is the honest answer, the same convention ``recognition_error`` uses."""
        for nothing in ({}, None, [], "", "not a mapping"):
            with self.subTest(evidence=nothing):
                self.assertEqual(_stamina_route_reason(nothing), ("", ""))

    def test_a_partial_decision_does_not_invent_the_other_half(self):
        sink, reason = _stamina_route_reason({"stamina_sink": "BEAST_HUNT"})
        self.assertEqual(sink, "BEAST_HUNT")
        self.assertEqual(reason, "")

    def test_the_episode_carries_the_route_choice(self):
        """The fields have to survive the one serialisation the ledger uses."""
        episode = Episode(
            skill="SUBMIT_GIANT_BEAST_SEARCH", state_before={}, action={}, state_after={},
            result="FAILURE", failure_type="GIANT_BEAST_SEARCH_NOT_PROVEN",
            duration=0.0, mode="PRODUCTION",
            stamina_sink="GIANT_BEAST",
            stamina_sink_reason="intel_unavailable_use_verified_giant_beast",
        )
        row = asdict(episode)
        self.assertEqual(row["stamina_sink"], "GIANT_BEAST")
        self.assertEqual(row["stamina_sink_reason"], "intel_unavailable_use_verified_giant_beast")

    def test_a_route_less_step_defaults_to_empty(self):
        """A step that is not stamina-routed must not claim a sink."""
        episode = Episode(
            skill="OPEN_HOME", state_before={}, action={}, state_after={},
            result="SUCCESS", failure_type=None, duration=0.0, mode="PRODUCTION",
        )
        row = asdict(episode)
        self.assertEqual(row["stamina_sink"], "")
        self.assertEqual(row["stamina_sink_reason"], "")


if __name__ == "__main__":
    unittest.main()
