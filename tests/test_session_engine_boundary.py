"""The four properties the operator's directive names, proved rather than asserted.

``GENERIC_SESSION_ENGINE_V1`` is only allowed to exist if it is *not* a second Scheduler.  The
directive's 必须证明 clause names four things, and this file is the evidence for each:

1. **没有第二 Scheduler** -- asserted three ways: by module identity (``session_host``
   re-exports the project's own ``WorldState`` rather than defining one), by source text (no
   session module imports ``scheduler`` or ``runtime``, and none defines a Scheduler, a
   Registry, a Goal Library, a Brain, a WorldState or a queue), and by the type the engine is
   written against (``SessionHost`` declares no goal-selection and no role-switch method, so an
   adapter cannot call one even by accident).
2. **没有跨 Goal 自主决策** -- ``SessionSpec.goal_id`` is required and frozen, ``SessionContext``
   is frozen, the engine's single contact with the scheduler is one call at a safe point, and a
   session believes only the Goal it was handed.
3. **Hard Event 能在安全点抢占** -- ``Scheduler.session_preemption`` answers in the directive's
   own §17 classes, and a session stops between two steps rather than mid-step: the test drives a
   real ``LiveRuntime`` and watches a session that has already executed a step yield before its
   next one.
4. **Session 失败不会停止整个 AUTO** -- the same live run loop, with a session that fails at its
   first observation, and the run keeps taking steps afterwards.

The live-loop harness is the one ``tests/test_refusal_yields_the_cycle.py`` established:
``_FakeVision`` / ``_FakeSemantic`` / ``_FakeDevice`` plus a stubbed ``_selectable``, inside a
``TemporaryDirectory``.  Only ``_selectable`` and the brain are stubbed, and for the same
measured reason as there: the production answer comes from the capability gate, which reads
``knowledge/**`` and is rewritten by the running AUTO between runs.

One measured limitation is recorded here rather than hidden: the host asks the *runtime's*
Scheduler, and a run does not build one until it is about to dispatch an atomic step.  So a
run's very first session -- before any step has been executed -- has no oracle and will not be
preempted by the ladder.  That is bounded (a session has a step and a time budget, so it ends
within seconds) and it is the safe direction, but it is a fact and the yield test therefore
states the precondition it needs.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_schedule, models, session_adapters, session_host  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.executor import Executor  # noqa: E402
from winter_agent_v2.goal_library import GoalState, GoalStatus  # noqa: E402
from winter_agent_v2.models import Decision, Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.scheduler import Scheduler  # noqa: E402
from winter_agent_v2.session_adapters import SessionRoute  # noqa: E402
from winter_agent_v2.session_engine import (  # noqa: E402
    STEP_OBSERVE_ONLY,
    SessionAdapter,
    SessionEngine,
    SessionHost,
    SessionSpec,
    SessionStep,
    StepOutcome,
    StepVerdict,
)
from winter_agent_v2.session_host import LiveRuntimeSessionHost, SessionRunBinding  # noqa: E402

SESSION_MODULES = ("session_engine", "session_adapters", "session_host")


def source_of(module: str) -> str:
    return (ROOT / "winter_agent_v2" / f"{module}.py").read_text(encoding="utf-8")


# ==========================================================================================
# 1. There is no second Scheduler, and no second anything
# ==========================================================================================

class ThereIsNoSecondSchedulerTests(unittest.TestCase):
    def test_the_session_modules_do_not_import_the_scheduler_or_the_runtime(self):
        """The direction of the dependency is the boundary.

        ``runtime`` imports ``session_adapters`` (to answer "does this Goal have a session?")
        and ``scheduler`` imports ``session_engine`` (for ``YieldVerdict``).  If either edge were
        reversed -- a session module reaching back for the Scheduler or the Runtime -- the
        session could ask *global* questions, which is exactly what it may not do.
        """
        banned = ("from .scheduler import", "from .runtime import", "from . import scheduler",
                  "from . import runtime", "import winter_agent_v2.scheduler",
                  "import winter_agent_v2.runtime")
        for module in SESSION_MODULES:
            with self.subTest(module=module):
                text = source_of(module)
                for needle in banned:
                    self.assertNotIn(needle, text,
                                     f"{module} must not reach for the scheduler or the runtime")

    def test_a_re_export_is_not_a_second_world_state(self):
        """``session_host`` legitimately names ``WorldState`` -- and it must be the *same* one.

        A name-based check would flag this import as a second world state, which is how a first
        version of this test produced a false positive.  Identity is the honest test.
        """
        self.assertIs(session_host.WorldState, models.WorldState)

    def test_no_session_module_defines_a_scheduler_a_registry_or_a_queue(self):
        """The directive's forbidden list, expressed as a definition scan.

        ``第二 Scheduler / 第二 WorldState / 第二 Registry / 第二 Goal Engine / 平行 Manager /
        活动专属 Scheduler / 复杂 Orchestrator`` -- none of them may be *defined* here, however
        thin, because a thin one grows.
        """
        forbidden = re.compile(
            r"^\s*(?:class|def)\s+"
            r"(Scheduler|Registry|SkillRegistry|GoalLibrary|GoalEngine|Brain|RuleBrain|"
            r"WorldState|Manager|Orchestrator|Queue|TaskQueue)\b",
            re.MULTILINE,
        )
        for module in SESSION_MODULES:
            with self.subTest(module=module):
                found = forbidden.findall(source_of(module))
                self.assertEqual(found, [], f"{module} defines {found}")

    def test_no_session_module_keeps_a_module_level_queue(self):
        """A module-level queue is what a second task pipeline looks like on day one."""
        assignment = re.compile(r"^([A-Z_]+)\s*[:=]", re.MULTILINE)
        for module in SESSION_MODULES:
            with self.subTest(module=module):
                names = assignment.findall(source_of(module))
                offenders = [name for name in names if "QUEUE" in name or "PENDING" in name]
                self.assertEqual(offenders, [], f"{module} keeps {offenders} at module level")

    def test_the_engine_talks_to_the_scheduler_in_exactly_one_place(self):
        """One contact point, and it is a question.

        Counted in the source rather than inferred from behaviour, because the property is
        structural: a second call site would be a second answer to "may I keep the device".
        """
        text = source_of("session_engine")
        self.assertEqual(text.count("host.yield_verdict"), 1)
        self.assertEqual(text.count("session_preemption"), 0,
                         "the engine must ask the host, never the Scheduler directly")

    def test_the_session_host_borrows_the_runtime_rather_than_rebuilding_it(self):
        """One executor, one router, one verifier, one episode writer, one OCR service.

        Asserted as a source fact because it is the thing that keeps a session step
        indistinguishable from a loop step in the episode stream.
        """
        text = source_of("session_host")
        for borrowed in ("runtime._session_execute_atomic", "runtime._session_verify",
                         "runtime._record_episode", "runtime._ocr_service",
                         "runtime._observe", "runtime._capture_path"):
            with self.subTest(borrowed=borrowed):
                self.assertIn(borrowed, text)


class TheHostSurfaceItselfForbidsGlobalDecisionsTests(unittest.TestCase):
    """The boundary as a fact about the *type*, not as a promise in a comment."""

    FORBIDDEN = ("select_goal", "switch_role", "set_goal", "choose_goal", "schedule",
                 "arbitrate", "select_next", "rank_goals", "rank", "brain", "goal_library",
                 "registry", "candidate_pool")

    def _host(self) -> LiveRuntimeSessionHost:
        runtime = SimpleNamespace(
            device=SimpleNamespace(), adb_device=None, sleeper=lambda _s: None,
            capture_dir=Path("capture"), _scheduler=None,
        )
        binding = SessionRunBinding(index=1, goal_id="G", role_id="R",
                                    before=WorldState(), before_path=Path("before.png"))
        return LiveRuntimeSessionHost(runtime, binding)

    def test_the_live_host_satisfies_the_protocol(self):
        self.assertIsInstance(self._host(), SessionHost)

    def test_the_live_host_has_no_goal_selection_and_no_role_switch(self):
        host = self._host()
        present = [name for name in self.FORBIDDEN if hasattr(host, name)]
        self.assertEqual(present, [], f"the host exposes {present}")

    def test_the_protocol_itself_declares_no_global_surface(self):
        declared = set(dir(SessionHost))
        present = [name for name in self.FORBIDDEN if name in declared]
        self.assertEqual(present, [], f"SessionHost declares {present}")

    def test_an_adapter_is_never_handed_the_runtime_as_a_collaborator(self):
        """The host wraps the runtime; the protocol does not name it.

        ``self.runtime`` exists on the host -- it is how a capability is borrowed -- but the
        engine's protocol never mentions it, so an adapter written against ``SessionHost`` cannot
        reach the Goal Library through the type it was given.
        """
        public = {name for name in dir(SessionHost) if not name.startswith("_")}
        self.assertNotIn("runtime", public)
        self.assertIn("device", public, "and the one capability it does expose is named")


# ==========================================================================================
# 2. No cross-Goal autonomous decision
# ==========================================================================================

class ASessionCannotChooseAnotherGoalTests(unittest.TestCase):
    def test_the_spec_refuses_to_exist_without_a_goal(self):
        with self.assertRaises(ValueError):
            SessionSpec(goal_id="", adapter="fishing")

    def test_the_context_is_frozen_so_a_session_cannot_re_bind_mid_flight(self):
        from dataclasses import FrozenInstanceError

        from winter_agent_v2.session_engine import SessionContext

        context = SessionContext(spec=SessionSpec(goal_id="G", adapter="a", role_id="R1"),
                                 started_at=0.0)
        with self.assertRaises(FrozenInstanceError):
            context.spec = SessionSpec(goal_id="OTHER", adapter="a")  # type: ignore[misc]

    def test_the_engine_holds_no_state_between_sessions(self):
        """Everything a session knows lives in the context+state it was handed for that call.

        A class-level counter would let a second session inherit the first one's counts -- which
        is how one Goal's remaining budget would silently become another Goal's.
        """
        class_level = {name: value for name, value in vars(SessionEngine).items()
                       if not name.startswith("__")
                       and not callable(value) and not isinstance(value, (str, property))}
        self.assertEqual(class_level, {}, "the engine carries nothing on the class")


# ==========================================================================================
# 3. The Hard Event oracle: the Scheduler's own classes, and nothing else
# ==========================================================================================

class _Role:
    """The three fields ``session_preemption`` reads off the readiness ladder's role."""

    def __init__(self, role_id="R1", live="OPEN", minutes=10.0):
        self.role_id = role_id
        self.live_window_state = live
        self._minutes = minutes

    def minutes_to_start(self, now=None):
        return self._minutes


