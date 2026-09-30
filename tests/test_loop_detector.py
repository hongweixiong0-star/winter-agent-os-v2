"""LOOP_DETECTOR_V1 — the signatures, the four patterns, and the recovery ladder.

The detector is a pure function of the signatures it is fed, so most of this file is a
sequence of observations and a claim about what came back.  The parts worth reading are the
negatives: three *identical successes* must not be a loop, an **unread** progress must not be
counted as *no* progress, and a detection must be retractable by the very next frame -- those
are the three ways a detector silently becomes either useless or harmful, and each has its
own test.

The engine half (does a looping session actually drive the ladder, and does it end the
session rather than the run?) lives in ``test_loop_detector_boundary.py``, next to the other
acceptance properties the directive names.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.loop_detector import (  # noqa: E402
    LOOP_DEFERRED,
    LOOP_DETECTED,
    LOOP_DETECTED_NET,
    LOOP_FALSE_POSITIVE,
    LOOP_RECOVERED,
    RECOVERY_LADDER,
    RELEVANT_STATE_FIELDS,
    RUNG_DEFER_GOAL,
    RUNG_FEATURE_REOPEN,
    RUNG_HOME_RECOVERY,
    RUNG_LOCAL_REOBSERVE,
    RUNG_SEMANTIC_RETRY,
    RUNG_WIDEN_OBSERVE,
    LoopDetector,
    LoopPattern,
    LoopSignature,
    LoopVerdict,
    progress_from_outcome,
    relevant_state_hash,
)
from winter_agent_v2.session_engine import StepOutcome  # noqa: E402


class World:
    """The smallest thing ``relevant_state_hash`` can read.

    Deliberately an object rather than a dict: the live path reads a ``WorldState`` by
    attribute, and a detector that only worked on mappings would pass every test here and
    hash ``None`` for every field in production.
    """

    def __init__(self, page="HOME", popup=None, march_used=3, march_max=6,
                 normal_idle_slots=2):
        self.page = page
        self.popup = popup
        self.march_used = march_used
        self.march_max = march_max
        self.normal_idle_slots = normal_idle_slots


def sig(page="HOME", goal="G1", skill="TAP", target="X", state_hash="h1", outcome="FAILED",
        progress=False, role="R1"):
    return LoopSignature(role_id=role, page=page, goal_id=goal, skill_id=skill,
                         semantic_target=target, state_hash=state_hash,
                         verifier_outcome=outcome, progress=progress)


class AStepIsContextActionFeedbackTests(unittest.TestCase):
    """The signature carries the directive's seven fields, and they mean what they say."""

    def test_the_signature_carries_all_seven_declared_fields(self):
        s = sig()
        row = s.as_row()
        for field in ("role_id", "page", "goal_id", "skill_id", "semantic_target",
                      "state_hash", "verifier_outcome"):
            self.assertIn(field, row, f"{field} is part of the declared signature")

    def test_the_full_key_includes_the_state_and_the_verdict(self):
        base = sig()
        self.assertNotEqual(base.key, sig(state_hash="h2").key,
                            "a different situation is a different signature")
        self.assertNotEqual(base.key, sig(outcome="SUCCESS").key,
                            "a different answer is a different signature")

    def test_the_action_key_excludes_the_page_state_and_verdict(self):
        """The same tap is the same tap even when the page drifts and the frame changes.

        This is the whole reason there are two keys: a detector keyed only on the full
        signature cannot see the pattern that costs the most (the same absent target being
        tapped again from a different page).
        """
        base = sig()
        self.assertEqual(base.action_key, sig(page="DAILY", state_hash="zz", outcome="SUCCESS").action_key)
        self.assertNotEqual(base.action_key, sig(skill="OTHER").action_key)
        self.assertNotEqual(base.action_key, sig(role="R2").action_key,
                            "a different role is a different context")

    def test_the_digest_is_stable_and_short(self):
        self.assertEqual(sig().digest, sig().digest)
        self.assertEqual(len(sig().digest), 10)

    def test_progress_is_derived_from_the_outcome_with_a_real_tri_state(self):
        self.assertIs(progress_from_outcome(StepOutcome.SUCCESS), True)
        self.assertIs(progress_from_outcome(StepOutcome.PROGRESS), True)
        self.assertIs(progress_from_outcome(StepOutcome.FAILED), False)
        # The two that must stay *unread*.  A STILL_PENDING step is honest work in flight;
        # calling it "no progress" is how a detector counts a working cast as a loop.
        self.assertIsNone(progress_from_outcome(StepOutcome.STILL_PENDING))
        self.assertIsNone(progress_from_outcome(StepOutcome.AMBIGUOUS))


