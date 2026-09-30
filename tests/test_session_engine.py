"""The Generic Session Engine, measured against a host that answers instead of a client.

These are the engine's own semantics: the nine lifecycle states, the five step outcomes, the
four budgets, the three retry counters, bounded WAITING, the episode linkage and the
return-to-scheduler rule.  Every one of them is asserted without a device, because the engine
is a loop with budgets and the client is not part of that question.

The three defects these tests were written against, all found by running the engine for the
first time and all invisible to a reading:

* the engine asked ``host.verify_step`` where it had to ask ``adapter.verify_step``, so every
  adapter's own verifier was dead code -- a bear session could never count a join, and an
  ``OBSERVE_ONLY`` step died with ``SESSION_STEP_NOT_VERIFIED`` before the adapter was
  consulted at all;
* ``record_step`` was declared in the protocol and never called, so a session ran a whole cast
  and left no row in the episode stream;
* a ``WAITING`` ending returned a report whose outcome was read with ``.value`` on a string,
  which raised inside the engine's own ``try`` and reported ``SESSION_RAISED:AttributeError``
  instead of the wait's real ending.

The sibling files are ``test_session_engine_boundary.py`` (the four acceptance properties,
including the live run loop) and ``test_session_adapters.py`` (the four business adapters).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import VerificationResult  # noqa: E402
from winter_agent_v2.session_engine import (  # noqa: E402
    SESSION_NO_STEP_PRODUCED,
    SESSION_OBSERVE_FAILED,
    SESSION_RESOURCE_BUDGET_EXHAUSTED,
    SESSION_STEP_NOT_VERIFIED,
    SESSION_TIME_BUDGET_EXHAUSTED,
    SESSION_TIMEOUT,
    STEP_OBSERVE_ONLY,
    STEP_SKILL,
    IllegalSessionTransition,
    SessionAdapter,
    SessionContext,
    SessionEngine,
    SessionLifecycle,
    SessionSpec,
    SessionState,
    SessionStep,
    StepExecution,
    StepOutcome,
    StepVerdict,
    YieldVerdict,
)


# ==========================================================================================
# The two collaborators the engine is allowed to have
# ==========================================================================================

class FakeHost:
    """A ``SessionHost`` that answers from a list and never touches a device.

    The clock is virtual and ``sleep`` advances it, so the engine's own time budgets can be
    exercised without a real second of waiting: a session that must wait 45 seconds waits 45
    virtual ones.  Every one of the protocol's methods is implemented, because the boundary
    test asserts this object really is a ``SessionHost``.
    """

    def __init__(self, *, resources=None, yields_on=(), lease=True, record_raises=False,
                 host_verdict=("ok", True), device=None, step_seconds=0.0):
        self.clock = 0.0
        self.sleeps: list[float] = []
        self.executions = 0
        self.executed: list[SessionStep] = []
        self.recorded: list[dict] = []
        self.record_raises = bool(record_raises)
        self.captures = 0
        self.observations = 0
        self.notes: list[str] = []
        #: How long a real step takes.  The engine's time budget is checked before each step,
        #: so without a step cost the clock would never move and the budget could never bite --
        #: which is exactly how a first version of the time-budget test passed for no reason.
        self.step_seconds = float(step_seconds)
        #: The ``steps_used`` values at which the oracle says "yield".  Empty means never.
        self.yields_on = set(yields_on)
        self.yield_calls: list[int] = []
        self._lease = bool(lease)
        self._resources = dict(resources or {})
        #: ``("ok"|"none"|"unreadable", payload)`` -- what ``verify_step`` hands the adapter.
        self._host_verdict = host_verdict
        self._device = device

    # ---- time ------------------------------------------------------------------
    def now(self) -> float:
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.clock += max(0.0, float(seconds))

    # ---- device ----------------------------------------------------------------
    def capture(self):
        self.captures += 1
        return f"frame-{self.captures}"

    def device(self):
        return self._device

    # ---- reading ---------------------------------------------------------------
    def ocr(self, frame=None, *, region=None):
        return []

    def observe(self, phase: str):
        self.observations += 1
        return {"phase": phase}

    # ---- one step --------------------------------------------------------------
    def execute_step(self, step: SessionStep) -> StepExecution:
        self.executions += 1
        self.executed.append(step)
        self.clock += self.step_seconds
        if step.kind == STEP_OBSERVE_ONLY:
            # Nothing to drive -- exactly what the real host answers for this kind.
            return StepExecution(executed=False, reason="OBSERVE_ONLY", latency_ms=0.0,
                                 before={"n": self.executions}, after={"n": self.executions})
        return StepExecution(executed=True, reason=step.skill_id, latency_ms=1.0,
                             backend="ADB", tap_point=(10, 20),
                             evidence={"skill": step.skill_id},
                             before={"n": self.executions}, after={"n": self.executions + 1})

    def verify_step(self, step: SessionStep, execution: StepExecution):
        kind, payload = self._host_verdict
        if kind == "none":
            return None
        if kind == "unreadable":
            return payload
        return VerificationResult(bool(payload), "HOST_VERDICT", {"from": "host"})

    def record_step(self, report) -> str | None:
        if self.record_raises:
            raise OSError("the episode store is not writable")
        self.recorded.append(report.as_row())
        return f"EP{len(self.recorded)}"

    # ---- scheduler contact -----------------------------------------------------
    def yield_verdict(self, context: SessionContext, steps_used: int) -> YieldVerdict:
        self.yield_calls.append(int(steps_used))
        if int(steps_used) in self.yields_on:
            return YieldVerdict(True, "hard event: bear", "HARD_EVENT_PREEMPT")
        return YieldVerdict(False)

    # ---- environment -----------------------------------------------------------
    def resource_state(self):
        return dict(self._resources)

    def lease_ok(self) -> bool:
        return self._lease

    def note(self, event: str, **fields) -> None:
        self.notes.append(event)


class ScriptedAdapter(SessionAdapter):
    """An adapter whose answers are a list, so the engine can be run without a client.

    The script index is ``host.executions`` rather than an internal counter, and that is
    deliberate: ``_wait_for_work`` calls ``choose_step`` as a *probe* ("is there work?"), so an
    adapter that advanced on every call would consume a step per probe and the waiting test
    would pass for the wrong reason.
    """

    name = "scripted"

    def __init__(self, *, steps=(), complete_after=None, verdicts=(), recover_times=0,
                 raise_on_observe=False):
        self.script = list(steps)
        self.complete_after = complete_after
        self.verdicts = list(verdicts)
        self.recover_times = int(recover_times)
        self.raise_on_observe = bool(raise_on_observe)
        self.prepared = 0
        self.asked = 0
        self.recovered = 0

    def prepare(self, context, host):
        self.prepared += 1
        return None

    def observe(self, context, host):
        if self.raise_on_observe:
            raise RuntimeError("ScriptedAdapter was told to fail its observation")
        return {"blob": True}

    def is_complete(self, context, host, domain):
        done = self.complete_after is not None and host.executions >= self.complete_after
        return done, ("GOAL_FINISHED" if done else "")

    def choose_step(self, context, host, domain):
        if host.executions >= len(self.script):
            return None
        return self.script[host.executions]

    def verify_step(self, context, host, step, execution):
        self.asked += 1
        if not self.verdicts:
            return StepVerdict(StepOutcome.SUCCESS, "SCRIPTED_OK")
        index = min(self.asked - 1, len(self.verdicts) - 1)
        return self.verdicts[index]

    def recover(self, context, host, step, verdict):
        self.recovered += 1
        return True if self.recovered <= self.recover_times else None


class BareAdapter(SessionAdapter):
    """An adapter that implements only the four required answers and **no** ``verify_step``.

    The base class's default verifier is the subject of
    ``test_the_default_adapter_verifier_inherits_the_runtime_verifier``.  ``ScriptedAdapter``
    overrides that method, so using it there would have asserted a failure while the scripted
    override answered ``SUCCESS`` -- measured: the first version of that test did exactly that,
    and it failed loudly only because it asserted the *outcome* rather than a call count.
    """

    name = "bare"

    def __init__(self, *, steps=()):
        self.script = list(steps)

    def observe(self, context, host):
        return {"blob": True}

    def is_complete(self, context, host, domain):
        return False, ""

    def choose_step(self, context, host, domain):
        if host.executions >= len(self.script):
            return None
        return self.script[host.executions]


def skill_step(skill_id: str = "SOME_SKILL") -> SessionStep:
    return SessionStep(0, STEP_SKILL, skill_id=skill_id)


def context_for(**spec_changes) -> SessionContext:
    """A context whose clock starts where the fake host's does, so budgets are comparable."""
    spec = SessionSpec(goal_id="USE_NORMAL_FISHING_BAIT", adapter="scripted", **spec_changes)
    return SessionContext(spec=spec, run_id="RUN1", started_at=0.0)


