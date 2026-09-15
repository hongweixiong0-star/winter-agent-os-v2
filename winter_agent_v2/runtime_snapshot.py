from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AgentState(str, Enum):
    AUTO_RUNNING = "AUTO_RUNNING"
    IDLE = "IDLE"
    GOAL_RUNNING = "GOAL_RUNNING"
    RECOVERING = "RECOVERING"
    DEGRADED = "DEGRADED"
    SAFE_STOP = "SAFE_STOP"
    FATAL_STOPPED = "FATAL_STOPPED"
    PAUSED = "PAUSED"


@dataclass
class RuntimeSnapshot:
    agent_state: str = AgentState.IDLE.value
    runtime_thread_alive: bool = False
    scheduler_loop_alive: bool = False
    last_tick_time: str | None = None
    last_action_time: str | None = None
    last_success_time: str | None = None
    last_fatal_error: str | None = None
    watchdog_restart_count: int = 0
    unexpected_worker_exits: int = 0
    page: str = "UNKNOWN"
    current_goal: str | None = None
    current_skill: str | None = None
    reason: str | None = None
    preconditions: list[str] = field(default_factory=list)
    verifier: str | None = None
    next_action: str | None = None
    risk: str = "UNKNOWN"
    confidence: float = 0.0
    device: str = "UNKNOWN"
    game: str = "UNKNOWN"
    mode: str = "AUTO"
    qwen: str = "ON_DEMAND"
    vision: str = "UNKNOWN"
    screenshot_path: str | None = None
    march_used: int | None = None
    march_max: int | None = None
    queues: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


NON_FATAL_STOPS = {
    "NOT_PROVEN", "NOT_VERIFIED", "SEMANTIC_NOT_FOUND", "SEMANTIC_TARGET_NOT_VERIFIED",
    "QUEUE_FULL", "NO_ATTEMPT", "RALLY_FULL", "NOT_REFRESHED", "EVENT_CLOSED",
    "no_idle_march", "reserved_march_for_stamina", "mail_all_clear",
    "exploration_income_not_ready", "daily_no_claimable_rewards",
    "daily_state_unknown_or_not_actionable", "alliance_action_not_needed",
    "training_queue_busy", "research_queue_busy", "intel_state_unknown",
    "intel_available_no_claim", "verified_beast_target_not_visible", "unknown_page",
    "goal_page_mismatch", "SKILL_NOT_ENABLED_FOR_LIVE_LOOP", "MAX_ACTIONS_REACHED",
    "TARGET_SKILL_VERIFIED",
    # Honest end of a run whose march counter stayed unreadable.  Kept next to
    # SKILL_NOT_ENABLED_FOR_LIVE_LOOP on purpose: that reason used to be what
    # this state produced, and it described a wiring hole rather than the game.
    "MARCH_COUNT_NOT_READ", "intel_no_untried_pins",
}


def is_fatal_stop(reason: str | None) -> bool:
    if not reason:
        return False
    normalized = str(reason).strip()
    if normalized in NON_FATAL_STOPS:
        return False
    return normalized.startswith(("FATAL_", "ACCOUNT_", "PAYMENT_"))


class RuntimeSnapshotStore:
    """Atomic single source of truth written by Runtime and read by the GUI."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> RuntimeSnapshot:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return RuntimeSnapshot()
        fields = RuntimeSnapshot.__dataclass_fields__
        return RuntimeSnapshot(**{key: value for key, value in data.items() if key in fields})

    def update(self, **changes: Any) -> RuntimeSnapshot:
        current = self.read()
        data = asdict(current)
        data.update(changes)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        state = str(data.get("agent_state", AgentState.IDLE.value))
        alive = bool(data.get("runtime_thread_alive")) and bool(data.get("scheduler_loop_alive"))
        invalid_running = state in {AgentState.AUTO_RUNNING.value, AgentState.GOAL_RUNNING.value} and not alive
        invalid_recovery = state == AgentState.RECOVERING.value and not bool(data.get("runtime_thread_alive"))
        if invalid_running or invalid_recovery:
            data["agent_state"] = AgentState.DEGRADED.value
        snapshot = RuntimeSnapshot(**{key: value for key, value in data.items() if key in RuntimeSnapshot.__dataclass_fields__})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return snapshot