class TheStateHashOnlyCoversWhatALoopCanBeStuckAboutTests(unittest.TestCase):

    def test_an_unread_field_does_not_hash_like_a_read_zero(self):
        """'empty != none'.  An unread march count must not be flattened to 0."""
        unread = relevant_state_hash(World(march_used=None))
        zero = relevant_state_hash(World(march_used=0))
        self.assertNotEqual(unread, zero)

    def test_a_changed_relevant_field_changes_the_hash(self):
        self.assertNotEqual(relevant_state_hash(World(page="HOME")),
                            relevant_state_hash(World(page="DAILY")))

    def test_an_irrelevant_change_does_not_change_the_hash(self):
        """The hash must be insensitive to things a loop is not about.

        If it covered the whole WorldState it would change every frame for reasons unrelated
        to progress, no repeat would ever match, and the detector would be silently useless.
        """
        class WithExtra:
            page = "HOME"
            popup = None
            march_used = 3
            march_max = 6
            normal_idle_slots = 2
            stamina = {"value": 999}
            confidence = 0.12

        self.assertEqual(relevant_state_hash(World()),
                         relevant_state_hash(WithExtra()),
                         "fields outside the declared projection must not move the hash")

    def test_it_reads_a_mapping_as_well_as_an_object(self):
        live = {"page": "MAP", "popup": None, "march_used": 1, "march_max": 6,
                "normal_idle_slots": 5}
        self.assertEqual(relevant_state_hash(live), relevant_state_hash(World(page="MAP", march_used=1, normal_idle_slots=5)))

    def test_the_projection_is_declared_and_short(self):
        self.assertIn("page", RELEVANT_STATE_FIELDS)
        self.assertLessEqual(len(RELEVANT_STATE_FIELDS), 8,
                             "a wide projection is how the hash stops matching anything")