def run_session(adapter: SessionAdapter, host: FakeHost, **spec_changes):
    return SessionEngine().run(context_for(**spec_changes), adapter, host)


# ==========================================================================================
# The happy path, and the three defects it was blind to
# ==========================================================================================

class AStepSequenceEndsInCompleteTests(unittest.TestCase):
    def test_a_two_step_goal_is_complete_and_says_so(self):
        adapter = ScriptedAdapter(steps=[skill_step("A"), skill_step("B")], complete_after=2)
        host = FakeHost()
        result = run_session(adapter, host)

        self.assertTrue(result.completed, f"expected COMPLETE, got {result.lifecycle.value}")
        self.assertEqual(result.reason, "GOAL_FINISHED")
        self.assertEqual(host.executions, 2)
        self.assertEqual(adapter.prepared, 1, "prepare runs exactly once")

    def test_every_step_becomes_an_episode(self):
        """``record_step`` was declared in the protocol for a whole session and never called.

        A cast that ran and left no row is a cast whose evidence does not exist, so the
        linkage is asserted as an equality rather than as "at least one".
        """
        adapter = ScriptedAdapter(steps=[skill_step("A"), skill_step("B")], complete_after=2)
        host = FakeHost()
        result = run_session(adapter, host)
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(len(host.recorded), 2, "one episode row per step")
        self.assertEqual(result.episode_ids, ("EP1", "EP2"))
        self.assertEqual([row["skill"] for row in host.recorded], ["A", "B"])

    def test_an_unwritable_episode_stream_is_not_a_session_failure(self):
        """The episode is evidence *of* the step, not the step.

        A store that cannot be written must not turn a completed goal into a failed session --
        the work happened either way, and reporting otherwise loses the work's outcome to a
        disk problem.
        """
        adapter = ScriptedAdapter(steps=[skill_step("A")], complete_after=1)
        host = FakeHost(record_raises=True)
        result = run_session(adapter, host)
        self.assertTrue(result.completed)
        self.assertEqual(result.episode_ids, (), "no id, because none was written")

    def test_the_engine_asks_the_adapters_verifier_not_the_hosts(self):
        """The defect that made every adapter's ``verify_step`` dead code.

        The host is told to answer "no" and the adapter is told to answer ``SUCCESS``; if the
        engine consults the host, the session fails and the adapter is never asked.  Asserted
        by outcome rather than by counting, because counting alone would pass if the engine
        asked both.
        """
        adapter = ScriptedAdapter(steps=[skill_step("JOIN_RALLY")], complete_after=1,
                                  verdicts=[StepVerdict(StepOutcome.SUCCESS, "BEAR_JOINED")])
        host = FakeHost(host_verdict=("ok", False))
        result = run_session(adapter, host)
        self.assertTrue(result.completed, "the adapter's verifier decided, not the host's")
        self.assertEqual(adapter.asked, 1)
        self.assertEqual(result.steps[0].reason, "BEAR_JOINED")

    def test_the_default_adapter_verifier_inherits_the_runtime_verifier(self):
        """An adapter with nothing domain-specific to add must not make its steps look unjudged.

        The default used to answer ``AMBIGUOUS``, which the engine reads as "the client never
        answered" -- a different and much worse fact than "the runtime's own verifier ran".
        """
        adapter = BareAdapter(steps=[skill_step("A")])
        host = FakeHost(host_verdict=("ok", False))
        result = run_session(adapter, host)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, f"{SESSION_STEP_NOT_VERIFIED}:HOST_VERDICT",
                         "the runtime's refusal is the reason, not ADAPTER_HAS_NO_VERIFIER")

    def test_no_verdict_at_all_is_ambiguous_rather_than_a_refusal(self):
        """``None`` from the runtime means "nobody judged this", which is not "the client said no".

        A verifier that flattened the two would turn a missing verifier into a failure report,
        and the engine would send a step that was never judged into the adapter's recovery.
        """
        adapter = BareAdapter(steps=[skill_step("A")])
        result = run_session(adapter, FakeHost(host_verdict=("none", None)),
                             max_ambiguous_retries=0)
        self.assertEqual(result.outcome, StepOutcome.AMBIGUOUS.value)
        self.assertEqual(result.reason, "SESSION_AMBIGUOUS:ADAPTER_NO_HOST_VERDICT")

    def test_a_verdict_this_layer_cannot_read_is_not_a_no(self):
        """An object with no ``ok`` is unreadable, and unreadable is unknown (§真值纪律)."""
        adapter = BareAdapter(steps=[skill_step("A")])
        result = run_session(adapter, FakeHost(host_verdict=("unreadable", object())),
                             max_ambiguous_retries=0)
        self.assertEqual(result.reason, "SESSION_AMBIGUOUS:ADAPTER_UNREADABLE_VERDICT")


