"""The scheduler must be able to say "not this again", and prove why.

Measured 2026-09-18 08:20 local: 58 of the last 60 production episodes were
``AVOID_STAMINA_WASTE / SCAN_MAP_FOR_BEAST`` with ``verifier_ok=True`` and stamina
fixed at 457.  Every step passed its verifier, the escalation for that capability sat
in ``COOLDOWN`` with the repair budget spent, and the scheduler re-selected the same
goal every 30 seconds.  These tests pin the three answers that were missing:

* the *goal's* progress is measured separately from the action's verifier,
* a path that cannot advance steps aside, and steps aside for a measurable reason,
* stepping aside is not permanent -- it expires into a deliberate, rare probe.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.capability_gate import (
    BLOCKED,
    BLOCKED_PROBE_MINUTES,
    COOLDOWN,
    DEFERRED,
    DEVELOPMENT_PENDING,
    LIVE_VERIFIED,
    NO_PROGRESS_PROBE_MINUTES,
    SOURCE_NO_PROGRESS,
    SOURCE_QUEUE,
    CapabilityGate,
    capability_states,
    runs,
)
from winter_agent_v2.escalation_queue import EscalationPolicy, fold
from winter_agent_v2.goal_library import (
    GoalComposition,
    GoalLibrary,
    GoalState,
    GoalStatus,
    goal_compositions,
    progress_moved,
)
from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime

NOW = datetime(2026, 9, 18, 8, 30, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def goal(goal_id, distance=0.0, skills=("SKILL",)):
    return GoalState(goal_id, GoalStatus.READY, available_skills=tuple(skills), distance=distance)


def episode(stamp, goal_id, *, skill="SKILL", progress=None, run_id="run"):
    return {
        "recorded_at": stamp.isoformat(),
        "episode_id": run_id,
        "goal_id": goal_id,
        "skill": skill,
        "goal_progress": progress,
    }


class GoalProgressIsNotActionProgressTests(unittest.TestCase):
    """``verifier_ok`` answers "did the step work"; this answers "did the goal move"."""

    def test_an_action_that_changed_nothing_is_not_goal_progress(self):
        observed = {"AVOID_STAMINA_WASTE": 427.0}
        self.assertIs(
            progress_moved(observed, [goal("AVOID_STAMINA_WASTE", distance=427.0)], "AVOID_STAMINA_WASTE"),
            False,
        )

    def test_spending_stamina_is_goal_progress(self):
        observed = {"AVOID_STAMINA_WASTE": 427.0}
        self.assertIs(
            progress_moved(observed, [goal("AVOID_STAMINA_WASTE", distance=407.0)], "AVOID_STAMINA_WASTE"),
            True,
        )

    def test_a_step_whose_before_frame_could_not_see_the_goal_still_measures(self):
        """The case that made this signature necessary.

        Measured 2026-09-18: DISPATCH_MARCH's before-frame is the formation page, which
        has no march counter, and its after-frame is MAP with one more march out.  A
        strict before/after comparison called every dispatch "not measured".
        """
        observed = {"KEEP_MARCHES_PRODUCTIVE": 2.0}  # last real reading, on MAP
        after = [goal("KEEP_MARCHES_PRODUCTIVE", distance=1.0)]
        self.assertIs(progress_moved(observed, after, "KEEP_MARCHES_PRODUCTIVE"), True)

    def test_a_goal_that_was_not_observable_is_unmeasured_not_stalled(self):
        """A queue goal does not exist while its page is off screen."""
        self.assertIsNone(progress_moved({}, [goal("KEEP_TRAINING_PRODUCTIVE")], "KEEP_TRAINING_PRODUCTIVE"))
        self.assertIsNone(progress_moved({"X": 1.0}, [], "X"))

    def test_the_stamina_goal_meters_the_work_still_left(self):
        live = WorldState(page=Page.MAP, stamina={"current": 457}, confidence=0.99)
        states = {state.goal_id: state for state in GoalLibrary().discover(live)}
        self.assertEqual(states["AVOID_STAMINA_WASTE"].distance, 427.0)

        spent = WorldState(page=Page.MAP, stamina={"current": 437}, confidence=0.99)
        after = {state.goal_id: state for state in GoalLibrary().discover(spent)}
        self.assertEqual(after["AVOID_STAMINA_WASTE"].distance, 407.0)

    def test_the_gather_goal_meters_idle_marches(self):
        """GATHER as a goal with a meter: work left is the idle march slots."""
        idle = WorldState(page=Page.MAP, march_used=2, march_max=6, confidence=0.99)
        states = {state.goal_id: state for state in GoalLibrary().discover(idle)}
        self.assertIn("KEEP_MARCHES_PRODUCTIVE", states)
        self.assertEqual(states["KEEP_MARCHES_PRODUCTIVE"].distance, 4.0)
        self.assertIs(states["KEEP_MARCHES_PRODUCTIVE"].status, GoalStatus.READY)

        busy = WorldState(page=Page.MAP, march_used=6, march_max=6, confidence=0.99)
        after = {state.goal_id: state for state in GoalLibrary().discover(busy)}
        self.assertEqual(after["KEEP_MARCHES_PRODUCTIVE"].distance, 0.0)
        self.assertIs(after["KEEP_MARCHES_PRODUCTIVE"].status, GoalStatus.COMPLETE)
        self.assertIs(
            progress_moved({"KEEP_MARCHES_PRODUCTIVE": 4.0},
                           list(after.values()), "KEEP_MARCHES_PRODUCTIVE"),
            True,
            "sending a march is progress, and now it is measurable",
        )

    def test_an_unread_march_counter_is_not_an_empty_one(self):
        """Unknown is not zero: a goal invented from a failed read would be a fiction."""
        unknown = WorldState(page=Page.MAP, confidence=0.99)
        ids = {state.goal_id for state in GoalLibrary().discover(unknown)}
        self.assertNotIn("KEEP_MARCHES_PRODUCTIVE", ids)


def ledger(*events):
    return fold(list(events))


class CapabilityStateTests(unittest.TestCase):
    """The queue's own verdict, folded -- never a second copy of it."""

    def _states(self, events, now=NOW):
        return capability_states(ledger(*events), now=now, policy=EscalationPolicy())

    def test_a_working_job_means_the_capability_is_development_pending(self):
        states = self._states([
            {"event": "escalation_created", "key": "CAP|F|SKILL", "capability": "CAP"},
            {"event": "submitted", "key": "CAP|F|SKILL", "job_id": "abc"},
            {"event": "job_state", "key": "CAP|F|SKILL", "state": "WORKING"},
        ])
        self.assertEqual(states["CAP"][0], DEVELOPMENT_PENDING)

    def test_a_fresh_cooldown_defers_until_its_own_deadline(self):
        states = self._states([
            {"event": "escalation_created", "key": "CAP|F|SKILL", "capability": "CAP"},
            {"event": "cooldown_started", "key": "CAP|F|SKILL",
             "until": (NOW + timedelta(minutes=20)).isoformat(), "reason": "spent"},
        ])
        self.assertEqual(states["CAP"][0], COOLDOWN)
        self.assertEqual(states["CAP"][2], NOW + timedelta(minutes=20))

    def test_a_spent_budget_becomes_blocked_once_the_cooldown_ends(self):
        """The operator's BUDGET_EXHAUSTED case: no job is coming, so stop re-entering."""
        events = [
            {"event": "escalation_created", "key": "CAP|F|SKILL", "capability": "CAP"},
            {"event": "cooldown_started", "key": "CAP|F|SKILL",
             "until": (NOW - timedelta(minutes=5)).isoformat(), "reason": "spent"},
            {"event": "reconciled", "key": "CAP|F|SKILL", "outcome": "TEST_PASS", "repair_used": True},
            {"event": "reconciled", "key": "CAP|F|SKILL", "outcome": "TEST_PASS", "repair_used": True},
        ]
        states = self._states(events)
        self.assertEqual(states["CAP"][0], BLOCKED)
        self.assertIn("repair budget exhausted", states["CAP"][1])

    def test_live_verified_is_what_releases_a_capability(self):
        """Learned is the only thing that puts a path back in the pool."""
        states = self._states([
            {"event": "escalation_created", "key": "CAP|F|SKILL", "capability": "CAP"},
            {"event": "submitted", "key": "CAP|F|SKILL", "job_id": "abc"},
            {"event": "job_state", "key": "CAP|F|SKILL", "state": "DONE"},
            {"event": "reconciled", "key": "CAP|F|SKILL", "outcome": LIVE_VERIFIED},
        ])
        self.assertEqual(states["CAP"][0], LIVE_VERIFIED)

    def test_a_test_pass_alone_does_not_release_it(self):
        """Job DONE and TEST_PASS are not "learned" (operator section 9)."""
        states = self._states([
            {"event": "escalation_created", "key": "CAP|F|SKILL", "capability": "CAP"},
            {"event": "submitted", "key": "CAP|F|SKILL", "job_id": "abc"},
            {"event": "job_state", "key": "CAP|F|SKILL", "state": "DONE"},
            {"event": "reconciled", "key": "CAP|F|SKILL", "outcome": "TEST_PASS"},
        ])
        self.assertNotEqual(states["CAP"][0], LIVE_VERIFIED)


