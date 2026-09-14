from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Page(str, Enum):
    HOME = "HOME"
    MAP = "MAP"
    LOADING = "LOADING"
    MAINTENANCE = "MAINTENANCE"
    RESOURCE_DETAIL = "RESOURCE_DETAIL"
    MARCH = "MARCH"
    MARCH_QUEUE = "MARCH_QUEUE"
    BUILDING = "BUILDING"
    RESEARCH = "RESEARCH"
    TRAINING = "TRAINING"
    INTEL = "INTEL"
    BEAST = "BEAST"
    DAILY = "DAILY"
    ALLIANCE = "ALLIANCE"
    MAIL = "MAIL"
    EXPLORATION = "EXPLORATION"
    HERO = "HERO"
    EVENT = "EVENT"
    POPUP = "POPUP"
    UNKNOWN = "UNKNOWN"


class MarchState(str, Enum):
    IDLE = "IDLE"
    MARCHING = "MARCHING"
    GATHERING = "GATHERING"
    RETURNING = "RETURNING"
    UNKNOWN = "UNKNOWN"


class SkillState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    STABLE = "STABLE"
    BLOCKED = "BLOCKED"


class LatencyClass(str, Enum):
    NORMAL = "NORMAL"
    FAST = "FAST"
    REALTIME = "REALTIME"


class IntelState(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLAIMABLE = "CLAIMABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WorldState:
    page: Page = Page.UNKNOWN
    popup: str | None = None
    resources: dict[str, int | None] = field(default_factory=dict)
    marches: tuple[MarchState, ...] = ()
    march_used: int | None = None
    march_max: int | None = None
    normal_march_slots: int | None = None
    normal_idle_slots: int | None = None
    bear_rally_special_slot: bool | None = None
    bear_rally_special_available: bool | None = None
    building: dict[str, Any] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)
    training: dict[str, Any] = field(default_factory=dict)
    events: dict[str, Any] = field(default_factory=dict)
    alliance: dict[str, Any] = field(default_factory=dict)
    intel: dict[str, Any] = field(default_factory=dict)
    beast: dict[str, Any] = field(default_factory=dict)
    daily: dict[str, Any] = field(default_factory=dict)
    mail: dict[str, Any] = field(default_factory=dict)
    exploration: dict[str, Any] = field(default_factory=dict)
    stamina: dict[str, Any] = field(default_factory=dict)
    hospital: dict[str, Any] = field(default_factory=dict)
    defense: dict[str, Any] = field(default_factory=dict)
    rewards: dict[str, Any] = field(default_factory=dict)
    account_stage: dict[str, Any] = field(default_factory=dict)
    resource_bank: dict[str, Any] = field(default_factory=dict)
    queues: dict[str, Any] = field(default_factory=dict)
    rally: dict[str, Any] = field(default_factory=dict)
    hero_troop: dict[str, Any] = field(default_factory=dict)
    attempts: dict[str, Any] = field(default_factory=dict)
    battlefield: dict[str, Any] = field(default_factory=dict)
    inventory: dict[str, Any] = field(default_factory=dict)
    resource_target: str | None = None
    resource_search_open: bool = False
    resource_search_exhausted: bool = False
    resource_selected: str | None = None
    resource_level: int | None = None
    resource_available: bool | None = None
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def known(self) -> bool:
        return self.page is not Page.UNKNOWN

    @property
    def idle_marches(self) -> int | None:
        if self.normal_idle_slots is not None:
            return self.normal_idle_slots
        if self.march_used is None or self.march_max is None:
            return None
        return max(0, self.march_max - self.march_used)

    @property
    def effective_normal_march_slots(self) -> int | None:
        return self.normal_march_slots if self.normal_march_slots is not None else self.march_max

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    skill: str
    reason: str
    confidence: float
    expected_result: str


@dataclass(frozen=True)
class Action:
    kind: str
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    executed: bool
    dry_run: bool
    action: Action
    error: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