class TheFourPatternsTheDirectiveNamesTests(unittest.TestCase):

    def test_aaa_fires_on_the_third_identical_signature(self):
        d = LoopDetector()
        self.assertFalse(d.observe(sig()).detected)
        self.assertFalse(d.observe(sig()).detected)
        v = d.observe(sig())
        self.assertTrue(v.detected)
        self.assertEqual(v.pattern, LoopPattern.AAA.value)
        self.assertEqual(v.repeats, 3)

    def test_abab_fires_on_the_fourth_entry(self):
        d = LoopDetector()
        for page in ("HOME", "DAILY", "HOME"):
            d.observe(sig(page=page, skill="K" + page, state_hash="h" + page))
        v = d.observe(sig(page="DAILY", skill="KDAILY", state_hash="hDAILY"))
        self.assertTrue(v.detected)
        self.assertEqual(v.pattern, LoopPattern.ABAB.value)

    def test_same_action_no_progress_fires_while_the_page_and_state_drift(self):
        """The pattern a full-key detector cannot see: same tap, moving frame, no progress."""
        d = LoopDetector()
        for i, page in enumerate(("EXPLORATION", "EXPLORATION", "DAILY")):
            v = d.observe(sig(page=page, state_hash=f"h{i}", target="钓鱼锦标赛",
                              outcome="NO_EXECUTION", progress=False))
        self.assertTrue(v.detected)
        self.assertEqual(v.pattern, LoopPattern.SAME_ACTION_NO_PROGRESS.value)

    def test_navigation_loop_fires_on_the_second_cycle_of_pages(self):
        d = LoopDetector()
        for page in ("HOME", "DAILY", "POPUP"):
            d.observe(sig(page=page, skill="K" + page, state_hash="h" + page))
        v = d.observe(sig(page="HOME", skill="KHOME", state_hash="hHOME"))
        self.assertFalse(v.detected, "one cycle is not yet a loop")
        d.observe(sig(page="DAILY", skill="KDAILY", state_hash="hDAILY"))
        v = d.observe(sig(page="POPUP", skill="KPOPUP", state_hash="hPOPUP"))
        self.assertTrue(v.detected)
        self.assertEqual(v.pattern, LoopPattern.NAVIGATION_LOOP.value)

    def test_a_single_page_repeating_is_never_called_navigation(self):
        """A stuck page is AAA's business.  Calling it navigation would mislabel the remedy:
        there is nothing to navigate back to."""
        d = LoopDetector()
        for _ in range(8):
            v = d.observe(sig(page="HOME", skill="TAP"))
        self.assertNotEqual(v.pattern, LoopPattern.NAVIGATION_LOOP.value)

    def test_two_pages_revisited_with_different_work_each_lap_are_not_a_navigation_loop(self):
        """The case a page-only test gets wrong, and the reason ``move_key`` exists.

        ``HOME -> ALLIANCE -> HOME -> ALLIANCE`` while tapping a *different* control on each
        visit is a client being used, not a client walked in a circle: the pages repeat but
        nothing was retried.  Page periodicity alone calls this a navigation loop, which would
        spend rungs on honest work -- the one failure mode worse than no detector.
        """
        d = LoopDetector()
        laps = [("HOME", "OPEN_ALLIANCE"), ("ALLIANCE", "OPEN_GIFTS"),
                ("HOME", "OPEN_MAIL"), ("ALLIANCE", "COLLECT_DONATION")]
        for page, skill in laps:
            v = d.observe(sig(page=page, skill=skill, state_hash="h"))
        self.assertFalse(v.detected)
        self.assertEqual(d.summary()[LOOP_DETECTED], 0)

    def test_a_move_cycle_still_fires_when_the_state_and_verdict_differ_lap_to_lap(self):
        """The other side of the same coin: the *moves* repeat, so it is still a circle.

        A reward popup that appears on one lap and not the other changes the state hash and
        the verdict.  Requiring the whole signature to be periodic would miss exactly the
        circuit a player is stuck in, so only the move has to repeat.
        """
        d = LoopDetector()
        d.observe(sig(page="HOME", skill="K_HOME", state_hash="a", outcome="SUCCESS"))
        d.observe(sig(page="ALLIANCE", skill="K_ALLIANCE", state_hash="b", outcome="SUCCESS"))
        d.observe(sig(page="HOME", skill="K_HOME", state_hash="c", outcome="FAILED"))
        v = d.observe(sig(page="ALLIANCE", skill="K_ALLIANCE", state_hash="d", outcome="FAILED"))
        self.assertTrue(v.detected)
        self.assertEqual(v.pattern, LoopPattern.NAVIGATION_LOOP.value)


class TheDetectorDoesNotFireOnHonestWorkTests(unittest.TestCase):
    """The negatives.  A detector that fires here is worse than no detector."""

    def test_three_identical_successes_that_each_made_progress_are_not_a_loop(self):
        d = LoopDetector()
        for _ in range(6):
            v = d.observe(sig(outcome="SUCCESS", progress=True))
        self.assertFalse(v.detected)
        self.assertEqual(d.summary()[LOOP_DETECTED], 0)

    def test_an_unread_progress_is_not_counted_as_no_progress(self):
        """The tri-state exists for this.  Two taps with unread progress must not be a loop."""
        d = LoopDetector()
        for _ in range(6):
            v = d.observe(sig(outcome="STILL_PENDING", progress=None))
        self.assertFalse(v.detected)

    def test_a_two_page_walk_that_progressed_is_not_a_navigation_loop(self):
        d = LoopDetector()
        pages = ("HOME", "DAILY", "HOME", "DAILY")
        for page in pages[:-1]:
            d.observe(sig(page=page, skill="K" + page, state_hash="h" + page))
        v = d.observe(sig(page="DAILY", skill="KDAILY", state_hash="hDAILY", progress=True))
        self.assertFalse(v.detected, "progress anywhere in the block disqualifies it")

    def test_a_different_skill_each_time_is_not_a_repeat(self):
        d = LoopDetector()
        for i in range(6):
            v = d.observe(sig(skill=f"SKILL_{i}"))
        self.assertFalse(v.detected)

    def test_a_short_session_that_edits_a_different_control_never_fires(self):
        """Three dismissals of three *different* popups are three different actions."""
        d = LoopDetector()
        for popup in ("A", "B", "C", "D"):
            v = d.observe(sig(page="POPUP", skill="DISMISS", target=popup, outcome="SUCCESS"))
        self.assertFalse(v.detected)


