from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AttemptState:
    activity: str
    remaining: int | None
    reset_seconds: int | None
    cooldown_seconds: int | None = None
    raid_available: bool = False


def attempt_priority(state: AttemptState) -> float:
    if state.remaining is None or state.remaining <= 0:
        return 0.0
    value = float(state.remaining * 100)
    if state.reset_seconds is not None:
        if state.reset_seconds < 2 * 3600:
            value += 10_000
        elif state.reset_seconds < 6 * 3600:
            value += 4_000
        elif state.reset_seconds < 24 * 3600:
            value += 1_000
    if state.cooldown_seconds and state.cooldown_seconds > 0:
        value -= min(value, state.cooldown_seconds / 10)
    if state.raid_available:
        value += 100
    return value
