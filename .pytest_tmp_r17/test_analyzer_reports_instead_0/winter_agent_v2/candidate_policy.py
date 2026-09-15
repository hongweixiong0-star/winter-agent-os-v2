from __future__ import annotations

import json
from pathlib import Path

from .models import SkillState
from .skills import Skill


class CandidateAttemptPool:
    """Persistent starvation counter consumed by the one Scheduler."""

    def __init__(self, path: Path | None = None, *, verifier_skills: set[str] | None = None,
                 recovery_skills: set[str] | None = None, threshold: int = 5,
                 allowed_risks: set[str] | None = None) -> None:
        self.path = path
        self.verifier_skills = verifier_skills or set()
        self.recovery_skills = recovery_skills or set()
        self.threshold = max(1, threshold)
        self.allowed_risks = allowed_risks or {"LOW", "LOW_RESOURCE_SPEND", "MEDIUM_RESOURCE_SPEND", "MEDIUM_STAMINA_SPEND"}
        self.cycles = self._load()

    def eligible(self, skill: Skill | None) -> bool:
        return bool(skill and skill.state is SkillState.CANDIDATE and skill.id in self.verifier_skills
                    and skill.id in self.recovery_skills and skill.risk in self.allowed_risks
                    and skill.semantic_contract_complete)

    def wait_cycle(self, skill: Skill) -> int:
        if not self.eligible(skill): return 0
        self.cycles[skill.id] = self.cycles.get(skill.id, 0) + 1
        self._save()
        return self.cycles[skill.id]

    def starved(self, skill: Skill | None) -> bool:
        return bool(self.eligible(skill) and self.cycles.get(skill.id, 0) >= self.threshold)

    def attempted(self, skill: Skill) -> None:
        self.cycles[skill.id] = 0
        self._save()

    def _load(self) -> dict[str, int]:
        if self.path is None: return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(key): max(0, int(value)) for key, value in raw.get("ready_cycles", {}).items()}
        except (OSError, ValueError, TypeError, json.JSONDecodeError): return {}

    def _save(self) -> None:
        if self.path is None: return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps({"threshold":self.threshold, "ready_cycles":self.cycles}, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