class TheRecoveryLadderIsTheOneTheDirectiveSpecifiesTests(unittest.TestCase):

    def test_the_ladder_is_exactly_the_declared_order(self):
        self.assertEqual(RECOVERY_LADDER, (
            RUNG_SEMANTIC_RETRY, RUNG_LOCAL_REOBSERVE, RUNG_WIDEN_OBSERVE,
            RUNG_FEATURE_REOPEN, RUNG_HOME_RECOVERY, RUNG_DEFER_GOAL,
        ))

    def test_repeats_escalate_monotonically_and_stop_at_defer(self):
        d = LoopDetector()
        rungs = []
        for _ in range(20):
            v = d.observe(sig())
            if v.detected:
                rungs.append(v.rung)
        self.assertEqual(rungs[0], RUNG_SEMANTIC_RETRY)
        self.assertEqual(rungs[-1], RUNG_DEFER_GOAL)
        self.assertEqual(rungs[-1], RECOVERY_LADDER[-1],
                         "the ladder must saturate rather than invent a rung")
        self.assertEqual(len(set(rungs)) <= len(RECOVERY_LADDER), True)
        # Monotone: never go back down while the same action keeps failing.
        order = {name: i for i, name in enumerate(RECOVERY_LADDER)}
        indices = [order[r] for r in rungs]
        self.assertEqual(indices, sorted(indices))

    def test_the_ladder_resets_when_the_action_finally_makes_progress(self):
        d = LoopDetector()
        for _ in range(4):
            d.observe(sig())
        self.assertEqual(d.summary()["LOOP_LADDER_TOP"], RUNG_LOCAL_REOBSERVE)
        d.observe(sig(outcome="SUCCESS", progress=True))
        self.assertEqual(d.summary()["LOOP_LADDER_TOP"], "",
                         "a Goal that moved must not start the next flow one rung up")

    def test_a_gap_restarts_the_ladder_at_its_cheapest_rung(self):
        """The rung is dropped the moment the flow does something else.

        Measured on ``learning/episodes.jsonl``: all 222 defer-rung detections were
        *consecutive* escalations, none was reached across a gap.  That is load-bearing.  A
        move that fails once per round would otherwise climb to ``defer_goal`` over a whole
        run and take the Goal away for a fault the Goal-level ``no_progress_streak`` already
        handles between rounds -- the detector would be answering the coarse question with
        fine-grained evidence.  Spending the ladder only on consecutive repeats is what keeps
        the two halves of the remedy separate.
        """
        d = LoopDetector()
        for _ in range(4):
            d.observe(sig())
        self.assertEqual(d.summary()["LOOP_LADDER_TOP"], RUNG_LOCAL_REOBSERVE)
        d.observe(sig(skill="OTHER", state_hash="h9"))  # the flow did something else
        for _ in range(2):
            d.observe(sig())
        v = d.observe(sig())
        self.assertTrue(v.detected)
        self.assertEqual(v.rung, RUNG_SEMANTIC_RETRY,
                         "a fresh repeat after a gap starts the ladder over")

    def test_deferring_is_counted_separately(self):
        d = LoopDetector()
        for _ in range(8):
            d.observe(sig())
        self.assertEqual(d.summary()[LOOP_DEFERRED], 1)
        self.assertTrue(d.observe(sig()).wants_defer,
                        "once spent, the ladder stays at defer rather than restarting")

    def test_note_progress_forgets_the_action_the_adapter_reports(self):
        """A domain layer can know progress the step outcome cannot show."""
        d = LoopDetector()
        for _ in range(3):
            d.observe(sig(goal="TRAIN", skill="TRAIN_TROOPS"))
        self.assertNotEqual(d.summary()["LOOP_LADDER_TOP"], "")
        d.note_progress(goal_id="TRAIN")
        self.assertEqual(d.summary()["LOOP_LADDER_TOP"], "")


