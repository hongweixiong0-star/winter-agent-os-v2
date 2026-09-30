"""LOOP_DETECTOR_V1's boundary: what it may not become, and what it may not stop.

Two clauses of the operator's directive are about *limits*, and limits are the ones that
erode quietly, so both are asserted here rather than trusted:

1. 「不得新增：第二 Scheduler / 第二 Executor / 第二 WorldState / 第二本地模型」
   The detector's whole licence is that it is a small pure function over signatures it is
   handed.  That is checked four ways: the source's imports (standard library only), the
   *loaded* module's own attributes (no project module object can have been smuggled in
   under a conditional), the definitions it contains (no Scheduler / Executor / WorldState /
   Registry / Model / Queue), and the module-level names it binds (a module-level list is
   what a second pipeline looks like on its first day).

2. 「Loop Detector 只能阻止当前局部流程，不得停止整个 AUTO」
   The mechanism is a single named ending: the session ends with ``SESSION_DOMAIN_STUCK``,
   the stop-reason classifier declares that token recoverable, and the runtime answers a
   non-completed session by handing the Goal back to the Global Scheduler.  All three links
   are asserted -- the last one driven through a real ``LiveRuntime`` with a real looping
   adapter, because "the panel would not stop AUTO" is a claim about the runtime and not
   about a table.

The live harness is the one ``tests/test_session_engine_boundary.py`` established (the same
``_FakeVision`` / ``_FakeSemantic`` / ``_FakeDevice`` trio, the same two stubs, the same
``TemporaryDirectory``), deliberately: a second harness would let the two files disagree
about what "a run" is.
"""

from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import loop_detector, session_adapters  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.goal_library import GoalState, GoalStatus  # noqa: E402
from winter_agent_v2.loop_detector import (  # noqa: E402
    RECOVERY_LADDER,
    RUNG_DEFER_GOAL,
    RUNG_HOME_RECOVERY,
)
from winter_agent_v2.models import Decision, Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.runtime_snapshot import (  # noqa: E402
    StopCategory,
    classify_stop_reason,
    is_fatal_stop,
)
from winter_agent_v2.session_adapters import (  # noqa: E402
    BearSessionAdapter,
    FishingSessionAdapter,
    SessionRoute,
    StaminaSpendSessionAdapter,
    TrainingBatchSessionAdapter,
)
from winter_agent_v2.session_engine import (  # noqa: E402
    SESSION_DOMAIN_STUCK,
    STEP_OBSERVE_ONLY,
    SessionAdapter,
    SessionEngine,
    SessionStep,
    StepOutcome,
    StepVerdict,
)
from winter_agent_v2.session_host import LiveRuntimeSessionHost  # noqa: E402

ADAPTER_MODULES = ("session_adapters", "fishing_session", "rally")
BANNED_IMPORTS = ("subprocess", "socket", "http", "urllib", "requests", "ctypes",
                  "torch", "numpy", "cv2", "onnxruntime", "openai", "adb")


def source_of(module: str) -> str:
    return (ROOT / "winter_agent_v2" / f"{module}.py").read_text(encoding="utf-8")


def imported_roots(text: str) -> set[str]:
    """Every top-level module name an ``import``/``from`` statement names."""
    roots: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            for part in stripped[len("import "):].split(","):
                roots.add(part.strip().split(" as ")[0].split(".")[0])
        elif stripped.startswith("from "):
            roots.add(stripped[len("from "):].split(" import ")[0].strip().split(".")[0])
    roots.discard("")
    return roots


# ==========================================================================================
# 1. There is no second Scheduler / Executor / WorldState / model
# ==========================================================================================

