"""Persist restart-safe logical state for the existing global Scheduler.

This file deliberately excludes screenshots, OCR objects, bounding boxes, and other
frame-derived data. Those values expire when the worker exits or the account changes.
The module is a state codec/store, not another scheduler or device controller.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .role_session import (
    RoleSessionState,
    classify_switch_reason,
    new_session,
    role_switch_quality_metrics,
)


LIVE_ONLY_KEYS = frozenset({
    "frame", "frame_path", "bbox", "target_bbox", "tap_point", "click_point",
    "box", "coordinates", "ocr_tokens",
    "rally_rows", "march_rows", "formation_bbox", "semantic_result",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aware_iso(value: str | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str | datetime | None) -> datetime | None:
    """The datetime form of ``_aware_iso``, for callers that need arithmetic not text."""
    stamp = _aware_iso(value)
    if stamp is None:
        return None
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


@dataclass
class RoleRuntimeState:
    """Restart-safe, role-scoped scheduler summary; never a cached live screen."""

    role_key: str
    role_id: str = ""
    role_name: str = ""
    identity_source: str = ""
    identity_observed_at: str | None = None
    identity_evidence: list[str] = field(default_factory=list)
    enabled: bool = True
    health: str = "STALE"
    last_observed_at: str | None = None
    last_active_at: str | None = None
    page: str | None = None
    page_confidence: float = 0.0
    top_goal: str = ""
    goal_ids: list[str] = field(default_factory=list)
    current_goal: str = ""
    current_skill: str = ""
    last_failure: str = ""
    blocked_until: str | None = None
    switch_failure_streak: int = 0
    next_action_at: str | None = None
    last_ready_count: int = 0
    last_blocked_count: int = 0
    dirty_live_state: bool = True

    def __post_init__(self) -> None:
        if not self.role_key.strip():
            raise ValueError("role_key is required")
        self.last_observed_at = _aware_iso(self.last_observed_at)
        self.last_active_at = _aware_iso(self.last_active_at)
        self.identity_observed_at = _aware_iso(self.identity_observed_at)
        self.blocked_until = _aware_iso(self.blocked_until)
        self.next_action_at = _aware_iso(self.next_action_at)
        self.switch_failure_streak = max(0, int(self.switch_failure_streak or 0))
        # Filter defensively when loading old or externally edited state. Live data never
        # belongs in this codec, even if a future caller accidentally passes it through.
        self.goal_ids = [str(item) for item in self.goal_ids if item]
        self.identity_evidence = [str(item) for item in self.identity_evidence if item]
        self.page = str(self.page) if self.page else None
        self.health = str(self.health or "STALE").upper()
        self.dirty_live_state = True


@dataclass
class GlobalSchedulerState:
    schema_version: int = 1
    active_role_id: str = ""
    last_role_switch_at: str | None = None
    last_switch_reason: str = ""
    global_next_wakeup_at: str | None = None
    last_decision: dict[str, Any] = field(default_factory=dict)
    decision_history: list[dict[str, Any]] = field(default_factory=list)
    roles: dict[str, RoleRuntimeState] = field(default_factory=dict)
    scheduler_generation: int = 0
    running_session: dict[str, Any] | None = None
    role_switch_pending: dict[str, Any] | None = None
    role_switch_count: int = 0
    role_switch_success_count: int = 0
    role_switch_failure_count: int = 0
    role_switch_durations_ms: list[float] = field(default_factory=list)
    latest_action_outcome: dict[str, Any] = field(default_factory=dict)
    action_outcome_history: list[dict[str, Any]] = field(default_factory=list)
    telemetry_since: str | None = None
    global_wait_count: int = 0
    global_wait_with_runnable_goal_count: int = 0
    action_outcome_count: int = 0
    shared_goal_credit_count: int = 0
    completed_goal_count_by_role: dict[str, int] = field(default_factory=dict)
    global_health: str = "WAITING"
    #: ROLE_SESSION_POLICY (operator directive 2026-09-30): the current role's logical
    #: batch.  ``None`` means no session has been established for the active role yet.
    role_session: RoleSessionState | None = None
    #: One row per committed role switch: {at, source_role_id, target_role_id,
    #: reason_class, reason, duration_seconds, goals_completed}.  This is what turns the
    #: switch-quality metrics of directive §17 into measured numbers instead of a claim.
    role_switch_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.last_role_switch_at = _aware_iso(self.last_role_switch_at)
        self.global_next_wakeup_at = _aware_iso(self.global_next_wakeup_at)
        self.telemetry_since = _aware_iso(self.telemetry_since)
        if len(self.decision_history) > 10:
            self.decision_history = self.decision_history[-10:]
        if len(self.action_outcome_history) > 200:
            self.action_outcome_history = self.action_outcome_history[-200:]
        self.role_switch_count = max(0, int(self.role_switch_count or 0))
        self.role_switch_success_count = max(0, int(self.role_switch_success_count or 0))
        self.role_switch_failure_count = max(0, int(self.role_switch_failure_count or 0))
        self.global_wait_count = max(0, int(self.global_wait_count or 0))
        self.global_wait_with_runnable_goal_count = max(
            0, int(self.global_wait_with_runnable_goal_count or 0),
        )
        self.action_outcome_count = max(0, int(self.action_outcome_count or 0))
        self.shared_goal_credit_count = max(0, int(self.shared_goal_credit_count or 0))
        self.completed_goal_count_by_role = {
            str(role_id): max(0, int(count or 0))
            for role_id, count in self.completed_goal_count_by_role.items()
            if role_id
        }
        self.role_switch_durations_ms = [
            max(0.0, float(value)) for value in self.role_switch_durations_ms[-200:]
            if isinstance(value, (int, float))
        ]
        if self.role_session is not None and not isinstance(self.role_session, RoleSessionState):
            self.role_session = None
        self.role_switch_history = [
            dict(row) for row in self.role_switch_history[-200:] if isinstance(row, Mapping)
        ]


class GlobalSchedulerStateStore:
    """Atomic persistence for logical role state and explainable decisions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def load(self) -> GlobalSchedulerState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return GlobalSchedulerState()
        if not isinstance(payload, Mapping):
            return GlobalSchedulerState()
        roles: dict[str, RoleRuntimeState] = {}
        raw_roles = payload.get("roles", {})
        if isinstance(raw_roles, Mapping):
            for key, row in raw_roles.items():
                if not isinstance(row, Mapping):
                    continue
                allowed = RoleRuntimeState.__dataclass_fields__.keys()
                values = {name: row[name] for name in allowed if name in row}
                values["role_key"] = str(values.get("role_key") or key)
                try:
                    roles[str(key)] = RoleRuntimeState(**values)
                except (TypeError, ValueError):
                    continue
        return GlobalSchedulerState(
            schema_version=int(payload.get("schema_version", 1) or 1),
            active_role_id=str(payload.get("active_role_id") or ""),
            last_role_switch_at=_aware_iso(payload.get("last_role_switch_at")),
            last_switch_reason=str(payload.get("last_switch_reason") or ""),
            global_next_wakeup_at=_aware_iso(payload.get("global_next_wakeup_at")),
            last_decision=self._logical_mapping(payload.get("last_decision")),
            decision_history=[self._logical_mapping(row) for row in payload.get("decision_history", [])
                              if isinstance(row, Mapping)][-10:],
            roles=roles,
            scheduler_generation=max(0, int(payload.get("scheduler_generation", 0) or 0)),
            running_session=self._logical_mapping(payload.get("running_session"))
            if isinstance(payload.get("running_session"), Mapping) else None,
            role_switch_pending=self._logical_mapping(payload.get("role_switch_pending"))
            if isinstance(payload.get("role_switch_pending"), Mapping) else None,
            role_switch_count=int(payload.get("role_switch_count", 0) or 0),
            role_switch_success_count=int(payload.get("role_switch_success_count", 0) or 0),
            role_switch_failure_count=int(payload.get("role_switch_failure_count", 0) or 0),
            role_switch_durations_ms=list(payload.get("role_switch_durations_ms", ()))
            if isinstance(payload.get("role_switch_durations_ms", ()), list) else [],
            latest_action_outcome=self._logical_mapping(payload.get("latest_action_outcome")),
            action_outcome_history=[self._logical_mapping(row)
                                    for row in payload.get("action_outcome_history", ())
                                    if isinstance(row, Mapping)][-200:],
            telemetry_since=_aware_iso(payload.get("telemetry_since")),
            global_wait_count=int(payload.get("global_wait_count", 0) or 0),
            global_wait_with_runnable_goal_count=int(
                payload.get("global_wait_with_runnable_goal_count", 0) or 0,
            ),
            action_outcome_count=int(payload.get("action_outcome_count", 0) or 0),
            shared_goal_credit_count=int(payload.get("shared_goal_credit_count", 0) or 0),
            completed_goal_count_by_role=dict(payload.get("completed_goal_count_by_role", {}))
            if isinstance(payload.get("completed_goal_count_by_role", {}), Mapping) else {},
            global_health=str(payload.get("global_health") or "WAITING").upper(),
            role_session=self._load_session(payload.get("role_session")),
            role_switch_history=[dict(row) for row in payload.get("role_switch_history", ())
                                 if isinstance(row, Mapping)][-200:],
        )

    @staticmethod
    def _load_session(raw: Any) -> RoleSessionState | None:
        """Rebuild the logical session, tolerating a schema the running code no longer has."""
        if not isinstance(raw, Mapping):
            return None
        allowed = RoleSessionState.__dataclass_fields__.keys()
        values = {name: raw[name] for name in allowed if name in raw}
        if not str(values.get("role_id") or "").strip():
            return None
        try:
            return RoleSessionState(**values)
        except (TypeError, ValueError):
            return None

    def save(self, state: GlobalSchedulerState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        payload["roles"] = {key: asdict(value) for key, value in state.roles.items()}
        payload["decision_history"] = state.decision_history[-10:]
        payload = self._logical_mapping(payload)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp",
                                         dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def recover_after_restart(self, *, actual_role_id: str, actual_role_name: str = "",
                               observed_at: str | datetime | None = None) -> GlobalSchedulerState:
        """Trust the newly observed client identity over a persisted active-role hint."""
        state = self.load()
        stamp = _aware_iso(observed_at) or _now_iso()
        actual = str(actual_role_id or "").strip()
        state.scheduler_generation += 1
        state.running_session = None
        state.role_switch_pending = None
        for role in state.roles.values():
            role.health = "STALE"
            role.dirty_live_state = True
            role.page = None
            role.page_confidence = 0.0
            role.current_goal = ""
            role.current_skill = ""
        if actual:
            role = state.roles.get(actual) or RoleRuntimeState(role_key=actual, role_id=actual)
            role.role_id = actual
            if actual_role_name:
                role.role_name = str(actual_role_name)
            role.last_active_at = stamp
            role.health = "NEEDS_FRESH_OBSERVATION"
            role.dirty_live_state = True
            state.roles[actual] = role
            state.active_role_id = actual
            state.global_health = "RUNNING"
            # Keep the session when the restarted worker came back on the *same* account:
            # a switch is implemented as a worker restart, and resetting here would make
            # every session look zero seconds long (directive §17).
            session = state.role_session
            if session is None or session.role_id != actual:
                state.role_session = new_session(actual, at=stamp)
        else:
            state.active_role_id = ""
            state.global_health = "DEGRADED"
            state.last_switch_reason = "ROLE_IDENTITY_UNKNOWN_ON_RECOVERY"
        self.save(state)
        return state

    def register_role_catalog(self, roles: list[Mapping[str, Any]], *,
                              active_role_id: str = "",
                              observed_at: str | datetime | None = None) -> GlobalSchedulerState:
        """Record identities discovered in the live role manager without importing live state.

        The active identity may seed ``active_role_id`` only when the caller passes it
        explicitly. Every role remains stale until that character gets a fresh WorldState.
        This catalog is knowledge/configuration, not a second task queue.
        """
        stamp = _aware_iso(observed_at) or _now_iso()
        incoming: dict[str, Mapping[str, Any]] = {}
        for row in roles:
            role_id = str(row.get("role_id") or "").strip()
            if not role_id:
                raise ValueError("role catalog entry requires a confirmed role_id")
            if role_id in incoming:
                raise ValueError(f"duplicate role_id in role catalog: {role_id}")
            incoming[role_id] = row
        active = str(active_role_id or "").strip()
        if active and active not in incoming:
            raise ValueError("active_role_id must be present in the observed role catalog")

        state = self.load()
        for role_id, row in incoming.items():
            role = state.roles.get(role_id) or RoleRuntimeState(role_key=str(row.get("role_key") or role_id),
                                                                role_id=role_id)
            role.role_key = str(row.get("role_key") or role.role_key or role_id)
            role.role_id = role_id
            role.role_name = str(row.get("display_name") or row.get("role_name") or role.role_name)
            role.identity_source = str(row.get("identity_source") or row.get("source") or "LIVE_ROLE_MANAGER")
            role.identity_observed_at = stamp
            refs = row.get("identity_evidence") or row.get("evidence") or ()
            role.identity_evidence = [str(ref) for ref in refs if ref] if isinstance(refs, (list, tuple)) else [str(refs)]
            role.enabled = bool(row.get("enabled", True))
            role.health = "NEEDS_FRESH_OBSERVATION" if role_id == active else "STALE"
            role.page = None
            role.page_confidence = 0.0
            role.current_goal = ""
            role.current_skill = ""
            role.dirty_live_state = True
            state.roles[role_id] = role
        if active:
            state.active_role_id = active
            state.roles[active].last_active_at = stamp
            state.global_health = "RUNNING"
            session = state.role_session
            if session is None or session.role_id != active:
                state.role_session = new_session(active, at=stamp)
        self.save(state)
        return state

    def record_role_observation(self, *, role_id: str, role_name: str = "",
                                observed_at: str | datetime, page: str = "",
                                page_confidence: float = 0.0, goal_summaries: list[Mapping[str, Any]] | None = None,
                                next_action_at: str | datetime | None = None,
                                current_goal: str = "", current_skill: str = "") -> GlobalSchedulerState:
        role_id = str(role_id or "").strip()
        if not role_id:
            raise ValueError("cannot persist a role observation without a confirmed role_id")
        stamp = _aware_iso(observed_at)
        if stamp is None:
            raise ValueError("role observation must have a valid timestamp")
        state = self.load()
        # There is exactly one live client. Seeing this role means every other
        # role's screen-derived state is no longer current, while its logical Goal
        # snapshot and timers remain available for future arbitration.
        for other_id, other in state.roles.items():
            if other_id == role_id:
                continue
            other.health = "STALE"
            other.dirty_live_state = True
            other.page = None
            other.page_confidence = 0.0
            other.current_goal = ""
            other.current_skill = ""
        role = state.roles.get(role_id) or RoleRuntimeState(role_key=role_id, role_id=role_id)
        rows = [self._logical_mapping(dict(row)) for row in (goal_summaries or ())]
        ready_count = sum(str(row.get("status", "")).upper() in {"READY", "DISCOVERED", "RUNNABLE"}
                          for row in rows)
        blocked_count = sum(str(row.get("status", "")).upper() in {"BLOCKED", "UNKNOWN", "DEFERRED"}
                            for row in rows)
        role.role_id = role_id
        if role_name:
            role.role_name = str(role_name)
        role.health = "ACTIVE"
        role.last_observed_at = stamp
        role.last_active_at = stamp
        role.page = str(page) if page else None
        role.page_confidence = max(0.0, min(1.0, float(page_confidence or 0.0)))
        role.goal_ids = [str(row.get("goal_id")) for row in rows if row.get("goal_id")]
        role.top_goal = max(rows, key=lambda row: float(row.get("priority") or 0.0), default={}).get("goal_id", "")
        role.last_ready_count = ready_count
        role.last_blocked_count = blocked_count
        role.next_action_at = _aware_iso(next_action_at)
        role.current_goal = str(current_goal or "")
        role.current_skill = str(current_skill or "")
        role.dirty_live_state = True
        state.roles[role_id] = role
        state.active_role_id = role_id
        state.global_health = "RUNNING"
        state.scheduler_generation += 1
        self.save(state)
        return state

    def record_decision(self, *, decision: Mapping[str, Any], at: str | datetime | None = None) -> GlobalSchedulerState:
        state = self.load()
        row = self._logical_mapping(dict(decision))
        row["at"] = _aware_iso(at) or _now_iso()
        if state.telemetry_since is None:
            state.telemetry_since = row["at"]
        if str(row.get("decision") or "").upper() == "GLOBAL_WAIT":
            state.global_wait_count += 1
            statuses = row.get("role_statuses")
            if isinstance(statuses, list) and any(
                isinstance(status, Mapping)
                and max(
                    int(status.get("runnable_count") or 0),
                    int(status.get("runnable_goal_count") or 0),
                ) > 0
                for status in statuses
            ):
                state.global_wait_with_runnable_goal_count += 1
        state.last_decision = row
        state.decision_history = [*state.decision_history, row][-10:]
        state.global_next_wakeup_at = _aware_iso(row.get("next_wakeup"))
        self._refresh_role_session(state, decision=row)
        self.save(state)
        return state

    def record_action_outcome(self, outcome: Mapping[str, Any]) -> GlobalSchedulerState:
        """Persist measured action-to-Goal effects without retaining ephemeral UI data."""
        row = self._logical_mapping(dict(outcome))
        action_id = str(row.get("action_id") or "").strip()
        role_id = str(row.get("role_id") or "").strip()
        if not action_id or not role_id:
            raise ValueError("ActionOutcome requires action_id and confirmed role_id")
        row["action_id"] = action_id
        row["role_id"] = role_id
        row["recorded_at"] = _aware_iso(row.get("recorded_at")) or _now_iso()
        state = self.load()
        if state.telemetry_since is None:
            state.telemetry_since = row["recorded_at"]
        state.action_outcome_count += 1
        credited = row.get("credited_goal_ids")
        credited_ids = {str(item) for item in credited if item} if isinstance(credited, (list, tuple)) else set()
        if len(credited_ids) > 1:
            state.shared_goal_credit_count += 1
        completed = row.get("completed_goal_ids")
        completed_ids = {str(item) for item in completed if item} if isinstance(completed, (list, tuple)) else set()
        if completed_ids:
            state.completed_goal_count_by_role[role_id] = (
                state.completed_goal_count_by_role.get(role_id, 0) + len(completed_ids)
            )
        state.latest_action_outcome = row
        state.action_outcome_history = [*state.action_outcome_history, row][-200:]
        session = state.role_session
        if session is not None and session.role_id == role_id:
            if completed_ids:
                session.note_completed(sorted(completed_ids))
                session.goals_completed += len(completed_ids)
            if (str(row.get("verifier_result") or "").upper() == "PASS"
                    and bool(row.get("action_sent", True))):
                session.actions_verified += 1
        self.save(state)
        return state

    # ------------------------------------------------------- ROLE_SESSION_POLICY

    @staticmethod
    def _refresh_role_session(state: GlobalSchedulerState, *,
                              decision: Mapping[str, Any]) -> None:
        """Fold one arbitration decision into the current role's logical session.

        Called from ``record_decision``, i.e. once per scheduling, which is exactly the
        cadence directive §4's ``no_work_streak`` is defined over.
        """
        session = state.role_session
        if session is None:
            return
        current = str(decision.get("current_role_id") or "")
        if not current or current != session.role_id:
            return
        statuses = decision.get("role_statuses")
        row: Mapping[str, Any] | None = None
        if isinstance(statuses, list):
            for item in statuses:
                if isinstance(item, Mapping) and str(item.get("role_id") or "") == current:
                    row = item
                    break
        if row is not None:
            session.ready_now = max(0, int(row.get("ready_goal_count") or 0))
            session.runnable_now = max(
                0, int(row.get("runnable_goal_count") or row.get("runnable_count") or 0),
            )
            session.capability_gap_now = max(0, int(row.get("capability_gap_count") or 0))
            session.blocked_now = max(0, int(row.get("blocked_count") or 0))
            session.waiting_now = max(0, int(row.get("waiting_goal_count") or 0))
            session.note_board(
                goal_ids=row.get("board_goal_ids") or (),
                settled_goal_ids=row.get("board_settled_goal_ids") or (),
                runnable_goal_ids=row.get("board_runnable_goal_ids") or (),
            )
            session.no_work_streak = (
                0 if session.runnable_now > 0 else min(10_000, session.no_work_streak + 1)
            )
        gate = decision.get("session_gate")
        if isinstance(gate, Mapping):
            session.switch_allowed = bool(gate.get("allowed"))
            session.switch_reason = str(
                gate.get("detail") or gate.get("description") or ""
            )
        session.last_evaluated_at = _aware_iso(decision.get("at")) or _now_iso()

    def start_role_session(self, *, role_id: str, ready_at_start: int = 0,
                           at: str | datetime | None = None) -> GlobalSchedulerState:
        """Open a fresh session for a role that now owns the device.

        Idempotent for the same role only when ``force`` is not needed: a worker restart
        on the *same* account must keep its session, or directive §17's session-duration
        metric would reset on every crash.
        """
        role_id = str(role_id or "").strip()
        if not role_id:
            raise ValueError("a role session requires a confirmed role_id")
        state = self.load()
        session = new_session(role_id, at=at, ready_at_start=ready_at_start)
        session.switch_allowed = False
        session.switch_reason = "ROLE_SESSION_ACTIVE"
        state.role_session = session
        self.save(state)
        return state

    def ensure_role_session(self, *, role_id: str, at: str | datetime | None = None,
                            ready_at_start: int = 0) -> GlobalSchedulerState:
        """Start a session only when the active role does not already have one."""
        role_id = str(role_id or "").strip()
        if not role_id:
            raise ValueError("a role session requires a confirmed role_id")
        state = self.load()
        current = state.role_session
        if current is not None and current.role_id == role_id:
            return state
        return self.start_role_session(role_id=role_id, ready_at_start=ready_at_start, at=at)

    def _close_role_session_locked(
        self, state: GlobalSchedulerState, *, source_role_id: str,
        reason: str, reason_class: str, at: str | datetime | None,
    ) -> None:
        """Archive the ending session into the switch history, then clear it."""
        session = state.role_session
        if session is not None:
            elapsed = session.elapsed_seconds(_parse_dt(at))
            state.role_switch_history = [*state.role_switch_history, {
                "at": _aware_iso(at) or _now_iso(),
                "source_role_id": session.role_id or str(source_role_id or ""),
                "target_role_id": "",
                "reason_class": str(reason_class or ""),
                "reason": str(reason or ""),
                "duration_seconds": round(elapsed, 1) if elapsed is not None else None,
                "goals_completed": session.goals_completed,
                "actions_verified": session.actions_verified,
                "goals_discovered": len(session.session_goal_ids),
                "completion_ratio": round(session.completion_ratio, 4),
                "no_work_streak": session.no_work_streak,
                "switch_reason_detail": session.switch_reason,
            }][-200:]
        state.role_session = None

    def role_switch_quality_metrics(self) -> dict[str, Any]:
        """Directive §17's switch-quality block, measured from the persisted history."""
        state = self.load()
        return role_switch_quality_metrics(
            switch_history=state.role_switch_history, session=state.role_session,
        )

    def role_session_view(self) -> dict[str, Any] | None:
        state = self.load()
        session = state.role_session
        return session.as_logical_row() if session is not None else None

    def begin_role_switch(self, *, source_role_id: str, target_role_id: str,
                          reason: str, at: str | datetime | None = None,
                          reason_class: str = "") -> GlobalSchedulerState:
        source = str(source_role_id or "").strip()
        target = str(target_role_id or "").strip()
        if not target or source == target:
            raise ValueError("role switch requires a distinct confirmed target role")
        state = self.load()
        if state.role_switch_pending:
            raise RuntimeError("ROLE_SWITCH_ALREADY_PENDING")
        state.role_switch_pending = {
            "source_role_id": source,
            "target_role_id": target,
            "reason": str(reason),
            "reason_class": str(reason_class or classify_switch_reason(reason)),
            "phase": "BEGIN",
            "started_at": _aware_iso(at) or _now_iso(),
        }
        state.role_switch_count += 1
        state.last_switch_reason = str(reason)
        state.global_health = "RUNNING"
        self.save(state)
        return state

    def commit_role_switch(self, *, confirmed_role_id: str,
                           at: str | datetime | None = None,
                           elapsed_ms: float | None = None) -> GlobalSchedulerState:
        state = self.load()
        pending = state.role_switch_pending
        if not pending:
            raise RuntimeError("ROLE_SWITCH_NOT_PENDING")
        target = str(pending.get("target_role_id") or "")
        if not target or str(confirmed_role_id or "") != target:
            raise ValueError("ROLE_SWITCH_NOT_VERIFIED")
        source = str(pending.get("source_role_id") or "")
        if source and source in state.roles:
            state.roles[source].health = "STALE"
            state.roles[source].dirty_live_state = True
            state.roles[source].page = None
            state.roles[source].page_confidence = 0.0
            state.roles[source].current_goal = ""
            state.roles[source].current_skill = ""
        role = state.roles.get(target) or RoleRuntimeState(role_key=target, role_id=target)
        role.health = "NEEDS_FRESH_OBSERVATION"
        role.dirty_live_state = True
        role.page = None
        role.page_confidence = 0.0
        role.current_goal = ""
        role.current_skill = ""
        role.blocked_until = None
        role.switch_failure_streak = 0
        role.last_failure = ""
        state.roles[target] = role
        state.active_role_id = target
        committed_at = _aware_iso(at) or _now_iso()
        state.last_role_switch_at = committed_at
        state.last_switch_reason = str(pending.get("reason") or "")
        # ROLE_SESSION_POLICY: the source session ends here and is archived with its own
        # measured duration and Goal count; the target opens a fresh batch.  Field order
        # matters -- ``_close_role_session_locked`` reads the *old* session, so it runs
        # before the new one is written.  The history length is captured first because
        # ``_close`` appends nothing when there was no session to close, and indexing
        # ``[-1]`` then would have rewritten an *older* switch's target.
        history_before = len(state.role_switch_history)
        self._close_role_session_locked(
            state, source_role_id=source,
            reason=str(pending.get("reason") or ""),
            reason_class=str(pending.get("reason_class") or ""),
            at=committed_at,
        )
        if len(state.role_switch_history) > history_before:
            state.role_switch_history[-1]["target_role_id"] = target
        state.role_session = new_session(target, at=committed_at)
        state.role_switch_pending = None
        state.role_switch_success_count += 1
        self._append_switch_duration(state, elapsed_ms)
        state.scheduler_generation += 1
        state.global_health = "RUNNING"
        self.save(state)
        return state

    def abort_role_switch(self, *, actual_role_id: str = "", reason: str,
                          elapsed_ms: float | None = None) -> GlobalSchedulerState:
        state = self.load()
        pending = state.role_switch_pending
        had_pending = pending is not None
        state.role_switch_pending = None
        if had_pending:
            state.role_switch_failure_count += 1
            self._append_switch_duration(state, elapsed_ms)
            target_id = str((pending or {}).get("target_role_id") or "").strip()
            if target_id:
                target = state.roles.get(target_id) or RoleRuntimeState(
                    role_key=target_id, role_id=target_id,
                )
                target.switch_failure_streak += 1
                # First retry after 15s; exponential backoff caps at five minutes.
                # This gives a transient login/load failure room to recover without
                # letting the controller hammer the same account every AUTO cycle.
                delay_seconds = min(300, 15 * (2 ** min(4, target.switch_failure_streak - 1)))
                target.blocked_until = (
                    datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
                ).isoformat()
                target.last_failure = str(reason)
                target.health = "STALE"
                target.dirty_live_state = True
                target.page = None
                target.page_confidence = 0.0
                target.current_goal = ""
                target.current_skill = ""
                state.roles[target_id] = target
        actual = str(actual_role_id or "").strip()
        if actual:
            state.active_role_id = actual
            role = state.roles.get(actual) or RoleRuntimeState(role_key=actual, role_id=actual)
            role.health = "NEEDS_FRESH_OBSERVATION"
            role.dirty_live_state = True
            role.page = None
            role.page_confidence = 0.0
            role.current_goal = ""
            role.current_skill = ""
            state.roles[actual] = role
            state.global_health = "RUNNING"
            # The device is on an account, and it is not the one the session belongs to,
            # so the session cannot keep counting for it (directive §17's per-session
            # numbers would silently accrue to the wrong role).
            session = state.role_session
            if session is None or session.role_id != actual:
                state.role_session = new_session(actual, at=_now_iso())
        else:
            state.active_role_id = ""
            state.global_health = "DEGRADED"
            for role in state.roles.values():
                role.health = "STALE"
                role.dirty_live_state = True
                role.page = None
                role.page_confidence = 0.0
                role.current_goal = ""
                role.current_skill = ""
        state.last_switch_reason = f"ROLE_SWITCH_ABORT:{reason}"
        state.scheduler_generation += 1
        self.save(state)
        return state

    @staticmethod
    def _append_switch_duration(state: GlobalSchedulerState, elapsed_ms: float | None) -> None:
        if elapsed_ms is None:
            return
        try:
            value = max(0.0, float(elapsed_ms))
        except (TypeError, ValueError):
            return
        state.role_switch_durations_ms = [*state.role_switch_durations_ms, value][-200:]

    def role_switch_metrics(self) -> dict[str, Any]:
        state = self.load()
        samples = sorted(state.role_switch_durations_ms)

        def percentile(value: float) -> float | None:
            if not samples:
                return None
            index = max(0, min(len(samples) - 1, int((len(samples) * value + 0.999999)) - 1))
            return samples[index]

        completed = state.role_switch_success_count + state.role_switch_failure_count
        return {
            "count": state.role_switch_count,
            "success_count": state.role_switch_success_count,
            "failure_count": state.role_switch_failure_count,
            "success_rate": (state.role_switch_success_count / completed) if completed else None,
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
        }

    def production_telemetry_metrics(self) -> dict[str, Any]:
        """Return counters backed by explicit global decisions and ActionOutcome rows."""
        state = self.load()
        return {
            "since": state.telemetry_since,
            "global_wait_count": state.global_wait_count,
            "global_wait_with_runnable_goal_count": state.global_wait_with_runnable_goal_count,
            "action_outcome_count": state.action_outcome_count,
            "shared_goal_credit_count": state.shared_goal_credit_count,
            "completed_goal_count_by_role": dict(state.completed_goal_count_by_role),
        }

    @classmethod
    def _logical_mapping(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in LIVE_ONLY_KEYS:
                continue
            if isinstance(item, Mapping):
                out[str(key)] = cls._logical_mapping(item)
            elif isinstance(item, list):
                # Filter each element *in place*.  Dropping an element that merely
                # mentions one live key silently deleted whole rows -- a
                # ``role_statuses`` entry that happened to carry a stray ``bbox``
                # vanished from the persisted decision, and every reader of that row
                # (the panel, the session refresh) then saw zeros instead of the truth.
                # Stripping the live field is what the doctrine asks for; discarding the
                # record was never the intent.
                out[str(key)] = [cls._logical_mapping(row) if isinstance(row, Mapping) else row
                                 for row in item]
            else:
                out[str(key)] = item
        return out
