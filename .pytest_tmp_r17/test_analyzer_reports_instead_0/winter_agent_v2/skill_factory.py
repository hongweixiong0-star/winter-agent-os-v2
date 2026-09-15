from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .models import SkillState
from .skills import SkillRegistry


@dataclass(frozen=True)
class OperationPrior:
    skill_id: str
    goal_support: tuple[str, ...]
    entry_pages: tuple[str, ...]
    target_pages: tuple[str, ...]
    required_semantics: tuple[str, ...]
    execute_steps: tuple[str, ...]
    success_conditions: tuple[str, ...]
    risk: str = "LOW"


GOAL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "CLEAR_INTEL": ("OPEN_INTEL", "READ_INTEL_LIST", "SELECT_INTEL", "EXECUTE_INTEL", "CLAIM_INTEL"),
    "DAILY_ACTIVITY_TARGET": ("OPEN_DAILY", "READ_DAILY_PROGRESS", "DAILY_CLAIM_REWARDS"),
    "CLAIM_FREE_REWARDS": ("CLAIM_FREE_REWARD", "OPEN_VIP", "CLAIM_VIP_FREE"),
    "USE_FREE_ARENA_ATTEMPTS": ("OPEN_ARENA", "READ_FREE_ATTEMPTS", "SELECT_ARENA_OPPONENT", "START_ARENA", "VERIFY_ARENA_RESULT"),
    "EVENT_MINIMUM_GUARANTEE": ("OPEN_EVENT", "READ_EVENT_LIST", "READ_EVENT_TIMER", "READ_EVENT_PROGRESS", "READ_EVENT_RULES", "READ_EVENT_REWARD_TIERS", "CLAIM_EVENT_TIER"),
    "PARTICIPATE_BEAR": ("CHECK_ALLIANCE_EVENT", "READ_BEAR_TIMER", "SELECT_TARGET", "SELECT_TROOP_PRESET", "START_RALLY", "JOIN_RALLY", "CONFIRM_MARCH"),
    "KEEP_MARCHES_PRODUCTIVE": ("OPEN_MAP", "SEARCH_RESOURCE", "SELECT_RESOURCE", "CHECK_MARCH", "DISPATCH_MARCH", "VERIFY_GATHERING"),
    "KEEP_BUILDING_PRODUCTIVE": ("OPEN_BUILDING", "BUILDING_UPGRADE"),
    "KEEP_RESEARCH_PRODUCTIVE": ("OPEN_RESEARCH", "RESEARCH"),
    "KEEP_TRAINING_PRODUCTIVE": ("OPEN_TRAINING", "TRAIN_TROOPS", "PROMOTE_TROOPS"),
    "ALLIANCE_ROUTINE": ("OPEN_ALLIANCE", "ALLIANCE_HELP", "ALLIANCE_TECH_CONTRIBUTE", "ALLIANCE_GIFTS"),
    "CLAIM_EXPLORATION_IDLE": ("OPEN_EXPLORATION", "EXPLORATION_IDLE_CLAIM"),
    "AVOID_STAMINA_WASTE": ("OPEN_INTEL", "READ_INTEL_LIST", "BEAST_HUNT", "JOIN_POLAR_TERROR_RALLY"),
    "LABYRINTH_DAILY": ("OPEN_LABYRINTH", "READ_LABYRINTH_ATTEMPTS", "START_LABYRINTH", "VERIFY_LABYRINTH_RESULT"),
    "ALLIANCE_TIMED_EVENTS": ("CHECK_ALLIANCE_EVENT", "READ_ALLIANCE_EVENT_TIMER", "CLAIM_EVENT_TIER"),
}


def _prior(skill_id: str, goals: tuple[str, ...], entry: tuple[str, ...], target: tuple[str, ...], semantics: tuple[str, ...], steps: tuple[str, ...], success: tuple[str, ...], risk: str = "LOW") -> OperationPrior:
    return OperationPrior(skill_id, goals, entry, target, semantics, steps, success, risk)