def oracle(*, phase, role=None):
    """A real ``Scheduler.session_preemption`` with only its clock input replaced.

    ``object.__new__`` rather than the constructor because the constructor builds a
    ``GoalLibrary`` and nothing in the oracle reads it -- and because the subject here is the
    oracle's own decision table, not the scheduler's wiring.
    """
    scheduler = object.__new__(Scheduler)
    came_from = role or _Role()
    scheduler.readiness = lambda now=None: (
        event_schedule.PHASE_PRIORITY[phase], phase, came_from)
    return scheduler


class TheHardEventOracleTests(unittest.TestCase):
    def test_a_fatal_reason_yields_in_the_fatal_class(self):
        verdict = oracle(phase=event_schedule.ReadinessPhase.IDLE).session_preemption(
            goal_id="G", role_id="R1", fatal_reason="DEVICE_LOST")
        self.assertTrue(verdict.yield_now)
        self.assertEqual(verdict.reason_class, "FATAL")
        self.assertEqual(verdict.reason, "FATAL:DEVICE_LOST")

    def test_a_hard_event_yields_in_the_preempt_class(self):
        verdict = oracle(phase=event_schedule.ReadinessPhase.IDLE).session_preemption(
            goal_id="G", role_id="R1", hard_event="BEAR_WINDOW_OPEN")
        self.assertTrue(verdict.yield_now)
        self.assertEqual(verdict.reason_class, "HARD_EVENT_PREEMPT")

    def test_the_ordinary_ladder_does_not_interrupt_an_ordinary_session(self):
        """T30 / T15 is preparation time, not a stop: a bounded session costs more to interrupt."""
        for phase in (event_schedule.ReadinessPhase.IDLE, event_schedule.ReadinessPhase.T30,
                      event_schedule.ReadinessPhase.T15):
            with self.subTest(phase=phase.value):
                verdict = oracle(phase=phase).session_preemption(goal_id="G", role_id="R1")
                self.assertFalse(verdict.yield_now)

    def test_t5_and_tighter_hand_the_device_back(self):
        """The book's own break point: "T5 and tighter is the rung where 普通任务让路"."""
        for phase in (event_schedule.ReadinessPhase.T5, event_schedule.ReadinessPhase.T1):
            with self.subTest(phase=phase.value):
                verdict = oracle(phase=phase).session_preemption(goal_id="G", role_id="R1",
                                                                 steps_used=2)
                self.assertTrue(verdict.yield_now)
                self.assertEqual(verdict.reason_class, "HARD_EVENT_PREEMPT")
                self.assertIn("after 2 session step(s)", verdict.reason)

    def test_an_expired_window_does_not_preempt(self):
        """The client said the window is over, so a past reservation is a stale record."""
        scheduler = oracle(phase=event_schedule.ReadinessPhase.OPEN,
                           role=_Role(live=event_schedule.LiveWindowState.EXPIRED.value))
        self.assertFalse(scheduler.session_preemption(goal_id="G", role_id="R1").yield_now)

    def test_a_stale_open_reservation_does_not_preempt_forever(self):
        """Measured 2026-09-30: three reservations from 2026-09-27/28 were still reading OPEN.

        Without the grace bound the ladder is permanently open once a reservation's start
        passes, which pinned the bear skill's priority for a window that did not exist.
        """
        role = _Role(live=event_schedule.LiveWindowState.UNKNOWN.value,
                     minutes=-(Scheduler.STALE_RESERVATION_GRACE_MINUTES + 1))
        self.assertFalse(oracle(phase=event_schedule.ReadinessPhase.OPEN,
                                role=role).session_preemption(goal_id="G", role_id="R1").yield_now)

    def test_a_recent_open_reservation_still_preempts(self):
        role = _Role(live=event_schedule.LiveWindowState.UNKNOWN.value, minutes=-5.0)
        self.assertTrue(oracle(phase=event_schedule.ReadinessPhase.OPEN,
                               role=role).session_preemption(goal_id="G", role_id="R1").yield_now)

    def test_a_window_the_client_has_not_opened_yet_does_not_preempt(self):
        role = _Role(live=event_schedule.LiveWindowState.SCHEDULED_NOT_OPEN.value)
        self.assertFalse(oracle(phase=event_schedule.ReadinessPhase.OPEN,
                                role=role).session_preemption(goal_id="G", role_id="R1").yield_now)

    def test_a_role_handoff_is_not_a_yield_reason(self):
        """A session cannot switch role (constraint 3), so a handoff is the *Goal*'s ending."""
        text = source_of("scheduler")
        block = text.split("def session_preemption", 1)[1].split("def _bear_goal_skills", 1)[0]
        self.assertNotIn("switch_role", block)
        self.assertNotIn("select_global", block)