class GateRuleTests(unittest.TestCase):
    def _gate(self, **kwargs):
        base = {
            "compositions": {
                "ANY": GoalComposition("ANY", "ANY_OF", ("A", "B", "C")),
                "SEQ": GoalComposition("SEQ", "SEQUENCE", ("A", "B")),
            },
            "capabilities": {},
            "streaks": {},
            "attempted": {},
            "reached": {},
        }
        base.update(kwargs)
        return CapabilityGate(**base)

    def test_a_sequence_goal_steps_aside_when_one_required_capability_is_unavailable(self):
        gate = self._gate(capabilities={"A": (BLOCKED, "spent", None)})
        self.assertIsNotNone(gate.blocks(goal("SEQ")))

    def test_an_any_of_goal_keeps_working_while_a_sibling_path_remains(self):
        """One dead beast route must not switch off the intel and rally routes."""
        gate = self._gate(capabilities={"A": (BLOCKED, "spent", None)})
        self.assertIsNone(gate.blocks(goal("ANY")))

    def test_an_any_of_goal_steps_aside_when_every_path_is_unavailable(self):
        gate = self._gate(capabilities={
            "A": (BLOCKED, "spent", None),
            "B": (DEVELOPMENT_PENDING, "job", None),
            "C": (COOLDOWN, "cooling", NOW + timedelta(minutes=10)),
        })
        found = gate.blocks(goal("ANY"), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.state, BLOCKED)

    def test_the_path_the_goal_is_actually_driven_along_is_what_defers_it(self):
        """Rules 1 beats rules 2: the route matters, not the node count."""
        gate = self._gate(
            capabilities={"A": (DEVELOPMENT_PENDING, "job abc", None)},
            reached={"ANY": frozenset({"A"})},
        )
        found = gate.blocks(goal("ANY"))
        self.assertIsNotNone(found)
        self.assertEqual(found.capability, "A")
        self.assertEqual(found.source, SOURCE_QUEUE)

    def test_development_pending_never_lapses(self):
        """A job is inside the code; probing would measure the tree it replaces."""
        gate = self._gate(
            capabilities={"A": (DEVELOPMENT_PENDING, "job abc", None)},
            reached={"ANY": frozenset({"A"})},
            streaks={"ANY": (9, NOW - timedelta(days=3), "SKILL")},
        )
        self.assertIsNotNone(gate.blocks(goal("ANY"), now=NOW))

    def test_a_blocked_path_is_probed_rarely_instead_of_never(self):
        """Neither a soft loop nor starvation."""
        gate = self._gate(
            capabilities={"A": (BLOCKED, "budget spent", None)},
            reached={"ANY": frozenset({"A"})},
            streaks={"ANY": (9, NOW - timedelta(minutes=5), "SKILL")},
        )
        self.assertIsNotNone(gate.blocks(goal("ANY"), now=NOW))
        lapsed = gate.blocks(goal("ANY"), now=NOW + timedelta(minutes=BLOCKED_PROBE_MINUTES + 1))
        self.assertIsNone(lapsed, "after the probe window the path must be reachable again")

    def test_no_progress_steps_aside_and_comes_back_on_a_probe_window(self):
        gate = self._gate(
            streaks={"ANY": (5, NOW - timedelta(minutes=2), "EAT")},
            attempted={"ANY": frozenset({"EAT"})},
        )
        found = gate.blocks(goal("ANY"), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.state, DEFERRED)
        self.assertEqual(found.source, SOURCE_NO_PROGRESS)
        self.assertEqual(found.streak, 5)
        self.assertIsNone(gate.blocks(goal("ANY"), now=NOW + timedelta(minutes=NO_PROGRESS_PROBE_MINUTES + 1)))

    def test_a_pending_reload_holds_every_deferral(self):
        """The runtime is about to be replaced by a version that may contain the fix."""
        gate = self._gate(
            streaks={"ANY": (5, NOW - timedelta(minutes=90), "EAT")},
            attempted={"ANY": frozenset({"EAT"})},
            reload_pending=True,
        )
        self.assertIsNotNone(gate.blocks(goal("ANY"), now=NOW))

    def test_an_empty_gate_defers_nothing(self):
        self.assertIsNone(CapabilityGate.empty().blocks(goal("ANY")))

    def test_a_no_progress_deferral_names_the_capability_the_goal_itself_declares(self):
        """The stalled route's steps need not be things the capability table names.

        Measured 2026-09-18: ``AVOID_STAMINA_WASTE`` stalled while running
        ``SCAN_MAP_FOR_BEAST`` alone, a navigation step that resolves to itself, so
        nothing in the goal's ``reached`` set intersected its composition and the
        deferral went out with an empty capability.  The goal's own declared skills
        still say which capabilities would satisfy it, and the project already maps
        ``BEAST_HUNT`` to ``SPEND_STAMINA_ON_BEAST``.
        """
        gate = CapabilityGate(
            compositions={
                "GOAL": GoalComposition(
                    "GOAL", "ANY_OF",
                    ("SPEND_STAMINA_ON_BEAST", "SPEND_STAMINA_ON_INTEL", "SPEND_STAMINA_ON_RALLY"),
                ),
            },
            streaks={"GOAL": (3, NOW - timedelta(minutes=1), "SCAN_MAP_FOR_BEAST")},
            attempted={"GOAL": frozenset({"SCAN_MAP_FOR_BEAST"})},
            reached={"GOAL": frozenset({"SCAN_MAP_FOR_BEAST"})},
        )
        found = gate.blocks(
            goal("GOAL", skills=("INTEL_CLAIM_REWARDS", "BEAST_HUNT")),
            now=NOW,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.capability, "SPEND_STAMINA_ON_BEAST")
        self.assertEqual(
            found.failure_signature,
            "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST",
        )

    def test_a_no_progress_signature_keeps_its_three_positional_fields(self):
        """An unresolvable capability leaves the field empty; it never collapses.

        Collapsing is what let the escalation queue read the failure type as the
        capability, so the shape has to be stable even when it says nothing.
        """
        gate = self._gate(
            streaks={"ANY": (3, NOW - timedelta(minutes=1), "SWIPE")},
            attempted={"ANY": frozenset({"SWIPE"})},
            reached={"ANY": frozenset({"SWIPE"})},
        )
        found = gate.blocks(goal("ANY", skills=("SWIPE",)), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.capability, "")
        self.assertEqual(found.failure_signature, "|NO_GOAL_PROGRESS|SWIPE")