PRIORS: dict[str, OperationPrior] = {
    "READ_INTEL_LIST": _prior("READ_INTEL_LIST", ("CLEAR_INTEL",), ("INTEL",), ("INTEL",), ("INTEL_CARD", "INTEL_STATUS"), ("SCREENSHOT", "OCR_INTEL_CARDS", "CLASSIFY_STATUS"), ("intel_count_and_status_known",)),
    "SELECT_INTEL": _prior("SELECT_INTEL", ("CLEAR_INTEL",), ("INTEL",), ("POPUP", "MAP"), ("INTEL_AVAILABLE_CARD",), ("FIND_SEMANTIC", "TAP_CENTER", "SCREENSHOT"), ("selected_mission_identity_matches",)),
    "EXECUTE_INTEL": _prior("EXECUTE_INTEL", ("CLEAR_INTEL",), ("POPUP", "MAP", "BEAST"), ("MARCH", "INTEL"), ("INTEL_EXECUTE", "STAMINA_COST"), ("VERIFY_COST", "TAP_CENTER", "SCREENSHOT"), ("mission_status_changed",), "MEDIUM_STAMINA_SPEND"),
    "CLAIM_INTEL": _prior("CLAIM_INTEL", ("CLEAR_INTEL",), ("INTEL",), ("INTEL", "POPUP"), ("INTEL_CLAIMABLE",), ("FIND_SEMANTIC", "TAP_CENTER", "SCREENSHOT"), ("claimable_count_decreased",)),
    "READ_DAILY_PROGRESS": _prior("READ_DAILY_PROGRESS", ("DAILY_ACTIVITY_TARGET",), ("DAILY",), ("DAILY",), ("DAILY_ACTIVITY_COUNTER", "DAILY_REWARD_TIER"), ("SCREENSHOT", "OCR_PROGRESS", "CLASSIFY_TIERS"), ("activity_and_tiers_known",)),
    "CLAIM_FREE_REWARD": _prior("CLAIM_FREE_REWARD", ("CLAIM_FREE_REWARDS",), ("HOME", "EVENT", "VIP", "ALLIANCE"), ("POPUP",), ("FREE_LABEL", "CLAIM_BUTTON"), ("VERIFY_FREE_OR_ZERO_COST", "TAP_CENTER", "SCREENSHOT"), ("claim_state_changed",), "LOW"),
    "OPEN_VIP": _prior("OPEN_VIP", ("CLAIM_FREE_REWARDS",), ("HOME",), ("VIP",), ("BTN_OPEN_VIP",), ("FIND_SEMANTIC", "TAP_CENTER", "SCREENSHOT"), ("page_is_vip",)),
    "CLAIM_VIP_FREE": _prior("CLAIM_VIP_FREE", ("CLAIM_FREE_REWARDS",), ("VIP",), ("VIP", "POPUP"), ("VIP_FREE_CHEST",), ("VERIFY_FREE", "TAP_CENTER", "SCREENSHOT"), ("free_chest_claimed",)),
    "OPEN_ARENA": _prior("OPEN_ARENA", ("USE_FREE_ARENA_ATTEMPTS",), ("HOME",), ("ARENA",), ("BTN_OPEN_ARENA",), ("FIND_SEMANTIC", "TAP_CENTER", "SCREENSHOT"), ("page_is_arena",)),
    "READ_FREE_ATTEMPTS": _prior("READ_FREE_ATTEMPTS", ("USE_FREE_ARENA_ATTEMPTS",), ("ARENA",), ("ARENA",), ("ARENA_FREE_ATTEMPTS",), ("SCREENSHOT", "OCR_COUNTER"), ("free_attempts_known",)),
    "SELECT_ARENA_OPPONENT": _prior("SELECT_ARENA_OPPONENT", ("USE_FREE_ARENA_ATTEMPTS",), ("ARENA",), ("ARENA",), ("ARENA_OPPONENT_CARD", "POWER"), ("READ_OPPONENTS", "SELECT_HIGH_CONFIDENCE_WIN", "TAP_CENTER"), ("opponent_selected",), "LOW_COMBAT"),
    "START_ARENA": _prior("START_ARENA", ("USE_FREE_ARENA_ATTEMPTS",), ("ARENA",), ("ARENA", "POPUP"), ("BTN_ARENA_CHALLENGE_FREE",), ("VERIFY_FREE_ATTEMPT", "TAP_CENTER"), ("battle_started",), "LOW_COMBAT"),
    "VERIFY_ARENA_RESULT": _prior("VERIFY_ARENA_RESULT", ("USE_FREE_ARENA_ATTEMPTS",), ("ARENA", "POPUP"), ("ARENA",), ("ARENA_RESULT", "ARENA_FREE_ATTEMPTS"), ("SCREENSHOT", "OCR_RESULT_AND_COUNTER"), ("free_attempts_decreased",)),
    "OPEN_EVENT": _prior("OPEN_EVENT", ("EVENT_MINIMUM_GUARANTEE",), ("HOME",), ("EVENT",), ("BTN_OPEN_EVENT",), ("FIND_SEMANTIC", "TAP_CENTER", "SCREENSHOT"), ("page_is_event",)),
    "READ_EVENT_LIST": _prior("READ_EVENT_LIST", ("EVENT_MINIMUM_GUARANTEE",), ("EVENT",), ("EVENT",), ("EVENT_CARD",), ("SCREENSHOT", "OCR_EVENT_NAMES"), ("active_events_known",)),
    "READ_EVENT_TIMER": _prior("READ_EVENT_TIMER", ("EVENT_MINIMUM_GUARANTEE", "PARTICIPATE_BEAR"), ("EVENT", "ALLIANCE"), ("EVENT", "ALLIANCE"), ("EVENT_TIMER",), ("SCREENSHOT", "OCR_TIMER"), ("remaining_time_known",)),
    "READ_EVENT_PROGRESS": _prior("READ_EVENT_PROGRESS", ("EVENT_MINIMUM_GUARANTEE",), ("EVENT",), ("EVENT",), ("EVENT_POINTS", "EVENT_REWARD_TIER"), ("SCREENSHOT", "OCR_PROGRESS"), ("current_points_and_tiers_known",)),
    "READ_EVENT_RULES": _prior("READ_EVENT_RULES", ("EVENT_MINIMUM_GUARANTEE",), ("EVENT",), ("EVENT",), ("BTN_EVENT_RULES", "EVENT_SCORING_ROW"), ("OPEN_RULES", "OCR_SCORING_ACTIONS", "BACK"), ("scoring_actions_known",)),
    "READ_EVENT_REWARD_TIERS": _prior("READ_EVENT_REWARD_TIERS", ("EVENT_MINIMUM_GUARANTEE",), ("EVENT",), ("EVENT",), ("EVENT_REWARD_TIER",), ("SCREENSHOT", "OCR_TIERS"), ("reward_tiers_known",)),
    "CLAIM_EVENT_TIER": _prior("CLAIM_EVENT_TIER", ("EVENT_MINIMUM_GUARANTEE", "ALLIANCE_TIMED_EVENTS"), ("EVENT",), ("EVENT", "POPUP"), ("EVENT_TIER_CLAIMABLE",), ("FIND_SEMANTIC", "TAP_CENTER", "SCREENSHOT"), ("tier_state_is_claimed",)),
    "CHECK_ALLIANCE_EVENT": _prior("CHECK_ALLIANCE_EVENT", ("PARTICIPATE_BEAR", "ALLIANCE_TIMED_EVENTS"), ("ALLIANCE",), ("ALLIANCE", "EVENT"), ("ALLIANCE_EVENT_ENTRY",), ("OPEN_ENTRY", "SCREENSHOT", "OCR_EVENT_STATE"), ("event_identity_and_timer_known",)),
    "READ_BEAR_TIMER": _prior("READ_BEAR_TIMER", ("PARTICIPATE_BEAR",), ("ALLIANCE", "EVENT"), ("EVENT",), ("BEAR_TIMER",), ("SCREENSHOT", "OCR_TIMER"), ("bear_start_time_known",)),
    "PREPARE_BEAR_MARCH": _prior("PREPARE_BEAR_MARCH", ("PARTICIPATE_BEAR",), ("HOME", "MAP"), ("HOME", "MAP"), ("MARCH_QUEUE",), ("READ_MARCHES", "RECALL_LOW_VALUE_IF_REQUIRED"), ("required_march_available",), "MEDIUM"),
    "SELECT_TARGET": _prior("SELECT_TARGET", ("PARTICIPATE_BEAR", "AVOID_STAMINA_WASTE", "ALLIANCE_TIMED_EVENTS"), ("ALLIANCE", "EVENT", "MAP"), ("ALLIANCE", "MARCH"), ("RALLY_TARGET",), ("FILTER_TARGET_TYPE", "SELECT_FIRST_ELIGIBLE"), ("target_identity_matches",), "LOW"),
    "SELECT_TROOP_PRESET": _prior("SELECT_TROOP_PRESET", ("PARTICIPATE_BEAR", "AVOID_STAMINA_WASTE", "ALLIANCE_TIMED_EVENTS"), ("MARCH",), ("MARCH",), ("TROOP_PRESET",), ("APPLY_CONTEXT_TROOP_POLICY",), ("troop_policy_applied",), "MEDIUM_COMBAT"),
    "CONFIRM_MARCH": _prior("CONFIRM_MARCH", ("PARTICIPATE_BEAR", "AVOID_STAMINA_WASTE", "ALLIANCE_TIMED_EVENTS"), ("MARCH",), ("MAP", "ALLIANCE"), ("BTN_DISPATCH",), ("TAP_CONFIRM",), ("march_started",), "MEDIUM_COMBAT"),
    "OPEN_BUILDING": _prior("OPEN_BUILDING", ("KEEP_BUILDING_PRODUCTIVE",), ("HOME",), ("BUILDING",), ("BUILDING_UPGRADABLE",), ("FIND_SEMANTIC", "TAP_CENTER"), ("page_is_building",)),
    "OPEN_RESEARCH": _prior("OPEN_RESEARCH", ("KEEP_RESEARCH_PRODUCTIVE",), ("HOME",), ("RESEARCH",), ("RESEARCH_CENTER",), ("FIND_SEMANTIC", "TAP_CENTER"), ("page_is_research",)),
    "OPEN_TRAINING": _prior("OPEN_TRAINING", ("KEEP_TRAINING_PRODUCTIVE",), ("HOME",), ("TRAINING",), ("TRAINING_CAMP_AVAILABLE",), ("SELECT_BALANCED_TROOP_CAMP", "TAP_CENTER"), ("page_is_training_and_type_matches",)),
    "PROMOTE_TROOPS": _prior("PROMOTE_TROOPS", ("KEEP_TRAINING_PRODUCTIVE",), ("TRAINING",), ("TRAINING",), ("BTN_PROMOTE_TROOPS",), ("VERIFY_QUEUE_FREE", "TAP_CENTER"), ("training_queue_active",), "MEDIUM_RESOURCE_SPEND"),
    "OPEN_LABYRINTH": _prior("OPEN_LABYRINTH", ("LABYRINTH_DAILY",), ("HOME",), ("LABYRINTH",), ("BTN_OPEN_LABYRINTH",), ("FIND_SEMANTIC", "TAP_CENTER"), ("page_is_labyrinth",)),
    "READ_LABYRINTH_ATTEMPTS": _prior("READ_LABYRINTH_ATTEMPTS", ("LABYRINTH_DAILY",), ("LABYRINTH",), ("LABYRINTH",), ("LABYRINTH_ATTEMPTS",), ("SCREENSHOT", "OCR_COUNTER"), ("attempts_known",)),
    "START_LABYRINTH": _prior("START_LABYRINTH", ("LABYRINTH_DAILY",), ("LABYRINTH",), ("LABYRINTH", "MARCH"), ("LABYRINTH_START",), ("VERIFY_FREE_ATTEMPT", "TAP_CENTER"), ("attempt_started",), "LOW_COMBAT"),
    "VERIFY_LABYRINTH_RESULT": _prior("VERIFY_LABYRINTH_RESULT", ("LABYRINTH_DAILY",), ("LABYRINTH", "POPUP"), ("LABYRINTH",), ("LABYRINTH_RESULT",), ("SCREENSHOT", "OCR_RESULT"), ("attempts_decreased",)),
    "READ_ALLIANCE_EVENT_TIMER": _prior("READ_ALLIANCE_EVENT_TIMER", ("ALLIANCE_TIMED_EVENTS",), ("ALLIANCE", "EVENT"), ("EVENT",), ("ALLIANCE_EVENT_TIMER",), ("SCREENSHOT", "OCR_TIMER"), ("remaining_time_known",)),
}


