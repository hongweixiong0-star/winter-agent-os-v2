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
    # Which recogniser this skill is declared to use: "MAA", "LEGACY" (the V2
    # semantic vision) or "NONE" (the action needs no recognition, e.g. BACK).
    recognition_backend: str = ""
    # The per-semantic recognition nodes declared for this skill, if any.
    recognition: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


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
            recognition_backend=str(entry.get("recognition_backend", "")),
            recognition=dict(entry.get("recognition", {}) or {}),
            evidence=dict(entry.get("evidence", {}) or {}),
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
        # Update in place rather than write a fresh document. This table also
        # carries ``not_migrated`` -- rejections with their reasons, some earned
        # through live regressions -- and an earlier version of this method built
        # a brand-new payload containing only the keys it knew, which silently
        # deleted every one of those records on the first autogen write. Any key
        # this class does not model must survive a save untouched.
        existing: dict[str, Any] = {}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (OSError, json.JSONDecodeError):
                existing = {}
        existing.update({
            "version": 1,
            "policy": {
                "default_preferred": self.default_preferred,
                "default_fallback": self.default_fallback,
                # The note is documentation that has been edited in the file itself
                # (the checked-in one is longer than this default); an update must
                # not quietly shorten it back.
                "note": (existing.get("policy") or {}).get("note")
                or "A skill absent from `skills` keeps its historical ADB path. "
                   "MAA is only promoted per skill after an A/B shows it is not worse.",
            },
            "device": {
                "preferred": self.device_preferred,
                "fallback": self.device_fallback,
                "evidence": self.device_evidence,
            },
            "skills": self.skills,
        })
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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


def build_maa_adapter(
    config: dict[str, Any],
    *,
    production: bool = True,
    project_root: Path = PROJECT_ROOT,
) -> MaaExecutorAdapter | None:
    """Build the MAA backend from ``config/v2.json`` — one switch to turn it off.

    Returns ``None`` only when MAA is disabled by configuration.  When it is
    enabled the adapter is returned even if it fails to come up: its
    ``unavailable_reason`` then reaches the ledger, so a dead MAA shows up as a
    recorded fallback instead of vanishing into a silent try/except.
    """
    section = (config.get("executor") or {}).get("maa") or {}
    if not section.get("enabled", False):
        return None
    device = config.get("device", {}) or {}
    adapter = MaaExecutorAdapter(
        adb_path=device.get("adb_path", ""),
        serial=str(device.get("serial", "")),
        production=bool(production),
        template_dir=project_root / "dataset/candidate/templates",
        log_dir=project_root / "learning/maa_logs",
        save_draw=bool(section.get("save_draw", True)),
        stdout_level=str(section.get("stdout_level", "error")),
    )
    adapter.ensure_ready()
    return adapter


def build_router(
    *,
    adb_executor: Executor,
    adb_resolver: Callable[[str], tuple[float, float] | None] | None,
    maa_adapter: MaaExecutorAdapter | None,
    skill_id: str | None,
    production: bool = True,
    routing: RoutingTable | None = None,
    ledger: BackendLedger | None = None,
) -> Executor | ExecutorRouter:
    """Return the executor to use for one step.

    With no MAA adapter attached this is the plain ADB executor, so a machine
    without MaaFramework behaves exactly as before.
    """
    if maa_adapter is None:
        return adb_executor
    router = ExecutorRouter(
        adb_executor=adb_executor,
        maa_adapter=maa_adapter,
        routing=routing or RoutingTable.load(),
        ledger=ledger,
        adb_resolver=adb_resolver,
    )
    router.maa_executor = Executor(
        production=production,
        dry_run=False,
        device=maa_adapter,
        target_resolver=lambda semantic: router.maa_resolver(semantic, skill_id),
        backend=MAA,
    )
    return router