class StreakCountingTests(unittest.TestCase):
    """A streak is counted in runs, and runs that never attempted the goal are skipped."""

    def test_consecutive_no_progress_runs_accumulate(self):
        rows = [
            episode(NOW - timedelta(minutes=30), "G", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=20), "G", progress=False, run_id="r2"),
            episode(NOW - timedelta(minutes=10), "G", progress=False, run_id="r3"),
        ]
        gate = CapabilityGate.load(ROOT, snapshot=fold([]), episodes=rows, no_progress_threshold=3)
        found = gate.blocks(goal("G"), now=NOW)
        self.assertIsNotNone(found)
        self.assertEqual(found.streak, 3)

    def test_a_run_that_advanced_the_goal_resets_the_streak(self):
        rows = [
            episode(NOW - timedelta(minutes=30), "G", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=20), "G", progress=False, run_id="r2"),
            episode(NOW - timedelta(minutes=10), "G", progress=True, run_id="r3"),
        ]
        gate = CapabilityGate.load(ROOT, snapshot=fold([]), episodes=rows, no_progress_threshold=3)
        self.assertIsNone(gate.blocks(goal("G"), now=NOW))

    def test_runs_that_never_attempted_the_goal_do_not_reset_it(self):
        """This is the difference between a deferral that holds and a soft loop.

        Measured 2026-09-18: after the beast goal stepped aside, the next run was all
        navigation steps with no beast episode in it.  Counting that as "the streak is
        over" would have sent the run straight back to the same wall.
        """
        rows = [
            episode(NOW - timedelta(minutes=40), "G", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=30), "G", progress=False, run_id="r2"),
            episode(NOW - timedelta(minutes=20), "G", progress=False, run_id="r3"),
            episode(NOW - timedelta(minutes=10), "OTHER", progress=False, run_id="r4"),
        ]
        gate = CapabilityGate.load(ROOT, snapshot=fold([]), episodes=rows, no_progress_threshold=3)
        found = gate.blocks(goal("G"), now=NOW)
        self.assertIsNotNone(found, "a run about another goal must not clear the streak")
        self.assertEqual(found.streak, 3)

    def test_an_unmeasured_run_does_not_count_as_stalled(self):
        rows = [
            episode(NOW - timedelta(minutes=30), "G", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=20), "G", progress=False, run_id="r2"),
            episode(NOW - timedelta(minutes=10), "G", progress=None, run_id="r3"),
        ]
        gate = CapabilityGate.load(ROOT, snapshot=fold([]), episodes=rows, no_progress_threshold=3)
        self.assertIsNone(gate.blocks(goal("G"), now=NOW))

    def test_many_steps_inside_one_run_count_once(self):
        """A six-step route that finishes its batch is not six failed attempts."""
        rows = [
            episode(NOW - timedelta(minutes=30), "G", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=29), "G", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=28), "G", progress=True, run_id="r1"),
        ]
        gate = CapabilityGate.load(ROOT, snapshot=fold([]), episodes=rows, no_progress_threshold=1)
        self.assertIsNone(gate.blocks(goal("G"), now=NOW))

    def test_a_settled_job_moves_the_boundary_the_streak_is_measured_from(self):
        """Code changed; a streak describing the old code says nothing about the new one."""
        rows = [
            episode(NOW - timedelta(minutes=30), "G", skill="CAP", progress=False, run_id="r1"),
            episode(NOW - timedelta(minutes=20), "G", skill="CAP", progress=False, run_id="r2"),
            episode(NOW - timedelta(minutes=10), "G", skill="CAP", progress=False, run_id="r3"),
        ]
        settled = NOW - timedelta(minutes=25)
        snapshot = fold([
            {"event": "escalation_created", "key": "CAP|F|CAP", "capability": "CAP"},
            {"event": "submitted", "key": "CAP|F|CAP", "job_id": "abc"},
            {"event": "job_state", "key": "CAP|F|CAP", "state": "DONE"},
            {"event": "reconciled", "key": "CAP|F|CAP", "outcome": "TEST_PASS",
             "recorded_at": settled.isoformat()},
        ])
        with_job = CapabilityGate.load(ROOT, snapshot=snapshot, episodes=rows, no_progress_threshold=3)
        # r1 and r2 ran before the tree changed, so only r3 describes the current code.
        self.assertIsNone(with_job.blocks(goal("G"), now=NOW))

        without = CapabilityGate.load(ROOT, snapshot=fold([]), episodes=rows, no_progress_threshold=3)
        self.assertIsNotNone(without.blocks(goal("G"), now=NOW))


