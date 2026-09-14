from __future__ import annotations

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
    ) -> None:
        if production and dry_run:
            raise ValueError("production and dry_run are mutually exclusive")
        self.production = production
        self.dry_run = dry_run
        self.policy = policy or SafetyPolicy()
        self.device = device
        self.target_resolver = target_resolver

    def execute(self, action: Action) -> ExecutionResult:
        policy = self.policy.evaluate(action)
        if not policy.allowed:
            return ExecutionResult(False, self.dry_run, action, policy.reason)
        if (action.kind.startswith("TAP") or action.kind == "PRESS_BACK") and not self.production:
            return ExecutionResult(False, True, action, "DRY_RUN_BLOCKED_DEVICE_ACTION")
        if action.kind == "OBSERVE":
            return ExecutionResult(True, self.dry_run, action)
        if action.kind == "TAP_SEMANTIC":
            if self.device is None or self.target_resolver is None or not action.target:
                return ExecutionResult(False, self.dry_run, action, "DEVICE_ADAPTER_NOT_CONNECTED")
            center = self.target_resolver(action.target)
            if center is None:
                return ExecutionResult(False, self.dry_run, action, "SEMANTIC_TARGET_NOT_VERIFIED")
            x_norm, y_norm = center
            if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
                return ExecutionResult(False, self.dry_run, action, "SEMANTIC_TARGET_OUT_OF_BOUNDS")
            status = self.device.status()
            if not status.connected or status.resolution is None:
                return ExecutionResult(False, self.dry_run, action, "DEVICE_BUSY")
            width, height = status.resolution
            self.device.tap(round(x_norm * width), round(y_norm * height))
            return ExecutionResult(True, False, action)
        if action.kind == "PRESS_BACK":
            if self.device is None:
                return ExecutionResult(False, self.dry_run, action, "DEVICE_ADAPTER_NOT_CONNECTED")
            status = self.device.status()
            if not status.connected:
                return ExecutionResult(False, self.dry_run, action, "DEVICE_BUSY")
            self.device.press_back()
            return ExecutionResult(True, False, action)
        if action.kind == "SWIPE":
            # ``target`` carries "x1_norm,y1_norm,x2_norm,y2_norm" and payload may
            # carry a duration. Used only to move scrollable in-game lists
            # (resource-target strip, event lists) before a semantic tap.
            if self.device is None:
                return ExecutionResult(False, self.dry_run, action, "DEVICE_ADAPTER_NOT_CONNECTED")
            try:
                x1, y1, x2, y2 = (float(part) for part in str(action.target or "").split(","))
            except ValueError:
                return ExecutionResult(False, self.dry_run, action, "SWIPE_TARGET_INVALID")
            if not all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
                return ExecutionResult(False, self.dry_run, action, "SWIPE_TARGET_OUT_OF_BOUNDS")
            status = self.device.status()
            if not status.connected or status.resolution is None:
                return ExecutionResult(False, self.dry_run, action, "DEVICE_BUSY")
            width, height = status.resolution
            self.device.swipe(
                round(x1 * width), round(y1 * height),
                round(x2 * width), round(y2 * height),
                int(action.payload.get("duration_ms", 300)),
            )
            return ExecutionResult(True, False, action)
        return ExecutionResult(False, self.dry_run, action, "DEVICE_ADAPTER_NOT_CONNECTED")
