"""GENERIC_SESSION_ENGINE_V1 — the multi-step executor inside ONE already-chosen Goal.

Boundary (operator directive 2026-09-30, "GENERIC_SESSION_ENGINE_V1, 但不得形成第二
Scheduler").  Exactly two answerable questions exist:

* ``Global Scheduler`` — 做哪个 Goal / 哪个角色.  Unchanged; ``scheduler.py`` remains the
  only thing that ranks Goals and switches roles.
* ``Generic Session Engine`` (this module) — 已选 Goal 内部的连续多步执行.  It is
  handed a Goal that has already been chosen and a role that has already been
  confirmed, and it runs that Goal's own steps until it is done, must yield, or fails.

The engine therefore decides **nothing global**:

* it cannot select another Goal (``SessionSpec.goal_id`` is immutable for the session's
  whole life and is never re-read from the Goal library);
* it cannot switch role (``SessionContext.role_id`` is fixed and every step is recorded
  against it);
* it opens no second device owner — it *asserts* the lease the runtime already holds;
* it never calls the Global Scheduler from the realtime loop.  The only moment it speaks
  to the scheduler is a **safe point** between steps, and only through ``SessionHost``,
  which is what keeps 「Hard Event 只能通过 Global Scheduler 抢占」 true (constraint 6).

Why this exists at all: measured, one verified action per AUTO round plus a HOME →
普通任务 → back round trip between them is the dominant time loss.  A Goal whose work is
naturally a *sequence* (one fishing cast, one rally list, one stamina budget, one
barracks batch) paid the scheduler's re-observation cost once per micro-step.  The engine
moves that cost to the session boundary — one arbitration in, many steps, one return.

What is deliberately NOT here
-----------------------------
No queue, no registry, no world state, no goal ranking, no skill table.  The engine is a
*loop with budgets*; every domain decision belongs to the Adapter, and every global
decision belongs to the Scheduler.  ``tests/test_session_engine_boundary.py`` pins the
imports so the boundary cannot erode by accident.

Lifecycle (operator directive, 统一生命周期)
--------------------------------------------
    CREATED → PREPARING → RUNNING → VERIFYING → COMPLETE
                             ↕ WAITING / YIELDING / RECOVERING → FAILED

Step outcome (operator directive, 统一 Step 结果)
-------------------------------------------------
    SUCCESS / PROGRESS / STILL_PENDING / AMBIGUOUS / FAILED
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable

# LOOP_DETECTOR_V1 as a **common capability of this engine** (operator directive
# 2026-09-30).  It is imported here rather than implemented per adapter for the same reason
# the lifecycle is: a loop is a property of "a Goal doing steps", not of fishing or bearing,
# and four adapters each growing their own repeat counter is four places to get the threshold
# wrong.  ``loop_detector`` imports the standard library only, so this adds no dependency and
# cannot become a second runtime, world or model.
from .loop_detector import (
    LoopDetector,
    LoopSignature,
    RUNG_DEFER_GOAL,
    RUNG_FEATURE_REOPEN,
    RUNG_HOME_RECOVERY,
    RUNG_LOCAL_REOBSERVE,
    RUNG_SEMANTIC_RETRY,
    RUNG_WIDEN_OBSERVE,
    progress_from_outcome,
    relevant_state_hash,
)


# --------------------------------------------------------------------------- lifecycle

class SessionLifecycle(str, Enum):
    """The nine unified session states.  No other state may be invented."""

    CREATED = "CREATED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    WAITING = "WAITING"
    YIELDING = "YIELDING"
    RECOVERING = "RECOVERING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


TERMINAL_LIFECYCLES: frozenset[SessionLifecycle] = frozenset(
    {SessionLifecycle.COMPLETE, SessionLifecycle.FAILED}
)

#: The legal edges.  Declared rather than inferred so an illegal move is a loud refusal
#: instead of a state nobody can explain afterwards.  Every terminal state is reachable
#: from every working state, because timeouts and a lost lease are always possible.
_LEGAL_TRANSITIONS: dict[SessionLifecycle, frozenset[SessionLifecycle]] = {
    SessionLifecycle.CREATED: frozenset({SessionLifecycle.PREPARING, SessionLifecycle.FAILED}),
    SessionLifecycle.PREPARING: frozenset({SessionLifecycle.RUNNING, SessionLifecycle.WAITING,
                                           SessionLifecycle.YIELDING, SessionLifecycle.FAILED}),
    SessionLifecycle.RUNNING: frozenset({SessionLifecycle.VERIFYING, SessionLifecycle.WAITING,
                                         SessionLifecycle.RECOVERING, SessionLifecycle.YIELDING,
                                         SessionLifecycle.COMPLETE, SessionLifecycle.FAILED}),
    SessionLifecycle.VERIFYING: frozenset({SessionLifecycle.RUNNING, SessionLifecycle.RECOVERING,
                                           SessionLifecycle.WAITING, SessionLifecycle.COMPLETE,
                                           SessionLifecycle.FAILED}),
    SessionLifecycle.WAITING: frozenset({SessionLifecycle.RUNNING, SessionLifecycle.YIELDING,
                                         SessionLifecycle.COMPLETE, SessionLifecycle.FAILED}),
    SessionLifecycle.YIELDING: frozenset({SessionLifecycle.FAILED}),
    SessionLifecycle.RECOVERING: frozenset({SessionLifecycle.RUNNING, SessionLifecycle.WAITING,
                                            SessionLifecycle.YIELDING, SessionLifecycle.COMPLETE,
                                            SessionLifecycle.FAILED}),
    SessionLifecycle.COMPLETE: frozenset(),
    SessionLifecycle.FAILED: frozenset(),
}


class IllegalSessionTransition(RuntimeError):
    """Raised when a caller asks for an edge the lifecycle does not have."""


# ----------------------------------------------------------------------- step outcome

class StepOutcome(str, Enum):
    """The five unified step results.  ``AMBIGUOUS`` is not a synonym for ``FAILED``.

    The distinction is load-bearing: an ambiguous step means the client did not answer
    clearly enough to judge (a frame that could not be read, a page still animating), and
    the correct response is to look again.  A failed step means the client answered and
    the answer was no, and the correct response is the adapter's recovery.  Collapsing the
    two would either retry a real failure forever or give up on an unread frame.
    """

    SUCCESS = "SUCCESS"
    PROGRESS = "PROGRESS"
    STILL_PENDING = "STILL_PENDING"
    AMBIGUOUS = "AMBIGUOUS"
    FAILED = "FAILED"


#: Outcomes that mean "the step moved the session toward its completion predicate".
_ACCEPTED: frozenset[StepOutcome] = frozenset({StepOutcome.SUCCESS, StepOutcome.PROGRESS})

#: The engine's own failure names.  Distinct strings for distinct root causes (§6): a
#: session that ran out of steps is not a session that lost the device.
SESSION_LEASE_LOST = "SESSION_LEASE_LOST"
SESSION_TIMEOUT = "SESSION_STEP_BUDGET_EXHAUSTED"
SESSION_TIME_BUDGET_EXHAUSTED = "SESSION_TIME_BUDGET_EXHAUSTED"
SESSION_RESOURCE_BUDGET_EXHAUSTED = "SESSION_RESOURCE_BUDGET_EXHAUSTED"
SESSION_NO_STEP_PRODUCED = "SESSION_NO_STEP_PRODUCED"
SESSION_STEP_NOT_VERIFIED = "SESSION_STEP_NOT_VERIFIED"
SESSION_OBSERVE_FAILED = "SESSION_OBSERVE_FAILED"
SESSION_PREPARE_REFUSED = "SESSION_PREPARE_REFUSED"
SESSION_DOMAIN_STUCK = "SESSION_DOMAIN_STUCK"


# ------------------------------------------------------------------------------ types

@dataclass(frozen=True)
class SessionSpec:
    """Everything the engine needs to bound a session.  Declared by the adapter's owner.

    ``step_budget`` and ``time_budget_s`` are *ceilings*, not targets: a session that
    finishes in two steps of a twelve-step budget is complete, not short.  The budgets
    exist so a session can never become a second runtime loop that outlives the round.

    ``resource_budget`` is a floor map, not a cost map: ``{"stamina": 30}`` means "stop
    before the next step if stamina has fallen below 30".  Floors rather than deltas
    because a delta needs a baseline the reader must trust, and the client's own reading
    is the only value that cannot drift.
    """

    goal_id: str
    adapter: str
    skill_id: str = ""
    role_id: str = ""
    session_id: str = ""
    step_budget: int = 8
    time_budget_s: float = 180.0
    resource_budget: Mapping[str, float] = field(default_factory=dict)
    max_semantic_retries: int = 2
    max_recoveries: int = 2
    max_ambiguous_retries: int = 2
    #: How long a WAITING session may wait for its domain to become actionable before it
    #: gives the device back.  A session that waits forever is a scheduler that dropped
    #: out of the loop, which is exactly what constraint 8 forbids.
    max_wait_s: float = 45.0
    #: How many rungs of ``loop_detector.RECOVERY_LADDER`` one session may spend on loops.
    #: A fourth budget alongside the three retry budgets, deliberately separate: a step that
    #: fails twice and a step that is issued a *third identical time* are different facts,
    #: and one counter cannot bound both without making the loop remedy depend on the retry
    #: budget's value.  Default covers the whole ladder (6 rungs in, `defer_goal` out).
    max_loop_recoveries: int = 6
    #: The fixed class the yield oracle must report for a preemption to be accepted.
    yield_classes: tuple[str, ...] = ("HARD_EVENT_PREEMPT", "EVENT_DEADLINE", "OPERATOR",
                                      "FATAL", "RECOVERY")

    def __post_init__(self) -> None:
        if not str(self.goal_id or "").strip():
            raise ValueError("a session must be bound to a Goal; it may not choose one")
        if not str(self.adapter or "").strip():
            raise ValueError("a session must name its adapter")
        object.__setattr__(self, "step_budget", max(1, int(self.step_budget or 1)))
        object.__setattr__(self, "time_budget_s", max(0.1, float(self.time_budget_s or 0.1)))
        object.__setattr__(self, "max_semantic_retries", max(0, int(self.max_semantic_retries or 0)))
        object.__setattr__(self, "max_recoveries", max(0, int(self.max_recoveries or 0)))
        object.__setattr__(self, "max_ambiguous_retries", max(0, int(self.max_ambiguous_retries or 0)))
        object.__setattr__(self, "max_wait_s", max(0.0, float(self.max_wait_s or 0.0)))
        object.__setattr__(self, "max_loop_recoveries", max(0, int(self.max_loop_recoveries or 0)))
        object.__setattr__(self, "goal_id", str(self.goal_id))
        object.__setattr__(self, "adapter", str(self.adapter))
        object.__setattr__(self, "skill_id", str(self.skill_id or ""))
        object.__setattr__(self, "role_id", str(self.role_id or ""))
        object.__setattr__(self, "session_id", str(self.session_id or f"S{xuid()}"))


def xuid() -> str:
    """A short unique tail.  ``uuid4`` rather than a counter: a counter that resets per
    process would let two processes name two different sessions identically, and the
    episode linkage is a durable key."""
    return uuid.uuid4().hex[:10].upper()


@dataclass(frozen=True)
class SessionContext:
    """The session's binding facts.  Frozen on purpose — a session cannot re-bind itself
    to another role or another Goal part-way through; that would be the second scheduler
    the directive forbids."""

    spec: SessionSpec
    run_id: str = ""
    episode_prefix: str = ""
    started_at: float = field(default_factory=time.monotonic)
    #: The Goal's own deadline, as the Goal Library expressed it (``remaining_seconds``).
    #: ``None`` means the Goal carries no deadline, which is different from "0 seconds
    #: left" — an absent deadline must never read as an expired one.
    goal_deadline_s: float | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)

    @property
    def goal_id(self) -> str:
        return self.spec.goal_id

    @property
    def role_id(self) -> str:
        return self.spec.role_id

    @property
    def session_id(self) -> str:
        return self.spec.session_id

    def elapsed_s(self, now: float | None = None) -> float:
        return max(0.0, (now if now is not None else time.monotonic()) - self.started_at)

    def remaining_goal_seconds(self, now: float | None = None) -> float | None:
        if self.goal_deadline_s is None:
            return None
        return self.goal_deadline_s - self.elapsed_s(now)


# ------------------------------------------------------------------ step vocabulary
#
# A session step is one atomic move inside the Goal.  Four kinds is the whole list, and
# each exists because a real adapter needed exactly it.  Nothing here is a coordinate:
# every kind resolves its target from the CURRENT frame, which is what keeps 宪法 A true
# on the session path too.

#: A registered Skill, dispatched through the one Executor exactly as the Scheduler would.
STEP_SKILL = "SKILL"
#: Tap the UI element the client's own printed words name on the current frame.
STEP_PRINTED_TAP = "PRINTED_TAP"
#: Tap a semantic control the runtime's resolver knows (dictionary / page model).
STEP_SEMANTIC_TAP = "SEMANTIC_TAP"
#: Hand the device to a realtime closed-loop controller (the visual servo).  The ADAPTER
#: owns the detector and the controller; the HOST owns the touch mechanics and the frame
#: rate.  This is the one kind under which hundreds of frames pass with no scheduler
#: contact at all, which is exactly why 「实时控制循环不得调用 Global Scheduler」 holds.
STEP_REALTIME = "REALTIME"
#: Look only.  Spends a step so the session can re-read its domain without acting.
STEP_OBSERVE_ONLY = "OBSERVE_ONLY"

STEP_KINDS: tuple[str, ...] = (STEP_SKILL, STEP_PRINTED_TAP, STEP_SEMANTIC_TAP,
                               STEP_REALTIME, STEP_OBSERVE_ONLY)


@dataclass(frozen=True)
class RealtimeControl:
    """What a ``STEP_REALTIME`` step hands the host.

    The division is the point: the **adapter** owns the detector (what to look at) and the
    controller (what to do with what it saw) — that is domain knowledge.  The **host** owns
    the device: the touch mechanics, the frame rate, the guaranteed finger release.  Neither
    can do the other's job, and neither needs to know the other's internals.

    ``start_words`` is the honest way to dismiss a start prompt: the host taps the control
    the client's own words name on the current frame, and if no such word is printed it
    waits and then reports that the line never appeared.  It never taps a remembered point.
    """

    detector: Callable[[Any], Any]
    controller: Callable[[Any], Any]
    config: Any = None
    max_seconds: float = 30.0
    #: How long the host may wait for the observable to actually appear before calling the
    #: step a failure.  Distinct from ``max_seconds`` (the control budget) because the
    #: waiting happens before a single frame of control is issued.
    wait_for_line_s: float = 45.0
    start_words: tuple[str, ...] = ()
    #: Frame predicate the host polls to dismiss the start prompt.  ``None`` means the
    #: detector's own ``found`` flag is used.
    start_signal: Callable[[Any], bool] | None = None
    #: Stop the moment the observable has been gone for this many consecutive frames: that
    #: is what "the level ended" looks like from the control loop's side.
    lost_ticks_to_end: int = 16


@dataclass(frozen=True)
class SessionStep:
    """One atomic move *inside* the Goal.

    ``kind`` says how the host should carry it out, ``skill_id`` / ``target`` say what.
    A ``STEP_SKILL`` names an existing registered skill, so one MAA Executor and one
    Verifier set serve both the scheduler's steps and the session's.
    """

    index: int
    kind: str = STEP_SKILL
    skill_id: str = ""
    target: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    expected: str = ""
    reason: str = ""
    #: Free-form tags the adapter uses to describe the step to the engine and to the
    #: episode (the fishing phase, the barracks name, the rally id).  Never a coordinate.
    tags: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"unknown session step kind {self.kind!r}; "
                             f"expected one of {list(STEP_KINDS)}")
        if self.kind == STEP_SKILL and not str(self.skill_id or "").strip():
            raise ValueError("a SKILL step must name a registered skill")
        if self.kind in (STEP_PRINTED_TAP, STEP_SEMANTIC_TAP) and not str(self.target or "").strip():
            raise ValueError(f"a {self.kind} step must name the control it wants")

    def label(self) -> str:
        return self.target or self.skill_id or self.kind


@dataclass(frozen=True)
class StepExecution:
    """What the host's single executor actually did for one step."""

    executed: bool
    reason: str = ""
    before: Any = None
    after: Any = None
    backend: str = ""
    latency_ms: float | None = None
    tap_point: tuple[int, int] | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepVerdict:
    """The adapter's local verifier answer for one step."""

    outcome: StepOutcome
    reason: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)
    #: Goal-level progress, when the adapter can actually tell.  ``None`` means "the adapter
    #: did not say", and the loop detector then falls back to the step's own outcome.
    #:
    #: The two are not the same fact, and LOOP_DETECTOR_V1's no-progress pattern needs the
    #: difference: a daily-reward cycle in production has every tap *verified* (``SUCCESS``)
    #: while ``goal_progress`` stayed False for the whole cycle, which the step outcome alone
    #: reads as progress and therefore as honest work.  Only the domain knows whether a meter
    #: moved, so the domain is asked -- and an adapter with nothing to say says nothing.
    progress: bool | None = None