def _rapid_ocr_results(frame: Any, roi: tuple[int, int, int, int] | None,
                       expected: list[str]) -> list[dict[str, Any]]:
    """Text recognition through the project's own RapidOCR engine.

    The MAA resource carries no OCR model (post_ocr_model is never called
    anywhere), so MAA text recognition always comes back empty and every
    OCR-kind node read as "anchor not found".  Doctrine is text -> RapidOCR;
    boxes are converted to absolute device pixels so callers keep the same
    shape ``adapter.ocr`` used to return.
    """
    from PIL import Image as _PILImage
    from .ocr import RapidOCRBackend
    image = _PILImage.fromarray(frame)
    ox, oy = 0, 0
    if roi:
        ox, oy = int(roi[0]), int(roi[1])
        image = image.crop((ox, oy, ox + int(roi[2]), oy + int(roi[3])))
    results = []
    for token in RapidOCRBackend().recognize(image):
        text = token.text
        if expected and not any(w in text for w in expected):
            continue
        if not token.box:
            continue
        xs = [p[0] for p in token.box]
        ys = [p[1] for p in token.box]
        results.append({
            "text": text,
            "box": [round(min(xs) + ox), round(min(ys) + oy),
                    round(max(xs) - min(xs)), round(max(ys) - min(ys))],
            "score": float(token.confidence),
        })
    return results


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
        #: Set when a node of another recognition kind was asked to fail informatively:
        #: it distinguishes "the control is absent" from "this node kind is misrouted".
        self.last_recognition_error: str | None = None

    # -------------------------------------------------------------- resolution
    def maa_resolver(self, semantic: str, skill_id: str | None) -> tuple[float, float] | None:
        """Resolver handed to the MAA ``Executor``.

        Two tiers, because the two migration axes have different evidence:

        1. If this skill has a measured MAA recognition node for the semantic,
           MAA finds the target on the frame and the coordinate comes from MAA.
        2. Otherwise fall through to the legacy semantic resolver.  The frame is
           still captured by MAA (that is the 20x win) while the game knowledge
           stays where it is already live-verified.  Returning ``None`` here
           instead would make every non-migrated semantic fail on a MAA-device
           skill, which is a regression, not a migration.

        The frame used is the adapter's most recent one — the same frame the
        runtime saved as evidence — so the tapped coordinate and the frame a
        reviewer looks at cannot disagree.
        """
        adapter = self.maa_adapter
        if adapter is None:
            return self.adb_resolver(semantic) if self.adb_resolver else None
        node = self.routing.recognition_node(skill_id, semantic)
        if node is None:
            return self.adb_resolver(semantic) if self.adb_resolver else None
        frame = adapter.frame()
        if frame is None:
            return None

        # A node may recognise text rather than pixels. Dispatched here instead of
        # inside ``find`` because ``find`` is the template entry point and its
        # callers rely on that; routing the two apart at the top keeps one node
        # shape meaning one thing.
        #
        # Without this branch a generated OCR node falls into the template path
        # below, which looks for ``<template_dir>/<semantic>.png``, fails, and
        # reports SEMANTIC_TARGET_NOT_VERIFIED -- reading as "the control is not
        # on screen" when the truth is "this node is of the other kind".
        # Added for winter_agent_v2.pipeline_autogen, whose OCR nodes are shaped
        # like maa-pipeline-generate's output.
        from winter_agent_v2.pipeline_autogen import dispatch_hint

        if dispatch_hint(node) == "OCR":
            expected = list(node.get("expected") or [])
            roi = tuple(node["roi"]) if node.get("roi") else None
            results = _rapid_ocr_results(frame, roi, expected)
            if not results:
                self.last_outcome = None
                self.last_recognition_error = "MAA_OCR:NO_TEXT"
                return None
            best = max(results, key=lambda r: float(r.get("score", 0.0) or 0.0))
            box = best.get("box") or ()
            if len(box) != 4:
                self.last_outcome = None
                self.last_recognition_error = "MAA_OCR:BAD_BOX"
                return None
            x, y, w, h = (int(v) for v in box)
            size = adapter.last_frame
            if size is None or getattr(size, "shape", None) is None:
                self.last_outcome = None
                self.last_recognition_error = "MAA_OCR:NO_SIZE"
                return None
            height, width = int(size.shape[0]), int(size.shape[1])
            if width <= 0 or height <= 0:
                self.last_outcome = None
                self.last_recognition_error = "MAA_OCR:BAD_SIZE"
                return None
            self.last_recognition_error = None
            return ((x + w / 2.0) / width, (y + h / 2.0) / height)

        # STRUCTURE nodes find a stable text anchor inside a parent semantic
        # row, then tap a child region at a fixed offset relative to that
        # anchor (e.g. the research-queue arrow right of the 「科技研究」
        # label).  This replaces the rejected full-screen blue-arrow TEMPLATE,
        # which also matched arrows on unrelated rows.  Node shape:
        #   {"kind": "STRUCTURE",
        #    "anchor": {"expected": ["科技研究"], "roi": [x, y, w, h]},
        #    "offset": {"dx": 136, "dy": 5}}
        # dx/dy are measured from the anchor box's right edge / vertical
        # centre, calibrated on a real frame and recorded in evidence.
        if dispatch_hint(node) == "STRUCTURE":
            anchor = dict(node.get("anchor") or {})
            offset = dict(node.get("offset") or {})
            expected = list(anchor.get("expected") or [])
            roi = tuple(anchor["roi"]) if anchor.get("roi") else None
            if not expected:
                self.last_recognition_error = "STRUCTURE:NO_ANCHOR"
                return None
            results = _rapid_ocr_results(frame, roi, expected)
            if not results:
                self.last_recognition_error = "STRUCTURE:ANCHOR_NOT_FOUND"
                return None
            best = max(results, key=lambda r: float(r.get("score", 0.0) or 0.0))
            box = best.get("box") or ()
            if len(box) != 4:
                self.last_recognition_error = "STRUCTURE:BAD_BOX"
                return None
            x, y, w, h = (int(v) for v in box)
            size = adapter.last_frame
            if size is None or getattr(size, "shape", None) is None:
                self.last_recognition_error = "STRUCTURE:NO_SIZE"
                return None
            height, width = int(size.shape[0]), int(size.shape[1])
            if width <= 0 or height <= 0:
                self.last_recognition_error = "STRUCTURE:BAD_SIZE"
                return None
            tap_x = x + w + float(offset.get("dx", 0.0))
            tap_y = y + h / 2.0 + float(offset.get("dy", 0.0))
            self.last_recognition_error = None
            return (tap_x / width, tap_y / height)

        template_name = str(node.get("template", semantic))
        # A node names its template semantically, but the file is named for its
        # provenance and usually lives outside ``template_dir``.  Registering
        # that file is what makes the node usable: without it ``_load_template``
        # looks for ``<template_dir>/BTN_HERO_CAMP_FIGHT.png``, fails, and the
        # whole skill reports SEMANTIC_TARGET_NOT_VERIFIED as though the control
        # were absent.  Live 2026-09-14: this made every skill with a node
        # unresolvable through MAA while the same template scored 1.000 when
        # handed over explicitly.
        source = node.get("source_template")
        images: dict[str, Any] | None = None
        if source:
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = PROJECT_ROOT / source_path
            if source_path.is_file():
                images = {template_name: source_path}
        outcome = adapter.find(
            frame, semantic,
            template=template_name,
            roi=tuple(node["roi"]) if node.get("roi") else None,
            threshold=node.get("threshold", 0.7),
            images=images,
        )
        self.last_outcome = outcome
        # A miss stays a miss.  Falling through to the legacy resolver here would
        # hide a drifting MAA node behind a position-blind match, so the skill
        # fails instead and the drift shows up in the ledger.
        return outcome.center_norm()

    # -------------------------------------------------------------- dispatch
    def _bear_auto_join_guard(self, action: Action, skill_id: str | None) -> ExecutionResult | None:
        """Production state guard for BEAR_AUTO_JOIN (2026-09-26 directive #4).

        The auto-join switch is a toggle: clicking an already-ON switch turns
        it OFF.  Before any production tap of BTN_BEAR_AUTO_JOIN the switch
        state is read from the live frame:

          ON      -> SUCCESS / NOOP, no click issued
          UNKNOWN -> action refused (NOT_EXECUTABLE), no click issued
          OFF     -> click allowed; the verifier reads OFF -> ON

        The reader never caches, so the state is inherently per-role.
        """
        if skill_id != "BEAR_AUTO_JOIN":
            return None
        if str(getattr(action, "kind", "")).upper() != "TAP_SEMANTIC":
            return None
        if str(getattr(action, "target", "")).upper() != "BTN_BEAR_AUTO_JOIN":
            return None
        if self.maa_adapter is None:
            return None
        from .bear_state import read_state_from_image
        frame = self.maa_adapter.frame()
        if frame is None:
            return None
        from PIL import Image
        state = read_state_from_image(Image.fromarray(frame))["state"]
        if state == "ON":
            self._stat("bear_guard").record(True, 0.0, "NOOP_ALREADY_ON")
            return ExecutionResult(executed=True, dry_run=False, action=action,
                                   backend=MAA, capture_backend="MAA_MUMU_EXTRAS",
                                   recognition_backend="MAA",
                                   detail={"guard": "NOOP_ALREADY_ON"})
        if state == "UNKNOWN":
            self._stat("bear_guard").record(False, 0.0, "BLOCKED_UNKNOWN_STATE")
            return ExecutionResult(executed=False, dry_run=False, action=action,
                                   backend=MAA, error="BEAR_TOGGLE_STATE_UNKNOWN",
                                   capture_backend="MAA_MUMU_EXTRAS",
                                   recognition_backend="MAA",
                                   detail={"guard": "BLOCKED_UNKNOWN_STATE"})
        return None  # OFF: proceed with the normal dispatch path

    def available_backends(self) -> dict[str, bool]:
        maa_ok = False
        if self.maa_adapter is not None:
            maa_ok = self.maa_adapter.available()
        return {MAA: maa_ok, ADB: True}

    def route_for(self, skill_id: str | None) -> Route:
        return self.routing.route(skill_id)

    def execute(self, action: Action, skill_id: str | None = None) -> ExecutionResult:
        guard = self._bear_auto_join_guard(action, skill_id)
        if guard is not None:
            return guard
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
        # Who actually recognised the target.  Derived from what ran: the MAA
        # recognition path only exists where the routing file declares a node for
        # this skill+semantic, so a MAA-device action with no node is honestly
        # reported as V2 recognition rather than as a MAA migration.
        recognition = "NONE"
        if result.action.kind == "TAP_SEMANTIC":
            if backend == MAA and self.routing.recognition_node(
                route.skill_id, str(result.action.target or "")
            ) is not None:
                recognition = "MAA"
            else:
                recognition = "V2"
        executor = self._executor_for(backend, route.skill_id)
        device = getattr(executor, "device", None) if executor is not None else None
        capture = getattr(device, "capture_backend", "ADB_EXEC_OUT") if device is not None else ""
        routed = ExecutionResult(
            executed=result.executed, dry_run=result.dry_run, action=result.action,
            error=result.error, backend=backend, capture_backend=capture,
            recognition_backend=recognition, latency_ms=result.latency_ms,
        
            tap_point=result.tap_point,
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
            "capture_backend": capture,
            "recognition_backend": recognition,
            "fallback_used": bool(fallback_used),
            "migration_priority": route.migration_priority,
            "executed": result.executed,
            "error": result.error,
            "latency_ms": result.latency_ms,
            # Where a TAP_SEMANTIC landed, in device pixels.  ExecutionResult has carried this since
            # 2026-09-20, and the ledger -- the artifact a post-mortem actually reads -- dropped it,
            # so every row in learning/executor_backend.jsonl showed tap_point None including the
            # taps that worked.  "The target did not open" is only answerable next to "and it landed
            # here"; that is the whole reason the field exists.
            "tap_point": list(result.tap_point) if result.tap_point else None,
            "attempts": attempts,
        })
        return routed