class RunsGroupingTests(unittest.TestCase):
    def test_rows_sharing_an_episode_id_are_one_run(self):
        rows = [
            episode(NOW, "G", run_id="a"),
            episode(NOW, "G", run_id="a"),
            episode(NOW, "G", run_id="b"),
        ]
        self.assertEqual([len(group) for group in runs(rows)], [2, 1])

    def test_a_row_without_an_episode_id_is_its_own_run(self):
        rows = [episode(NOW, "G"), episode(NOW, "G")]
        rows[0]["episode_id"] = ""
        rows[1]["episode_id"] = ""
        self.assertEqual([len(group) for group in runs(rows)], [1, 1])


class ProjectTableTests(unittest.TestCase):
    """The gate reads the project's own Goal -> Capability table, not a new one."""

    def test_the_stamina_goal_names_three_alternative_paths(self):
        composition = goal_compositions(ROOT)["AVOID_STAMINA_WASTE"]
        self.assertEqual(composition.composition, "ANY_OF")
        self.assertIn("SPEND_STAMINA_ON_BEAST", composition.capabilities)


class FakeMatch:
    center_norm = (0.84, 0.50)


class FakeSemantic:
    def find(self, _path, semantic):
        return FakeMatch() if semantic in {"BTN_OPEN_HOME", "PAGE_MAP"} else None

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class FakeVision:
    def __init__(self, states):
        self.states = iter(states)

    def observe(self, _path):
        return next(self.states)