class TheDetectorIsNotASecondAnythingTests(unittest.TestCase):
    def test_everything_it_imports_is_in_the_standard_library(self):
        """The strongest available guarantee, and the cheapest to keep.

        A detector that cannot import a runtime cannot *reach* one, so the boundary is
        enforced by the import graph instead of by review.  ``sys.stdlib_module_names`` is
        the interpreter's own list rather than a hand-kept one -- a hand-kept list is how a
        check silently starts passing after an upgrade.
        """
        roots = imported_roots(source_of("loop_detector"))
        self.assertTrue(roots, "the parse must actually find imports")
        foreign = sorted(r for r in roots if r not in sys.stdlib_module_names)
        self.assertEqual(foreign, [], f"non-stdlib imports: {foreign}")

    def test_it_never_names_a_project_module(self):
        for root in sorted(imported_roots(source_of("loop_detector"))):
            with self.subTest(root=root):
                self.assertNotIn("winter_agent_v2", root)

    def test_it_cannot_open_a_device_or_reach_a_model(self):
        """Neither of the two things「第二设备宿主」and「第二本地模型」would need."""
        text = source_of("loop_detector")
        roots = imported_roots(text)
        for banned in BANNED_IMPORTS:
            with self.subTest(banned=banned):
                self.assertNotIn(banned, roots)

    def test_the_loaded_module_holds_no_project_module_object(self):
        """Asserted on the live module, not only on the text.

        An import placed behind an ``if`` or inside a function would still bind a name, and
        the source scan above would still read as clean.
        """
        bound = {name: value for name, value in vars(loop_detector).items()
                 if isinstance(value, types.ModuleType)}
        self.assertTrue(bound, "the parse must actually find module objects")
        for name, value in bound.items():
            with self.subTest(name=name):
                self.assertIn(value.__name__, sys.stdlib_module_names)

    def test_it_defines_no_scheduler_executor_world_state_registry_or_model(self):
        """The directive's forbidden list, as a definition scan.

        ``WorldState`` is included even though the detector obviously needs to read a state:
        the point is that it must *borrow* one (``relevant_state_hash`` takes whatever it is
        handed), never define a second one to keep its own view in.
        """
        forbidden = re.compile(
            r"^\s*(?:class|def)\s+"
            r"(Scheduler|Executor|Registry|SkillRegistry|GoalLibrary|GoalEngine|Brain|"
            r"WorldState|StateStore|Manager|Orchestrator|Queue|TaskQueue|Model|Planner)\b",
            re.MULTILINE,
        )
        found = forbidden.findall(source_of("loop_detector"))
        self.assertEqual(found, [], f"loop_detector defines {found}")

    def test_it_keeps_no_module_level_mutable_state(self):
        """A module-level list or dict is a second pipeline on its first day.

        Every counter in this detector is per-instance (``LoopDetector.counts``), which is
        what makes "one detector per session" true rather than aspirational.  Module-level
        declarative constants -- the ladder, the metric names, the projection -- are fine and
        are the only things the scan should find.
        """
        assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=\n]+)?=\s*(.+)$",
                                re.MULTILINE)
        mutable = re.compile(r"^(\[|\{|set\(|list\(|dict\(|deque\(|bytearray\()")
        offenders = [name for name, rhs in assignment.findall(source_of("loop_detector"))
                     if not name.startswith("__") and mutable.match(rhs.strip())]
        self.assertEqual(offenders, [], f"module-level mutable state: {offenders}")


