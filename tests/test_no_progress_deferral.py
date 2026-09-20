"""The no-progress deferral must name the cause the episodes actually show.

Measured 2026-09-20: a goal that could not resolve its tap target produced 30 consecutive
episodes, and then 29 more after the route changed, and the deferral that exists to bound exactly
that stall could never fire -- ``runtime.py`` recorded no ``goal_progress`` for those steps, which
``_streak_and_last`` reads as "not measured".  ``runtime.py`` now records ``False`` for that case
(there is no after-frame, so the goal definitionally did not advance).

These tests cover the other half of the repair: the deferral's *reason* used to claim
unconditionally that the counted episodes "passed their verifier".  That was true of the case it
was written for (2026-09-18: 58 beast scans that landed and moved nothing) and false for this one,
where no verifier judged anything because no action was ever issued.  A reason the episodes
contradict is worse than a reason that says less, so the cause is read off the episodes and an
unmeasured cause is left unnamed.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from winter_agent_v2.capability_gate import (
    CapabilityGate,
    _no_progress_reason,
    _streak_and_last,
    _streak_record,
)
from winter_agent_v2.goal_library import GoalState, GoalStatus

GOAL = "MAIL_ROUTINE"
#: ``NO_PROGRESS_STREAK`` is 3; the counting itself is what is under test here, so the tests use
#: literal 2 and 3 and do not import the constant.
THRESHOLD = 3


def _row(progress, verifier="ABSENT"):
    """One episode row as ``_streak_and_last`` reads it.

    ``verifier`` may be ``True`` (an action was judged and passed), ``False`` (judged and
    rejected), ``None`` (no verdict), or omitted entirely, which is how the older episodes look.
    """
    row = {"goal_id": GOAL, "goal_progress": progress}
    if verifier != "ABSENT":
        row["verifier_ok"] = verifier
    return row


def _groups(*verdicts):
    return [[_row(False, verdict)] for verdict in verdicts]


class NoProgressReasonTests(unittest.TestCase):
    def test_episodes_that_issued_no_action_say_so(self):
        streak, _last, _skill, evidence = _streak_and_last(
            _groups(None, None, None), GOAL, since=None
        )
        self.assertEqual(streak, THRESHOLD)
        self.assertEqual(evidence, (3, 0, 0))
        reason = _no_progress_reason(streak, evidence)
        self.assertIn("issued no action at all", reason)
        self.assertNotIn("passed their verifier", reason)

    def test_episodes_that_passed_their_verifier_still_say_that(self):
        streak, _last, _skill, evidence = _streak_and_last(
            _groups(True, True, True), GOAL, since=None
        )
        self.assertEqual(evidence, (0, 0, 3))
        self.assertIn("passed their verifier", _no_progress_reason(streak, evidence))

    def test_rejected_actions_say_rejected(self):
        streak, _last, _skill, evidence = _streak_and_last(
            _groups(False, False, False), GOAL, since=None
        )
        self.assertEqual(evidence, (0, 3, 0))
        reason = _no_progress_reason(streak, evidence)
        self.assertIn("rejected", reason)
        self.assertNotIn("passed their verifier", reason)

    def test_a_mixed_population_reports_the_breakdown(self):
        streak, _last, _skill, evidence = _streak_and_last(
            _groups(True, None, False), GOAL, since=None
        )
        self.assertEqual(evidence, (1, 1, 1))
        reason = _no_progress_reason(streak, evidence)
        self.assertIn("1 passed their verifier", reason)
        self.assertIn("1 were rejected", reason)
        self.assertIn("1 issued no action", reason)

    def test_an_unmeasured_cause_is_not_named(self):
        """A legacy three-field record says nothing about what the episodes did."""
        self.assertIsNone(_streak_record((3, None, "DISMISS_MAIL_GENERIC_REWARD"))[3])
        reason = _no_progress_reason(3, None)
        self.assertNotIn("passed their verifier", reason)
        self.assertNotIn("issued no action", reason)
        self.assertNotIn("rejected", reason)

    def test_episodes_without_a_recorded_verdict_count_as_no_action(self):
        rows = [[{"goal_id": GOAL, "goal_progress": False}] for _ in range(THRESHOLD)]
        self.assertEqual(_streak_and_last(rows, GOAL, since=None)[3], (3, 0, 0))

    def test_other_goals_in_the_same_runs_are_ignored(self):
        rows = [[{"goal_id": "OTHER", "goal_progress": None}, _row(False, None)]
                for _ in range(THRESHOLD)]
        self.assertEqual(_streak_and_last(rows, GOAL, since=None)[0], THRESHOLD)
        self.assertEqual(_streak_and_last(rows, "OTHER", since=None)[0], 0)

    def test_progress_that_was_never_measured_breaks_the_streak(self):
        """The guard that keeps "everything counts as a streak" from coming back."""
        self.assertEqual(
            _streak_and_last([[_row(None, None)] for _ in range(THRESHOLD)], GOAL, since=None)[0],
            0,
        )

    def test_a_short_streak_is_counted_but_is_not_yet_a_deferral(self):
        self.assertEqual(
            _streak_and_last([[_row(False, None)] for _ in range(THRESHOLD - 1)], GOAL,
                             since=None)[0],
            THRESHOLD - 1,
        )

    def test_the_new_record_shape_survives_a_round_trip(self):
        res = _streak_and_last(_groups(None, None, None), GOAL, since=None)
        self.assertEqual(_streak_record(res), res)


class TheDeferralCarriesThoseWordsTests(unittest.TestCase):
    """The half that matters: the deferral itself, not the helper beside it.

    These go through ``CapabilityGate._no_progress_deferral``, the path production uses.  A test
    that only calls ``_no_progress_reason`` cannot fail if the gate stops calling it -- the first
    version of this file made exactly that mistake, and it was caught by restoring the old
    unconditional reason string and watching all ten tests stay green.
    """

    NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    SKILL = "DISMISS_MAIL_GENERIC_REWARD"

    def _gate(self, evidence, *, streak=THRESHOLD):
        return CapabilityGate(
            streaks={GOAL: (streak, self.NOW - timedelta(minutes=5), self.SKILL, evidence)},
            no_progress_threshold=THRESHOLD,
        )

    def _goal(self):
        return GoalState(GOAL, GoalStatus.READY, available_skills=(self.SKILL,), distance=1)

    def test_a_stall_that_issued_no_action_is_deferred_and_says_so(self):
        defer = self._gate((3, 0, 0))._no_progress_deferral(self._goal(), self.NOW)
        self.assertIsNotNone(defer, "three no-progress episodes must produce a deferral")
        self.assertIn("issued no action at all", defer.reason)
        self.assertNotIn("passed their verifier", defer.reason)

    def test_a_streak_that_passed_its_verifier_keeps_the_original_wording(self):
        defer = self._gate((0, 0, 3))._no_progress_deferral(self._goal(), self.NOW)
        self.assertIsNotNone(defer)
        self.assertIn("passed their verifier", defer.reason)

    def test_a_legacy_record_is_deferred_without_claiming_a_cause(self):
        """A streak written before the evidence field existed must not be given a cause."""
        defer = self._gate(None)._no_progress_deferral(self._goal(), self.NOW)
        self.assertIsNotNone(defer, "a legacy streak still defers; it just says less")
        self.assertNotIn("passed their verifier", defer.reason)
        self.assertNotIn("issued no action", defer.reason)
        self.assertNotIn("rejected", defer.reason)

    def test_below_the_threshold_nothing_is_deferred(self):
        self.assertIsNone(
            self._gate((2, 0, 0), streak=THRESHOLD - 1)._no_progress_deferral(self._goal(), self.NOW)
        )


if __name__ == "__main__":
    unittest.main()