class AnObserveOnlyStepIsLookedAtNotDispatchedTests(unittest.TestCase):
    def test_observe_only_does_not_require_an_execution(self):
        """It spends a step to look again; there is no action for an execution to be missing from.

        The first version failed every such step with ``SESSION_STEP_NOT_VERIFIED`` before the
        adapter's verifier was reached -- which is the fishing adapter's "wait for the level to
        draw" step, so the defect made every fishing cast fail on its second step.
        """
        adapter = ScriptedAdapter(
            steps=[SessionStep(0, STEP_OBSERVE_ONLY), skill_step("B")], complete_after=2,
            verdicts=[StepVerdict(StepOutcome.PROGRESS, "FISHING_LINE_VISIBLE"),
                      StepVerdict(StepOutcome.SUCCESS, "FISHING_CONTROL_SESSION_RAN")],
        )
        host = FakeHost()
        result = run_session(adapter, host)
        self.assertTrue(result.completed, f"got {result.lifecycle.value}/{result.reason}")
        self.assertEqual([step.kind for step in result.steps],
                         [STEP_OBSERVE_ONLY, STEP_SKILL])
        self.assertEqual(result.steps[0].outcome, StepOutcome.PROGRESS.value)
        self.assertFalse(result.steps[0].executed,
                         "the report says honestly that nothing was driven")


