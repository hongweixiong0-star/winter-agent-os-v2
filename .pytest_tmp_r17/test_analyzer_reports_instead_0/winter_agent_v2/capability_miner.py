from __future__ import annotations

from dataclasses import dataclass

from .skills import SkillRegistry


@dataclass(frozen=True)
class ExternalCapability:
    capability: str
    source: str
    preconditions: tuple[str, ...]
    navigation: tuple[str, ...]
    recognition: tuple[str, ...]
    verification: tuple[str, ...]
    recovery: tuple[str, ...]


@dataclass(frozen=True)
class SkillGap:
    skill_id: str
    status: str
    source: str


class ExternalCapabilityMiner:
    def find_gaps(self, capabilities: list[ExternalCapability], registry: SkillRegistry) -> list[SkillGap]:
        gaps = []
        for capability in capabilities:
            skill_id = capability.capability.upper()
            if registry.get(skill_id) is None:
                gaps.append(SkillGap(skill_id, "CANDIDATE", capability.source))
        return gaps