class TheEngineIsTheOnlyThingThatWatchesForLoopsTests(unittest.TestCase):
    """「把 Loop Detector 作为 Generic Session Engine 的公共能力，四个 Adapter 全部复用」."""

    def test_the_engine_observes_a_loop_in_exactly_one_place(self):
        """One call site, counted in the source.

        The property is structural: a second site would be a second notion of "this is a
        loop", and the two would answer differently after the first edit.
        """
        self.assertEqual(source_of("session_engine").count("state.loop.observe("), 1)

    def test_no_adapter_grows_its_own_detector_or_threshold(self):
        """Four adapters, four chances to pick a different repeat count.

        The engine owns the detector exactly once so fishing, bear, stamina and training
        batch cannot drift apart -- and so a fifth adapter inherits it for free.
        """
        for module in ADAPTER_MODULES:
            path = ROOT / "winter_agent_v2" / f"{module}.py"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(module=module):
                self.assertNotIn("LoopDetector", text)
                self.assertNotIn("LoopSignature", text)
                self.assertNotIn("RECOVERY_LADDER", text)

    def test_the_four_business_adapters_all_go_through_that_one_engine(self):
        for adapter in (FishingSessionAdapter, BearSessionAdapter,
                        StaminaSpendSessionAdapter, TrainingBatchSessionAdapter):
            with self.subTest(adapter=adapter.__name__):
                self.assertTrue(issubclass(adapter, SessionAdapter),
                                "a session adapter is what the engine runs")

    def test_every_adapter_reaches_the_detector_by_subclassing_rather_than_by_calling(self):
        """The reuse claim, expressed as a fact about the type hierarchy.

        ``SessionEngine.run`` feeds the detector from inside ``_run_one_step``, which every
        adapter's steps go through.  So an adapter gets loop detection by *being* an adapter,
        and there is no opt-in flag for a future adapter to forget.
        """
        text = source_of("session_engine")
        self.assertIn("state.loop.observe(self._signature_for(", text)
        self.assertNotIn("def loop_detector_enabled", text)
        self.assertNotIn("enable_loop_detection", text)

    def test_the_engine_has_no_way_to_end_the_run(self):
        """「不得停止整个 AUTO」asserted as an absence.

        The engine's worst outcome is a ``SessionResult``; there is no call in it that could
        end a process or a run, so a loop can only ever end the thing it is inside.
        """
        text = source_of("session_engine")
        for banned in ("sys.exit", "raise SystemExit", "os._exit", "signal.raise_signal",
                       "AgentState.DEGRADED", "FATAL_STOPPED"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, text)

    def test_a_loop_ending_is_classified_recoverable_and_not_fatal(self):
        """The single link between "a session stopped" and "AUTO keeps going".

        ``SESSION_DOMAIN_STUCK`` reaches the classifier carrying detail after a colon
        (``SESSION_DOMAIN_STUCK:AAA: the same signature 3x running (ab12cd34ef)``), which is
        why the classifier matches a declared token with a colon-aware test.  Both halves are
        asserted: the real emitted shape is recoverable, and the colon test did not become a
        substring test -- a wider "do not stop" table is how a classifier starts excusing
        real faults.
        """
        emitted = f"{SESSION_DOMAIN_STUCK}:AAA: the same signature 3x running (ab12cd34ef)"
        self.assertIs(classify_stop_reason(emitted), StopCategory.CAPABILITY_GAP)
        self.assertFalse(is_fatal_stop(emitted))
        self.assertIs(classify_stop_reason(SESSION_DOMAIN_STUCK), StopCategory.CAPABILITY_GAP)
        # ... and the colon rule must not swallow an undeclared prefix.
        self.assertIs(classify_stop_reason("SEMANTIC_NOT_FOUND_BECAUSE_X"),
                      StopCategory.SYSTEM_FAILURE)


# ==========================================================================================
# 2. A loop ends the session, and the run continues
# ==========================================================================================

LOOPING_GOAL = GoalState(
    goal_id="KEEP_TRAINING_PRODUCTIVE",
    status=GoalStatus.READY,
    available_skills=("TRAIN_TROOPS",),
    reward_value=1.0,
)


class _FakeDevice:
    def __init__(self):
        self.taps = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return SimpleNamespace(connected=True, resolution=(720, 1280))

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        pass

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


class _FakeVision:
    def __init__(self, state):
        self.state = state

    def observe(self, _path):
        return self.state