# ==========================================================================================
# The four budgets, each with its own name
# ==========================================================================================

class TheBudgetsEachHaveTheirOwnEndingTests(unittest.TestCase):
    def test_the_step_budget_is_a_ceiling_not_a_target(self):
        adapter = ScriptedAdapter(steps=[skill_step(f"S{n}") for n in range(9)])
        host = FakeHost()
        result = run_session(adapter, host, step_budget=3)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, SESSION_TIMEOUT)
        self.assertEqual(result.reason, "SESSION_STEP_BUDGET_EXHAUSTED",
                         "the constant's value is the name a reader sees in the log")
        self.assertEqual(host.executions, 3, "three steps of the declared budget, no more")

    def test_the_time_budget_ends_a_session_that_will_not_finish(self):
        """A step costs the clock something, and the budget is checked before the next one.

        The fake host charges two virtual seconds a step, so the boundary is exact: three steps
        fit inside five seconds, and the fourth is the one the budget refuses.  (Measured while
        writing this: a host that charged nothing made the clock stand still, the budget never
        arrived, and the session ended on its step budget instead -- the test would have passed
        while proving nothing about time.)
        """
        adapter = ScriptedAdapter(steps=[skill_step(f"S{n}") for n in range(9)])
        host = FakeHost(step_seconds=2.0)
        result = run_session(adapter, host, time_budget_s=5.0, step_budget=50)
        self.assertEqual(result.reason, SESSION_TIME_BUDGET_EXHAUSTED)
        self.assertEqual(host.executions, 3, "2s, 4s, 6s -- the fourth step is past the budget")
        self.assertGreaterEqual(host.clock, 5.0)

    def test_a_resource_floor_stops_the_very_next_step(self):
        """``{"stamina": 30}`` is a floor, and the engine owns only the refusal.

        The session is stopped *before* the step that would break the floor, which is why the
        execution count is zero: the adapter's own predicate (tested in
        ``test_session_adapters.py``) is what reports the work as finished; this is the engine
        declining to issue the step.
        """
        adapter = ScriptedAdapter(steps=[skill_step("DISPATCH_MARCH")])
        host = FakeHost(resources={"stamina": 10})
        result = run_session(adapter, host, resource_budget={"stamina": 30})
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, f"{SESSION_RESOURCE_BUDGET_EXHAUSTED}:stamina=10<30")
        self.assertEqual(host.executions, 0)

    def test_an_unread_reading_does_not_trip_the_floor(self):
        """§真值纪律 空 ≠ 没有: an unread stamina is unknown, not zero.

        A session that refused on an unreadable panel would stop spending stamina on frames
        that simply did not show the number.
        """
        for resources in ({}, {"stamina": None}, {"stamina": "unknown"}):
            with self.subTest(resources=resources):
                adapter = ScriptedAdapter(steps=[skill_step("DISPATCH_MARCH")],
                                          complete_after=1)
                host = FakeHost(resources=resources)
                result = run_session(adapter, host, resource_budget={"stamina": 30})
                self.assertTrue(result.completed, "the floor is unknown, so it does not bite")
                self.assertEqual(host.executions, 1)

    def test_a_lost_lease_ends_the_session_and_names_itself(self):
        adapter = ScriptedAdapter(steps=[skill_step("A")])
        host = FakeHost(lease=False)
        result = run_session(adapter, host)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, "SESSION_LEASE_LOST")
        self.assertEqual(host.executions, 0, "nothing is dispatched without the lease")


