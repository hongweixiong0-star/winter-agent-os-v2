from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import Any, Mapping


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


# --------------------------------------------------------------- known activities
#
# Operator directive 2026-09-23 §二/§三: 知道未来有什么事 -- for a known periodic activity the plan
# has to survive the gap between occurrences, without the agent navigating anywhere to find an
# entrance that is not drawn yet, and without inventing a start time it never measured.
#
# This is a *reader*, not a second knowledge base.  ``knowledge/events/event_registry.json`` is the
# project's existing activity registry (its own ``policy`` already defines what adding an entry
# costs: a new or changed event enters at DISCOVERED and production requires VERIFIED).  What this
# adds is the one thing the registry could not answer, because nothing was reading it: which of the
# activities it names are real enough to hold a plan against, and what that plan is.
#
# Why it is needed at all is measurable.  Before this, an activity existed in the agent's world only
# as a field on a frame: ``world.events`` is written in exactly one place (``ocr.py``, from what the
# current page prints), and ``GoalLibrary`` emitted ``PARTICIPATE_BEAR``/``EVENT_MINIMUM_GUARANTEE``
# only when that field was present.  Measured over the production corpus (2026-09-23): of 7593
# episodes, 5 carried ``minimum_guarantee`` and **none** carried ``bear``.  So "we are not standing
# on the page that prints it" and "this task does not exist" were the same state of the world, and
# there was nothing to prepare for, nothing to wait for, and no record of a window closing.

ACTIVITY_REGISTRY = Path(__file__).resolve().parents[1] / "knowledge/events/event_registry.json"

#: Registry entries that have an identity in the canonical event catalog.  Registration is not
#: approval to act: DISCOVERED items stay UNKNOWN until the current client supplies an event page,
#: timer, or other positive condition.  Filtering them out here made "not yet verified" look like
#: "does not exist", which prevented the already-registered generic flow/Qwen fallback from ever
#: seeing a newly discovered event.
_KNOWN_GATES = frozenset({"DISCOVERED", "REVIEWED", "VERIFIED"})


class WindowState(str, Enum):
    """Whether an activity's window is open, and what is known about when it will be.

    Deliberately four values and not two: ``UNKNOWN`` is the honest answer when the activity is
    real but nothing readable says when it opens, and collapsing it into "not open" would make a
    preparation plan look like a closed window.
    """

    OPEN = "OPEN"
    SCHEDULED_NOT_OPEN = "SCHEDULED_NOT_OPEN"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Activity:
    """One known periodic activity, with the plan that has to survive until it opens (§二)."""

    event_id: str
    name: str
    gate: str
    aliases: tuple[str, ...]
    cadence: str
    applies_to_roles: Mapping[str, Any]
    next_open_condition: Mapping[str, Any]
    participation_conditions: tuple[str, ...]
    unwired_steps: tuple[str, ...]
    knowledge: tuple[str, ...]
    prepare: tuple[str, ...]
    occurrence: Mapping[str, Any]
    start: str | None = None
    end: str | None = None

    @property
    def time_is_known(self) -> bool:
        """Whether a *reliable* start or end time is on file.

        Both are null for every event this project has ever recorded, which is the point: §二 says
        如果时间信息不可靠，保留 UNKNOWN，不编造活动时间.  So the window is answered by
        ``next_open_condition`` -- what the game itself printed -- and never by the clock.
        """
        return bool(self.start or self.end)

    def window(self, now: datetime | None = None) -> WindowState:
        """The window **as the record knows it**, with no live reading in hand.

        Deliberately takes no countdown.  When the client is printing one, ``rally.bear_phase``
        already owns every threshold that turns it into a phase (120 s -> READY, 600 s -> PREPARING),
        and a second copy of those numbers here is the "one table, two readers" mistake this project
        has already paid for.  This answers the other question: standing anywhere else, what does
        the record support?

        * no trustworthy current-occurrence timer -> ``UNKNOWN``.  The registry's ``occurrence`` is
          historical evidence; an expired past instance does not prove today's recurring event is
          closed;
        * a future, timezone-aware start -> ``SCHEDULED_NOT_OPEN``;
        * a reached start with no reached end -> ``OPEN``;
        * a reached end -> ``EXPIRED``;
        * nothing reliable on file -> ``UNKNOWN``.  §二: 如果时间信息不可靠，保留 UNKNOWN，不编造
          活动时间.  ``UNKNOWN`` is not "not open" -- it is "we cannot say", and the plan is kept
          either way.
        """
        def instant(value: str | None) -> datetime | None:
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                return None
            # A local timestamp without an offset cannot drive an unattended wake safely.
            return parsed if parsed.tzinfo is not None else None

        start = instant(self.start)
        end = instant(self.end)
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if end is not None and moment >= end:
            return WindowState.EXPIRED
        if start is not None:
            return WindowState.OPEN if moment >= start else WindowState.SCHEDULED_NOT_OPEN
        if not self.time_is_known:
            return WindowState.UNKNOWN
        return WindowState.UNKNOWN

    def plan(self) -> dict[str, Any]:
        """The part of this record a run needs in order to prepare rather than to act."""
        return {
            "event_id": self.event_id,
            "name": self.name,
            "gate": self.gate,
            "aliases": list(self.aliases),
            "registration_state": "REGISTERED",
            "current_occurrence_state": "UNKNOWN",
            "execution_readiness": "AWAITING_LIVE_CLIENT_READING",
            "cadence": self.cadence,
            "applies_to_roles": dict(self.applies_to_roles),
            "next_open_condition": dict(self.next_open_condition),
            "participation_conditions": list(self.participation_conditions),
            "unwired_steps": list(self.unwired_steps),
            "knowledge": list(self.knowledge),
            "prepare": list(self.prepare),
            "occurrence": dict(self.occurrence),
            "reliable_start": self.start,
            "reliable_end": self.end,
        }