@dataclass(frozen=True)
class StepReport:
    """The row the engine hands to the host for the episode stream."""

    session_id: str
    goal_id: str
    role_id: str
    index: int
    skill_id: str
    outcome: str
    reason: str
    executed: bool
    backend: str
    latency_ms: float | None
    tap_point: tuple[int, int] | None
    semantic_retries: int = 0
    lifecycle: str = SessionLifecycle.RUNNING.value
    kind: str = STEP_SKILL
    target: str = ""
    tags: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    before: Any = None
    after: Any = None

    def as_row(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "role_id": self.role_id,
            "step_index": self.index,
            "kind": self.kind,
            "skill": self.skill_id,
            "target": self.target or None,
            "outcome": self.outcome,
            "reason": self.reason,
            "executed": bool(self.executed),
            "backend": self.backend,
            "latency_ms": self.latency_ms,
            "tap_point": list(self.tap_point) if self.tap_point else None,
            "semantic_retries": self.semantic_retries,
            "lifecycle": self.lifecycle,
            "tags": dict(self.tags or {}),
        }


@dataclass(frozen=True)
class YieldVerdict:
    """The Global Scheduler's answer to "may this session keep the device?".

    Only the Scheduler produces one.  The engine's job is to *ask at a safe point* and to
    obey — which is the whole of constraint 6.  ``reason_class`` is the directive §17
    vocabulary, so a yield is reported in the same words a role switch is.
    """

    yield_now: bool
    reason: str = ""
    reason_class: str = ""
    next_action_at: str | None = None

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return bool(self.yield_now)