# ==========================================================================================
# The three bounded retries
# ==========================================================================================

class TheRetriesAreBoundedAndDistinctTests(unittest.TestCase):
    def test_a_failed_verdict_is_handed_to_the_adapters_recovery(self):
        """One recovery attempt pairs with one retry, and a recovered step really runs again."""
        adapter = ScriptedAdapter(
            steps=[skill_step("START_RALLY")], complete_after=2,
            verdicts=[StepVerdict(StepOutcome.FAILED, "RALLY_FULL"),
                      StepVerdict(StepOutcome.SUCCESS, "BEAR_JOINED")],
            recover_times=1,
        )
        host = FakeHost()
        result = run_session(adapter, host, max_recoveries=1)
        self.assertTrue(result.completed, f"got {result.lifecycle.value}/{result.reason}")
        self.assertEqual(adapter.recovered, 1)
        self.assertEqual(host.executions, 2, "the recovered step was actually tried again")

    def test_recovery_exhausted_ends_with_the_step_not_verified(self):
        adapter = ScriptedAdapter(steps=[skill_step("A")],
                                  verdicts=[StepVerdict(StepOutcome.FAILED, "RUNTIME_REFUSED")],
                                  recover_times=0)
        host = FakeHost()
        result = run_session(adapter, host, max_recoveries=1)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, f"{SESSION_STEP_NOT_VERIFIED}:RUNTIME_REFUSED")

    def test_an_ambiguous_client_is_retried_then_named_ambiguous(self):
        """``AMBIGUOUS`` is not a synonym for ``FAILED``: no answer arrived.

        The ending is a failure with its own name, so a reader can tell "the client said no"
        from "the client never said anything" -- and the retry count says how many looks it
        took before giving up.
        """
        adapter = ScriptedAdapter(steps=[skill_step("A")],
                                  verdicts=[StepVerdict(StepOutcome.AMBIGUOUS, "FRAME_UNREADABLE")])
        host = FakeHost()
        result = run_session(adapter, host, max_ambiguous_retries=2)
        self.assertTrue(result.failed)
        self.assertEqual(result.outcome, StepOutcome.AMBIGUOUS.value)
        self.assertEqual(result.reason, "SESSION_AMBIGUOUS:FRAME_UNREADABLE")
        self.assertEqual(result.metrics["SESSION_AMBIGUOUS_RETRIES"], 2)
        self.assertEqual(host.executions, 3, "the original look plus two more")

    def test_a_semantic_miss_is_retried_against_a_fresh_frame(self):
        """The executor finding no target is a retry of the *same* step, not a new one."""
        class NeverExecutes(FakeHost):
            def execute_step(self, step):
                self.executions += 1
                self.executed.append(step)
                return StepExecution(executed=False, reason="SEMANTIC_TARGET_NOT_FOUND")

        adapter = ScriptedAdapter(steps=[skill_step("A")])
        host = NeverExecutes()
        result = run_session(adapter, host, max_semantic_retries=2)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason,
                         f"{SESSION_STEP_NOT_VERIFIED}:SEMANTIC_TARGET_NOT_FOUND")
        self.assertEqual(result.metrics["SESSION_SEMANTIC_RETRIES"], 2)
        self.assertEqual(host.executions, 3)
        self.assertEqual(adapter.asked, 0, "a step that never ran is never verified")

    def test_a_step_that_raises_is_a_step_that_did_not_execute(self):
        class ExplodingHost(FakeHost):
            def execute_step(self, step):
                raise RuntimeError("the executor blew up")

        adapter = ScriptedAdapter(steps=[skill_step("A")])
        host = ExplodingHost()
        result = run_session(adapter, host, max_semantic_retries=0)
        self.assertTrue(result.failed)
        self.assertIn("SESSION_STEP_NOT_VERIFIED:STEP_RAISED:RuntimeError", result.reason)


