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

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import control_experience  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.goal_library import GoalState, GoalStatus  # noqa: E402
from winter_agent_v2.learning import EpisodeStore  # noqa: E402
from winter_agent_v2.models import Decision, Page, VerificationResult, WorldState  # noqa: E402
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
    #: BTN_CLOSE is in the set because the exit-sequence tests below drive a real
    #: LEAVE_FOREIGN_LAYER step, whose whole point is the close in the layer's corner.
    #: Without it the step answers SEMANTIC_TARGET_NOT_VERIFIED and the scenario degenerates
    #: into "the close was never sendable", which is a different (and already tested) fact.
    def find(self, _path, semantic):
        return _FakeMatch() if semantic in {"BTN_ALLY_GIFT_CLAIM", "PAGE_MAP", "BTN_OPEN_HOME", "BTN_CLOSE"} else None

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _FakeVision:
    """Replay a fixed frame list, then keep answering with the last one.

    The sticky tail is deliberate for the exit-sequence tests: a run that is refused and
    re-observes captures more frames than the scenario list has, and stopping the iterator
    there would report a test-harness exhaustion as if it were a product failure.  A
    scenario that wants a run to end supplies its own terminal frame.
    """

    def __init__(self, states, *, sticky: bool = False):
        self.states = list(states)
        self._index = 0
        self._sticky = sticky

    def observe(self, _path):
        if self._index < len(self.states):
            state = self.states[self._index]
            self._index += 1
            return state
        if self._sticky and self.states:
            return self.states[-1]
        raise StopIteration


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
    where the line is.

    ``camp_entry_is_a_guided_step_not_a_selection`` replaced ``camp_menu_never_drawn``
    on 2026-09-21, when issue #82 was settled off the frames: the gold ellipse is on the
    ground, the tutorial hand points at the 2-badged action block, and three consecutive
    live frames showed nothing progressing toward a menu.  A guided step is a
    precondition, not a menu that is late, so the reason now says so -- and unlike its
    predecessor it is named in NON_FATAL_STOPS as well, because "this entry point is not
    usable right now" is the same class of answer as ``training_queue_busy``.
    """

    NAMED = (
        "reserved_march_for_stamina",
        "no_idle_march",
        "camp_entry_is_a_guided_step_not_a_selection",
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

    def test_the_guided_step_reason_is_named_in_the_non_fatal_set(self):
        """The replacement is not merely shaped like a refusal -- it is listed as one.

        The predecessor qualified only by shape (no FATAL_ prefix), which worked but left
        a reader guessing whether that was intended.  Naming it is the durable version.
        """
        from winter_agent_v2.runtime_snapshot import NON_FATAL_STOPS

        self.assertIn("camp_entry_is_a_guided_step_not_a_selection", NON_FATAL_STOPS)
        self.assertIn("training_queue_busy", NON_FATAL_STOPS,
                      "the reason it is modelled on must still be there")

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


class ABackThatDoesNotMoveTheClientDoesNotEndTheCycleTests(unittest.TestCase):
    """The other half of "a refusal is about one goal": a FAILED exit is too.

    Measured live 2026-09-21 14:22, and this is the frame the class is named for:

        goal KEEP_TRAINING_PRODUCTIVE, page ALLIANCE (the alliance chest layer)
        step 1  BACK  ->  after page ALLIANCE   verifier SAFE_BACK_NOT_PROVEN
        stop_reason SAFE_BACK_NOT_PROVEN

    The layer is a sub-page with its own X in the corner; a Back moves nothing.  The run
    ended, and ``foreign_page_left`` was already set, so every later run answered
    ``training_entry_not_verified`` without trying -- one unmovable layer cost the cycle
    its training work permanently.  Two things had to change and both are asserted here:
    the runtime must give the brain room for its second exit, and the brain must have one.
    """

    #: The goal from the live frame.  KEEP_TRAINING_PRODUCTIVE is what the 14:22 run selected,
    #: and it is the one that carries the two-step route: its brain branch starts from HOME,
    #: so a client found on ALLIANCE gets the foreign-page hop -- Back, then the close.  The
    #: sibling class above uses ALLIANCE_ROUTINE, whose *own* route answers on this layer and
    #: therefore never reaches the hop; using it here would have tested the SAFE_STOP handover
    #: a second time instead of the exit sequence, which is exactly what the first red run of
    #: these tests showed.  ``available_skills`` is load-bearing: ``GoalLibrary.best`` drops a
    #: goal that declares none.
    LAYER_GOAL = GoalState(
        goal_id="KEEP_TRAINING_PRODUCTIVE",
        status=GoalStatus.READY,
        available_skills=("TRAIN_TROOPS",),
    )

    def _selectable_stub(self, goal):
        def stub(runtime, _goals, _deferrals):
            if goal is None or goal.goal_id in runtime._yielded_goals:
                return []
            return [goal]
        return stub

    def _run(self, states, max_actions=6):
        device = _FakeDevice()
        with TemporaryDirectory() as temp:
            with patch.object(LiveRuntime, "_selectable", self._selectable_stub(self.LAYER_GOAL)):
                run = LiveRuntime(
                    device=device,
                    vision=_FakeVision(states, sticky=True),
                    semantic_vision=_FakeSemantic(),
                    capture_dir=Path(temp),
                    sleeper=lambda _seconds: None,
                ).run(max_actions=max_actions)
        return device, run

    def test_the_second_exit_is_the_close_not_a_repeated_back(self):
        """The Back moves nothing, so the close is what the run must reach.

        Both frames are the alliance layer.  The first Back cannot change that, so the
        only way this run touches the device twice is if the runtime handed the cycle
        back and the brain answered the layer's own exit.
        """
        layer = alliance_gift("CLAIMED", buttons=0, claimed=2, progress=250)
        device, run = self._run([layer, layer, layer])
        self.assertGreaterEqual(
            len(device.backs), 1,
            "the first exit is still a Back -- it is correct on every panel measured so far",
        )
        self.assertGreaterEqual(
            len(device.taps), 1,
            "the layer ignored the Back, so the close must actually be sent",
        )

    def test_a_layer_that_answers_neither_exit_still_ends_honestly(self):
        """The pair is bounded, and so is the runtime's patience with it.

        The device never moves, so neither exit can verify.  The run must stop rather
        than spend its whole action budget re-sending two commands at a wall, and the
        stop reason must be the verifier's own answer rather than a fabricated success.
        """
        layer = alliance_gift("CLAIMED", buttons=0, claimed=2, progress=250)
        device, run = self._run([layer] * 10, max_actions=8)
        # The wall costs the pair and nothing more.  Asserted as a bound rather than as one
        # exact stop reason: once the goal has been held back, the selector may legitimately
        # land on a different goal's own answer, and pinning that here would make this test
        # about the selector instead of about the exit sequence it exists to guard.
        self.assertLessEqual(
            len(run.steps), 6,
            "a wall must cost a bounded number of attempts, not the whole budget",
        )
        self.assertGreaterEqual(
            len(device.backs) + len(device.taps), 1,
            "the exits were tried before the run gave up",
        )
        self.assertIsNotNone(run.stop_reason, "and it ended with a stated reason, not silence")

    def test_the_leaving_skills_are_the_two_the_brain_can_answer(self):
        """Pinned where the branch reads it, so the recovery cannot silently lose a skill."""
        self.assertEqual(
            set(LiveRuntime.LEAVING_SKILLS), {"BACK", "LEAVE_FOREIGN_LAYER"},
        )


class AFailedStepHandsOverTheCycleTests(unittest.TestCase):
    """Operator §二.5 / §二.7 (2026-09-21): one failed step is not the whole run.

    The sibling class above covers a *decision* the runtime refused.  This one covers
    the next wall along: the action ran, the verifier said the state did not arrive,
    and the run ended -- taking every other goal with it even though nothing about
    them had changed.

    The relaxation is scoped, and each edge is asserted rather than described:

    * the cycle is handed over through the existing ``_yield_to_next_goal``, so the
      *failing goal is held back* for the rest of the run and the next iteration
      selects a different task -- "try another candidate", not "retry the same step";
    * a run with nobody left to hand to keeps the original honest stop;
    * ``max_verification_retries`` bounds it, so this cannot become a spin;
    * fatal reasons still end the run, because ``is_fatal_stop`` decides and the
      relaxation is written under that guard rather than as a reason allow-list.

    The one stubbed thing is the brain, and the reason is that the subject here is the
    handover, not which skill the brain would have picked.  ``VERIFIED_ATOMIC`` is
    patched rather than added to, so the real table is never mutated.
    """

    #: ``BTN_ALLY_GIFT_CLAIM`` is one of the targets ``_FakeSemantic`` resolves, so the
    #: step really is executed and really does reach its verifier.  A target that did
    #: NOT resolve would answer SEMANTIC_TARGET_NOT_VERIFIED at the *resolution* stage
    #: -- the already-covered Rule A path -- and would leave the branch under test
    #: unexercised.  (Learned by writing it the wrong way first.)
    FAILING = "ALLIANCE_ALLY_GIFT_CLAIM"
    CONTROL = "BTN_ALLY_GIFT_CLAIM"
    #: A second, *different* control on the same page, so the scenario can show the
    #: handover reaching new work rather than tapping the same place again.
    OTHER = "LEAVE_FOREIGN_LAYER"
    OTHER_CONTROL = "BTN_CLOSE"

    def _second_goal(self) -> GoalState:
        return GoalState(
            goal_id="KEEP_TRAINING_PRODUCTIVE",
            status=GoalStatus.READY,
            available_skills=(self.FAILING, self.OTHER),
        )

    def _run(self, *, goals, max_actions=4, decisions=None):
        device = _FakeDevice()
        verifier = lambda _before, _after: VerificationResult(False, "FORCED_VERIFIER_FAILURE")  # noqa: E731
        sequence = decisions or [Decision(self.FAILING, "forced", 1.0, "opens gifts")] * 6

        def stub(runtime, _goals, _deferrals):
            return [goal for goal in goals if goal.goal_id not in runtime._yielded_goals]

        with TemporaryDirectory() as temp:
            temp_path = Path(temp)
            ledger_path = temp_path / "control_experience.json"
            episodes_path = temp_path / "episodes.jsonl"
            # Two things this fixture has to declare, because it fakes a production run
            # inside a temporary directory and the ledger now distinguishes the two:
            #
            #   STATE_PATH            -- do not write the real ledger
            #   measured_on_a_real_frame
            #                         -- the frames here land under the system temp dir,
            #                            which is exactly the marker of a scratch frame.
            #                            The production run this stands in for captures
            #                            under dataset/raw/, so the fixture says so
            #                            rather than the guard being loosened for tests.
            with patch.object(control_experience, "STATE_PATH", ledger_path), \
                 patch.object(control_experience, "measured_on_a_real_frame",
                              return_value=True), \
                 patch.object(LiveRuntime, "_selectable", stub), \
                 patch.object(RuleBrain, "decide", side_effect=sequence), \
                 patch.dict(LiveRuntime.VERIFIED_ATOMIC,
                            {self.FAILING: verifier, self.OTHER: verifier}):
                run = LiveRuntime(
                    device=device,
                    vision=_FakeVision([has_something_to_claim()] * 8, sticky=True),
                    semantic_vision=_FakeSemantic(),
                    capture_dir=temp_path,
                    sleeper=lambda _seconds: None,
                    episode_store=EpisodeStore(episodes_path),
                ).run(max_actions=max_actions)
                # Read the ledger *inside* the isolation block, for the same reason the
                # write happened there: ``load`` applies the provenance rule too, so
                # reading after the patch is undone would drop the very rows this test is
                # about -- and report "the ledger was never written" for a run that wrote it.
                ledger = control_experience.load(ledger_path)
            rows = [
                json.loads(line) for line in episodes_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ] if episodes_path.exists() else []
            # (The temporary directory is still alive here; the context manager deletes it
            # on exit, which is why the contents are returned rather than the path.)
        return device, run, ledger, rows

    def _two_steps(self):
        return [
            Decision(self.FAILING, "forced", 1.0, "opens gifts"),
            Decision(self.OTHER, "forced", 1.0, "leaves the layer"),
        ] + [Decision(self.OTHER, "forced", 1.0, "leaves the layer")] * 4

    def test_a_failed_step_hands_the_cycle_to_the_next_goal(self):
        device, run, _ledger, rows = self._run(
            goals=[ONLY_GOAL, self._second_goal()], decisions=self._two_steps())
        self.assertEqual(len(device.taps), 2,
                         "the second goal must get its own cycle after the first one's step failed")
        self.assertEqual(run.stop_reason, "FORCED_VERIFIER_FAILURE",
                         "...and the run still ends with the real reason, not silence")
        self.assertEqual([row["control"] for row in rows],
                         [self.CONTROL, self.OTHER_CONTROL],
                         "and the work it reached was a *different* control, not the same one again")

    def test_the_same_control_is_never_tapped_twice_in_one_run(self):
        """Operator §七.3, and the first version of this relaxation broke it.

        The handover holds the failing goal back, but the next goal's route can land
        on the very same control -- and with the guard removed the identical failing
        tap was issued once per goal.  A repeat at the same position is what the rule
        forbids, so the second attempt at the same control ends the run instead.
        """
        device, run, _ledger, rows = self._run(goals=[ONLY_GOAL, self._second_goal()])
        self.assertEqual(len(device.taps), 1, "one tap, then the same control is left alone")
        self.assertEqual(len(rows), 1)
        self.assertEqual(run.stop_reason, "FORCED_VERIFIER_FAILURE")

    def test_the_handover_is_bounded_and_does_not_spin(self):
        _device, run, _ledger, _rows = self._run(goals=[ONLY_GOAL])
        self.assertEqual(run.stop_reason, "FORCED_VERIFIER_FAILURE")
        self.assertLessEqual(len(run.steps), 3, "two retries, three failures at the most")

    def test_a_run_out_of_budget_keeps_the_original_honest_stop(self):
        """Same guard as the other handovers: yielding costs an iteration."""
        _device, run, _ledger, _rows = self._run(
            goals=[ONLY_GOAL, self._second_goal()], max_actions=1)
        self.assertEqual(len(run.steps), 1)
        self.assertEqual(run.stop_reason, "FORCED_VERIFIER_FAILURE")

    def test_a_fatal_reason_is_still_an_ending(self):
        """The line the relaxation is written under, asserted where it is used."""
        self.assertFalse(is_fatal_stop("FORCED_VERIFIER_FAILURE"))
        for fatal in ("FATAL_ADB_LOST", "ACCOUNT_SUSPENDED", "PAYMENT_REQUIRED"):
            self.assertTrue(is_fatal_stop(fatal))

    def test_the_episode_now_carries_what_was_expected_and_what_changed(self):
        """Operator §六/§十二: the causal half of the row reaches the stream."""
        _device, _run_, _ledger, rows = self._run(
            goals=[ONLY_GOAL, self._second_goal()], decisions=self._two_steps())
        self.assertTrue(rows, "the scenario must actually record an episode")
        row = rows[0]
        self.assertEqual(row["expected_result"], "opens gifts",
                         "the decision's own expectation reaches the row")
        self.assertEqual(row["control"], self.CONTROL,
                         "and the semantic that was aimed at, for joining back to the ledger")
        self.assertIn(row["observed_change"], control_experience.CHANGE_KINDS)
        self.assertFalse(row["verifier_ok"])
        self.assertEqual(row["failure_type"], "FORCED_VERIFIER_FAILURE")
        self.assertEqual(row["decision_reason"], "forced",
                         "and *which branch* decided it, verbatim: measured 2026-09-23, eight "
                         "OPEN_HOME failures needed exactly this string to be answerable, and the "
                         "reason only ever lived in the worker's stdout")

    def test_the_control_ledger_records_the_attempt_and_keeps_the_failed_hypothesis(self):
        """§七: a guess that produced nothing stays on the record as a failed guess.

        The expectation is stored as a *hypothesis*, and a step that moved nothing
        leaves it in place -- which is what stops the same guess being made again
        with the same confidence.
        """
        _device, _run_, ledger, _rows = self._run(goals=[ONLY_GOAL, self._second_goal()])
        self.assertTrue(ledger, "the run must have written the ledger")
        entry = ledger[control_experience.control_key("ALLIANCE", self.CONTROL)]
        self.assertEqual(entry.attempts, 1, "one tap, recorded once")
        self.assertIn(entry.last_result, control_experience.CHANGE_KINDS)
        self.assertAlmostEqual(entry.position_norm[0], 0.84, places=3,
                               msg="the landing point is stored as a normalized position")
        self.assertAlmostEqual(entry.position_norm[1], 0.50, places=3)
        self.assertTrue(entry.read_from_frame,
                        "and it stays traceable to the frame it was read from")
        self.assertEqual(entry.hypotheses, ("opens gifts",),
                         "a hypothesis that produced nothing remains on the record")
        self.assertFalse(entry.resolved)


if __name__ == "__main__":
    unittest.main()