@dataclass
class SessionState:
    """The running bookkeeping.  One instance per session; never persisted as truth."""

    lifecycle: SessionLifecycle = SessionLifecycle.CREATED
    steps_used: int = 0
    verified_steps: int = 0
    semantic_retries: int = 0
    recoveries: int = 0
    ambiguous_retries: int = 0
    observes: int = 0
    waits: int = 0
    #: Steps whose verdict was ``STILL_PENDING``: the client was asked to finish and did not.
    #: Counted separately from ``observes`` because they answer different questions, and
    #: separately from ``loop_recoveries`` because a pending step is *not* a detected loop --
    #: it is honest work in flight.  Measured 2026-09-30: the fishing wait spends one step of
    #: the budget per look with no delay between looks, so ten looks cost 0.3 s of a 150 s
    #: budget and the session dies at the step ceiling with every counter still reading zero.
    #: A count is the precondition for a bound; without it "how long may this stay pending"
    #: has no answer a run can be held to.
    still_pending: int = 0
    #: Rungs of the recovery ladder this session has spent.  Kept here rather than inside
    #: the detector because it bounds a *session*; the detector owns which rung is next.
    loop_recoveries: int = 0
    #: LOOP_DETECTOR_V1.  One per session by construction -- ``run`` builds a fresh
    #: ``SessionState``, so a Goal that looped cannot leave its rung index for the next
    #: Goal's session to start from.
    loop: LoopDetector = field(default_factory=LoopDetector)
    #: Why the session stopped, in the engine's own vocabulary.  Empty while running.
    failure: str = ""
    yield_reason: str = ""
    yield_class: str = ""
    history: list[tuple[str, str]] = field(default_factory=list)
    episodes: list[str] = field(default_factory=list)

    def move(self, target: SessionLifecycle) -> None:
        if target is self.lifecycle:
            return
        allowed = _LEGAL_TRANSITIONS[self.lifecycle]
        if target not in allowed:
            raise IllegalSessionTransition(
                f"{self.lifecycle.value} -> {target.value} is not a legal session edge"
            )
        self.history.append((self.lifecycle.value, target.value))
        self.lifecycle = target

    @property
    def terminal(self) -> bool:
        return self.lifecycle in TERMINAL_LIFECYCLES