# ==========================================================================================
# Bounded WAITING: a state, not a failure, and not a second runtime loop
# ==========================================================================================

class WaitingIsBoundedTests(unittest.TestCase):
    def test_a_domain_with_nothing_to_do_waits_then_ends_honestly(self):
        """``choose_step`` returning ``None`` is not an ending, so the engine waits -- but bounded.

        A session that waited forever would be a runtime loop with no scheduler in it, which is
        what constraint 8 forbids.  The virtual clock makes the bound cost nothing to test.
        """
        adapter = ScriptedAdapter(steps=[])  # nothing is ever choosable
        host = FakeHost()
        result = run_session(adapter, host, max_wait_s=2.0)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, SESSION_NO_STEP_PRODUCED)
        self.assertEqual(result.metrics["SESSION_WAITS"], 1)
        self.assertGreater(host.sleeps, [], "the wait really slept rather than spinning")

    def test_a_wait_that_finds_work_continues_the_session(self):
        """The wait's probe is ``choose_step``: when it answers, the session goes back to RUNNING."""
        class LaterAdapter(ScriptedAdapter):
            def choose_step(self, context, host, domain):
                if host.now() < 1.0:
                    return None       # not ready yet
                return SessionStep(0, STEP_SKILL, skill_id="READY")

        adapter = LaterAdapter(steps=[], complete_after=1)
        host = FakeHost()
        result = run_session(adapter, host, max_wait_s=5.0)
        self.assertTrue(result.completed, f"got {result.lifecycle.value}/{result.reason}")
        self.assertEqual(host.executions, 1)

    def test_a_wait_that_finds_the_goal_done_completes(self):
        class CompletesWhileWaiting(ScriptedAdapter):
            def is_complete(self, context, host, domain):
                return host.now() >= 1.0, "GOAL_FINISHED"

        adapter = CompletesWhileWaiting(steps=[])
        host = FakeHost()
        result = run_session(adapter, host, max_wait_s=5.0)
        self.assertTrue(result.completed,
                        "the wait's own ending must be the session's completion, not a failure")
        self.assertEqual(result.reason, "GOAL_FINISHED")
        self.assertEqual(result.lifecycle, SessionLifecycle.COMPLETE)

    def test_a_wait_does_not_fabricate_a_step(self):
        """No step was chosen, so no step is reported and no episode is written.

        This is the third defect of the three: a WAITING ending used to be appended to ``steps``
        *and* to the episode stream, so a session that never acted reported one skill step with
        an empty skill id and a ``SUCCESS`` outcome.  A fabricated step is worse than a missing
        one, and the equality below is the whole assertion.
        """
        adapter = ScriptedAdapter(steps=[])
        host = FakeHost()
        result = run_session(adapter, host, max_wait_s=2.0)
        self.assertEqual(result.steps, ())
        self.assertEqual(result.episode_ids, ())
        self.assertEqual(host.recorded, [])
        self.assertEqual(result.metrics["SESSION_STEPS"], 0)

    def test_a_lost_lease_during_the_wait_ends_the_session(self):
        class LosesLease(ScriptedAdapter):
            def choose_step(self, context, host, domain):
                host._lease = False
                return None

        adapter = LosesLease(steps=[])
        host = FakeHost()
        result = run_session(adapter, host, max_wait_s=5.0)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, "SESSION_LEASE_LOST")