class _FakeSemantic:
    center_norm = (0.84, 0.50)
    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def find(self, _path, semantic):
        return None

    def resource_cell_center_norm(self, _resource):
        return None

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _LoopingAdapter(SessionAdapter):
    """A domain that keeps issuing the same move and keeps being told it did not work.

    ``OBSERVE_ONLY`` rather than a registered skill on purpose: the subject is the *engine's*
    reaction to a repeating answer, and a real skill would drag in the semantic resolver, the
    backend router and a device frame that this property is not about.  The step still costs
    one unit of the session's budget and still produces one verifier answer, which is the
    whole of what a loop detector is fed.

    ``recover`` answers ``True`` -- "the domain is ready again, try the same move" -- and that
    is what makes this a *loop* rather than a single failure.  Measured while writing this
    file: without it, the engine's own bounded recovery (`max_recoveries`) takes the step once,
    the adapter declines to say "ready", and the session ends after one attempt under
    ``SESSION_STEP_NOT_VERIFIED``.  A flow that re-issues the same move is one whose recovery
    keeps promising the next attempt will work, which is exactly the shape the detector exists
    to shorten.

    ``progress=False`` on every verdict is the honest declaration: this domain moved nothing.
    It is exactly the case the step's own outcome cannot express, which is why
    ``StepVerdict`` carries the Goal-level fact separately.
    """

    name = "looping"

    def __init__(self):
        self.issued = 0
        self.recovered = 0

    def observe(self, context, host):
        return {"blob": True}

    def is_complete(self, context, host, domain):
        return False, ""

    def choose_step(self, context, host, domain):
        return SessionStep(0, STEP_OBSERVE_ONLY, reason="the same move again")

    def verify_step(self, context, host, step, execution):
        self.issued += 1
        return StepVerdict(StepOutcome.FAILED, "SAME_ACTION_NO_PROGRESS", progress=False)

    def recover(self, context, host, step, verdict):
        self.recovered += 1
        return True


def _map_frame():
    return WorldState(page=Page.MAP, confidence=0.99, normal_idle_slots=2)


def _selectable_stub(goals, on_call=None):
    def stub(runtime, _goals, _deferrals):
        if on_call is not None:
            on_call()
        return [g for g in goals if g.goal_id not in runtime._yielded_goals]

    return stub


def _route(adapter: str) -> SessionRoute:
    """The looping route, with a step budget the ladder cannot reach the hard way.

    ``step_budget=12`` rather than the default 8 on purpose: the ladder spends a rung per
    repeat and saturates at ``defer_goal`` after six, so with a budget of 8 the session would
    end on the *ceiling* and the test could not tell a working detector from an exhausted
    budget.  With 12 the two outcomes are different numbers and the assertion has teeth.
    """
    return SessionRoute(goal_id=LOOPING_GOAL.goal_id, adapter=adapter, step_budget=12,
                        skills=frozenset({"TRAIN_TROOPS"}))