@dataclass(frozen=True)
class SessionResult:
    """What the runtime gets back.  Always produced — a session never raises out."""

    session_id: str
    goal_id: str
    role_id: str
    lifecycle: SessionLifecycle
    outcome: str
    reason: str
    steps: tuple[StepReport, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    episode_ids: tuple[str, ...] = ()
    yield_reason: str = ""
    yield_class: str = ""

    @property
    def completed(self) -> bool:
        return self.lifecycle is SessionLifecycle.COMPLETE

    @property
    def yielded(self) -> bool:
        return self.lifecycle is SessionLifecycle.YIELDING

    @property
    def failed(self) -> bool:
        return self.lifecycle is SessionLifecycle.FAILED

    def as_row(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "goal_id": self.goal_id,
            "role_id": self.role_id,
            "lifecycle": self.lifecycle.value,
            "outcome": self.outcome,
            "reason": self.reason,
            "steps": len(self.steps),
            "verified": self.metrics.get("SESSION_VERIFIED_STEPS"),
            "yield_reason": self.yield_reason or None,
            "yield_class": self.yield_class or None,
            "metrics": dict(self.metrics),
        }


# ------------------------------------------------------------------- the host bridge

@runtime_checkable
class SessionHost(Protocol):
    """The narrow surface the engine is allowed to touch.

    Deliberately small.  There is no ``select_goal`` and no ``switch_role`` in it, so the
    "session must not decide globally" rule is enforced by the *type*, not by discipline.
    """

    def now(self) -> float:
        """Monotonic seconds."""

    def sleep(self, seconds: float) -> None:
        """The runtime's own sleeper, so a session is interruptible the same way a step is."""

    def capture(self) -> Any:
        """One frame.  Cheap path only — used by realtime adapters, never OCR'd here."""

    def ocr(self, frame: Any = None, *, region: tuple[float, float, float, float] | None = None
            ) -> list[dict[str, Any]]:
        """Read the necessary text off a frame (or one region of it).

        The directive's split: OCR is for the words a step cannot be judged without
        (bait, points, depth, a button's own label) and is never used to locate a pixel
        target when a template or feature can.  ``region`` is normalised ``(x0, y0, x1, y1)``
        so an adapter can read a HUD corner without paying for the whole frame.
        """

    def device(self) -> Any:
        """The raw touch/press device a realtime controller drives.

        Exposed because the visual servo needs ``touch_down`` / ``touch_move`` /
        ``touch_up``.  It is a capability, not a decision: nothing about *what* to do
        comes from here.
        """

    def observe(self, phase: str) -> Any:
        """The runtime's existing observation (full WorldState).  Safe points only."""

    def widen(self, phase: str = "loop_widen") -> Any:
        """Look again with every expensive sweep allowed, and hand back a fresh WorldState.

        LOOP_DETECTOR_V1's ``widen_observe`` rung.  It is the *same* observation the runtime
        already performs when a focused look leaves a frame unnamed -- one flag on one code
        path, not a second reader.  A host that cannot widen (a replay harness, a unit test)
        simply omits this method and the rung degrades to a plain re-observe; the engine asks
        with ``getattr`` rather than by catching ``TypeError``, because a ``TypeError`` from
        inside a real observation must not be misread as "this host cannot widen".
        """

    def execute_step(self, step: SessionStep) -> StepExecution:
        """Run one atomic skill through the single Executor + ExecutorRouter."""

    def verify_step(self, step: SessionStep, execution: StepExecution) -> Any:
        """Judge one atomic skill and hand back the runtime's own verdict object.

        Deliberately **not** a ``StepVerdict``: this is the transport's view -- the
        registered verifier the runtime already owns for that skill, or ``None`` when it
        has none.  Mapping that onto the five unified outcomes is the *adapter's*
        decision (``SessionAdapter.verify_step``), because only the domain knows whether
        a verdict means "one more march is fine" or "that join did not happen".
        """

    def record_step(self, report: StepReport) -> str | None:
        """Append the step to the episode stream.  Returns the episode id, if any."""

    def yield_verdict(self, context: SessionContext, steps_used: int) -> YieldVerdict:
        """Ask the Global Scheduler, at a safe point, whether to hand the device back."""

    def resource_state(self) -> Mapping[str, Any]:
        """Current readings for the spec's resource floors.  Missing keys are unknown."""

    def lease_ok(self) -> bool:
        """True while this process still owns the device lease."""

    def note(self, event: str, **fields: Any) -> None:
        """One narration line.  Diagnostics only; must never alter the outcome."""


# --------------------------------------------------------------------------- the engine

class SessionEngine:
    """Runs one Goal's internal sequence, then returns to the Global Scheduler.

    The class is deliberately stateless between sessions: everything a session knows lives
    in the ``SessionContext`` + ``SessionState`` pair it is handed for that call, so a
    second session cannot inherit the first one's counts.
    """

    #: Emitted through ``host.note`` at the two ends of every session, so a production
    #: log answers "which goal ran a session and how did it end" without a report.
    START_EVENT = "session_start"
    END_EVENT = "session_end"
    #: The registered atomic skill the ladder's HOME rung dispatches.  Named here so the rung
    #: goes through ``host.execute_step`` like any other step -- one executor, not a second
    #: navigation path.
    HOME_SKILL = "OPEN_HOME"

    def run(self, context: SessionContext, adapter: "SessionAdapter", host: SessionHost) -> SessionResult:
        spec = context.spec
        state = SessionState()
        steps: list[StepReport] = []
        started = host.now()
        hz_marks: list[float] = []
        host.note(self.START_EVENT, session_id=spec.session_id, goal_id=spec.goal_id,
                  adapter=spec.adapter, role_id=spec.role_id,
                  step_budget=spec.step_budget, time_budget_s=spec.time_budget_s)

        def finish(outcome: str, reason: str) -> SessionResult:
            # The metrics block is diagnostics.  A defect in it must never be the reason a
            # session's outcome is lost, so it degrades to the facts the result already has.
            try:
                metrics = self._metrics(context, state, started, host.now(), hz_marks)
            except Exception as exc:  # noqa: BLE001
                metrics = {"SESSION_METRICS_ERROR": f"{type(exc).__name__}:{exc}",
                           "SESSION_LIFECYCLE": state.lifecycle.value}
            result = SessionResult(
                session_id=spec.session_id, goal_id=spec.goal_id, role_id=spec.role_id,
                lifecycle=state.lifecycle, outcome=outcome, reason=reason,
                steps=tuple(steps), metrics=metrics, episode_ids=tuple(state.episodes),
                yield_reason=state.yield_reason, yield_class=state.yield_class,
            )
            host.note(self.END_EVENT, session_id=spec.session_id, goal_id=spec.goal_id,
                      lifecycle=state.lifecycle.value, outcome=outcome, reason=reason,
                      steps=state.steps_used, verified=state.verified_steps,
                      duration_ms=metrics.get("SESSION_DURATION_MS"))
            return result

        try:
            # ---- PREPARING ------------------------------------------------------------
            state.move(SessionLifecycle.PREPARING)
            if not host.lease_ok():
                state.move(SessionLifecycle.FAILED)
                state.failure = SESSION_LEASE_LOST
                return finish(StepOutcome.FAILED.value, SESSION_LEASE_LOST)
            verdict = adapter.prepare(context, host)
            if verdict is not None and verdict.outcome is StepOutcome.FAILED:
                state.move(SessionLifecycle.FAILED)
                state.failure = SESSION_PREPARE_REFUSED
                return finish(verdict.outcome.value, verdict.reason or SESSION_PREPARE_REFUSED)

            # ---- RUNNING --------------------------------------------------------------
            state.move(SessionLifecycle.RUNNING)
            while True:
                # Budgets first: three ways out, each with its own name.
                if state.steps_used >= spec.step_budget:
                    state.move(SessionLifecycle.FAILED)
                    state.failure = SESSION_TIMEOUT
                    return finish(StepOutcome.FAILED.value, SESSION_TIMEOUT)
                if context.elapsed_s(host.now()) >= spec.time_budget_s:
                    state.move(SessionLifecycle.FAILED)
                    state.failure = SESSION_TIME_BUDGET_EXHAUSTED
                    return finish(StepOutcome.FAILED.value, SESSION_TIME_BUDGET_EXHAUSTED)
                if not host.lease_ok():
                    state.move(SessionLifecycle.FAILED)
                    state.failure = SESSION_LEASE_LOST
                    return finish(StepOutcome.FAILED.value, SESSION_LEASE_LOST)

                # ---- the safe point ---------------------------------------------------
                # The ONLY place the session speaks to the Global Scheduler, and it speaks
                # only to ask permission.  Between safe points a realtime adapter may run
                # hundreds of frames without the scheduler being consulted at all, which
                # is what makes 「实时控制循环不得调用 Global Scheduler」 true.
                yielding = self._check_yield(context, state, host)
                if yielding is not None:
                    state.move(SessionLifecycle.YIELDING)
                    state.yield_reason = yielding.reason
                    state.yield_class = yielding.reason_class
                    return finish(SessionLifecycle.YIELDING.value, yielding.reason)

                # ---- domain observation ----------------------------------------------
                domain = self._observe(context, state, adapter, host)
                if domain is None:
                    state.move(SessionLifecycle.FAILED)
                    state.failure = SESSION_OBSERVE_FAILED
                    return finish(StepOutcome.FAILED.value, SESSION_OBSERVE_FAILED)

                done, done_reason = self._is_complete(context, adapter, host, domain)
                if done:
                    state.move(SessionLifecycle.COMPLETE)
                    return finish(StepOutcome.SUCCESS.value, done_reason or "SESSION_COMPLETE")

                # ---- choose the next step --------------------------------------------
                step = adapter.choose_step(context, host, domain)
                if step is None:
                    # The domain has nothing to do yet.  WAITING is a real state, not a
                    # failure, but it is bounded: a session that waits forever has stopped
                    # being a session and become a second runtime loop.
                    waited = self._wait_for_work(context, state, adapter, host, done_reason)
                    if waited is not None:
                        # The wait's ending is the *session's* ending, not a step: nothing was
                        # chosen and nothing was dispatched, so it goes in neither ``steps``
                        # nor the episode stream.  Its outcome/reason travel out through
                        # ``finish`` and the ``END_EVENT`` note.  (It did briefly go in both,
                        # which made a session that never acted report a step with an empty
                        # skill id and a SUCCESS outcome -- a fabricated step, which is worse
                        # than a missing one.)
                        return finish(waited.outcome, waited.reason)
                    continue

                step = replace(step, index=state.steps_used + 1)

                # ---- resource floor ---------------------------------------------------
                blocked = self._resource_refusal(context, host, step)
                if blocked:
                    state.move(SessionLifecycle.FAILED)
                    state.failure = SESSION_RESOURCE_BUDGET_EXHAUSTED
                    return finish(StepOutcome.FAILED.value, blocked)

                # ---- execute + verify, with the three bounded retry budgets -----------
                outcome, report = self._run_one_step(context, state, adapter, host, step)
                steps.append(report)
                self._record(context, state, host, report)
                hz_marks.append(host.now())
                if report.lifecycle == SessionLifecycle.RUNNING.value:
                    state.move(SessionLifecycle.RUNNING)
                    continue
                if report.lifecycle == SessionLifecycle.COMPLETE.value:
                    state.move(SessionLifecycle.COMPLETE)
                    return finish(outcome.value, report.reason)
                state.move(SessionLifecycle.FAILED)
                state.failure = report.reason or SESSION_STEP_NOT_VERIFIED
                return finish(outcome.value, state.failure)
        except IllegalSessionTransition as exc:  # pragma: no cover - a programming error
            state.lifecycle = SessionLifecycle.FAILED
            state.failure = f"ILLEGAL_TRANSITION:{exc}"
            return finish(StepOutcome.FAILED.value, state.failure)
        except Exception as exc:  # noqa: BLE001
            # Constraint: a session failure must never take the runtime down.  The name of
            # the exception is kept so the failure is diagnosable from the run alone.
            state.lifecycle = SessionLifecycle.FAILED
            state.failure = f"SESSION_RAISED:{type(exc).__name__}:{exc}"
            return finish(StepOutcome.FAILED.value, state.failure)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _record(context: SessionContext, state: SessionState, host: SessionHost,
                report: StepReport) -> None:
        """Hand one step to the host's episode stream, then remember its id.

        Declared in the protocol as "Episode关联" and, until now, never called: a session
        ran a full cast and left no row behind, so the only evidence of a session step was
        the session's own metrics.  Wrapped, because a host that cannot write an episode
        must not turn a step's outcome into a session failure -- the episode is evidence
        *of* the step, not the step.
        """
        try:
            episode_id = host.record_step(report)
        except Exception:  # noqa: BLE001
            episode_id = None
        if episode_id:
            state.episodes.append(str(episode_id))

    def _check_yield(self, context: SessionContext, state: SessionState,
                     host: SessionHost) -> YieldVerdict | None:
        """Ask the Global Scheduler.  Only its own classes are honoured.

        A host that has no oracle (a replay harness, a unit test) says "no" by returning an
        empty verdict, and the session keeps the device — the safe default, because the
        alternative would be a session that yields on every step.

        This is asked at *every* safe point, the one before the first step included, and
        there is deliberately no "is this the first step" argument.  One was carried here
        and never read, which was worse than useless: a reader would take it as a licence
        for a session to act before ever offering the device back, and a hard event that
        arrives between the lease and the first tap is exactly the case 抢占 has to cover.
        Where the oracle genuinely cannot answer yet -- the runtime builds its Scheduler
        lazily, so a run's very first session meets one that has not arbitrated anything --
        the protocol's own answer for "no oracle" applies: an empty verdict, so the session
        keeps the device.  That boundary belongs to the host, not to a flag here.
        """
        try:
            verdict = host.yield_verdict(context, state.steps_used)
        except Exception:  # noqa: BLE001 - an oracle that raises must not strand a session
            return None
        if verdict is None or not verdict.yield_now:
            return None
        allowed = tuple(context.spec.yield_classes)
        if verdict.reason_class and allowed and verdict.reason_class not in allowed:
            # A yield the directive does not recognise is not a licence to drop the work.
            return None
        return verdict

    def _observe(self, context: SessionContext, state: SessionState, adapter: "SessionAdapter",
                 host: SessionHost) -> Any:
        """One domain observation, retried a bounded number of times.

        ``None`` from the adapter means "I could not read my domain this time", which is a
        retry, not a verdict.  The bound exists so an unreadable screen cannot burn the
        session's whole time budget one sleep at a time.
        """
        attempts = max(1, int(context.spec.max_ambiguous_retries) + 1)
        for attempt in range(attempts):
            state.observes += 1
            try:
                domain = adapter.observe(context, host)
            except Exception:  # noqa: BLE001 - an adapter bug is the session's failure, not AUTO's
                domain = None
            if domain is not None:
                return domain
            if attempt + 1 < attempts:
                host.sleep(0.4)
        return None

    @staticmethod
    def _is_complete(context: SessionContext, adapter: "SessionAdapter", host: SessionHost,
                     domain: Any) -> tuple[bool, str]:
        try:
            answer = adapter.is_complete(context, host, domain)
        except Exception:  # noqa: BLE001
            return False, ""
        if isinstance(answer, tuple):
            return bool(answer[0]), str(answer[1] if len(answer) > 1 else "")
        return bool(answer), ""

    def _wait_for_work(self, context: SessionContext, state: SessionState,
                       adapter: "SessionAdapter", host: SessionHost,
                       why: str) -> StepReport | None:
        """Bounded WAITING.  Returns a terminal report when the wait is over, else None.

        Every exit moves the *state* to match the report it returns.  Leaving ``state`` on
        ``WAITING`` while the report said ``COMPLETE`` made ``SessionResult.completed`` False
        for a session that had in fact finished its work -- the report and the lifecycle are
        two views of one fact and they are kept in step here.

        ``kind`` is deliberately **empty** on every report this method returns: no step was
        chosen, so a report carrying the default ``SKILL`` kind would read downstream as a
        skill step with no skill.  The list of steps stays the list of things that were
        actually attempted.
        """
        state.move(SessionLifecycle.WAITING)
        state.waits += 1
        deadline = host.now() + max(0.0, float(context.spec.max_wait_s))
        while host.now() < deadline:
            host.sleep(min(0.5, max(0.05, deadline - host.now())))
            if not host.lease_ok():
                state.move(SessionLifecycle.FAILED)
                state.failure = SESSION_LEASE_LOST
                return StepReport(
                    session_id=context.session_id, goal_id=context.goal_id,
                    role_id=context.role_id, index=state.steps_used,
                    skill_id="", outcome=StepOutcome.FAILED.value, reason=SESSION_LEASE_LOST,
                    executed=False, backend="", latency_ms=None, tap_point=None,
                    lifecycle=SessionLifecycle.FAILED.value, kind="")
            domain = self._observe(context, state, adapter, host)
            if domain is None:
                continue
            done, done_reason = self._is_complete(context, adapter, host, domain)
            if done:
                state.move(SessionLifecycle.COMPLETE)
                return StepReport(
                    session_id=context.session_id, goal_id=context.goal_id,
                    role_id=context.role_id, index=state.steps_used,
                    skill_id="", outcome=StepOutcome.SUCCESS.value,
                    reason=done_reason or "SESSION_COMPLETE", executed=False, backend="",
                    latency_ms=None, tap_point=None,
                    lifecycle=SessionLifecycle.COMPLETE.value, kind="")
            if adapter.choose_step(context, host, domain) is not None:
                state.move(SessionLifecycle.RUNNING)
                return None
        # The wait produced nothing.  This is the engine's own name for it -- not the domain
        # declining (that is a verifier's job) -- so the caller can tell "nothing was there"
        # from "the client said no" without reading the reason backwards.
        state.move(SessionLifecycle.FAILED)
        state.failure = why or SESSION_NO_STEP_PRODUCED
        return StepReport(
            session_id=context.session_id, goal_id=context.goal_id, role_id=context.role_id,
            index=state.steps_used, skill_id="", outcome=StepOutcome.STILL_PENDING.value,
            reason=why or SESSION_NO_STEP_PRODUCED, executed=False, backend="",
            latency_ms=None, tap_point=None, lifecycle=SessionLifecycle.FAILED.value, kind="")

    def _resource_refusal(self, context: SessionContext, host: SessionHost,
                          step: SessionStep) -> str:
        """The spec's floors, checked against whatever the host can actually read.

        A floor whose reading is missing is NOT treated as violated.  §真值纪律: "empty ≠
        none" — an unread stamina is unknown, and refusing on an unknown would stop sessions
        the client never asked to stop.  The adapter owns the *domain* rule; this owns only
        the budget the spec declared.
        """
        floors = dict(context.spec.resource_budget or {})
        if not floors:
            return ""
        try:
            readings = dict(host.resource_state() or {})
        except Exception:  # noqa: BLE001
            return ""
        for name, floor in floors.items():
            value = _numeric(readings.get(name))
            if value is None:
                continue
            if value < float(floor):
                return f"{SESSION_RESOURCE_BUDGET_EXHAUSTED}:{name}={value:g}<{float(floor):g}"
        return ""

    def _run_one_step(self, context: SessionContext, state: SessionState,
                      adapter: "SessionAdapter", host: SessionHost,
                      step: SessionStep) -> tuple[StepOutcome, StepReport]:
        """Execute + verify one step, applying the three bounded retry budgets in order.

        * ``max_semantic_retries`` — the executor found no target for the step's control.
          Re-observe and try *the same* step again; the frame is new even when the step is
          not, which is why a second attempt is a second chance rather than a repeat.
        * ``max_ambiguous_retries`` — the client did not answer clearly.  Look again.
        * ``max_recoveries`` — the client answered "no".  Hand it to the adapter's recovery,
          which is domain knowledge the engine does not have.
        """
        semantic_retries = 0
        ambiguous_retries = 0
        recoveries = 0
        last_reason = ""
        while True:
            state.move(SessionLifecycle.RUNNING)
            state.steps_used += 1
            try:
                execution = host.execute_step(step)
            except Exception as exc:  # noqa: BLE001
                execution = StepExecution(executed=False, reason=f"STEP_RAISED:{type(exc).__name__}")
            if execution is None:
                execution = StepExecution(executed=False, reason="STEP_NO_EXECUTION")

            # A step that carries no action has no execution to be missing.  An
            # ``OBSERVE_ONLY`` step is the domain saying "I need to look again", and the look
            # is the adapter's own verifier -- so for that kind the missing-execution branch
            # does not apply, and jumping to it would fail every such step with
            # ``SESSION_STEP_NOT_VERIFIED`` while the adapter's answer was never asked for.
            needs_execution = step.kind != STEP_OBSERVE_ONLY
            if needs_execution and not execution.executed:
                last_reason = execution.reason or "STEP_NOT_EXECUTED"
                if semantic_retries < context.spec.max_semantic_retries:
                    semantic_retries += 1
                    state.semantic_retries += 1
                    host.sleep(0.3)
                    continue
                return self._terminal(context, state, StepOutcome.FAILED,
                                      f"{SESSION_STEP_NOT_VERIFIED}:{last_reason}", step,
                                      execution, semantic_retries, continues=False)

            state.move(SessionLifecycle.VERIFYING)
            try:
                # The **adapter's** verifier, not the host's.  The host owns the runtime's
                # registered atomic verdict (ground truth for one skill); the adapter owns the
                # *domain* reading of it -- how many joins, whether the cast finished, which
                # barracks are left.  Asking the host here made every adapter's own
                # ``verify_step`` dead code, which is why a bear session could never count a
                # join and a fishing session could never reach its leaving stage.
                verdict = adapter.verify_step(context, host, step, execution)
            except Exception as exc:  # noqa: BLE001
                verdict = StepVerdict(StepOutcome.AMBIGUOUS, f"VERIFIER_RAISED:{type(exc).__name__}")
            if verdict is None:
                verdict = StepVerdict(StepOutcome.AMBIGUOUS, "VERIFIER_NO_VERDICT")
            last_reason = verdict.reason or last_reason

            # ---- LOOP_DETECTOR_V1 -------------------------------------------------
            # Only *answered* attempts are shown to the detector.  ``AMBIGUOUS`` means the
            # client never answered and ``STILL_PENDING`` means honest work is in flight;
            # both already have their own bounded ladders and their own names, and feeding
            # them here would relabel "the screen was unreadable" as "the flow is looping"
            # -- a different fact with a different remedy.  A loop is an *answered* action
            # that changed nothing.
            #
            # Every answered attempt is fed, accepted or not: a success is how a pending
            # detection learns it was wrong, and dropping it here would leave every claim
            # permanently un-retracted.
            if verdict.outcome not in (StepOutcome.AMBIGUOUS, StepOutcome.STILL_PENDING):
                loop = state.loop.observe(self._signature_for(context, step, execution, verdict))
                if loop.detected:
                    state.loop_recoveries += 1
                    if loop.wants_defer or state.loop_recoveries > context.spec.max_loop_recoveries:
                        # The ladder is spent.  End the SESSION with a name the stop-reason
                        # classifier declares recoverable, so the runtime defers this Goal
                        # and AUTO continues with the next one.  A loop detector that could
                        # stop AUTO would be a second Scheduler, which this is not.
                        return self._terminal(context, state, StepOutcome.FAILED,
                                              f"{SESSION_DOMAIN_STUCK}:{loop.reason}", step,
                                              execution, semantic_retries, continues=False)
                    if self._apply_loop_rung(context, state, adapter, host, step, execution, loop):
                        continue
                    # A rung that could not be applied must never degrade into "issue the
                    # same step once more" -- that is the behaviour the detector exists to
                    # stop.  Fall through to the ordinary failure path, which ends the
                    # session instead.
                    return self._terminal(context, state, StepOutcome.FAILED,
                                          f"{SESSION_DOMAIN_STUCK}:{loop.rung}_UNAVAILABLE",
                                          step, execution, semantic_retries, continues=False)

            if verdict.outcome in _ACCEPTED:
                state.verified_steps += 1
                return self._terminal(context, state, verdict.outcome, last_reason, step,
                                      execution, semantic_retries, verdict.evidence)
            if verdict.outcome is StepOutcome.STILL_PENDING:
                # Accepted as honest work that is not finished: it counts as a step, not as a
                # success, and the session continues.  This is what a "the cast is still
                # running" answer looks like.
                state.still_pending += 1
                return self._terminal(context, state, StepOutcome.STILL_PENDING, last_reason,
                                      step, execution, semantic_retries, verdict.evidence)
            if verdict.outcome is StepOutcome.AMBIGUOUS:
                if ambiguous_retries < context.spec.max_ambiguous_retries:
                    ambiguous_retries += 1
                    state.ambiguous_retries += 1
                    host.sleep(0.4)
                    continue
                # The client kept not answering.  That is a session failure with its own
                # name -- it is not "the step failed", because no answer ever arrived.
                return self._terminal(context, state, StepOutcome.AMBIGUOUS,
                                      f"SESSION_AMBIGUOUS:{last_reason}", step, execution,
                                      semantic_retries, verdict.evidence, continues=False)

            # FAILED.  The adapter's recovery is the only thing that may answer "what now",
            # and one recovery attempt is paired with one retry: a recovery that says "the
            # domain is ready again" is a reason to try the step once more, and a recovery
            # that says anything else ends the session rather than repeating the same tap.
            if recoveries < context.spec.max_recoveries:
                recoveries += 1
                state.recoveries += 1
                state.move(SessionLifecycle.RECOVERING)
                try:
                    recovered = adapter.recover(context, host, step,
                                                StepVerdict(StepOutcome.FAILED, last_reason,
                                                            dict(verdict.evidence or {})))
                except Exception:  # noqa: BLE001
                    recovered = None
                if recovered is True:
                    continue
            break
        return self._terminal(context, state, StepOutcome.FAILED,
                              f"{SESSION_STEP_NOT_VERIFIED}:{last_reason}", step, None,
                              state.semantic_retries, continues=False)

    # ------------------------------------------------------- LOOP_DETECTOR_V1 plumbing

    @staticmethod
    def _signature_for(context: SessionContext, step: SessionStep, execution: StepExecution | None,
                       verdict: StepVerdict) -> LoopSignature:
        """One attempt, as ``loop_detector`` wants to see it: context, action, feedback.

        The state read is the *after* frame when there is one, because the question the
        detector asks is "did this action change anything"; the frame the decision was made
        on would answer "did anything change before the action", which is the wrong fact.

        ``progress`` is the *Goal*-level fact, so the adapter's own answer wins whenever it
        gave one; the step's outcome is only the fallback.  They are different questions --
        a step can succeed while the Goal stands still, and that case is precisely the one
        the no-progress pattern exists for.
        """
        state_like = getattr(execution, "after", None)
        if state_like is None:
            state_like = getattr(execution, "before", None)
        page = getattr(state_like, "page", None)
        outcome = getattr(verdict, "outcome", None)
        declared = getattr(verdict, "progress", None)
        return LoopSignature(
            role_id=str(context.role_id or ""),
            page=str(getattr(page, "value", page) or ""),
            goal_id=str(context.goal_id or ""),
            skill_id=str(getattr(step, "skill_id", "") or ""),
            semantic_target=str(getattr(step, "target", "") or ""),
            state_hash=relevant_state_hash(state_like),
            verifier_outcome=str(getattr(outcome, "value", outcome) or ""),
            progress=declared if declared is not None else progress_from_outcome(outcome),
        )

    def _apply_loop_rung(self, context: SessionContext, state: SessionState,
                         adapter: "SessionAdapter", host: SessionHost, step: SessionStep,
                         execution: StepExecution | None,
                         loop: Any) -> bool:
        """Carry out one rung of the ladder.  ``True`` means "the step may be retried".

        The ladder names the remedies; this only dispatches them onto surfaces that already
        exist.  Three of the six rungs need no new capability at all:

        * ``semantic_retry`` is the retry loop the caller is already inside;
        * ``feature_reopen`` is the adapter's own ``recover`` -- domain knowledge the engine
          does not have and must not invent;
        * ``home_recovery`` is the registered ``OPEN_HOME`` skill dispatched through
          ``host.execute_step``, i.e. the same one executor every other step uses.

        ``False`` is returned only when the host cannot do it; the caller then ends the
        session rather than repeating the step, because a remedy that silently did nothing is
        indistinguishable from no remedy at all.
        """
        rung = str(getattr(loop, "rung", "") or "")
        if rung == RUNG_SEMANTIC_RETRY:
            host.sleep(0.3)
            return True
        if rung == RUNG_LOCAL_REOBSERVE:
            return self._loop_look(host, state, "loop_reobserve", widen=False)
        if rung == RUNG_WIDEN_OBSERVE:
            return self._loop_look(host, state, "loop_widen", widen=True)
        if rung == RUNG_FEATURE_REOPEN:
            try:
                recovered = adapter.recover(context, host, step,
                                StepVerdict(StepOutcome.FAILED, loop.reason,
                                            {"loop_pattern": loop.pattern, "loop_rung": rung}))
            except Exception:  # noqa: BLE001 - an adapter bug is not a licence to repeat the tap
                return False
            return recovered is True
        if rung == RUNG_HOME_RECOVERY:
            return self._loop_home(host, step, rung)
        if rung == RUNG_DEFER_GOAL:
            # The last rung is not a remedy, it is the *ending*: the Goal goes back to the
            # Scheduler and AUTO carries on with the next one.  Named here so all six rungs of
            # ``RECOVERY_LADDER`` are accounted for in one dispatch, and so a seventh rung
            # added to the ladder fails loudly at this line instead of silently doing nothing.
            return False
        return False

    @staticmethod
    def _loop_look(host: SessionHost, state: SessionState, phase: str, *, widen: bool) -> bool:
        """Re-observe.  ``widen`` uses the host's widening look when it has one.

        A host without ``widen`` (a replay harness, a unit test) degrades to an ordinary
        observation rather than failing the rung: looking again is still strictly better than
        re-issuing the action, which is the only alternative the rung's failure would leave.
        """
        state.observes += 1
        try:
            if widen:
                usable_widen = getattr(host, "widen", None)
                if callable(usable_widen):
                    usable_widen(phase)
                    return True
            host.observe(phase)
        except Exception:  # noqa: BLE001
            return False
        return True

    def _loop_home(self, host: SessionHost, step: SessionStep, rung: str) -> bool:
        """Go HOME by dispatching the registered skill, then let the detector judge it."""
        home = SessionStep(index=step.index, kind=STEP_SKILL, skill_id=self.HOME_SKILL,
                           reason=f"loop recovery ({rung}): back to a known page")
        try:
            execution = host.execute_step(home)
        except Exception:  # noqa: BLE001
            return False
        return bool(getattr(execution, "executed", False))

    def _terminal(self, context: SessionContext, state: SessionState, outcome: StepOutcome,
                  reason: str, step: SessionStep, execution: StepExecution | None,
                  semantic_retries: int, evidence: Mapping[str, Any] | None = None,
                  *, continues: bool = True,
                  ) -> tuple[StepOutcome, StepReport]:
        """Record one step and tell the caller whether the loop continues.

        The ``lifecycle`` field of the report is how the caller learns what to do next:
        ``RUNNING`` continues and anything else ends the session.  Keeping that decision in
        the report rather than in a side-channel is deliberate — a session step and its
        verdict are one fact, and a caller that had to cross-reference two places to learn
        whether a session ended is how a step gets double-counted.

        ``continues`` is the caller's judgement, not a function of the outcome: a
        ``STILL_PENDING`` step continues (honest work, not finished) while an ``AMBIGUOUS``
        step whose retries are spent does not.
        """
        lifecycle = SessionLifecycle.RUNNING if continues else SessionLifecycle.FAILED
        report = StepReport(
            session_id=context.session_id, goal_id=context.goal_id, role_id=context.role_id,
            index=step.index if step is not None else state.steps_used,
            skill_id=getattr(step, "skill_id", ""), outcome=outcome.value, reason=reason,
            executed=bool(execution is not None and execution.executed),
            backend=getattr(execution, "backend", "") or "",
            latency_ms=getattr(execution, "latency_ms", None),
            tap_point=getattr(execution, "tap_point", None),
            semantic_retries=semantic_retries, lifecycle=lifecycle.value,
            kind=getattr(step, "kind", STEP_SKILL) or STEP_SKILL,
            target=str(getattr(step, "target", "") or ""),
            tags=dict(getattr(step, "tags", {}) or {}),
            evidence={**dict(getattr(execution, "evidence", {}) or {}), **dict(evidence or {})},
            before=getattr(execution, "before", None), after=getattr(execution, "after", None),
        )
        return outcome, report

    @staticmethod
    def _metrics(context: SessionContext, state: SessionState, started: float,
                 ended: float, hz_marks: Iterable[float]) -> dict[str, Any]:
        duration = max(0.0, ended - started)
        marks = list(hz_marks)
        gaps = [b - a for a, b in zip(marks, marks[1:]) if b > a]
        return {
            "SESSION_STEPS": state.steps_used,
            "SESSION_VERIFIED_STEPS": state.verified_steps,
            "SESSION_SEMANTIC_RETRIES": state.semantic_retries,
            "SESSION_AMBIGUOUS_RETRIES": state.ambiguous_retries,
            "SESSION_RECOVERIES": state.recoveries,
            "SESSION_OBSERVES": state.observes,
            "SESSION_WAITS": state.waits,
            # Its own line, never folded into SESSION_STEPS: a session that spent nine of its
            # ten steps waiting is a different finding from one that took ten real actions, and
            # the two were indistinguishable in the metrics block until this key existed.
            "SESSION_STILL_PENDING": state.still_pending,
            "SESSION_DURATION_MS": round(duration * 1000, 1),
            "SESSION_STEP_BUDGET": context.spec.step_budget,
            "SESSION_TIME_BUDGET_S": context.spec.time_budget_s,
            "SESSION_GOAL_DEADLINE_S": context.goal_deadline_s,
            "SESSION_MEAN_STEP_INTERVAL_MS": (round(1000 * sum(gaps) / len(gaps), 1)
                                              if gaps else None),
            "SESSION_MAX_STEP_INTERVAL_MS": round(1000 * max(gaps), 1) if gaps else None,
            "SESSION_LIFECYCLE": state.lifecycle.value,
            "SESSION_FAILURE": state.failure or None,
            "SESSION_YIELD_REASON": state.yield_reason or None,
            "SESSION_YIELD_CLASS": state.yield_class or None,
            "SESSION_TRANSITIONS": [f"{a}->{b}" for a, b in state.history],
            # LOOP_DETECTOR_V1's ledger and its Session Timeline (MAI design 4).  Spread in
            # here rather than stored separately: one session, one metrics block, so a reader
            # never has to join two tables to learn whether the session looped.
            **state.loop.summary(),
            "SESSION_LOOP_RECOVERIES": state.loop_recoveries,
        }


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


# ------------------------------------------------------------------------- the adapter

class SessionAdapter:
    """Base class for a Goal's internal behaviour.  Business knowledge lives here.

    Four responsibilities, and nothing else (operator directive, 业务Adapter负责):

    * ``observe`` — read the DOMAIN state (cheap: ROI / OpenCV / a cached row), never the
      whole world;
    * ``choose_step`` — the next local step, or ``None`` when the domain is not ready;
    * ``verify_step`` — the domain verifier, mapping the client's answer onto the five
      unified outcomes;
    * ``is_complete`` — the completion predicate, expressed in domain terms.

    An adapter has no access to the Scheduler, the Goal Library or the role controller —
    not by convention, but because ``SessionHost`` does not offer them.
    """

    #: The registry key.  ``SESSION_ROUTES`` in ``session_adapters`` maps skills to these.
    name: str = ""

    def prepare(self, context: SessionContext, host: SessionHost) -> StepVerdict | None:
        """Optional precondition work.  Return ``FAILED`` to refuse before any action."""
        return None

    def configure(self, extras: Mapping[str, Any],
                  resource_budget: Mapping[str, float] | None = None) -> None:
        """Apply the route's declaration to this fresh instance.

        Called exactly once, on a **fresh** adapter, before ``prepare``.  Freshness is a
        requirement rather than tidiness: these objects accumulate per-session counters
        (casts, joins, marches), and a reused instance would spend one session's budget on
        the next session's work.
        """
        return None

    def observe(self, context: SessionContext, host: SessionHost) -> Any:
        raise NotImplementedError

    def choose_step(self, context: SessionContext, host: SessionHost, domain: Any) -> SessionStep | None:
        raise NotImplementedError

    def is_complete(self, context: SessionContext, host: SessionHost, domain: Any) -> tuple[bool, str]:
        raise NotImplementedError

    def verify_step(self, context: SessionContext, host: SessionHost, step: SessionStep,
                    execution: StepExecution) -> StepVerdict:
        """The domain verifier, mapping the runtime's verdict onto the five outcomes.

        The default inherits the runtime's own registered verifier rather than inventing
        an opinion: an adapter that has nothing domain-specific to add should not make its
        steps look unverified.  Returning ``AMBIGUOUS`` here instead was the second
        reading of the same skill the directive forbids -- and it read to the engine as "the
        client never answered", which is a different fact from "nobody judged this".

        An adapter with domain knowledge overrides this and may still call
        ``host.verify_step`` for the runtime's ground truth; all three skill-driven
        adapters do exactly that and add their own counting on top.
        """
        try:
            verdict = host.verify_step(step, execution)
        except Exception:  # noqa: BLE001 - a broken host is not the client's answer
            return StepVerdict(StepOutcome.AMBIGUOUS, "ADAPTER_VERIFIER_RAISED")
        if verdict is None:
            return StepVerdict(StepOutcome.AMBIGUOUS, "ADAPTER_NO_HOST_VERDICT")
        ok = getattr(verdict, "ok", None)
        reason = str(getattr(verdict, "reason", "") or "")
        evidence = dict(getattr(verdict, "evidence", {}) or {})
        if ok is None:
            # A host that answered with something this layer cannot read is not a "no".
            return StepVerdict(StepOutcome.AMBIGUOUS, reason or "ADAPTER_UNREADABLE_VERDICT",
                               evidence)
        return StepVerdict(StepOutcome.SUCCESS if ok else StepOutcome.FAILED,
                           reason or ("STEP_VERIFIED" if ok else "STEP_NOT_VERIFIED"),
                           evidence)

    def recover(self, context: SessionContext, host: SessionHost, step: SessionStep,
                verdict: StepVerdict) -> bool | None:
        """Bounded recovery.  ``True`` means "the domain is ready again, continue"."""
        return None

    def budget(self, context: SessionContext) -> Mapping[str, Any]:
        """Adapter-declared budget overrides (step/time/resource).  Optional."""
        return {}


__all__ = [
    "IllegalSessionTransition", "SESSION_DOMAIN_STUCK", "SESSION_LEASE_LOST",
    "SESSION_NO_STEP_PRODUCED", "SESSION_OBSERVE_FAILED", "SESSION_PREPARE_REFUSED",
    "SESSION_RESOURCE_BUDGET_EXHAUSTED", "SESSION_STEP_NOT_VERIFIED",
    "SESSION_TIME_BUDGET_EXHAUSTED", "SESSION_TIMEOUT", "STEP_KINDS", "STEP_OBSERVE_ONLY",
    "STEP_PRINTED_TAP", "STEP_REALTIME", "STEP_SEMANTIC_TAP", "STEP_SKILL", "RealtimeControl",
    "SessionAdapter", "SessionContext", "SessionEngine", "SessionHost", "SessionLifecycle",
    "SessionResult", "SessionSpec", "SessionState", "SessionStep", "StepExecution",
    "StepOutcome", "StepReport", "StepVerdict", "TERMINAL_LIFECYCLES", "YieldVerdict", "xuid",
]