class StickyVision(FakeVision):
    """Keeps answering with the last state.

    A run decides when to re-observe (refresh loops, recovery waits), so a fake that
    runs dry mid-run turns the loop's own behaviour into a StopIteration instead of
    letting the test assert on it.
    """

    def __init__(self, states):
        super().__init__(states)
        self.last = None

    def observe(self, _path):
        try:
            self.last = next(self.states)
        except StopIteration:
            pass
        return self.last


class FakeDevice:
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


GATHER_ROUTE = frozenset({
    "OPEN_HOME", "OPEN_MAP", "SCAN_MAP_FOR_BEAST", "SEARCH_RESOURCE", "SELECT_RESOURCE",
    "SUBMIT_RESOURCE_SEARCH", "START_GATHER", "DISPATCH_MARCH",
})


class DeferredGoalSchedulingTests(unittest.TestCase):
    """The whole point: a deferred goal does not stop the run, and it is recorded."""

    def _gate(self, **kwargs):
        base = {
            "compositions": {"AVOID_STAMINA_WASTE": GoalComposition(
                "AVOID_STAMINA_WASTE", "ANY_OF", ("SPEND_STAMINA_ON_BEAST",))},
            "capabilities": {"SPEND_STAMINA_ON_BEAST": (BLOCKED, "repair budget exhausted", None)},
            "streaks": {"AVOID_STAMINA_WASTE": (58, NOW - timedelta(minutes=1), "SCAN_MAP_FOR_BEAST")},
            "attempted": {"AVOID_STAMINA_WASTE": frozenset({"SCAN_MAP_FOR_BEAST"})},
            "reached": {"AVOID_STAMINA_WASTE": frozenset({"SPEND_STAMINA_ON_BEAST"})},
        }
        base.update(kwargs)
        return CapabilityGate(**base)

    def _run(self, states, gate, **kwargs):
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "episodes.jsonl"
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(path),
                capability_gate=gate,
                **kwargs,
            ).run(max_actions=1, allowed_skills=GATHER_ROUTE)
            # A run that records no episode is a valid outcome (it may stop before
            # acting), so an absent file means "no episodes", not a broken test.
            rows = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ] if path.exists() else []
        return device, run, rows

    def test_a_deferred_goal_is_reported_by_the_run(self):
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
        ]
        device, run, _rows = self._run(states, self._gate())
        self.assertEqual(len(run.deferrals), 1)
        self.assertEqual(run.deferrals[0]["goal_id"], "AVOID_STAMINA_WASTE")
        self.assertEqual(run.deferrals[0]["state"], BLOCKED)

    def test_a_deferred_goal_is_replaced_by_a_hop_to_where_goals_are_observable(self):
        """Standing on the map doing nothing is not a plan.

        The frame carries no march reading on purpose: with one, the gather goal would
        be selectable and the run should stay and work, which the next test pins.
        """
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
        ]
        device, run, _rows = self._run(states, self._gate())
        self.assertEqual(run.steps[0].decision.skill, "OPEN_HOME")
        self.assertTrue(run.steps[0].decision.reason.startswith("deferred_"))
        self.assertEqual(len(device.taps), 1)

    def test_a_deferred_goal_does_not_displace_work_that_is_still_selectable(self):
        """Measured 2026-09-18 08:55: the missing guard cost a round trip.

        The run's first step hopped HOME even though the gather goal was selectable on
        that frame, and the run paid two steps to come back to the map it had left.
        """
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=2, march_max=6, confidence=0.99),
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=2, march_max=6, confidence=0.99),
        ]
        _device, run, _rows = self._run(states, self._gate())
        self.assertEqual(len(run.deferrals), 1, "the beast goal is still reported as deferred")
        self.assertNotEqual(
            run.steps[0].decision.skill, "OPEN_HOME",
            "a deferred goal must not switch off a goal that is still selectable",
        )

    def test_the_run_still_plays_when_the_blocked_goal_is_all_there_is(self):
        """Failure isolation: one blocked capability must not end unattended operation."""
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=2, march_max=6, confidence=0.99),
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=2, march_max=6, confidence=0.99),
        ]
        _device, run, _rows = self._run(states, self._gate())
        self.assertNotEqual(run.steps[0].decision.skill, "SCAN_MAP_FOR_BEAST")
        self.assertNotIn(run.stop_reason, {"verified_beast_target_not_visible", "SAFE_STOP"})
        self.assertIsNotNone(run.steps[0].execution, "a real action was issued instead of the blocked path")
        self.assertEqual(run.steps[0].decision.skill, "SEARCH_RESOURCE")

    def test_an_allowed_goal_is_untouched_by_the_gate(self):
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
        ]
        device, run, _rows = self._run(states, CapabilityGate.empty())
        self.assertEqual(run.deferrals, ())
        self.assertEqual(run.steps[0].decision.skill, "SCAN_MAP_FOR_BEAST")

    def test_a_deferral_is_narrated_once_per_reason_not_once_per_step(self):
        """A twelve-step run printed the identical line twelve times (2026-09-18)."""
        import contextlib
        import io

        device = FakeDevice()
        # No march reading, so the deferral leaves nothing selectable here and the run
        # takes its hop -- which is what gives this test more than one step.
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                run = LiveRuntime(
                    device=device,
                    vision=StickyVision(states),
                    semantic_vision=FakeSemantic(),
                    capture_dir=Path(temp) / "captures",
                    sleeper=lambda _seconds: None,
                    capability_gate=DeferredGoalSchedulingTests()._gate(),
                ).run(max_actions=3, allowed_skills={"OPEN_HOME", "OPEN_MAP", "SCAN_MAP_FOR_BEAST"})
        self.assertGreaterEqual(len(run.steps), 2, "the run has to take more than one step")
        self.assertEqual(capture.getvalue().count("[schedule] deferred"), 1)


