from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Iterable

from .models import WorldState


class RallyTarget(str, Enum):
    BEAR = "BEAR"
    POLAR_TERROR = "POLAR_TERROR"
    FORTRESS = "FORTRESS"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class RallyRowState(str, Enum):
    JOINABLE = "JOINABLE"
    FULL = "FULL"
    EXPIRED = "EXPIRED"
    JOINED = "JOINED"
    UNKNOWN = "UNKNOWN"


class BearRole(str, Enum):
    LEADER = "LEADER"
    JOINER = "JOINER"
    AUTO = "AUTO"


class BearPhase(str, Enum):
    DISCOVERED = "DISCOVERED"
    SCHEDULED = "SCHEDULED"
    PREPARING = "PREPARING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class RallyRow:
    target_type: RallyTarget
    leader: str | None
    state: RallyRowState
    remaining_seconds: int | None = None
    capacity_used: int | None = None
    capacity_max: int | None = None
    required_queue_type: str = "NORMAL"
    join_point: tuple[int, int] | None = None

    @property
    def joinable(self) -> bool:
        capacity = self.capacity_used is None or self.capacity_max is None or self.capacity_used < self.capacity_max
        return self.target_type is RallyTarget.BEAR and self.state is RallyRowState.JOINABLE and capacity


@dataclass(frozen=True)
class BearGoalState:
    phase: BearPhase
    role: BearRole = BearRole.AUTO
    reserved_start_time: str | None = None
    remaining_seconds: int | None = None
    normal_idle_slots: int | None = None
    special_start_available: bool | None = None


def bear_phase(event_status: str | None, seconds_to_start: int | None, seconds_remaining: int | None) -> BearPhase:
    if event_status == "ACTIVE" or (seconds_remaining is not None and seconds_remaining > 0):
        return BearPhase.ACTIVE
    if event_status in {"FINISHED", "COOLDOWN"} or (seconds_remaining is not None and seconds_remaining <= 0):
        return BearPhase.FINISHED
    if seconds_to_start is None:
        return BearPhase.DISCOVERED
    if seconds_to_start <= 120:
        return BearPhase.READY
    if seconds_to_start <= 600:
        return BearPhase.PREPARING
    return BearPhase.SCHEDULED


def choose_bear_operation(world: WorldState, role: BearRole, rows: Iterable[RallyRow]) -> str | None:
    """Choose WHAT only; execution stays in generic START_RALLY/JOIN_RALLY skills."""
    joinable = any(row.joinable for row in rows)
    normal_idle = world.idle_marches
    can_join = joinable and normal_idle is not None and normal_idle > 0
    can_start = world.bear_rally_special_available is True
    if role is BearRole.JOINER:
        return "JOIN_RALLY" if can_join else None
    if role is BearRole.LEADER:
        if can_start:
            return "START_RALLY"
        return "JOIN_RALLY" if can_join else None
    if can_start:
        return "START_RALLY"
    return "JOIN_RALLY" if can_join else None


def fastest_joinable_bear(rows: Iterable[RallyRow]) -> RallyRow | None:
    eligible = [row for row in rows if row.joinable]
    return min(eligible, key=lambda row: row.remaining_seconds if row.remaining_seconds is not None else 10**9, default=None)


def body_hero_order(available: Iterable[str]) -> tuple[str, ...]:
    available_set = {str(name).upper() for name in available}
    preferred = ("JESSIE", "SEO_YOON", "JASSER")
    selected = tuple(name for name in preferred if name in available_set)
    return selected + ("NO_HERO",)


@dataclass
class RallyMetrics:
    join_attempts: int = 0
    join_success: int = 0
    rally_full: int = 0
    join_failure: int = 0
    last_detect_to_join_ms: int | None = None
    last_join_to_confirm_ms: int | None = None
    last_total_join_ms: int | None = None
    _detected_at: float | None = field(default=None, repr=False)
    _clicked_at: float | None = field(default=None, repr=False)

    def detected(self) -> None:
        self._detected_at = monotonic()

    def clicked(self) -> None:
        self.join_attempts += 1
        self._clicked_at = monotonic()
        if self._detected_at is not None:
            self.last_detect_to_join_ms = round((self._clicked_at - self._detected_at) * 1000)

    def confirmed(self) -> None:
        now = monotonic()
        self.join_success += 1
        if self._clicked_at is not None:
            self.last_join_to_confirm_ms = round((now - self._clicked_at) * 1000)
        if self._detected_at is not None:
            self.last_total_join_ms = round((now - self._detected_at) * 1000)

    def race_lost(self) -> None:
        self.rally_full += 1