class ALoopEndsTheSessionAndNotTheRunTests(unittest.TestCase):
    """The directive's 必须证明, on the live run loop: LOOP_RECOVERED / AUTO_CONTINUED."""

    MAX_ACTIONS = 5

    def _run(self, *, goals, routes, adapters, max_actions=None):
        max_actions = max_actions or self.MAX_ACTIONS
        device = _FakeDevice()
        results = []
        audits = []
        arbitrations = []
        original_run = SessionEngine.run
        # Captured *before* the patch is installed: reading it inside the wrapper would read
        # the wrapper, and the run would die of recursion instead of the loop.
        original_init = LiveRuntimeSessionHost.__init__

        def spy(engine_self, context, adapter, host):
            result = original_run(engine_self, context, adapter, host)
            results.append(result)
            return result

        def capture_init(host_self, runtime, binding):
            original_init(host_self, runtime, binding)
            audits.append(binding.page_audit)

        def note_arbitration():
            # How many sessions had already finished when the Scheduler was asked again.
            # This is the run's own loop turning, which is what "AUTO continued" means at
            # this level: the count is taken *inside* the selector the run calls each turn.
            arbitrations.append(len(results))

        decision = Decision("TRAIN_TROOPS", "forced", 1.0, "works a barracks")
        patches = [
            patch.object(LiveRuntime, "_selectable",
                         _selectable_stub(goals, on_call=note_arbitration)),
            patch.object(RuleBrain, "decide", new=lambda *a, **k: decision),
            patch.object(session_adapters, "SESSION_ROUTES", tuple(routes)),
            patch.dict(session_adapters.SESSION_ADAPTERS, adapters),
            patch.object(SessionEngine, "run", spy),
            patch.object(LiveRuntimeSessionHost, "__init__", capture_init),
        ]
        for extra in patches:
            extra.start()
        try:
            with TemporaryDirectory() as temp:
                runtime = LiveRuntime(
                    device=device,
                    vision=_FakeVision(_map_frame()),
                    semantic_vision=_FakeSemantic(),
                    capture_dir=Path(temp),
                    sleeper=lambda _seconds: None,
                )
                run = runtime.run(max_actions=max_actions)
                yielded = set(runtime._yielded_goals)
        finally:
            for extra in patches:
                extra.stop()
        return run, results, audits, yielded, arbitrations

    def _looping_run(self, goals=None, max_actions=None):
        run, results, audits, yielded, arbitrations = self._run(
            goals=goals or [LOOPING_GOAL], routes=[_route("looping")],
            adapters={"looping": _LoopingAdapter}, max_actions=max_actions)
        self.assertTrue(results, "the run must actually have reached the session")
        self.assertEqual(len(results), 1, "one delegated Goal, one session")
        return run, results[0], audits, yielded, arbitrations

    def test_a_looping_session_ends_with_a_name_the_classifier_declares_recoverable(self):
        _run_, session, _audits, _yielded, _arb = self._looping_run()

        self.assertTrue(session.failed, f"expected a failed session, got {session.reason}")
        self.assertTrue(session.reason.startswith(SESSION_DOMAIN_STUCK),
                        f"the loop must end under its own name, got {session.reason}")
        self.assertIs(classify_stop_reason(session.reason), StopCategory.CAPABILITY_GAP)
        self.assertFalse(is_fatal_stop(session.reason))

        # The loop really was a loop, and the ladder really was driven: the evidence is in
        # the session's own metrics rather than in the fact that it ended.
        metrics = session.metrics
        self.assertGreaterEqual(metrics["LOOP_DETECTED"], 3,
                                f"expected repeats, got {metrics.get('LOOP_PATTERNS')}")
        self.assertIn("AAA", metrics["LOOP_PATTERNS"])
        self.assertGreaterEqual(metrics["SESSION_LOOP_RECOVERIES"], 1,
                                "a loop that ended without spending a rung is not a recovery")
        self.assertGreaterEqual(metrics["SESSION_STEPS"], 3)
        self.assertGreaterEqual(metrics["SESSION_LOOP_RECOVERIES"], 5,
                                "the ladder must keep escalating while the same move repeats")

        # The ladder, not the ceiling, is why it stopped.  Otherwise "recovered" would be
        # indistinguishable from "ran out of budget", which is the cheaper failure to have.
        self.assertLess(metrics["SESSION_STEPS"], metrics["SESSION_STEP_BUDGET"],
                        "the loop ended the session before its step budget did")
        self.assertIn(SESSION_DOMAIN_STUCK, str(metrics["SESSION_FAILURE"]))
        # ... and it is bounded by the design, not by luck: the first detection needs three
        # identical answers, the ladder then has six rungs and saturates rather than inventing
        # a seventh, so a loop can never outlive 3 + 6 attempts -- whatever the budget says.
        self.assertLessEqual(metrics["SESSION_STEPS"], 3 + len(RECOVERY_LADDER))
        self.assertIn(metrics["LOOP_LADDER_TOP"], RECOVERY_LADDER)

    def test_a_rung_the_host_cannot_perform_ends_the_session_rather_than_repeating_the_step(self):
        """The failure mode the ladder must not have: a remedy that silently does nothing.

        Measured, not constructed: in this harness the host cannot execute ``OPEN_HOME`` (the
        fake registry has no such skill), so the ladder stops at the HOME rung and the session
        ends with ``..._UNAVAILABLE``.  The alternative -- treating an unperformed rung as
        "carry on" -- reproduces exactly the behaviour the detector exists to stop, and the
        ending is asserted by name so a future "just keep going" change fails here loudly.
        """
        _run_, session, _audits, _yielded, _arb = self._looping_run()
        self.assertTrue(
            session.reason.startswith(SESSION_DOMAIN_STUCK + ":") and
            (session.reason.endswith("_UNAVAILABLE") or "defer_goal" in session.reason),
            f"a spent ladder ends under one of two names, got {session.reason}")
        ladder_endings = (f"{SESSION_DOMAIN_STUCK}:{RUNG_HOME_RECOVERY}_UNAVAILABLE",
                          f"{SESSION_DOMAIN_STUCK}:{RUNG_DEFER_GOAL}")
        if session.reason.endswith("_UNAVAILABLE"):
            self.assertIn(session.reason, ladder_endings)
            self.assertNotIn("SESSION_STEP_NOT_VERIFIED", session.reason,
                             "an unavailable rung must not fall back to the ordinary path")

    def test_the_session_timeline_is_carried_out_with_every_observation(self):
        """MAI design 4: "where did the run spend itself" readable from the run's own output."""
        _run_, session, audits, _yielded, _arb = self._looping_run()
        timeline = session.metrics["LOOP_TIMELINE"]
        self.assertTrue(timeline, "a session that looped must leave a timeline")
        self.assertEqual([row["kind"] for row in timeline].count("detected"),
                         session.metrics["LOOP_DETECTED"])
        detected = [row for row in timeline if row["kind"] == "detected"]
        self.assertTrue(all(row["rung"] for row in detected),
                        "a detection without a rung is a verdict nobody can act on")
        self.assertTrue(all(row["goal_id"] == LOOPING_GOAL.goal_id for row in timeline),
                        "the timeline is this Goal's, not the run's")
        # The audit row is what a reviewer reads afterwards, so the reason is asserted there
        # and not only in the metrics block.
        self.assertTrue(audits, "the session must have left an audit row")
        self.assertTrue(audits[0]["session_result"]["reason"].startswith(SESSION_DOMAIN_STUCK))
        self.assertEqual(audits[0]["session_result"]["lifecycle"], "FAILED")

    def test_the_goal_goes_back_to_the_scheduler_and_the_run_keeps_turning(self):
        """AUTO_CONTINUED: the loop ended a *session*, and the run loop went round again.

        Three separate facts, and each would otherwise be assumed:

        * the run's own reason is not the session's -- a session failure must never become
          the run's verdict (this is the ``return finish(session_result.reason)`` failure mode
          one layer up);
        * the stuck Goal is held back, so the *next* Goal gets the device: that is the defer
          rung's whole purpose and the reason §7 calls this ending recoverable;
        * the Scheduler was asked to select again *after* the session had ended -- the run's
          loop turned, taken inside the selector the loop calls each turn.

        The last one is deliberately not "another session ran": which Goal the Scheduler ranks
        first is read from project state the live AUTO rewrites between runs (measured while
        writing this file: the utility line read ``repeat-failure -60.0`` off production
        data), so asserting an ordering here would make the test a report on that data rather
        than on the loop detector.
        """
        run, session, _audits, yielded, arbitrations = self._looping_run()

        self.assertNotEqual(run.stop_reason, session.reason)
        self.assertFalse(is_fatal_stop(run.stop_reason))
        self.assertIn(LOOPING_GOAL.goal_id, yielded,
                      "the stuck Goal must be held back so the next one gets its turn")
        self.assertTrue(arbitrations, "the run must have arbitrated at least once")
        self.assertGreaterEqual(arbitrations[-1], 1,
                                "the run's last arbitration came after the loop had ended")


if __name__ == "__main__":
    unittest.main()
