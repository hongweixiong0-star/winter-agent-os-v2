"""Goal capability coverage, computed over the canonical capability layer.

A goal used to be modelled as a flat list of skill names and scored by matching
those names against the registry.  The two vocabularies had drifted apart, so a
goal whose requirement said ``SELECT_INTEL``/``EXECUTE_INTEL`` was scored against
registry ids ``SELECT_INTEL_BEAST_MISSION``/``DISPATCH_INTEL_BEAST`` and looked
unimplemented, while requirements naming skills that do not exist looked fine.

The model here is:

    Goal -> Canonical Capability -> Registered Skill Implementation -> Production Evidence

The mapping lives in ``knowledge/goals/goal_capability_map.json`` and supports
ALL_OF / ANY_OF / VARIANT / SEQUENCE.  Four layers are reported separately so a
goal can no longer be described by a single number:

    design_coverage         the capability is named at all
    implementation_coverage a registered, verifier-backed skill can perform it
    live_coverage           the production episode stream proves it worked
    stable_coverage         enough live successes for a dependable rate

``runtime_goal_status`` (does the Goal Library even discover this goal) is kept
apart from ``automation_coverage`` (how much of the workflow the automation can
actually carry out), because finishing one task does not automate the goal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import SkillState
from .skills import SkillRegistry

ALL_OF = "ALL_OF"
ANY_OF = "ANY_OF"
VARIANT = "VARIANT"
SEQUENCE = "SEQUENCE"
COMPOSITIONS = {ALL_OF, ANY_OF, VARIANT, SEQUENCE}

# Lifecycle values that mean "this alternative is a real, dispatchable skill".
EXECUTABLE_STATES = {SkillState.VERIFIED.value, SkillState.STABLE.value, SkillState.CANDIDATE.value}

# Goal-level status classes.
FULLY_LIVE_VERIFIED = "FULLY_LIVE_VERIFIED"
PARTIAL = "PARTIAL"
NEVER_TRIED = "NEVER_TRIED"
BLOCKED = "BLOCKED"
DEGRADED = "DEGRADED"
MISSING = "MISSING"

DEFAULT_RULES = {
    "stable_min_successes": 5,
    "stable_min_rate": 0.8,
    "degraded_min_failures": 2,
}


@dataclass
class CapabilityRow:
    capability: str
    alternatives: list[str]
    status: str
    implemented_by: str | None = None
    live_verified_by: str | None = None
    attempts: int = 0
    successes: int = 0
    failures: int = 0


@dataclass
class GoalRow:
    goal: str
    category: str
    composition: str
    status: str
    capabilities: list[CapabilityRow] = field(default_factory=list)
    design_requirements_total: int = 0
    implemented_capabilities: int = 0
    live_verified_capabilities: int = 0
    stable_capabilities: int = 0
    design_coverage: float = 0.0
    implementation_coverage: float = 0.0
    live_coverage: float = 0.0
    stable_coverage: float = 0.0
    runtime_goal_status: str = "NOT_A_RUNTIME_GOAL"
    blocked_by: list[str] = field(default_factory=list)


class CapabilityCoverage:
    """Build the capability-level coverage report for every mapped goal."""

    def __init__(
        self,
        registry: SkillRegistry,
        verifier_skills: set[str] | None = None,
        *,
        map_path: Path | None = None,
        rules: dict | None = None,
    ) -> None:
        self.registry = registry
        # A skill is only dispatchable in the live loop when an explicit
        # post-action verifier exists; the registry alone cannot prove that.
        self.verifier_skills = set(verifier_skills or ())
        self.map_path = map_path
        self.mapping = self._load_mapping(map_path)
        self.rules = {**DEFAULT_RULES, **(rules or self.mapping.get("lifecycle_rules", {}))}

    @staticmethod
    def _load_mapping(map_path: Path | None) -> dict:
        if map_path is None:
            map_path = Path(__file__).resolve().parents[1] / "knowledge/goals/goal_capability_map.json"
        try:
            return json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"goals": {}, "lifecycle_rules": {}}

    def _skill(self, skill_id: str):
        return self.registry.get(skill_id)

    def _implemented(self, skill_id: str) -> bool:
        skill = self._skill(skill_id)
        if skill is None:
            return False
        return skill.state.value in EXECUTABLE_STATES and skill_id in self.verifier_skills

    def _stats(self, stats: dict, skill_id: str) -> tuple[int, int, int]:
        row = stats.get(skill_id)
        if row is None:
            return 0, 0, 0
        if isinstance(row, int):
            return row, row, 0
        return (
            int(row.get("attempts", 0) or 0),
            int(row.get("success", 0) or 0),
            int(row.get("failure", 0) or 0),
        )

    def build(self, episode_stats: dict | None = None) -> dict:
        stats = episode_stats or {}
        rules = self.rules
        rows: list[GoalRow] = []

        for goal, definition in self.mapping.get("goals", {}).items():
            composition = str(definition.get("composition", ALL_OF)).upper()
            if composition not in COMPOSITIONS:
                composition = ALL_OF
            capabilities: list[CapabilityRow] = []
            for entry in definition.get("capabilities", []):
                name = str(entry.get("capability", ""))
                alternatives = [str(x) for x in entry.get("alternatives", [])]
                implemented_by = next((sid for sid in alternatives if self._implemented(sid)), None)
                live_by = None
                attempts = successes = failures = 0
                for sid in alternatives:
                    a, s, f = self._stats(stats, sid)
                    attempts += a
                    successes += s
                    failures += f
                    if live_by is None and s > 0:
                        live_by = sid
                if not alternatives:
                    status = MISSING
                elif implemented_by is None:
                    status = BLOCKED
                elif successes == 0:
                    status = "LIVE_TRIED" if attempts > 0 else "CANDIDATE"
                else:
                    rate = successes / max(1, attempts)
                    if successes >= int(rules["stable_min_successes"]) and rate >= float(rules["stable_min_rate"]):
                        status = SkillState.STABLE.value
                    elif failures >= int(rules["degraded_min_failures"]) and rate < float(rules["stable_min_rate"]):
                        status = DEGRADED
                    else:
                        status = "LIVE_VERIFIED"
                capabilities.append(CapabilityRow(
                    capability=name,
                    alternatives=alternatives,
                    status=status,
                    implemented_by=implemented_by,
                    live_verified_by=live_by,
                    attempts=attempts,
                    successes=successes,
                    failures=failures,
                ))

            total = len(capabilities)
            designed = sum(1 for row in capabilities if row.alternatives)
            implemented = sum(1 for row in capabilities if row.implemented_by)
            live = sum(1 for row in capabilities if row.live_verified_by)
            stable = sum(1 for row in capabilities if row.status == SkillState.STABLE.value)

            if total and implemented == 0:
                status = BLOCKED if designed == total else MISSING
            elif designed < total:
                status = MISSING
            elif live == 0:
                status = NEVER_TRIED
            elif live == total and any(row.status == DEGRADED for row in capabilities):
                # Every capability is proven, but at least one has regressed
                # below the dependable rate: that is a DEGRADED goal.  Without
                # this narrow reading the label swallowed every goal that had
                # any failures at all, which hid the NEVER_TRIED signal that
                # drives development priority.
                status = DEGRADED
            elif live == total:
                status = FULLY_LIVE_VERIFIED
            else:
                status = PARTIAL

            rows.append(GoalRow(
                goal=goal,
                category=str(definition.get("category", "")),
                composition=composition,
                status=status,
                capabilities=capabilities,
                design_requirements_total=total,
                implemented_capabilities=implemented,
                live_verified_capabilities=live,
                stable_capabilities=stable,
                design_coverage=round(designed / total, 4) if total else 0.0,
                implementation_coverage=round(implemented / total, 4) if total else 0.0,
                live_coverage=round(live / total, 4) if total else 0.0,
                stable_coverage=round(stable / total, 4) if total else 0.0,
                runtime_goal_status="RUNTIME_DISCOVERED" if definition.get("runtime_goal") else "NOT_A_RUNTIME_GOAL",
                blocked_by=sorted({row.capability for row in capabilities if row.implemented_by is None}),
            ))

        counts = {
            FULLY_LIVE_VERIFIED: sum(row.status == FULLY_LIVE_VERIFIED for row in rows),
            PARTIAL: sum(row.status == PARTIAL for row in rows),
            NEVER_TRIED: sum(row.status == NEVER_TRIED for row in rows),
            BLOCKED: sum(row.status == BLOCKED for row in rows),
            DEGRADED: sum(row.status == DEGRADED for row in rows),
            MISSING: sum(row.status == MISSING for row in rows),
        }
        total = len(rows)
        return {
            "schema_version": "1.0",
            "model": "Goal -> Canonical Capability -> Registered Skill -> Production Evidence",
            "summary": {
                "total": total,
                **{key.lower(): value for key, value in counts.items()},
                "fully_live_verified_percent": round(counts[FULLY_LIVE_VERIFIED] / total * 100, 1) if total else 0.0,
                "never_tried_percent": round(counts[NEVER_TRIED] / total * 100, 1) if total else 0.0,
                "automation_coverage_mean": round(
                    sum(row.implementation_coverage for row in rows) / total, 4) if total else 0.0,
                "live_coverage_mean": round(sum(row.live_coverage for row in rows) / total, 4) if total else 0.0,
            },
            "goals": [asdict(row) for row in rows],
            "highest_leverage": self._leverage(rows),
        }

    @staticmethod
    def _leverage(rows: list[GoalRow]) -> list[dict]:
        counts: dict[str, dict] = {}
        for row in rows:
            for capability in row.capabilities:
                if capability.implemented_by is not None:
                    continue
                for skill_id in capability.alternatives or [capability.capability]:
                    item = counts.setdefault(skill_id, {
                        "skill_id": skill_id,
                        "blocked_goals": 0,
                        "never_tried_goals": 0,
                        "goals": [],
                    })
                    item["blocked_goals"] += 1
                    if row.status == NEVER_TRIED:
                        item["never_tried_goals"] += 1
                    item["goals"].append(row.goal)
        ranked = sorted(counts.values(), key=lambda item: (-item["blocked_goals"], -item["never_tried_goals"], item["skill_id"]))
        return ranked[:20]

    @staticmethod
    def write(payload: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
