from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .models import SkillState
from .skills import Skill


class ClaimDecision(str, Enum):
    AUTO_CLAIM = "AUTO_CLAIM"
    SELECT_REWARD_OPTION = "SELECT_REWARD_OPTION"
    STRATEGY_REQUIRED = "STRATEGY_REQUIRED"
    BLOCK_UNKNOWN_ACTION = "BLOCK_UNKNOWN_ACTION"
    BLOCK_REAL_MONEY = "BLOCK_REAL_MONEY"


@dataclass(frozen=True)
class ClaimContext:
    claimable: bool | None
    is_free: bool | None
    requires_choice: bool | None
    real_money_cost: bool | None
    game_resource_cost: bool | None
    consumes_item: bool | None
    reward_known: bool = False


def decide_claim(context: ClaimContext) -> ClaimDecision:
    """Unknown reward content is safe; unknown action/cost is not."""
    if context.real_money_cost is True:
        return ClaimDecision.BLOCK_REAL_MONEY
    if context.claimable is not True or context.is_free is not True:
        return ClaimDecision.BLOCK_UNKNOWN_ACTION
    if context.requires_choice is True:
        return ClaimDecision.SELECT_REWARD_OPTION
    cost_flags = (context.real_money_cost, context.game_resource_cost, context.consumes_item)
    if any(flag is None for flag in cost_flags) or context.requires_choice is None:
        return ClaimDecision.BLOCK_UNKNOWN_ACTION
    if context.game_resource_cost or context.consumes_item:
        return ClaimDecision.STRATEGY_REQUIRED
    return ClaimDecision.AUTO_CLAIM


@dataclass(frozen=True)
class SemanticGateResult:
    ok: bool
    failures: tuple[str, ...]


def semantic_robustness_gate(skill: Skill) -> SemanticGateResult:
    failures: list[str] = []
    if not skill.semantic_contract_complete:
        failures.append("SEMANTIC_CONTRACT_INCOMPLETE")
    forbidden = {"FIXED_COORDINATE_ONLY", "FIXED_NUMBER_ONLY", "FIXED_REWARD_ONLY",
                 "FIXED_EVENT_NAME_ONLY", "SINGLE_TEMPLATE_ONLY", "CLICK_SUCCESS_ONLY"}
    declared = {item.upper() for item in skill.vision_evidence + skill.semantic_requirements}
    failures.extend(sorted(forbidden & declared))
    if skill.state is SkillState.STABLE and failures:
        failures.append("STABLE_PROMOTION_REJECTED")
    return SemanticGateResult(not failures, tuple(failures))


def audit_vision_asset(asset: Mapping[str, Any]) -> SemanticGateResult:
    failures: list[str] = []
    if not asset.get("semantic"):
        failures.append("SEMANTIC_MISSING")
    roi = asset.get("roi_norm")
    if roi is None:
        failures.append("NORMALIZED_ROI_MISSING")
    elif not isinstance(roi, Mapping) or not all(key in roi for key in ("x_norm", "y_norm", "w_norm", "h_norm")):
        failures.append("NORMALIZED_ROI_INVALID")
    if not asset.get("source"):
        failures.append("PROVENANCE_MISSING")
    if asset.get("absolute_coordinate_only") is True:
        failures.append("ABSOLUTE_COORDINATE_ONLY")
    return SemanticGateResult(not failures, tuple(failures))


def stable_promotion_allowed(skill: Skill) -> SemanticGateResult:
    result = semantic_robustness_gate(skill)
    failures = list(result.failures)
    if skill.verifier in {None, "CLICK_SUCCESS", "TEMPLATE_DISAPPEARED_ONLY"}:
        failures.append("STATE_CHANGE_VERIFIER_REQUIRED")
    if len(skill.context) == 1 and skill.context[0].startswith("EVENT_NAME="):
        failures.append("SINGLE_EVENT_BINDING")
    return SemanticGateResult(not failures, tuple(dict.fromkeys(failures)))


def can_promote_stable(skill: Skill) -> bool:
    return stable_promotion_allowed(skill).ok and skill.state in {SkillState.VERIFIED, SkillState.STABLE}
