from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


BASE_RESOURCES = ("MEAT", "WOOD", "COAL", "IRON")
TROOP_TYPES = ("INFANTRY", "LANCER", "MARKSMAN")


@dataclass(frozen=True)
class PolicyDecision:
    goal: str
    reason: str
    parameters: dict[str, object]
    blocked: bool = False


def choose_resource_balanced(
    stock: Mapping[str, int | None],
    dispatched: Mapping[str, int] | None = None,
    weights: Mapping[str, float] | None = None,
) -> PolicyDecision:
    """Select the largest normalized deficit; unknown stock uses dispatch history."""
    dispatched = dispatched or {}
    weights = weights or {name: 1.0 for name in BASE_RESOURCES}
    known = {name: stock.get(name) for name in BASE_RESOURCES}
    if all(value is not None for value in known.values()):
        target = min(BASE_RESOURCES, key=lambda name: float(known[name]) / max(float(weights.get(name, 1)), .001))
        return PolicyDecision("GATHER_RESOURCE", "largest_weighted_resource_deficit", {"resource": target})
    target = min(BASE_RESOURCES, key=lambda name: int(dispatched.get(name, 0)))
    return PolicyDecision("GATHER_RESOURCE", "balanced_round_robin_without_reliable_inventory", {"resource": target})


def choose_troop_rotation(queue_busy: Mapping[str, bool], trained: Mapping[str, int] | None = None) -> PolicyDecision:
    trained = trained or {}
    available = [name for name in TROOP_TYPES if not queue_busy.get(name, False)]
    if not available:
        return PolicyDecision("TRAIN", "all_training_queues_busy", {}, True)
    target = min(available, key=lambda name: int(trained.get(name, 0)))
    return PolicyDecision("TRAIN", "least_trained_available_troop", {"troop_type": target})


def choose_stamina_goal(current: int | None, intel_status: str, giant_beast_ready: bool, beast_ready: bool) -> PolicyDecision:
    if current is None:
        return PolicyDecision("OBSERVE_STAMINA", "stamina_unknown_no_spend", {}, True)
    if current <= 30:
        return PolicyDecision("NONE", "stamina_reserve_not_exceeded", {"stamina": current})
    if intel_status in {"AVAILABLE", "CLAIMABLE", "IN_PROGRESS"}:
        return PolicyDecision("INTEL", "stamina_above_30_intel_first", {"stamina": current})
    if giant_beast_ready:
        return PolicyDecision("GIANT_BEAST", "intel_unavailable_use_verified_giant_beast", {"stamina": current})
    if beast_ready:
        return PolicyDecision("BEAST_HUNT", "intel_unavailable_use_verified_beast", {"stamina": current})
    return PolicyDecision("STAMINA_BLOCKED", "no_verified_stamina_sink", {"stamina": current}, True)


def choose_shield(incoming_attack: bool, incoming_troops: int | None, free_shields: Mapping[str, int]) -> PolicyDecision:
    if not incoming_attack or incoming_troops is None or incoming_troops <= 100_000:
        return PolicyDecision("NONE", "no_verified_high_threat_city_attack", {})
    for duration in ("8H", "2H"):
        if int(free_shields.get(duration, 0)) > 0:
            return PolicyDecision("ACTIVATE_SHIELD", "verified_attack_over_100k", {"duration": duration})
    return PolicyDecision("DEFENSE_BLOCKED", "no_verified_free_shield", {"incoming_troops": incoming_troops}, True)


def choose_healing(wounded: int | None, capacity: int | None) -> PolicyDecision:
    if wounded is None or not capacity:
        return PolicyDecision("OBSERVE_HOSPITAL", "hospital_state_unknown", {}, True)
    ratio = wounded / capacity
    if ratio <= .05:
        return PolicyDecision("NONE", "wounded_not_over_5_percent", {"ratio": ratio})
    batch = min(1000, max(500, wounded // max(1, (wounded + 999) // 1000)))
    return PolicyDecision("HEAL_BATCH", "hospital_over_5_percent_use_alliance_help", {"batch": batch, "request_alliance_help": True})


def reward_candidates(red_dots: Sequence[str], verified_claim_pages: set[str]) -> tuple[str, ...]:
    """A red dot discovers work; it never authorizes an unverified click."""
    return tuple(page for page in red_dots if page in verified_claim_pages)


def operational_priority(goal: str, *, defense: Mapping[str, object], hospital: Mapping[str, object], stamina: Mapping[str, object]) -> float:
    """Priority modifier consumed by the one Scheduler; policies never execute."""
    troops = defense.get("incoming_troops")
    if goal == "ACTIVATE_SHIELD" and defense.get("incoming_attack") is True and isinstance(troops, int) and troops > 100_000:
        return 100_000.0
    wounded, capacity = hospital.get("wounded"), hospital.get("capacity")
    if goal == "HEAL_BATCH" and isinstance(wounded, int) and isinstance(capacity, int) and capacity > 0 and wounded / capacity > .05:
        return 10_000.0
    current = stamina.get("current")
    if goal in {"INTEL", "GIANT_BEAST", "BEAST_HUNT"} and isinstance(current, int) and current > 30:
        return 1_000.0 + current
    return 0.0