# ==========================================================================================
# 4. The four properties, driven through a real ``LiveRuntime``
# ==========================================================================================

ONLY_GOAL = GoalState(
    goal_id="KEEP_TRAINING_PRODUCTIVE",
    status=GoalStatus.READY,
    available_skills=("TRAIN_TROOPS",),
)


class _FakeDevice:
    def __init__(self):
        self.taps = []
        self.backs = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return SimpleNamespace(connected=True, resolution=(720, 1280))

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

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


class _FailingAdapter(SessionAdapter):
    """A session whose domain reader is broken.  Nothing else about it is wrong."""

    name = "boom"

    def observe(self, context, host):
        raise RuntimeError("the domain reader is broken")

    def choose_step(self, context, host, domain):
        return None

    def is_complete(self, context, host, domain):
        return False, ""


class _BusyTrainingAdapter(SessionAdapter):
    """Reports every barracks as already working, so the batch is done with no steps."""

    name = "busy_training"

    CAMPS = ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP")

    def observe(self, context, host):
        return {"camps": {camp: {"state": "训练中"} for camp in self.CAMPS}}

    def choose_step(self, context, host, domain):
        return None

    def is_complete(self, context, host, domain):
        return True, "TRAINING_BATCH_DONE"


class _OneStepThenWaitAdapter(SessionAdapter):
    """Executes exactly one step, then keeps offering another -- so the yield must catch it.

    The step is ``OBSERVE_ONLY`` rather than a registered skill, and deliberately: a real skill
    would need the semantic resolver, the backend router and a device frame, none of which this
    property is about.  It still costs one unit of the session's budget and still produces a safe
    point *after* it, which is the whole of "抢占发生在安全点".
    """

    name = "one_step_then_wait"

    def __init__(self):
        self.steps = 0

    def observe(self, context, host):
        return {"blob": True}

    def is_complete(self, context, host, domain):
        return False, ""

    def choose_step(self, context, host, domain):
        return SessionStep(0, STEP_OBSERVE_ONLY, reason="look again")

    def verify_step(self, context, host, step, execution):
        if step.kind == STEP_OBSERVE_ONLY:
            self.steps += 1
            return StepVerdict(StepOutcome.SUCCESS, "ONE_STEP")
        return super().verify_step(context, host, step, execution)