# ==========================================================================================
# Yielding: the one question the session may ask the scheduler
# ==========================================================================================

class TheYieldIsAskedAtASafePointTests(unittest.TestCase):
    def test_a_yield_before_any_step_dispatches_nothing(self):
        """Preemption happens between steps, so a preempted session has done nothing at all."""
        adapter = ScriptedAdapter(steps=[skill_step("A"), skill_step("B")], complete_after=2)
        host = FakeHost(yields_on={0})
        result = run_session(adapter, host)
        self.assertTrue(result.yielded)
        self.assertEqual(result.lifecycle, SessionLifecycle.YIELDING)
        self.assertEqual(result.yield_class, "HARD_EVENT_PREEMPT")
        self.assertEqual(host.executions, 0, "nothing was dispatched after the yield")

    def test_a_yield_is_asked_once_per_safe_point_and_nowhere_else(self):
        """The measurement of constraint 7: the session speaks to the scheduler between steps.

        Two steps and a completion means three safe points (before the first step, before the
        second, and the one that finds the goal done).  A session that consulted the scheduler
        *inside* a step would show more calls than safe points, which is the thing the realtime
        adapters exist to avoid.
        """
        adapter = ScriptedAdapter(steps=[skill_step("A"), skill_step("B")], complete_after=2)
        host = FakeHost()
        result = run_session(adapter, host)
        self.assertTrue(result.completed)
        self.assertEqual(host.yield_calls, [0, 1, 2])
        self.assertEqual(host.executions, 2)

    def test_a_yield_class_the_directive_does_not_recognise_is_refused(self):
        """A yield the directive does not know is not a licence to drop the work."""
        class StrangeOracle(FakeHost):
            def yield_verdict(self, context, steps_used):
                self.yield_calls.append(int(steps_used))
                return YieldVerdict(True, "because I say so", "WHIM")

        adapter = ScriptedAdapter(steps=[skill_step("A")], complete_after=1)
        host = StrangeOracle()
        result = run_session(adapter, host)
        self.assertTrue(result.completed, "an unrecognised yield class is ignored, not obeyed")

    def test_an_oracle_that_raises_does_not_strand_the_session(self):
        class BrokenOracle(FakeHost):
            def yield_verdict(self, context, steps_used):
                raise RuntimeError("the scheduler state is unreadable")

        adapter = ScriptedAdapter(steps=[skill_step("A")], complete_after=1)
        host = BrokenOracle()
        result = run_session(adapter, host)
        self.assertTrue(result.completed, "a broken oracle keeps the device, not the other way")

    def test_the_yield_is_asked_before_the_domain_is_observed(self):
        """Order matters: a preempted session must not have spent an observation on the frame.

        Asserted through ``observe``'s count rather than through the code path, because the
        cost the engine exists to avoid is exactly this one -- an observation paid before it
        was known the device would be handed back.
        """
        adapter = ScriptedAdapter(steps=[skill_step("A")])
        host = FakeHost(yields_on={0})
        run_session(adapter, host)
        self.assertEqual(host.observations, 0)