class ADetectionIsAClaimUntilTheNextFrameTests(unittest.TestCase):
    """``LOOP_FALSE_POSITIVE`` measured rather than assumed away."""

    def test_progress_on_the_tracked_action_retracts_the_detection(self):
        d = LoopDetector()
        for _ in range(3):
            d.observe(sig())
        self.assertEqual(d.summary()[LOOP_DETECTED], 1)
        v = d.observe(sig(outcome="SUCCESS", progress=True))
        self.assertTrue(v.retracted)
        self.assertFalse(v.detected)
        summary = d.summary()
        self.assertEqual(summary[LOOP_FALSE_POSITIVE], 1)
        self.assertEqual(summary[LOOP_DETECTED_NET], 0,
                         "the net is derived from the two halves, never stored")

    def test_progress_on_a_different_action_is_not_a_false_positive(self):
        """The flow moved on.  That says nothing about whether the tracked action was stuck,
        and counting it would inflate the error rate with cases the detector never got wrong."""
        d = LoopDetector()
        for _ in range(3):
            d.observe(sig(goal="G1", skill="TAP"))
        d.observe(sig(goal="G2", skill="OTHER", outcome="SUCCESS", progress=True))
        self.assertEqual(d.summary()[LOOP_FALSE_POSITIVE], 0)

    def test_a_rung_that_was_spent_before_the_flow_moved_counts_as_recovered(self):
        d = LoopDetector()
        for _ in range(4):
            d.observe(sig())
        d.observe(sig(goal="G2", skill="OTHER", outcome="SUCCESS", progress=True))
        self.assertEqual(d.summary()[LOOP_RECOVERED], 1)

    def test_the_summary_reports_both_halves_and_a_derived_net(self):
        d = LoopDetector()
        for _ in range(3):
            d.observe(sig())
        d.observe(sig(outcome="SUCCESS", progress=True))
        for _ in range(3):
            d.observe(sig(state_hash="h2"))
        s = d.summary()
        self.assertEqual(s[LOOP_DETECTED], 2)
        self.assertEqual(s[LOOP_FALSE_POSITIVE], 1)
        self.assertEqual(s[LOOP_DETECTED_NET], 1)

    def test_the_timeline_records_every_observation_and_every_verdict(self):
        d = LoopDetector()
        for _ in range(4):
            d.observe(sig())
        timeline = d.summary()["LOOP_TIMELINE"]
        kinds = [row["kind"] for row in timeline]
        self.assertEqual(kinds.count("detected"), 2)
        self.assertEqual(kinds.count("ok"), 2)
        detected = [row for row in timeline if row["kind"] == "detected"]
        self.assertTrue(all(row["rung"] for row in detected),
                        "a detection without a rung is a verdict nobody can act on")

    def test_an_one_off_loop_in_the_middle_of_a_long_flow_is_still_reported(self):
        d = LoopDetector()
        for i in range(5):
            d.observe(sig(skill=f"K{i}", state_hash=f"h{i}", outcome="SUCCESS", progress=True))
        for _ in range(3):
            d.observe(sig(skill="STUCK", state_hash="hs", outcome="FAILED", progress=False))
        self.assertEqual(d.summary()[LOOP_DETECTED], 1)
        self.assertEqual(d.summary()["LOOP_PATTERNS"], {LoopPattern.AAA.value: 1})


class TheLedgerIsPerFlowTests(unittest.TestCase):

    def test_reset_keeps_the_counters_but_forgets_the_window(self):
        d = LoopDetector()
        for _ in range(3):
            d.observe(sig())
        d.reset()
        self.assertEqual(d.summary()[LOOP_DETECTED], 1, "the ledger is the session's")
        self.assertFalse(d.observe(sig()).detected,
                         "a new flow must not inherit the old window")

    def test_two_detectors_share_nothing(self):
        a, b = LoopDetector(), LoopDetector()
        for _ in range(3):
            a.observe(sig())
        self.assertEqual(b.summary()[LOOP_DETECTED], 0)
        self.assertEqual(len(b.timeline), 0)

    def test_a_verdict_without_a_detection_is_falsy_and_carries_no_rung(self):
        v = LoopVerdict()
        self.assertFalse(v)
        self.assertEqual(v.rung, "")
        self.assertFalse(v.wants_defer)

    def test_a_detectable_verdict_is_truthy(self):
        self.assertTrue(LoopVerdict(detected=True, pattern="AAA", rung=RUNG_SEMANTIC_RETRY))


if __name__ == "__main__":
    unittest.main()
