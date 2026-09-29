"""ROLE_SESSION_POLICY -- one role keeps the device until its own batch is mostly done.

Operator directive 2026-09-30 (ROLE SESSION PRODUCTION V2).

The pre-existing guard was two knobs: ``min_role_dwell_seconds`` (120s) and
``switch_margin`` (30 points).  They stop two-minute thrash and nothing else.  Once the
dwell expired, any other role whose *ordinary* Goal happened to score ``+margin`` higher
took the device::

    ROLE_A TRAIN   = 1200
    ROLE_B RESEARCH= 1400   ->  SWITCH B

On a one-device / two-account setup that meant a switch on nearly every cycle, and every
switch costs a full logout/login plus every frame-derived value the running worker owned.

This module is a **policy layer above** that guard -- not a second scheduler and not a
second task system.  It answers exactly one question: *may the current role be left for an
ORDINARY reason right now?*  It answers it from persisted logical facts only:

* how much of this session's discovered work is already completed or started,
* how much is still READY / runnable right now,
* how many consecutive schedulings found no runnable work at all.

Limited-time work is deliberately **not** this layer's business.  ``HARD_EVENT_PREEMPT``
outranks the session and stays in the Scheduler, where the event schedule already lives.

Storage rule (directive §2): this is logical state.  It never holds a bbox, a page
coordinate, or a target read off an old frame -- only Goal *identities* and counters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------------- policy defaults

#: Directive §15's first-version parameters.  ``min_role_dwell_seconds`` rises from 120 to
#: 300 as *additional* anti-jitter only -- it is a floor, never a switching licence.
ROLE_SESSION_POLICY_DEFAULTS: dict[str, float] = {
    "mostly_done_ratio": 0.75,
    "max_ready_before_switch": 2,
    "no_work_streak_to_end_session": 2,
    "min_role_dwell_seconds": 300.0,
    "switch_margin": 30.0,
}


# ---------------------------------------------------------------- reason classes (directive §17)

SESSION_COMPLETE = "SESSION_COMPLETE"
NO_RUNNABLE_WORK = "NO_RUNNABLE_WORK"
HARD_EVENT_PREEMPT = "HARD_EVENT_PREEMPT"
RECOVERY = "RECOVERY"
OPERATOR = "OPERATOR"
ENVIRONMENT = "ENVIRONMENT"

#: Every class the operator accepts.  "higher global value" is deliberately absent: an
#: ordinary score difference is not a switch reason any more, it is only a tie-break
#: *after* the session gate has already allowed the move.
SWITCH_REASON_CLASSES: tuple[str, ...] = (
    SESSION_COMPLETE,
    NO_RUNNABLE_WORK,
    HARD_EVENT_PREEMPT,
    RECOVERY,
    OPERATOR,
    ENVIRONMENT,
)

#: Goal statuses that mean "there is something to do on this frame".
RUNNABLE_STATUSES = frozenset({"READY", "DISCOVERED", "RUNNABLE"})
#: Goal statuses that mean "counted as this session's work, but not actionable now".
WAITING_STATUSES = frozenset({"SCHEDULED_NOT_OPEN"})
BLOCKED_STATUSES = frozenset({"BLOCKED", "UNKNOWN", "DEFERRED", "WAITING_GAME_CONDITION"})
#: Goal statuses that mean "started or finished" -- the numerator of the session ratio.
SETTLED_STATUSES = frozenset({"IN_PROGRESS", "COMPLETE"})


def resolve_policy(policy: Mapping[str, Any] | None) -> dict[str, float]:
    """Merge caller overrides onto the defaults, ignoring unusable values."""
    resolved = dict(ROLE_SESSION_POLICY_DEFAULTS)
    if not isinstance(policy, Mapping):
        return resolved
    for key, fallback in ROLE_SESSION_POLICY_DEFAULTS.items():
        if key not in policy:
            continue
        raw = policy[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            continue
        try:
            resolved[key] = float(raw)
        except (TypeError, ValueError):
            continue
    return resolved


# ---------------------------------------------------------------- the logical session

@dataclass
class RoleSessionState:
    """Directive §2's logical session.  No bbox, no page coordinate, no old-frame target."""

    role_id: str = ""
    started_at: str | None = None
    goals_completed: int = 0
    actions_verified: int = 0
    ready_at_start: int = 0
    ready_now: int = 0
    runnable_now: int = 0
    waiting_now: int = 0
    blocked_now: int = 0
    capability_gap_now: int = 0
    completion_ratio: float = 0.0
    no_work_streak: int = 0
    switch_allowed: bool = False
    switch_reason: str = ""
    #: The session denominator (directive §5): every meaningful Goal this session has seen.
    #: Grows monotonically -- a newly discovered Goal joins *this* session's batch.
    session_goal_ids: list[str] = field(default_factory=list)
    #: Goals this session has seen sitting in a settled status (COMPLETE / IN_PROGRESS).
    session_done_goal_ids: list[str] = field(default_factory=list)
    #: Goals that are READY/runnable **right now**.  A Goal that was acted on and is still
    #: READY afterwards is recurring work, not consumed batch -- it is subtracted from the
    #: numerator, which is what stops a one-Goal role from reporting 100% after one tap.
    session_runnable_ids: list[str] = field(default_factory=list)
    last_evaluated_at: str | None = None

    def __post_init__(self) -> None:
        self.role_id = str(self.role_id or "").strip()
        for name in ("goals_completed", "actions_verified", "ready_at_start", "ready_now",
                     "runnable_now", "waiting_now", "blocked_now", "capability_gap_now",
                     "no_work_streak"):
            try:
                value = int(getattr(self, name) or 0)
            except (TypeError, ValueError):
                value = 0
            setattr(self, name, max(0, value))
        try:
            ratio = float(self.completion_ratio or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        self.completion_ratio = max(0.0, min(1.0, ratio))
        self.switch_allowed = bool(self.switch_allowed)
        self.switch_reason = str(self.switch_reason or "")
        self.started_at = str(self.started_at) if self.started_at else None
        self.last_evaluated_at = str(self.last_evaluated_at) if self.last_evaluated_at else None
        self.session_goal_ids = list(dict.fromkeys(
            str(item) for item in (self.session_goal_ids or ()) if item
        ))
        self.session_done_goal_ids = list(dict.fromkeys(
            str(item) for item in (self.session_done_goal_ids or ()) if item
        ))
        self.session_runnable_ids = list(dict.fromkeys(
            str(item) for item in (self.session_runnable_ids or ()) if item
        ))

    # ------------------------------------------------------------------ mutation

    def note_board(self, *, goal_ids: Iterable[str] = (),
                   settled_goal_ids: Iterable[str] = (),
                   runnable_goal_ids: Iterable[str] = ()) -> None:
        """Fold one role board into the session's (numerator, denominator) pair."""
        for goal_id in goal_ids:
            text = str(goal_id or "")
            if text and text not in self.session_goal_ids:
                self.session_goal_ids.append(text)
        for goal_id in settled_goal_ids:
            text = str(goal_id or "")
            if not text:
                continue
            if text not in self.session_goal_ids:
                self.session_goal_ids.append(text)
            if text not in self.session_done_goal_ids:
                self.session_done_goal_ids.append(text)
        # Replaced, not merged: this is "runnable at the moment of the last board", and a
        # Goal that stopped being READY must leave the set or the numerator could never
        # grow past it.
        self.session_runnable_ids = list(dict.fromkeys(
            str(item) for item in runnable_goal_ids if item
        ))
        self.recompute_ratio()

    def note_completed(self, goal_ids: Iterable[str]) -> None:
        for goal_id in goal_ids:
            text = str(goal_id or "")
            if not text:
                continue
            if text not in self.session_goal_ids:
                self.session_goal_ids.append(text)
            if text not in self.session_done_goal_ids:
                self.session_done_goal_ids.append(text)
        self.recompute_ratio()

    def consumed_goal_ids(self) -> list[str]:
        """Settled Goals that are *not* still READY -- the real numerator."""
        runnable = set(self.session_runnable_ids)
        return [goal_id for goal_id in self.session_done_goal_ids if goal_id not in runnable]

    def recompute_ratio(self) -> None:
        denominator = len(self.session_goal_ids)
        if denominator <= 0:
            self.completion_ratio = 0.0
            return
        self.completion_ratio = max(
            0.0, min(1.0, len(self.consumed_goal_ids()) / denominator),
        )

    def elapsed_seconds(self, now: datetime | None = None) -> float | None:
        start = _parse(self.started_at)
        if start is None:
            return None
        moment = now or datetime.now(timezone.utc)
        return max(0.0, (moment - start).total_seconds())

    def as_logical_row(self) -> dict[str, Any]:
        """The counter block the panel and the decision log both read."""
        return {
            "role_id": self.role_id,
            "started_at": self.started_at,
            "goals_completed": self.goals_completed,
            "actions_verified": self.actions_verified,
            "ready_at_start": self.ready_at_start,
            "ready_now": self.ready_now,
            "runnable_now": self.runnable_now,
            "waiting_now": self.waiting_now,
            "blocked_now": self.blocked_now,
            "capability_gap_now": self.capability_gap_now,
            "completion_ratio": round(self.completion_ratio, 4),
            "no_work_streak": self.no_work_streak,
            "switch_allowed": self.switch_allowed,
            "switch_reason": self.switch_reason,
            "session_goal_count": len(self.session_goal_ids),
            "session_done_goal_count": len(self.consumed_goal_ids()),
            "session_started_goal_count": len(self.session_done_goal_ids),
        }


def new_session(role_id: str, *, at: datetime | str | None = None,
                ready_at_start: int = 0) -> RoleSessionState:
    stamp = _iso(at) or _iso(datetime.now(timezone.utc))
    return RoleSessionState(role_id=str(role_id or ""), started_at=stamp,
                            ready_at_start=max(0, int(ready_at_start or 0)))


# ---------------------------------------------------------------- the gate

@dataclass(frozen=True)
class RoleSessionGate:
    """The answer to 'may the current role be left for an ordinary reason right now?'."""

    allowed: bool
    reason_class: str
    detail: str
    description: str

    @property
    def locked(self) -> bool:
        return not self.allowed


def evaluate_role_session_gate(
    session: RoleSessionState | None,
    *,
    current_role_id: str,
    runnable_now: int,
    ready_now: int,
    waiting_now: int = 0,
    blocked_now: int = 0,
    capability_gap_now: int = 0,
    policy: Mapping[str, Any] | None = None,
) -> RoleSessionGate:
    """Directive §4's ordinary-switch conditions, in priority order.

    A. the current role has nothing runnable at all; or
    C. everything left is WAITING / BLOCKED / CAPABILITY_GAP / SCHEDULED_NOT_OPEN /
       IN_PROGRESS_LONG_JOB -- which is the same fact, because none of those states is
       ever counted as runnable; or
    B. the batch is mostly done (``completion_ratio >= 0.75`` and ``ready_now <= 2``); or
    D. ``no_work_streak`` consecutive schedulings found no runnable work.

    Anything else keeps the current role.  A higher score on another role is **not** a
    condition here; it is only consulted after this gate has allowed the move.
    """
    params = resolve_policy(policy)
    mostly_done = float(params["mostly_done_ratio"])
    max_ready = int(params["max_ready_before_switch"])
    streak_needed = max(1, int(params["no_work_streak_to_end_session"]))

    runnable = max(0, int(runnable_now or 0))
    ready = max(0, int(ready_now or 0))
    waiting = max(0, int(waiting_now or 0))
    blocked = max(0, int(blocked_now or 0))
    gaps = max(0, int(capability_gap_now or 0))

    if runnable <= 0:
        parked = waiting + blocked + gaps
        detail = "NOTHING_RUNNABLE_LEFT" if parked <= 0 else "ONLY_PARKED_WORK_LEFT"
        return RoleSessionGate(
            True, NO_RUNNABLE_WORK, detail,
            f"current role has no runnable Goal ({parked} waiting/blocked/gap)",
        )

    if session is None or not session.role_id or session.role_id != str(current_role_id or ""):
        # No live session bound to this role.  Do not invent one here -- the store starts
        # it -- and do not let the absence of a session silently freeze switching.
        return RoleSessionGate(
            True, SESSION_COMPLETE, "NO_SESSION_FOR_ROLE",
            "no role session recorded for the current role yet",
        )

    if session.no_work_streak >= streak_needed:
        return RoleSessionGate(
            True, NO_RUNNABLE_WORK, "NO_WORK_STREAK",
            f"{session.no_work_streak} consecutive schedulings found no runnable work",
        )

    if session.completion_ratio >= mostly_done and ready <= max_ready:
        return RoleSessionGate(
            True, SESSION_COMPLETE, "FINISH_CURRENT_ROLE_BATCH",
            (f"role session is mostly done "
             f"({len(session.consumed_goal_ids())}/"
             f"{max(1, len(session.session_goal_ids))} = "
             f"{session.completion_ratio:.0%}) with {ready} READY left"),
        )

    return RoleSessionGate(
        False, "", "ROLE_SESSION_ACTIVE",
        (f"current role still owns {runnable} runnable Goal(s), "
         f"batch {len(session.consumed_goal_ids())}/"
         f"{max(1, len(session.session_goal_ids))} = {session.completion_ratio:.0%}"),
    )


# ---------------------------------------------------------------- reason classification

def classify_switch_reason(text: Any) -> str:
    """Fold the scheduler's free-text reason into directive §17's fixed classes."""
    blob = str(text or "").upper()
    if not blob:
        return ""
    if "HARD_EVENT_PREEMPT" in blob or "HARD DEADLINE/EVENT PHASE" in blob:
        return HARD_EVENT_PREEMPT
    if "ROLE_SESSION_END" in blob:
        if "NO_WORK_STREAK" in blob or "NO_RUNNABLE_WORK" in blob:
            return NO_RUNNABLE_WORK
        return SESSION_COMPLETE
    if "OPERATOR" in blob:
        return OPERATOR
    if "RECOVER" in blob or "IDENTITY" in blob or "REQUIRES_FRESH_OBSERVATION" in blob \
            or "GLOBAL_REFRESH" in blob:
        return RECOVERY
    if "DEVICE" in blob or "ENVIRONMENT" in blob or "CLIENT" in blob or "LOADING" in blob:
        return ENVIRONMENT
    if "NO FRESH RUNNABLE GOAL" in blob or "NO_FRESH_RUNNABLE" in blob:
        return NO_RUNNABLE_WORK
    if "ROLE_SWITCH_FAILED" in blob:
        return ENVIRONMENT
    return ""


# ---------------------------------------------------------------- quality metrics (§17)

def role_switch_quality_metrics(*, switch_history: Iterable[Mapping[str, Any]],
                                session: RoleSessionState | None = None,
                                now: datetime | None = None) -> dict[str, Any]:
    """ROLE_SWITCHES_PER_HOUR / avg session duration / avg Goals per session / reasons."""
    moment = now or datetime.now(timezone.utc)
    rows = [row for row in (switch_history or ()) if isinstance(row, Mapping)]
    stamps = [stamp for stamp in (_parse(row.get("at")) for row in rows) if stamp is not None]
    switches_per_hour: float | None = None
    if len(stamps) >= 2:
        span_hours = (max(stamps) - min(stamps)).total_seconds() / 3600.0
        switches_per_hour = (len(stamps) / span_hours) if span_hours > 0 else None
    durations = [float(row.get("duration_seconds") or 0.0) for row in rows
                 if isinstance(row.get("duration_seconds"), (int, float))
                 and float(row.get("duration_seconds") or 0.0) > 0]
    goals = [int(row.get("goals_completed") or 0) for row in rows
             if isinstance(row.get("goals_completed"), (int, float))]
    reasons = [str(row.get("reason_class") or "") or classify_switch_reason(row.get("reason"))
               for row in rows]
    return {
        "switch_sample_count": len(rows),
        "role_switches_per_hour": (round(switches_per_hour, 2)
                                   if switches_per_hour is not None else None),
        "avg_role_session_duration_seconds": (round(sum(durations) / len(durations), 1)
                                              if durations else None),
        "avg_goals_per_role_session": (round(sum(goals) / len(goals), 2) if goals else None),
        "last_switch_reasons": reasons[-10:],
        "current_session_goals_completed": (session.goals_completed if session else 0),
        "current_session_actions_verified": (session.actions_verified if session else 0),
        "current_session_seconds": (round(session.elapsed_seconds(moment), 1)
                                    if session and session.elapsed_seconds(moment) is not None
                                    else None),
    }


# ---------------------------------------------------------------- small helpers

def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def session_goal_statuses(row: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Split one role-board summary into (all meaningful ids, settled ids).

    Shared by the scheduler's ``role_statuses`` builder and the store's session refresh so
    the denominator and the numerator can never disagree about what a status means.
    """
    all_ids: list[str] = []
    done_ids: list[str] = []
    for goal in row.get("goals") or ():
        if not isinstance(goal, Mapping):
            continue
        goal_id = str(goal.get("goal_id") or "")
        if not goal_id:
            continue
        status = str(goal.get("status") or "").upper()
        if status in SETTLED_STATUSES:
            if goal_id not in all_ids:
                all_ids.append(goal_id)
            if goal_id not in done_ids:
                done_ids.append(goal_id)
            continue
        if status in RUNNABLE_STATUSES or status in WAITING_STATUSES \
                or status in BLOCKED_STATUSES:
            if goal_id not in all_ids:
                all_ids.append(goal_id)
    return all_ids, done_ids


__all__ = [
    "BLOCKED_STATUSES", "ENVIRONMENT", "HARD_EVENT_PREEMPT", "NO_RUNNABLE_WORK", "OPERATOR",
    "RECOVERY", "ROLE_SESSION_POLICY_DEFAULTS", "RUNNABLE_STATUSES", "SESSION_COMPLETE",
    "SETTLED_STATUSES", "SWITCH_REASON_CLASSES", "RoleSessionGate", "RoleSessionState",
    "WAITING_STATUSES", "classify_switch_reason", "evaluate_role_session_gate",
    "new_session", "resolve_policy", "role_switch_quality_metrics", "session_goal_statuses",
]
