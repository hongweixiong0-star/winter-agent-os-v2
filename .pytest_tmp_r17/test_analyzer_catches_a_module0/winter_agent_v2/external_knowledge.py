from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResearchTrigger(str, Enum):
    UNKNOWN_PAGE = "UNKNOWN_PAGE"
    UNKNOWN_POPUP = "UNKNOWN_POPUP"
    UNKNOWN_ICON = "UNKNOWN_ICON"
    UNKNOWN_BUTTON = "UNKNOWN_BUTTON"
    UNKNOWN_STATE = "UNKNOWN_STATE"
    UNKNOWN_TASK = "UNKNOWN_TASK"
    UNKNOWN_EVENT = "UNKNOWN_EVENT"
    SKILL_MISSING = "SKILL_MISSING"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"
    VISION_FAILED = "VISION_FAILED"
    VERIFIER_UNKNOWN = "VERIFIER_UNKNOWN"
    REPEATED_SKILL_FAILURE = "REPEATED_SKILL_FAILURE"
    KNOWLEDGE_MISSING = "KNOWLEDGE_MISSING"
    NEW_CONTENT = "NEW_CONTENT"
    NEW_EVENT = "NEW_EVENT"


class EvidenceSource(str, Enum):
    OFFICIAL = "OFFICIAL"
    COMMUNITY_DB = "COMMUNITY_DB"
    OPEN_SOURCE_PROJECT = "OPEN_SOURCE_PROJECT"
    PLAYER_GUIDE = "PLAYER_GUIDE"
    VIDEO = "VIDEO"
    LEGACY_EVIDENCE = "LEGACY_EVIDENCE"
    LIVE_CLIENT = "LIVE_CLIENT"


@dataclass(frozen=True)
class KnowledgeCandidate:
    key: str
    value: Any
    source_type: EvidenceSource
    source: str
    confidence: float
    retrieved_at: str
    license: str | None = None


@dataclass(frozen=True)
class FusionResult:
    key: str
    value: Any | None
    status: str
    confidence: float
    sources: tuple[str, ...]


class EvidenceFusion:
    """Fuse priors without allowing them to override contradictory live UI facts."""

    def fuse(self, candidates: list[KnowledgeCandidate]) -> FusionResult:
        if not candidates:
            raise ValueError("at least one candidate is required")
        key = candidates[0].key
        if any(row.key != key for row in candidates):
            raise ValueError("cannot fuse different knowledge keys")
        live = [row for row in candidates if row.source_type is EvidenceSource.LIVE_CLIENT]
        values = {repr(row.value) for row in candidates}
        sources = tuple(dict.fromkeys(row.source for row in candidates))
        if live:
            live_values = {repr(row.value) for row in live}
            if len(live_values) > 1:
                return FusionResult(key, None, "CONFLICT", 0.0, sources)
            winner = max(live, key=lambda row: row.confidence)
            support = [row for row in candidates if row.value == winner.value]
            confidence = min(1.0, winner.confidence + 0.01 * (len(support) - 1))
            return FusionResult(key, winner.value, "VERIFIED", confidence, sources)
        if len(values) > 1:
            return FusionResult(key, None, "CONFLICT", 0.0, sources)
        best = max(candidates, key=lambda row: row.confidence)
        status = "LIKELY" if len(candidates) >= 2 else "CANDIDATE"
        return FusionResult(key, best.value, status, best.confidence, sources)


class ExternalKnowledgeProvider:
    """One JIT research boundary shared by Vision, Skills and Recovery."""

    def __init__(self) -> None:
        self._candidates: dict[str, list[KnowledgeCandidate]] = {}
        self._events: list[tuple[ResearchTrigger, str]] = []

    def trigger(self, reason: ResearchTrigger, context: str) -> None:
        self._events.append((reason, context))

    def add(self, candidate: KnowledgeCandidate) -> None:
        self._candidates.setdefault(candidate.key, []).append(candidate)

    def resolve(self, key: str) -> FusionResult | None:
        rows = self._candidates.get(key)
        return EvidenceFusion().fuse(rows) if rows else None

    @property
    def events(self) -> tuple[tuple[ResearchTrigger, str], ...]:
        return tuple(self._events)
