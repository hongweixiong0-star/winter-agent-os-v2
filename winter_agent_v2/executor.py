from __future__ import annotations

import time
from collections.abc import Callable

from .device import ADBDevice
from .models import Action, ExecutionResult
from .policy import SafetyPolicy


NormalizedTargetResolver = Callable[[str], tuple[float, float] | None]


class Executor:
    def __init__(
        self,
        *,
        production: bool = False,
        dry_run: bool = True,
        policy: SafetyPolicy | None = None,
        device: ADBDevice | None = None,
        target_resolver: NormalizedTargetResolver | None = None,
        backend: str = "ADB",
    ) -> None:
        if production and dry_run:
            raise ValueError("production and dry_run are mutually exclusive")
        self.production = production
        self.dry_run = dry_run
        self.policy = policy or SafetyPolicy()
        self.device = device
        self.target_resolver = target_resolver
        # Stamped onto every ExecutionResult so an episode can state which
        # UI-automation backend really ran.  The device may be an ADBDevice or a
        # MaaExecutorAdapter; the two are interface-compatible on purpose.
        self.backend = backend

    def _result(
        self,
        executed: bool,
        action: Action,
        error: str | None = None,
        latency_ms: float | None = None,
        recognition_backend: str = "",
    ) -> ExecutionResult:
        capture = getattr(self.device, "capture_backend", "ADB_EXEC_OUT")
        return ExecutionResult(
            executed, self.dry_run, action, error,
            backend=self.backend if executed else "",
            capture_backend=capture if executed else "",
            recognition_backend=recognition_backend if executed else "",
            latency_ms=latency_ms,
        )

    def execute(self, action: Action, skill_id: str | None = None) -> ExecutionResult:
        """Run one atomic action on the configured backend.

        ``skill_id`` is accepted for the executor router's routing decision and
        is deliberately unused here: a skill's target resolution stays the job of
        its ``target_resolver``, so this class keeps exactly one responsibility.
        """
        policy = self.policy.evaluate(action)
        if not policy.allowed:
            return self._result(False, action, policy.reason)
        if (action.kind.startswith("TAP") or action.kind == "PRESS_BACK") and not self.production:
            return self._result(False, action, "DRY_RUN_BLOCKED_DEVICE_ACTION")
        if action.kind == "OBSERVE":
            return self._result(True, action)
        if action.kind == "TAP_SEMANTIC":
            if self.device is None or self.target_resolver is None or not action.target:
                return self._result(False, action, "DEVICE_ADAPTER_NOT_CONNECTED")
            center = self.target_resolver(action.target)
            if center is None:
                return self._result(False, action, "SEMANTIC_TARGET_NOT_VERIFIED")
            x_norm, y_norm = center
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return self._result(False, action, "SEMANTIC_TARGET_OUT_OF_BOUNDS")
            status = self.device.status()
            if not status.connected or status.resolution is None:
                return self._result(False, action, "DEVICE_BUSY")
            width, height = status.resolution
            started = time.perf_counter()
            self.device.tap(round(x_norm * width), round(y_norm * height))
            latency_ms = (time.perf_counter() - started) * 1000.0
            # The target came from this executor's ``target_resolver``, which on
            # the ADB path is the V2 semantic vision.  Stated explicitly so the
            # episode does not have to infer who did the recognition.
            return self._result(True, action, latency_ms=round(latency_ms, 2),
                                recognition_backend="V2")
        if action.kind == "PRESS_BACK":
            if self.device is None:
                return self._result(False, action, "DEVICE_ADAPTER_NOT_CONNECTED")
            status = self.device.status()
            if not status.connected:
                return self._result(False, action, "DEVICE_BUSY")
            started = time.perf_counter()
            self.device.press_back()
            latency_ms = (time.perf_counter() - started) * 1000.0
            # A system key involves no recognition step, and saying so is not
            # cosmetic: the router already reports "NONE" for this action, so
            # omitting it here made the same action record a different value
            # depending on whether it ran through the router.  Measured
            # 2026-09-15 (WB-EXECUTOR-EVIDENCE-AUDIT): two successful BACK steps
            # (accept_20260915_204301_run01/02) carried recognition_backend=""
            # while their sibling MAA steps carried "NONE", and a reader cannot
            # tell "no recognition was needed" from "the field was forgotten".
            return self._result(True, action, latency_ms=round(latency_ms, 2),
                                recognition_backend="NONE")
        if action.kind == "SWIPE":
            # ``target`` carries "x1_norm,y1_norm,x2_norm,y2_norm" and payload may
            # carry a duration. Used only to move scrollable in-game lists
            # (resource-target strip, event lists) before a semantic tap.
            if self.device is None:
                return self._result(False, action, "DEVICE_ADAPTER_NOT_CONNECTED")
            try:
                x1, y1, x2, y2 = (float(part) for part in str(action.target or "").split(","))
            except ValueError:
                return self._result(False, action, "SWIPE_TARGET_INVALID")
            if not all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
                return self._result(False, action, "SWIPE_TARGET_OUT_OF_BOUNDS")
            status = self.device.status()
            if not status.connected or status.resolution is None:
                return self._result(False, action, "DEVICE_BUSY")
            width, height = status.resolution
            started = time.perf_counter()
            self.device.swipe(
                round(x1 * width), round(y1 * height),
                round(x2 * width), round(y2 * height),
                int(action.payload.get("duration_ms", 300)),
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            return self._result(True, action, latency_ms=round(latency_ms, 2))
        return self._result(False, action, "DEVICE_ADAPTER_NOT_CONNECTED")