def _map_frame():
    return WorldState(page=Page.MAP, confidence=0.99, normal_idle_slots=2)


def _selectable_stub(goal):
    def stub(runtime, _goals, _deferrals):
        if goal is None or goal.goal_id in runtime._yielded_goals:
            return []
        return [goal]

    return stub


def _route(adapter: str) -> SessionRoute:
    return SessionRoute(goal_id="KEEP_TRAINING_PRODUCTIVE", adapter=adapter,
                        skills=frozenset({"TRAIN_TROOPS"}))


class ASessionInsideTheRunLoopTests(unittest.TestCase):
    """The acceptance flows, driven through the runtime's own loop.

    Only three things are stubbed, and each for a named reason: the goal selector (the
    production answer reads ``knowledge/**``, which the live AUTO rewrites between runs), the
    brain (the subject is the *session* boundary, not which skill the brain would pick on this
    frame), and the route table (the session adapters are registered here rather than in
    production so the test does not depend on a Goal being enabled by policy).
    """

    MAX_ACTIONS = 4

    def _run(self, *, routes, adapters, max_actions=None, prepare=None):
        max_actions = max_actions or self.MAX_ACTIONS
        device = _FakeDevice()
        results = []
        bindings = []
        original_run = SessionEngine.run
        original_init = LiveRuntimeSessionHost.__init__

        def spy(engine_self, context, adapter, host):
            result = original_run(engine_self, context, adapter, host)
            results.append(result)
            return result

        def capture_binding(host_self, runtime, binding):
            original_init(host_self, runtime, binding)
            # ``page_audit`` is built per iteration inside the loop, so this dict is that
            # iteration's own row and reading it after the run still reads the right one.
            bindings.append(binding)

        decision = Decision("TRAIN_TROOPS", "forced", 1.0, "works a barracks")
        patches = [
            patch.object(LiveRuntime, "_selectable", _selectable_stub(ONLY_GOAL)),
            patch.object(RuleBrain, "decide", new=lambda *a, **k: decision),
            patch.object(session_adapters, "SESSION_ROUTES", tuple(routes)),
            patch.dict(session_adapters.SESSION_ADAPTERS, adapters),
            patch.object(SessionEngine, "run", spy),
            patch.object(LiveRuntimeSessionHost, "__init__", capture_binding),
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
                if prepare is not None:
                    prepare(runtime)
                run = runtime.run(max_actions=max_actions)
        finally:
            for extra in patches:
                extra.stop()
        return device, run, results, [binding.page_audit for binding in bindings], bindings

    def test_a_session_that_fails_does_not_end_the_run(self):
        """必须证明: Session 失败不会停止整个 AUTO.

        The session fails at its very first observation, and the run must still take its next
        step.  The failure mode this guards is the one an over-eager implementation produces --
        ``return finish(session_result.reason)`` inside the hook, which would end the whole cycle
        on one Goal's broken reader.
        """
        _device, run, results, audits, bindings = self._run(
            routes=[_route("boom")], adapters={"boom": _FailingAdapter})

        self.assertTrue(results, "the run must actually have reached the session")
        for result in results:
            with self.subTest(session=result.session_id):
                self.assertTrue(result.failed)
                self.assertEqual(result.reason, "SESSION_OBSERVE_FAILED")
        self.assertGreaterEqual(len(run.steps), len(results),
                                "the run kept taking steps after every session it ran")
        self.assertNotIn(run.stop_reason, {result.reason for result in results},
                         "no session's reason may become the run's reason")
        self.assertIsNotNone(run.stop_reason, "and the run still ended with a stated reason")

        # The audit row is what a reviewer reads afterwards, so it is asserted rather than the
        # narration alone -- the narration is a print, the row is the record.
        first = audits[0]
        self.assertEqual(first["session_route"]["adapter"], "boom")
        self.assertEqual(first["session_route"]["lifecycle"], "CANDIDATE")
        self.assertEqual(first["session_result"]["lifecycle"], "FAILED")
        self.assertEqual(first["session_result"]["reason"], "SESSION_OBSERVE_FAILED")
        self.assertEqual(first["session_result"]["failure"], "SESSION_OBSERVE_FAILED")
        self.assertEqual(first["session_result"]["steps"], 0)
        self.assertTrue(first["session_result"]["session_id"].startswith("S"))
        self.assertEqual(first["verifier_result"]["lifecycle"], "FAILED")
        self.assertFalse(first["action_sent"], "a session that never acted sent nothing")
        self.assertTrue(first["attempted_reason"].startswith("session:boom:"))
        self.assertIn("session_ms", bindings[0].latency,
                      "the session's cost is accounted for where every other step's is")

    def test_a_failed_session_is_deferred_instead_of_repeated_each_iteration(self):
        """An unreadable domain yields this goal, leaving budget for other work."""
        _device, _run_, results, _audits, _bindings = self._run(
            routes=[_route("boom")], adapters={"boom": _FailingAdapter}, max_actions=5)
        self.assertEqual(len(results), 1)

    def test_a_completed_session_returns_to_the_scheduler_rather_than_ending_the_run(self):
        """必须证明: Session 完成/Yield/失败后必须返回 Global Scheduler.

        The training batch reports its work done on the first observation (every barracks is
        already training), so the session is COMPLETE with zero steps -- and the run must keep
        going rather than treat the completion as the cycle's end.
        """
        _device, run, results, audits, _bindings = self._run(
            routes=[_route("busy_training")], adapters={"busy_training": _BusyTrainingAdapter})
        self.assertTrue(results)
        self.assertTrue(all(result.completed for result in results),
                        f"expected completions, got {[r.reason for r in results]}")
        self.assertEqual({result.reason for result in results}, {"TRAINING_BATCH_DONE"})
        self.assertEqual(results[0].metrics["SESSION_STEPS"], 0,
                         "every barracks was already working, so nothing needed a tap")
        self.assertIn(run.stop_reason, ("MAX_ACTIONS_REACHED", "NO_EXECUTION"),
                      "the run ended for its own reason, not the session's")
        self.assertEqual(audits[0]["session_result"]["lifecycle"], "COMPLETE")
        self.assertEqual(audits[0]["session_result"]["steps"], 0)
        self.assertTrue(audits[0]["verifier_result"]["ok"],
                        "a completed session is a passing verifier result for the Goal")

    def test_a_hard_event_preempts_a_session_at_its_next_safe_point(self):
        """必须证明: Hard Event 能在安全点抢占.

        The ladder is patched to T5 **only for the second call the oracle makes** -- the first
        safe point is IDLE, so the session runs one step and is stopped before its second.  The
        runtime's own ranking path calls ``readiness`` with no argument and is left untouched,
        which is why the discriminator is the argument and not a global flag.

        The Scheduler is supplied up front because of the limitation recorded in this module's
        docstring: a run builds one only when it is about to dispatch an atomic step, so without
        it there is no oracle to ask.  This test is about what the oracle does when asked.
        """
        original_readiness = Scheduler.readiness
        answers = []

        def readiness(self, now=None):
            if now is None:
                return original_readiness(self)
            # IDLE on the first safe point, T5 from the second: the session gets to run one step
            # and is then stopped *between* steps, which is what "安全点" means.  Later sessions
            # in the same run see T5 immediately, and that is correct -- the event is still on.
            phase = (event_schedule.ReadinessPhase.IDLE if len(answers) < 1
                     else event_schedule.ReadinessPhase.T5)
            answers.append(phase.value)
            return (event_schedule.PHASE_PRIORITY[phase], phase,
                    _Role() if phase is event_schedule.ReadinessPhase.T5 else None)

        def supply_scheduler(runtime):
            runtime._scheduler = Scheduler(runtime.brain, runtime.registry, Executor(),
                                           runtime.candidate_pool)

        with patch.object(Scheduler, "readiness", readiness):
            _device, run, results, audits, _bindings = self._run(
                routes=[_route("one_step_then_wait")],
                adapters={"one_step_then_wait": _OneStepThenWaitAdapter},
                prepare=supply_scheduler,
            )

        self.assertTrue(results, "the run must actually have reached the session")
        first = results[0]
        self.assertTrue(first.yielded,
                        f"expected a yield, got {first.lifecycle.value}/{first.reason}")
        self.assertEqual(first.yield_class, "HARD_EVENT_PREEMPT")
        self.assertEqual(first.metrics["SESSION_STEPS"], 1,
                         "one step ran; the safe point before the second is where it stopped")
        self.assertEqual(answers[:2], ["IDLE", "T5"],
                         "the first safe point let it act; the second is where it was stopped")
        self.assertNotIn(run.stop_reason, {result.reason for result in results},
                         "the run continued instead of ending on the preemption")
        self.assertEqual(audits[0]["session_result"]["yield_class"], "HARD_EVENT_PREEMPT")
        self.assertEqual(audits[0]["session_result"]["lifecycle"], "YIELDING")
        self.assertFalse(audits[0]["session_result"]["failure"],
                         "a yield is not a failure and the audit row says so")


if __name__ == "__main__":
    unittest.main()
