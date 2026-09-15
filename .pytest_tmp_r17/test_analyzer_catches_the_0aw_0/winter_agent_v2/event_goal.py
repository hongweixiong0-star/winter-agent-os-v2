from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import ceil
from typing import Any


class DeadlineLevel(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    P0 = "P0"


@dataclass(frozen=True)
class ScoringAction:
    action_id: str
    points_per_unit: int
    available_units: int | None
    skill_id: str | None
    effective_cost: float = 1.0
    normal_value: float = 0.0
    allowed: bool = True
    resource: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ScoringAction":
        return cls(
            action_id=str(value["action_id"]),
            points_per_unit=int(value["points_per_unit"]),
            available_units=None if value.get("available_units") is None else int(value["available_units"]),
            skill_id=value.get("skill_id"),
            effective_cost=float(value.get("effective_cost", 1.0)),
            normal_value=float(value.get("normal_value", 0.0)),
            allowed=bool(value.get("allowed", True)),
            resource=value.get("resource"),
        )


@dataclass(frozen=True)
class EventState:
    event_id: str
    name: str
    current_points: int
    target_points: int
    remaining_seconds: int
    scoring_actions: tuple[ScoringAction, ...]
    claimable_rewards: tuple[int, ...] = ()
    completed_tiers: tuple[int, ...] = ()
    claimed_tiers: tuple[int, ...] = ()
    source: str = "LIVE_CLIENT"

    @property
    def points_missing(self) -> int:
        return max(0, self.target_points - self.current_points)

    @property
    def minimum_guarantee_complete(self) -> bool:
        return self.points_missing == 0 and all(tier in self.claimed_tiers for tier in self.completed_tiers)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "EventState":
        return cls(
            event_id=str(value["event_id"]), name=str(value["name"]),
            current_points=int(value["current_points"]), target_points=int(value["target_points"]),
            remaining_seconds=int(value["remaining_seconds"]),
            scoring_actions=tuple(ScoringAction.from_mapping(item) for item in value.get("scoring_actions", [])),
            claimable_rewards=tuple(int(x) for x in value.get("claimable_rewards", [])),
            completed_tiers=tuple(int(x) for x in value.get("completed_tiers", [])),
            claimed_tiers=tuple(int(x) for x in value.get("claimed_tiers", [])),
            source=str(value.get("source", "LIVE_CLIENT")),
        )


@dataclass(frozen=True)
class PlannedAction:
    action_id: str
    skill_id: str | None
    units: int
    expected_points: int
    resource: str | None


@dataclass(frozen=True)
class EventPlan:
    event_id: str
    deadline: DeadlineLevel
    points_needed: int
    actions: tuple[PlannedAction, ...]
    expected_points: int
    feasible: bool
    status: str


def deadline_level(remaining_seconds: int) -> DeadlineLevel:
    if remaining_seconds < 2 * 3600:
        return DeadlineLevel.P0
    if remaining_seconds < 6 * 3600:
        return DeadlineLevel.HIGH
    if remaining_seconds < 12 * 3600:
        return DeadlineLevel.ELEVATED
    return DeadlineLevel.NORMAL


class EventGoalPlanner:
    """Creates a goal plan; it never executes actions and is not a scheduler."""

    def plan(self, event: EventState, available_skills: set[str]) -> EventPlan:
        needed = event.points_missing
        deadline = deadline_level(event.remaining_seconds)
        if needed == 0:
            status = "COMPLETE" if event.minimum_guarantee_complete else "CLAIM_REQUIRED"
            return EventPlan(event.event_id, deadline, 0, (), 0, True, status)

        candidates = [
            action for action in event.scoring_actions
            if action.allowed and action.points_per_unit > 0
            and action.available_units != 0
            and (action.skill_id is None or action.skill_id in available_skills)
        ]
        candidates.sort(
            key=lambda action: (action.points_per_unit * (1.0 + action.normal_value)) / max(action.effective_cost, 0.001),
            reverse=True,
        )
        remaining = needed
        chosen: list[PlannedAction] = []
        for action in candidates:
            units = ceil(remaining / action.points_per_unit)
            if action.available_units is not None:
                units = min(units, action.available_units)
            if units <= 0:
                continue
            points = units * action.points_per_unit
            chosen.append(PlannedAction(action.action_id, action.skill_id, units, points, action.resource))
            remaining = max(0, remaining - points)
            if remaining == 0:
                break
        expected = sum(item.expected_points for item in chosen)
        feasible = remaining == 0
        return EventPlan(
            event.event_id, deadline, needed, tuple(chosen), expected, feasible,
            "NEED_PROGRESS" if feasible else "EVENT_TARGET_BLOCKED",
        )


def event_priority_modifier(events: dict[str, Any], skill_id: str) -> float:
    raw = events.get("minimum_guarantee") if isinstance(events, dict) else None
    if not isinstance(raw, dict) or raw.get("minimum_guarantee_complete") is True:
        return 0.0
    if int(raw.get("remaining_seconds", 0)) <= 0 or int(raw.get("points_missing", 0)) <= 0:
        return 0.0
    level = deadline_level(int(raw["remaining_seconds"]))
    deadline_weight = {DeadlineLevel.NORMAL: 1.0, DeadlineLevel.ELEVATED: 2.0,
                       DeadlineLevel.HIGH: 4.0, DeadlineLevel.P0: 10.0}[level]
    best = 0.0
    for action in raw.get("scoring_actions", []):
        if isinstance(action, dict) and action.get("skill_id") == skill_id and action.get("allowed", True):
            best = max(best, float(action.get("event_value", action.get("points_per_unit", 0))))
    return best * deadline_weight
