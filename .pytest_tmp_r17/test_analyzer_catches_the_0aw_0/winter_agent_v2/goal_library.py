from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import WorldState
from .rally import BearPhase, bear_phase


class GoalStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GoalState:
    goal_id: str
    status: GoalStatus
    completion: float = 0.0
    remaining_seconds: int | None = None
    reward_value: float = 0.0
    daily_loss: float = 0.0
    event_synergy: float = 0.0
    development_value: float = 0.0
    resource_cost: float = 0.0
    risk: float = 0.0
    available_skills: tuple[str, ...] = ()
    retry_after: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def priority(self) -> float:
        if self.status in {GoalStatus.COMPLETE, GoalStatus.BLOCKED, GoalStatus.UNKNOWN}:
            return float("-inf")
        deadline = deadline_pressure(self.remaining_seconds)
        return deadline + self.reward_value + self.daily_loss + self.event_synergy + self.development_value - self.resource_cost - self.risk


def deadline_pressure(seconds: int | None) -> float:
    if seconds is None:
        return 0.0
    if seconds <= 0:
        return -100_000.0
    if seconds < 2 * 3600:
        return 10_000.0
    if seconds < 6 * 3600:
        return 4_000.0
    if seconds < 12 * 3600:
        return 2_000.0
    if seconds < 24 * 3600:
        return 1_000.0
    return 100.0


class GoalLibrary:
    """Turns observed state into goals. It is knowledge, not another scheduler."""

    def discover(self, world: WorldState) -> tuple[GoalState, ...]:
        goals: list[GoalState] = []
        intel_status = str(world.intel.get("status", "UNKNOWN"))
        if intel_status != "UNKNOWN":
            complete = intel_status in {"NOT_AVAILABLE", "EXPIRED"}
            goals.append(GoalState(
                "CLEAR_INTEL", GoalStatus.COMPLETE if complete else GoalStatus.READY,
                completion=1.0 if complete else 0.0,
                remaining_seconds=_optional_int(world.intel.get("refresh_seconds")),
                reward_value=300, daily_loss=500,
                available_skills=("INTEL_CLAIM_REWARDS", "SELECT_INTEL_BEAST_MISSION", "SELECT_INTEL_RESCUE_SURVIVORS"),
                evidence={"status": intel_status},
            ))
        stamina = _optional_int(world.stamina.get("current") if world.stamina else world.intel.get("stamina"))
        if stamina is not None:
            goals.append(GoalState(
                "AVOID_STAMINA_WASTE", GoalStatus.READY if stamina > 30 else GoalStatus.COMPLETE,
                completion=1.0 if stamina <= 30 else 0.0, reward_value=100, daily_loss=max(0, stamina - 30) * 5,
                available_skills=("INTEL_CLAIM_REWARDS", "BEAST_HUNT"), evidence={"current": stamina, "threshold": 30},
            ))
        self._append_queue_goal(goals, "KEEP_TRAINING_PRODUCTIVE", world.training, ("TRAIN_TROOPS",), 90)
        self._append_queue_goal(goals, "KEEP_RESEARCH_PRODUCTIVE", world.research, ("RESEARCH",), 80)
        self._append_queue_goal(goals, "KEEP_BUILDING_PRODUCTIVE", world.building, ("BUILDING_UPGRADE",), 80)
        minimum = world.events.get("minimum_guarantee") if isinstance(world.events, dict) else None
        if isinstance(minimum, dict):
            missing = int(minimum.get("points_missing", 0))
            claimed = bool(minimum.get("all_target_rewards_claimed", False))
            complete = missing <= 0 and claimed
            goals.append(GoalState(
                "EVENT_MINIMUM_GUARANTEE", GoalStatus.COMPLETE if complete else GoalStatus.READY,
                completion=1.0 if complete else 0.0,
                remaining_seconds=_optional_int(minimum.get("remaining_seconds")), reward_value=500,
                event_synergy=500, resource_cost=float(minimum.get("estimated_cost", 0)),
                available_skills=tuple(str(x) for x in minimum.get("available_skills", ())),
                evidence={"points_missing": missing, "claimed": claimed},
            ))
        bear = world.events.get("bear") if isinstance(world.events, dict) else None
        if isinstance(bear, dict):
            phase = bear_phase(
                str(bear.get("status")) if bear.get("status") is not None else None,
                _optional_int(bear.get("seconds_to_start")),
                _optional_int(bear.get("remaining_seconds")),
            )
            finished = phase is BearPhase.FINISHED
            skills: tuple[str, ...]
            if phase is BearPhase.ACTIVE:
                skills = ("START_RALLY", "JOIN_RALLY")
            elif phase in {BearPhase.PREPARING, BearPhase.READY}:
                skills = ("CHECK_MARCH", "SELECT_TROOP_PRESET")
            else:
                skills = ("CHECK_ALLIANCE_EVENT", "READ_BEAR_TIMER")
            goals.append(GoalState(
                "PARTICIPATE_BEAR", GoalStatus.COMPLETE if finished else GoalStatus.READY,
                completion=1.0 if finished else 0.0,
                remaining_seconds=_optional_int(bear.get("remaining_seconds") or bear.get("seconds_to_start")),
                reward_value=1000, daily_loss=5000 if phase in {BearPhase.READY, BearPhase.ACTIVE} else 0,
                available_skills=skills,
                evidence={"phase":phase.value, "reserved_start_time":bear.get("reserved_start_time"),
                          "normal_idle_slots":world.idle_marches,
                          "bear_rally_special_available":world.bear_rally_special_available},
            ))
        for page in world.rewards.get("verified_claimable", ()):
            goals.append(GoalState(
                f"CLAIM_FREE_{page}", GoalStatus.READY, reward_value=250, daily_loss=250,
                available_skills=tuple(world.rewards.get("skills", {}).get(page, ())), evidence={"page": page},
            ))
        return tuple(goals)

    @staticmethod
    def _append_queue_goal(goals: list[GoalState], goal_id: str, state: dict[str, Any], skills: tuple[str, ...], value: float) -> None:
        if not state:
            return
        busy = state.get("queue_available") is False or state.get("status") == "IN_PROGRESS" or state.get("all_queues_busy") is True
        goals.append(GoalState(goal_id, GoalStatus.COMPLETE if busy else GoalStatus.READY,
                               completion=1.0 if busy else 0.0, development_value=value,
                               available_skills=skills, evidence={"queue_busy": busy}))

    def best(self, goals: Iterable[GoalState]) -> GoalState | None:
        actionable = [goal for goal in goals if goal.priority != float("-inf") and goal.available_skills]
        return max(actionable, key=lambda goal: goal.priority, default=None)

    def skill_modifier(self, world: WorldState, skill_id: str) -> float:
        # One action may advance several goals (for example Train + Daily + Event).
        # Aggregate marginal value instead of treating goals as isolated jobs.
        return sum(goal.priority for goal in self.discover(world) if skill_id in goal.available_skills)


def _optional_int(value: object) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


class GoalStateStore:
    """Atomic latest-snapshot persistence for the desktop Goal Board."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, world: WorldState, goals: Iterable[GoalState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "observed_at": world.timestamp,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "page": world.page.value,
            "confidence": world.confidence,
            "goals": [self._serialize(goal) for goal in goals],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _serialize(goal: GoalState) -> dict[str, Any]:
        value = asdict(goal)
        value["status"] = goal.status.value
        value["priority"] = None if goal.priority == float("-inf") else goal.priority
        return value
