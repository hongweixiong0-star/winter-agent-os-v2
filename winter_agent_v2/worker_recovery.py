from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class RecoveryOutcome:
    ready: bool
    stopped: bool
    attempts: int
    retries: int
    elapsed_seconds: float
    last_error: str | None = None


def retry_until_ready(
    operation: Callable[[], object],
    *,
    should_stop: Callable[[], bool],
    wait: Callable[[float], bool],
    is_recoverable: Callable[[Exception], bool],
    on_retry: Callable[[Exception, int, float, float], None],
    initial_delay_seconds: float = 5.0,
    max_delay_seconds: float = 60.0,
    clock: Callable[[], float] = monotonic,
) -> RecoveryOutcome:
    """Retry recoverable startup failures with bounded exponential backoff.

    ``wait`` returns true when an operator stop interrupts the delay.  Non-
    recoverable exceptions escape immediately to the normal worker crash path.
    """
    started = clock()
    attempts = 0
    retries = 0
    last_error: str | None = None
    while not should_stop():
        attempts += 1
        try:
            operation()
        except Exception as exc:
            if not is_recoverable(exc):
                raise
            last_error = f"{type(exc).__name__}: {exc}"
            if should_stop():
                break
            retries += 1
            delay = max(0.0, initial_delay_seconds)
            max_delay = max(0.0, max_delay_seconds)
            delay = min(delay, max_delay)
            for _ in range(max(0, retries - 1)):
                if delay <= 0.0 or delay >= max_delay:
                    break
                delay = min(max_delay, delay * 2.0)
            elapsed = max(0.0, clock() - started)
            on_retry(exc, retries, delay, elapsed)
            if wait(delay):
                return RecoveryOutcome(False, True, attempts, retries, max(0.0, clock() - started), last_error)
            continue
        return RecoveryOutcome(True, False, attempts, retries, max(0.0, clock() - started), last_error)
    return RecoveryOutcome(False, True, attempts, retries, max(0.0, clock() - started), last_error)