def known_activities(path: Path | str | None = None) -> tuple[Activity, ...]:
    """Every named activity in the canonical registry, including DISCOVERED candidates.

    Unreadable or malformed registry -> no activities, never an exception: a knowledge file that a
    run cannot parse is a gap in the plan, not a reason for the run to die.  Same trade the rest of
    this project makes with the template manifest and the UI dictionary.
    """
    target = Path(path) if path is not None else ACTIVITY_REGISTRY
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    out: list[Activity] = []
    for record in payload.get("events") or ():
        if not isinstance(record, Mapping):
            continue
        gate = str(record.get("gate") or "DISCOVERED").upper()
        if gate not in _KNOWN_GATES:
            continue
        out.append(Activity(
            event_id=str(record.get("event_id") or ""),
            name=str(record.get("name") or ""),
            gate=gate,
            aliases=tuple(str(x) for x in (record.get("aliases") or ())),
            cadence=str(record.get("cadence") or "UNKNOWN"),
            applies_to_roles=record.get("applies_to_roles") or {},
            next_open_condition=record.get("next_open_condition") or {},
            participation_conditions=tuple(str(x) for x in (record.get("participation_conditions") or ())),
            unwired_steps=tuple(str(x) for x in (record.get("unwired_steps") or ())),
            knowledge=tuple(str(x) for x in (record.get("knowledge") or ())),
            prepare=tuple(str(x) for x in (record.get("prepare") or ())),
            occurrence=record.get("occurrence") or {},
            start=record.get("start"),
            end=record.get("end"),
        ))
    return tuple(activity for activity in out if activity.event_id)


@lru_cache(maxsize=1)
def _event_label_index() -> dict[str, str]:
    """Index exact client title aliases from the canonical activity registry.

    OCR must not carry a second, hand-maintained event-name list.  The registry is loaded once
    per process; changes to it already require the normal safe runtime reload before production
    can use the new code/data revision.
    """
    labels: dict[str, str] = {}
    for activity in known_activities():
        for label in (activity.name, *activity.aliases):
            key = " ".join(str(label).strip().casefold().split())
            if key:
                labels[key] = activity.event_id
    return labels


def event_id_for_label(label: object) -> str | None:
    """Resolve an exact known event heading; unknown text stays unknown."""
    key = " ".join(str(label or "").strip().casefold().split())
    return _event_label_index().get(key) if key else None