# ==========================================================================================
# A session never takes the runtime down, and never invents a state
# ==========================================================================================

class ASessionFailureStaysInsideTheSessionTests(unittest.TestCase):
    def test_an_adapter_that_raises_is_a_session_failure_not_a_runtime_one(self):
        """``SESSION_OBSERVE_FAILED``, never ``SESSION_RAISED:...``.

        The adapter's bug is the session's to report.  An exception escaping to the caller would
        end the run, and one Goal's broken reader must not stop every other Goal.
        """
        adapter = ScriptedAdapter(steps=[skill_step("A")], raise_on_observe=True)
        host = FakeHost()
        result = run_session(adapter, host, max_ambiguous_retries=1)
        self.assertTrue(result.failed)
        self.assertEqual(result.reason, SESSION_OBSERVE_FAILED)
        self.assertEqual(host.executions, 0)

    def test_a_defect_in_the_engine_itself_is_named_rather_than_raised(self):
        """The backstop, asserted rather than assumed: a raise never escapes ``run``."""
        class ExplodingAdapter(ScriptedAdapter):
            def is_complete(self, context, host, domain):
                raise KeyError("a bug in the adapter, not in the client")

        adapter = ExplodingAdapter(steps=[skill_step("A")])
        host = FakeHost()
        result = run_session(adapter, host)
        # ``_is_complete`` catches this one, so the session simply keeps going and ends on its
        # budget -- the point being that nothing raised out of ``run``.
        self.assertIsInstance(result.lifecycle, SessionLifecycle)

    def test_an_illegal_lifecycle_edge_is_a_loud_refusal(self):
        state = SessionState()
        state.move(SessionLifecycle.PREPARING)
        state.move(SessionLifecycle.RUNNING)
        state.move(SessionLifecycle.COMPLETE)
        with self.assertRaises(IllegalSessionTransition):
            state.move(SessionLifecycle.RUNNING)
        self.assertTrue(state.terminal)

    def test_a_session_must_be_bound_to_a_goal(self):
        """The type, not the discipline: an unbound session is a session that could choose."""
        with self.assertRaises(ValueError):
            SessionSpec(goal_id="", adapter="fishing")
        with self.assertRaises(ValueError):
            SessionSpec(goal_id="USE_NORMAL_FISHING_BAIT", adapter="")

    def test_the_migration_is_a_migration_and_not_a_second_entry_point(self):
        """One session id, one goal id, one role id -- for the whole life of the session."""
        adapter = ScriptedAdapter(steps=[skill_step("A")], complete_after=1)
        host = FakeHost()
        context = context_for(role_id="R1")
        result = SessionEngine().run(context, adapter, host)
        self.assertEqual(result.session_id, context.session_id)
        self.assertEqual(result.goal_id, context.goal_id)
        self.assertEqual(result.role_id, context.role_id)
        self.assertEqual(result.metrics["SESSION_TRANSITIONS"][0], "CREATED->PREPARING")


if __name__ == "__main__":
    unittest.main()
