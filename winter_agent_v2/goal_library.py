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
    # How much is left before this goal is satisfied; smaller is closer, 0 is done.
    # This is the goal's own progress meter and it exists so that "the action's
    # verifier passed" and "the goal advanced" can never be the same statement
    # again.  Measured 2026-09-18: 58 consecutive AVOID_STAMINA_WASTE episodes all
    # passed their verifier while stamina never moved off 457 -- action progress
    # with no goal progress, which the scheduler read as a healthy goal.  Every
    # goal therefore has to answer "how far are you from being satisfied?" in a
    # comparable number, and the number is decided here, in the one place that
    # knows what the goal means.
    distance: float = 0.0

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
                distance=0.0 if complete else 1.0,
            ))
        stamina = _optional_int(world.stamina.get("current") if world.stamina else world.intel.get("stamina"))
        if stamina is not None:
            goals.append(GoalState(
                "AVOID_STAMINA_WASTE", GoalStatus.READY if stamina > 30 else GoalStatus.COMPLETE,
                completion=1.0 if stamina <= 30 else 0.0, reward_value=100, daily_loss=max(0, stamina - 30) * 5,
                available_skills=("INTEL_CLAIM_REWARDS", "BEAST_HUNT"), evidence={"current": stamina, "threshold": 30},
                # Stamina still above the floor is exactly the work left to do, and
                # it is what makes a beast kill progress while a map pan does not.
                distance=float(max(0, stamina - 30)),
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
                distance=float(max(0, missing)),
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
                distance=0.0 if finished else 1.0,
            ))
        for page in world.rewards.get("verified_claimable", ()):
            goals.append(GoalState(
                f"CLAIM_FREE_{page}", GoalStatus.READY, reward_value=250, daily_loss=250,
                available_skills=tuple(world.rewards.get("skills", {}).get(page, ())), evidence={"page": page},
                # Only ever discovered while something is claimable, so the one
                # unit of remaining work is the claim itself.
                distance=1.0,
            ))
        return tuple(goals)

    @staticmethod
    def _append_queue_goal(goals: list[GoalState], goal_id: str, state: dict[str, Any], skills: tuple[str, ...], value: float) -> None:
        if not state:
            return
        busy = state.get("queue_available") is False or state.get("status") == "IN_PROGRESS" or state.get("all_queues_busy") is True
        goals.append(GoalState(goal_id, GoalStatus.COMPLETE if busy else GoalStatus.READY,
                               completion=1.0 if busy else 0.0, development_value=value,
                               available_skills=skills, evidence={"queue_busy": busy},
                               distance=0.0 if busy else 1.0))

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


def progress_moved(
    before: Iterable[GoalState],
    after: Iterable[GoalState],
    goal_id: str,
) -> bool | None:
    """Did the goal itself advance between two observations?

    The action's verifier answers "did the input land and did the client respond
    the way this skill predicts".  This answers a different question: "is the goal
    closer to satisfied".  A successful swipe that pans the map answers yes to the
    first and no to the second, and conflating them is what let AUTO spend twenty
    minutes on 58 passing steps that changed nothing (2026-09-18).

    ``None`` means the goal was not observable on both frames.  That is not "no
    progress" -- a queue goal only exists while its page is on screen, and calling
    an unobserved goal stalled would defer work that is merely not being watched.
    """
    was = next((goal for goal in before if goal.goal_id == goal_id), None)
    now = next((goal for goal in after if goal.goal_id == goal_id), None)
    if was is None or now is None:
        return None
    return now.distance < was.distance


@dataclass(frozen=True)
class GoalComposition:
    """How a goal is composed out of capabilities, as the project already maps it.

    ``SEQUENCE`` means every capability is required, so one unavailable capability
    blocks the goal.  ``ANY_OF`` means any single capability satisfies it, so the
    goal is only blocked when *all* of its paths are unavailable -- which is what
    keeps a deferred beast route from also switching off the intel and rally routes
    that reach the same goal.
    """

    goal_id: str
    composition: str
    capabilities: tuple[str, ...]


GOAL_CAPABILITY_MAP = "knowledge/goals/goal_capability_map.json"


def goal_compositions(root: Path | str | None = None) -> dict[str, GoalComposition]:
    """Goal -> capability composition, read from the existing project table.

    Reads ``knowledge/goals/goal_capability_map.json`` (the ``Goal -> Capability``
    input the coverage report is already built from) rather than introducing a
    second mapping.  A goal the table does not describe simply has no composition,
    which the caller must treat as "unknown", never as "nothing required".
    """
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    try:
        payload = json.loads((base / GOAL_CAPABILITY_MAP).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    out: dict[str, GoalComposition] = {}
    for goal_id, entry in (payload.get("goals") or {}).items():
        if not isinstance(entry, dict):
            continue
        capabilities = tuple(
            str(item.get("capability"))
            for item in (entry.get("capabilities") or ())
            if isinstance(item, dict) and item.get("capability")
        )
        out[str(goal_id)] = GoalComposition(
            goal_id=str(goal_id),
            composition=str(entry.get("composition") or "SEQUENCE").upper(),
            capabilities=capabilities,
        )
    return out


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
