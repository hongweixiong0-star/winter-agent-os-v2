"""Executor router + backend ledger — one executor boundary, two backends.

Operator directive (2026-09-14): ``Skill → preferred_backend → fallback_backend``
with ``MAA`` preferred and ``ADB`` as device layer / fallback.  This module is the
whole of that routing.  It is **not** a second scheduler or a second registry: it
sits behind the single ``Executor`` interface that ``Scheduler.tick`` already
calls, so nothing above it changes.

Two independent axes are routed, because they have different evidence:

``device``
    Who captures frames and issues input.  Already measured on this machine:
    MAA's EmulatorExtras path captures in 12.1 ms against ADB's 246.2 ms and
    sends input through MuMu's native channel instead of ``adb shell input tap``.

``recognition``
    Who finds a semantic target on a frame.  Migrated per semantic, only after a
    node is authored *and* drawn on a real frame for visual check, and only after
    an A/B shows it is not worse than the legacy matcher.

Rollout is therefore staged: a skill that appears in neither table keeps the ADB
path it has today, so turning this on cannot regress a live-verified skill.  The
operator's rule "if MAA did not improve it, keep ADB" is enforced by the routing
file rather than by good intentions.

Fallback safety invariant (important): the router falls back to ADB **only when
the preferred backend issued no input at all** (``ExecutionResult.executed`` is
False).  Falling back after a tap had already landed would double-tap the game —
on a purchase surface that is exactly the kind of accident the safety rules
forbid.  A recognised, clicked, but *unverified* action is a verifier problem,
not a backend problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .executor import Executor
from .maa_executor import MaaExecutorAdapter, RecognitionOutcome
from .models import Action, ExecutionResult

MAA = "MAA"
ADB = "ADB"
HYBRID = "HYBRID"
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTING_PATH = PROJECT_ROOT / "knowledge" / "execution" / "backend_routing.json"
DEFAULT_NODES_PATH = PROJECT_ROOT / "knowledge" / "execution" / "maa_pipeline.json"
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "learning" / "executor_backend.jsonl"

# Errors that mean "the backend itself is unusable" rather than "the game said
# no".  Only these justify leaving the preferred backend behind.
BACKEND_LEVEL_ERRORS = {
    "DEVICE_ADAPTER_NOT_CONNECTED", "DEVICE_BUSY", "DRY_RUN_BLOCKED_DEVICE_ACTION",
    "MAA_CONNECT_FAILED", "MAA_SCREENCAP_FAILED", "MAA_SCREENCAP_EMPTY",
    "MAA_SCREENCAP_BLACK", "MAA_SETUP_FAILED", "MAA_IMPORT_FAILED",
    "MAA_BIND_FAILED", "MAA_CLICK_FAILED", "MAA_BACK_FAILED", "MAA_SWIPE_FAILED",
}


@dataclass(frozen=True)
class Route:
    """Chosen backends for one skill, plus where the decision came from."""

    skill_id: str
    preferred: str
    fallback: str
    migration_priority: str = "P3"
    source: str = "default"


@dataclass
class RoutingTable:
    """Declarative skill → backend map.  Absent skill ⇒ untouched ADB path."""

    skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_preferred: str = ADB
    default_fallback: str = ADB
    device_preferred: str = ADB
    device_fallback: str = ADB
    device_evidence: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "RoutingTable":
        target = Path(path or DEFAULT_ROUTING_PATH)
        if not target.is_file():
            return cls()
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        policy = payload.get("policy", {}) or {}
        device = payload.get("device", {}) or {}
        return cls(
            skills=payload.get("skills", {}) or {},
            default_preferred=str(policy.get("default_preferred", ADB)),
            default_fallback=str(policy.get("default_fallback", ADB)),
            device_preferred=str(device.get("preferred", ADB)),
            device_fallback=str(device.get("fallback", ADB)),
            device_evidence=device.get("evidence", {}) or {},
            path=target,
        )

    def route(self, skill_id: str | None) -> Route:
        entry = self.skills.get(skill_id or "")
        if not entry:
            return Route(skill_id or "", self.default_preferred, self.default_fallback, source="default")
        return Route(
            skill_id or "",
            str(entry.get("preferred", self.default_preferred)),
            str(entry.get("fallback", self.default_fallback)),
            str(entry.get("migration_priority", "P3")),
            source="table",
        )

    def recognition_node(self, skill_id: str | None, semantic: str) -> dict[str, Any] | None:
        entry = self.skills.get(skill_id or "")
        if not entry:
            return None
        nodes = entry.get("recognition", {})
        if semantic in nodes:
            return nodes[semantic]
        return nodes.get("*")

    def save(self) -> None:
        if self.path is None:
            return
        payload = {
            "version": 1,
            "policy": {
                "default_preferred": self.default_preferred,
                "default_fallback": self.default_fallback,
                "note": (
                    "A skill absent from `skills` keeps its historical ADB path. "
                    "MAA is only promoted per skill after an A/B shows it is not worse."
                ),
            },
            "device": {
                "preferred": self.device_preferred,
                "fallback": self.device_fallback,
                "evidence": self.device_evidence,
            },
            "skills": self.skills,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass
class BackendLedger:
    """Append-only record of which backend actually ran, for A/B accounting."""

    path: Path = DEFAULT_LEDGER_PATH
    limit: int = 20000

    def append(self, row: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            rows = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
            rows.append(json.dumps(row, ensure_ascii=False, default=str))
            self.path.write_text("\n".join(rows[-self.limit:]) + "\n", encoding="utf-8")
        except (OSError, TypeError, ValueError):
            # Accounting must never break an already-issued action.
            pass


class ExecutorRouter:
    """Single executor entry point that picks a backend per skill.

    Implements the same ``execute(action)`` contract as ``Executor`` so
    ``Scheduler`` stays backend-agnostic.
    """

    def __init__(
        self,
        *,
        adb_executor: Executor,
        maa_executor: Executor | None = None,
        maa_adapter: MaaExecutorAdapter | None = None,
        routing: RoutingTable | None = None,
        ledger: BackendLedger | None = None,
        adb_resolver: Callable[[str], tuple[float, float] | None] | None = None,
    ) -> None:
        self.adb_executor = adb_executor
        self.maa_executor = maa_executor
        self.maa_adapter = maa_adapter
        self.routing = routing or RoutingTable.load()
        self.ledger = ledger or BackendLedger()
        self.adb_resolver = adb_resolver
        self.last_outcome: RecognitionOutcome | None = None

    # -------------------------------------------------------------- resolution
    def maa_resolver(self, semantic: str, skill_id: str | None) -> tuple[float, float] | None:
        """MAA-recognition resolver handed to the MAA ``Executor``.

        Consumes the adapter's most recent frame — the same frame the runtime
        saved as evidence — so the coordinate that gets tapped and the frame a
        reviewer looks at cannot disagree.
        """
        adapter = self.maa_adapter
        if adapter is None or self.routing.recognition_node(skill_id, semantic) is None:
            return None
        node = self.routing.recognition_node(skill_id, semantic) or {}
        frame = adapter.frame()
        if frame is None:
            return None
        outcome = adapter.find(
            frame, semantic,
            template=node.get("template", semantic),
            roi=tuple(node["roi"]) if node.get("roi") else None,
            threshold=node.get("threshold", 0.7),
        )
        self.last_outcome = outcome
        return outcome.center_norm()

    # -------------------------------------------------------------- dispatch
    def available_backends(self) -> dict[str, bool]:
        maa_ok = False
        if self.maa_adapter is not None:
            maa_ok = self.maa_adapter.available()
        return {MAA: maa_ok, ADB: True}

    def route_for(self, skill_id: str | None) -> Route:
        return self.routing.route(skill_id)

    def execute(self, action: Action, skill_id: str | None = None) -> ExecutionResult:
        route = self.routing.route(skill_id)
        available = self.available_backends()
        order = [route.preferred, route.fallback]
        # A backend that is down must not be tried, but it must also be visible
        # in the ledger as the reason the fallback ran.
        attempts: list[dict[str, Any]] = []
        for backend in order:
            if backend == MAA and not available.get(MAA):
                attempts.append({"backend": MAA, "skipped": self._maa_reason()})
                continue
            executor = self._executor_for(backend, skill_id)
            if executor is None:
                attempts.append({"backend": backend, "skipped": "NO_EXECUTOR"})
                continue
            result = executor.execute(action)
            attempts.append({
                "backend": backend, "executed": result.executed,
                "error": result.error, "latency_ms": result.latency_ms,
            })
            used = backend if result.executed else None
            if result.executed or result.error not in BACKEND_LEVEL_ERRORS:
                return self._finish(result, route, attempts, used or backend)
        # Nothing was executed and every backend reported a backend-level error.
        return self._finish(
            ExecutionResult(False, True, action, "ALL_BACKENDS_UNAVAILABLE"),
            route, attempts, attempts[-1]["backend"] if attempts else ADB,
        )

    def _maa_reason(self) -> str:
        if self.maa_adapter is None:
            return "NO_MAA_ADAPTER"
        return self.maa_adapter.unavailable_reason or "MAA_UNAVAILABLE"

    def _executor_for(self, backend: str, skill_id: str | None) -> Executor | None:
        if backend == MAA:
            return self.maa_executor
        return self.adb_executor

    def _finish(
        self,
        result: ExecutionResult,
        route: Route,
        attempts: list[dict[str, Any]],
        backend: str,
    ) -> ExecutionResult:
        fallback_used = (
            route.preferred != backend
            or any(item.get("skipped") for item in attempts if item["backend"] == route.preferred)
        )
        routed = ExecutionResult(
            executed=result.executed, dry_run=result.dry_run, action=result.action,
            error=result.error, backend=backend, latency_ms=result.latency_ms,
        )
        self.ledger.append({
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "skill_id": route.skill_id,
            "skill_known": route.source == "table",
            "action_kind": result.action.kind,
            "action_target": result.action.target,
            "preferred_backend": route.preferred,
            "fallback_backend": route.fallback,
            "used_backend": backend,
            "fallback_used": bool(fallback_used),
            "migration_priority": route.migration_priority,
            "executed": result.executed,
            "error": result.error,
            "latency_ms": result.latency_ms,
            "attempts": attempts,
        })
        return routed