class EpisodeMeasurementTests(unittest.TestCase):
    """The measurement has to reach the artifact, or nothing downstream can use it."""

    def test_the_snapshot_keeps_the_deferrals_it_is_given(self):
        """The store filters unknown keys, so the field has to be declared.

        Measured 2026-09-18: the runtime's write of ``deferred_goals`` was silently
        dropped -- no error, no field -- which would have made the one place an
        operator asks "why is AUTO not doing that" answer nothing.
        """
        from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore

        with TemporaryDirectory() as temp:
            store = RuntimeSnapshotStore(Path(temp) / "snapshot.json")
            store.update(deferred_goals=[{"goal_id": "G", "state": "BLOCKED", "reason": "spent"}])
            written = json.loads((Path(temp) / "snapshot.json").read_text(encoding="utf-8"))
            reread = store.read()
        self.assertEqual(written["deferred_goals"][0]["goal_id"], "G")
        self.assertEqual(reread.deferred_goals[0]["state"], "BLOCKED")

    def test_a_deferred_run_writes_the_reason_to_the_snapshot(self):
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            snapshot_path = Path(temp) / "snapshot.json"
            from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore

            device = FakeDevice()
            LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                runtime_store=RuntimeSnapshotStore(snapshot_path),
                capability_gate=DeferredGoalSchedulingTests()._gate(),
            ).run(max_actions=1, allowed_skills={"OPEN_HOME"})
            written = json.loads(snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(written["deferred_goals"][0]["goal_id"], "AVOID_STAMINA_WASTE")
        self.assertTrue(written["deferred_goals"][0]["reason"])

    def test_a_verifier_pass_without_goal_progress_is_recorded_as_such(self):
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
        ]
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "episodes.jsonl"
            LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(path),
                capability_gate=CapabilityGate.empty(),
            ).run(max_actions=1, allowed_skills={"SCAN_MAP_FOR_BEAST"})
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        self.assertIs(row["verifier_ok"], True, "the action itself landed")
        self.assertIs(row["goal_progress"], False, "...and the goal did not move")
        self.assertEqual(row["goal_id"], "AVOID_STAMINA_WASTE")

    def test_a_goal_that_moved_is_recorded_as_progress(self):
        states = [
            WorldState(page=Page.MAP, stamina={"current": 457}, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.MAP, stamina={"current": 437}, march_used=1, march_max=6, confidence=0.99),
        ]
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            path = Path(temp) / "episodes.jsonl"
            LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(path),
                capability_gate=CapabilityGate.empty(),
            ).run(max_actions=1, allowed_skills={"SCAN_MAP_FOR_BEAST"})
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        self.assertIs(row["goal_progress"], True)


if __name__ == "__main__":
    unittest.main()
