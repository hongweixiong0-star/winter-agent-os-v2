from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping


class Mechanism(str, Enum):
    NAVIGATION = "NAVIGATION"
    QUEUE_JOB = "QUEUE_JOB"
    MARCH_RESOURCE = "MARCH_RESOURCE"
    RALLY = "RALLY"
    LIMITED_ATTEMPTS = "LIMITED_ATTEMPTS"
    SCORING_WRAPPER = "SCORING_WRAPPER"
    MISSION_BOARD = "MISSION_BOARD"
    PHASE_STATE_MACHINE = "PHASE_STATE_MACHINE"
    WAVE_DEFENSE = "WAVE_DEFENSE"
    BATTLEFIELD_CONTROL = "BATTLEFIELD_CONTROL"
    SHOP_EXCHANGE = "SHOP_EXCHANGE"
    REWARD_CLAIM = "REWARD_CLAIM"
    REFRESH_REROLL = "REFRESH_REROLL"
    REGISTRATION_SNAPSHOT = "REGISTRATION_SNAPSHOT"
    COOLDOWN_TIMER = "COOLDOWN_TIMER"


class ResourceBucket(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    QUEUE_RESERVE = "QUEUE_RESERVE"
    EVENT_RESERVE = "EVENT_RESERVE"
    RARE_RESERVE = "RARE_RESERVE"
    DAILY_CAP = "DAILY_CAP"
    SPENDABLE = "SPENDABLE"


@dataclass(frozen=True)
class ResourcePosition:
    resource: str
    available: int
    protected: int = 0
    reserved: int = 0
    event_reserved: int = 0
    rare_reserved: int = 0

    @property
    def safe_to_spend(self) -> int:
        return max(0, self.available - self.protected - self.reserved - self.event_reserved - self.rare_reserved)


@dataclass(frozen=True)
class SpendDecision:
    allowed: bool
    amount: int
    safe_to_spend: int
    reason: str


def save_or_spend(position: ResourcePosition, amount: int, *, real_money: bool = False,
                  account_security: bool = False) -> SpendDecision:
    if real_money or account_security:
        return SpendDecision(False, amount, position.safe_to_spend, "HARD_SAFETY_BLOCK")
    if amount < 0:
        return SpendDecision(False, amount, position.safe_to_spend, "INVALID_AMOUNT")
    allowed = amount <= position.safe_to_spend
    return SpendDecision(allowed, amount, position.safe_to_spend,
                         "WITHIN_SPENDABLE_BUDGET" if allowed else "RESERVE_PROTECTED")


@dataclass(frozen=True)
class GoalContribution:
    goal_id: str
    contribution: float
    priority: float
    deadline_factor: float = 1.0


def action_utility(contributions: Iterable[GoalContribution], *, resource_opportunity_cost: float = 0,
                   risk: float = 0, time_cost: float = 0, expected_failure_cost: float = 0) -> float:
    gain = sum(row.contribution * row.priority * row.deadline_factor for row in contributions)
    return gain - resource_opportunity_cost - risk - time_cost - expected_failure_cost


@dataclass(frozen=True)
class EventAdapter:
    event_id: str
    mechanisms: tuple[Mechanism, ...]
    skill_parameters: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    special_rules: Mapping[str, object] = field(default_factory=dict)

    def validates(self, known_skills: Iterable[str]) -> bool:
        known = set(known_skills)
        return all(skill_id in known for skill_id in self.skill_parameters)


MECHANISM_SKILL_MAP: dict[Mechanism, tuple[str, ...]] = {
    Mechanism.NAVIGATION: ("NAVIGATE_TO", "RECOVER_HOME"),
    Mechanism.QUEUE_JOB: ("BUILDING_UPGRADE", "RESEARCH", "TRAIN_TROOPS"),
    Mechanism.MARCH_RESOURCE: ("SEND_MARCH", "RECALL_MARCH"),
    Mechanism.RALLY: ("START_RALLY", "JOIN_RALLY"),
    Mechanism.LIMITED_ATTEMPTS: ("READ_COUNTER", "USE_ACTIVITY_ATTEMPT"),
    Mechanism.SCORING_WRAPPER: ("READ_COUNTER",),
    Mechanism.REWARD_CLAIM: ("CLAIM_REWARD",),
    Mechanism.COOLDOWN_TIMER: ("READ_TIMER",),
}


def missing_mechanism_skills(mechanisms: Iterable[Mechanism], known_skills: Iterable[str]) -> tuple[str, ...]:
    known = set(known_skills)
    required = dict.fromkeys(skill for mechanism in mechanisms for skill in MECHANISM_SKILL_MAP.get(mechanism, ()))
    return tuple(skill for skill in required if skill not in known)
