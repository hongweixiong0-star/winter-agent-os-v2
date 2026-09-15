from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class P0Evidence:
    adb_connected: bool
    foreground_package_ok: bool
    screenshot_ok: bool
    replay_chain_ok: bool
    live_vision_verified: bool
    live_executor_verified: bool
    live_verifier_verified: bool
    consecutive_live_successes: int


@dataclass(frozen=True)
class GateResult:
    ready: bool
    blockers: tuple[str, ...]


def evaluate_p0_production_gate(evidence: P0Evidence) -> GateResult:
    checks = (
        (evidence.adb_connected, "ADB_NOT_CONNECTED"),
        (evidence.foreground_package_ok, "WRONG_FOREGROUND_PACKAGE"),
        (evidence.screenshot_ok, "SCREENSHOT_NOT_VERIFIED"),
        (evidence.replay_chain_ok, "REPLAY_CHAIN_INCOMPLETE"),
        (evidence.live_vision_verified, "LIVE_VISION_NOT_VERIFIED"),
        (evidence.live_executor_verified, "LIVE_EXECUTOR_NOT_VERIFIED"),
        (evidence.live_verifier_verified, "LIVE_VERIFIER_NOT_VERIFIED"),
        (evidence.consecutive_live_successes >= 3, "GATHER_LIVE_SUCCESSES_LT_3"),
    )
    blockers = tuple(code for passed, code in checks if not passed)
    return GateResult(ready=not blockers, blockers=blockers)