ALIASES = {"CLAIM_INTEL":"INTEL_CLAIM_REWARDS", "CLAIM_EVENT_REWARD":"CLAIM_EVENT_TIER", "UPGRADE_BUILDING":"BUILDING_UPGRADE", "START_RESEARCH":"RESEARCH", "CHECK_MARCH_SLOT":"CHECK_MARCH", "CLAIM_ALLIANCE_GIFT":"ALLIANCE_GIFTS", "CLAIM_MAIL_REWARD":"MAIL_CLAIM_REWARDS", "CLAIM_EXPLORATION_IDLE":"EXPLORATION_IDLE_CLAIM"}


class SkillFactory:
    def __init__(self, registry: SkillRegistry, output_dir: Path) -> None:
        self.registry, self.output_dir = registry, output_dir

    def lifecycle(self, skill_id: str) -> str:
        actual = ALIASES.get(skill_id, skill_id)
        skill = self.registry.get(actual)
        return skill.state.value if skill else ("CANDIDATE" if skill_id in PRIORS else "MISSING")

    def generate_candidates(self) -> tuple[Path, ...]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for skill_id, prior in PRIORS.items():
            if self.registry.get(ALIASES.get(skill_id, skill_id)):
                continue
            path = self.output_dir / f"{skill_id}.json"
            if path.exists():
                continue
            payload = asdict(prior) | {
                "semantic_goal": prior.skill_id.replace("_", " ").title(),
                "parameters": [],
                "context": list(prior.entry_pages),
                "semantic_requirements": list(prior.required_semantics),
                "vision_evidence": ["PAGE_STATE", "SEMANTIC_ANCHOR", "RELATIVE_LAYOUT"],
                "preconditions": ["entry page recognized", "required semantics or reviewed prior available", "action-specific verifier exists before real try"],
                "failure_conditions": ["UNKNOWN_PAGE", "SEMANTIC_NOT_FOUND", "VERIFIER_FAILED", "PAID_ACTION"],
                "recovery": ["REFRESH_STATE", "BACK", "REOPEN_PAGE", "SWITCH_TASK"],
                "unknown_policy": "UNKNOWN_CONTENT does not block a known safe action; UNKNOWN_ACTION or UNKNOWN_COST blocks execution",
                "ui_change_tolerance": ["ICON", "NUMBER", "POSITION", "RESOLUTION", "SKIN", "LIST_ORDER"],
                "resource_cost": "READ_FROM_CURRENT_CLIENT",
                "external_evidence": ["CURRENT_KNOWLEDGE_BASE", "EXTERNAL_WOS_PRIOR"],
                "live_evidence": [], "confidence": 0.45, "lifecycle": "CANDIDATE",
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(path)
        return tuple(written)

    def coverage_markdown(self) -> str:
        lines = ["# Skill Coverage", "", "Goal | Required | Existing | Candidate | Verified | Stable | Missing", "---|---:|---:|---:|---:|---:|---:"]
        for goal, required in GOAL_REQUIREMENTS.items():
            states = [self.lifecycle(skill) for skill in required]
            existing = sum(state != "MISSING" for state in states)
            lines.append(f"{goal} | {len(required)} | {existing} | {states.count('CANDIDATE')} | {states.count('VERIFIED')} | {states.count('STABLE')} | {states.count('MISSING')}")
        return "\n".join(lines) + "\n"

    def write_coverage(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.coverage_markdown(), encoding="utf-8")

    def automation_audit(self, verifier_skills: set[str], template_semantics: set[str], episode_counts: dict[str, int] | None = None) -> dict:
        episode_counts = episode_counts or {}
        rows = []
        weights = {"CLEAR_INTEL":10, "DAILY_ACTIVITY_TARGET":10, "CLAIM_FREE_REWARDS":10,
                   "USE_FREE_ARENA_ATTEMPTS":9, "EVENT_MINIMUM_GUARANTEE":10, "PARTICIPATE_BEAR":9}
        for goal, required in GOAL_REQUIREMENTS.items():
            skill_rows = []
            for skill_id in required:
                actual = ALIASES.get(skill_id, skill_id)
                lifecycle = self.lifecycle(skill_id)
                prior = PRIORS.get(skill_id)
                required_semantics = set(prior.required_semantics if prior else ())
                vision_missing = sorted(required_semantics - template_semantics)
                verifier_missing = lifecycle not in {SkillState.VERIFIED.value, SkillState.STABLE.value} and actual not in verifier_skills
                recovery_missing = prior is None and lifecycle == "MISSING"
                skill_rows.append({
                    "skill_id": skill_id, "actual_skill_id": actual, "lifecycle": lifecycle,
                    "vision_missing": vision_missing, "verifier_missing": verifier_missing,
                    "recovery_missing": recovery_missing, "external_prior_available": prior is not None,
                    "live_evidence_count": int(episode_counts.get(actual, 0)),
                })
            states = [item["lifecycle"] for item in skill_rows]
            if all(state == "STABLE" for state in states): status = "AUTOMATED_STABLE"
            elif all(state in {"VERIFIED", "STABLE"} for state in states): status = "AUTOMATED_VERIFIED"
            elif all(state == "MISSING" for state in states): status = "MISSING"
            elif all(state in {"CANDIDATE", "VERIFIED", "STABLE"} for state in states): status = "AUTOMATED_CANDIDATE"
            else: status = "PARTIAL"
            rows.append({"goal":goal, "status":status, "required_skills":list(required), "skills":skill_rows,
                         "goal_priority":weights.get(goal, 5)})
        total = len(rows)
        automated = sum(row["status"] in {"AUTOMATED_STABLE", "AUTOMATED_VERIFIED"} for row in rows)
        candidate = sum(row["status"] in {"AUTOMATED_CANDIDATE", "PARTIAL"} for row in rows)
        missing = total - automated - candidate
        leverage: dict[str, dict[str, float | int]] = {}
        for row in rows:
            for skill in row["skills"]:
                if skill["lifecycle"] in {"VERIFIED", "STABLE"} and not skill["vision_missing"] and not skill["verifier_missing"]:
                    continue
                item = leverage.setdefault(skill["skill_id"], {"blocked_goals":0, "priority_sum":0.0, "complexity":1.0})
                item["blocked_goals"] += 1
                item["priority_sum"] += row["goal_priority"]
                prior = PRIORS.get(skill["skill_id"])
                item["complexity"] = max(1.0, len(prior.execute_steps) / 2 if prior else 4.0)
        top = []
        for skill_id, item in leverage.items():
            score = float(item["blocked_goals"]) * float(item["priority_sum"]) / float(item["complexity"])
            top.append({"skill_id":skill_id, **item, "automation_leverage":round(score, 2)})
        top.sort(key=lambda item: (-item["automation_leverage"], item["skill_id"]))
        return {"summary":{"total":total, "automated":automated, "candidate_or_partial":candidate, "missing":missing,
                           "automated_percent":round(automated/total*100,1) if total else 0,
                           "candidate_percent":round(candidate/total*100,1) if total else 0,
                           "missing_percent":round(missing/total*100,1) if total else 0},
                "goals":rows, "top_leverage":top[:20]}

    @staticmethod
    def audit_markdown(audit: dict) -> str:
        lines = ["# Goal Automation Coverage", "", "Goal | Status | Required Skills | Missing Vision | Missing Verifier | Missing Recovery | External Prior | Live Evidence",
                 "---|---|---|---:|---:|---:|---:|---:"]
        for row in audit["goals"]:
            skills = row["skills"]
            lines.append(f"{row['goal']} | {row['status']} | {len(skills)} | {sum(bool(x['vision_missing']) for x in skills)} | {sum(x['verifier_missing'] for x in skills)} | {sum(x['recovery_missing'] for x in skills)} | {sum(x['external_prior_available'] for x in skills)} | {sum(x['live_evidence_count'] for x in skills)}")
        lines += ["", "## Top 20 Highest-Leverage Gaps", "", "Skill | Blocked Goals | Priority Sum | Complexity | Automation Leverage", "---|---:|---:|---:|---:"]
        for item in audit["top_leverage"]:
            lines.append(f"{item['skill_id']} | {item['blocked_goals']} | {item['priority_sum']:.0f} | {item['complexity']:.1f} | {item['automation_leverage']:.2f}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def goal_skill_graph() -> dict:
        reverse: dict[str, list[str]] = {}
        for goal, skills in GOAL_REQUIREMENTS.items():
            for skill in skills: reverse.setdefault(skill, []).append(goal)
        return {"schema_version":"1.0", "goals":{goal:list(skills) for goal, skills in GOAL_REQUIREMENTS.items()}, "skills":reverse}
