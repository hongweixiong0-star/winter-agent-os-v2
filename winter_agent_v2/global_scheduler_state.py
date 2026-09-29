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
    global_health: str = "WAITING"

    def __post_init__(self) -> None:
        self.last_role_switch_at = _aware_iso(self.last_role_switch_at)
        self.global_next_wakeup_at = _aware_iso(self.global_next_wakeup_at)
        if len(self.decision_history) > 10:
            self.decision_history = self.decision_history[-10:]
        if len(self.action_outcome_history) > 200:
            self.action_outcome_history = self.action_outcome_history[-200:]
        self.role_switch_count = max(0, int(self.role_switch_count or 0))
        self.role_switch_success_count = max(0, int(self.role_switch_success_count or 0))
        self.role_switch_failure_count = max(0, int(self.role_switch_failure_count or 0))
        self.role_switch_durations_ms = [
            max(0.0, float(value)) for value in self.role_switch_durations_ms[-200:]
            if isinstance(value, (int, float))
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
            global_health=str(payload.get("global_health") or "WAITING").upper(),
        )

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
            role.current_skill = ""
            role.dirty_live_state = True
            state.roles[role_id] = role
        if active:
            state.active_role_id = active
            state.roles[active].last_active_at = stamp
            state.global_health = "RUNNING"
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
        state.last_decision = row
        state.decision_history = [*state.decision_history, row][-10:]
        state.global_next_wakeup_at = _aware_iso(row.get("next_wakeup"))
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
        state.latest_action_outcome = row
        state.action_outcome_history = [*state.action_outcome_history, row][-200:]
        self.save(state)
        return state

    def begin_role_switch(self, *, source_role_id: str, target_role_id: str,
                          reason: str, at: str | datetime | None = None) -> GlobalSchedulerState:
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
        role = state.roles.get(target) or RoleRuntimeState(role_key=target, role_id=target)
        role.health = "NEEDS_FRESH_OBSERVATION"
        role.dirty_live_state = True
        role.page = None
        role.page_confidence = 0.0
        role.blocked_until = None
        role.switch_failure_streak = 0
        role.last_failure = ""
        state.roles[target] = role
        state.active_role_id = target
        state.last_role_switch_at = _aware_iso(at) or _now_iso()
        state.last_switch_reason = str(pending.get("reason") or "")
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
            state.roles[actual] = role
            state.global_health = "RUNNING"
        else:
            state.active_role_id = ""
            state.global_health = "DEGRADED"
            for role in state.roles.values():
                role.health = "STALE"
                role.dirty_live_state = True
                role.page = None
                role.page_confidence = 0.0
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
                out[str(key)] = [cls._logical_mapping(row) if isinstance(row, Mapping) else row
                                 for row in item if not isinstance(row, Mapping)
                                 or not any(str(k).lower() in LIVE_ONLY_KEYS for k in row)]
            else:
                out[str(key)] = item
        return out
