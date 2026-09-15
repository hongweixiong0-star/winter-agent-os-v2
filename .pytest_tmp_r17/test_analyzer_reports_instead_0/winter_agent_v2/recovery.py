from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureType(str, Enum):
    UNKNOWN = "UNKNOWN"
    DEVICE_BUSY = "DEVICE_BUSY"
    QWEN_BUSY = "QWEN_BUSY"
    OCR_FAILED = "OCR_FAILED"
    NO_MARCH = "NO_MARCH"
    POPUP = "POPUP"
    TIMEOUT = "TIMEOUT"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    PAGE_NOT_FOUND = "PAGE_NOT_FOUND"


class RecoveryAction(str, Enum):
    DISMISS_POPUP = "DISMISS_POPUP"
    BACK = "BACK"
    REFRESH_SCREEN = "REFRESH_SCREEN"
    REFRESH_STATE = "REFRESH_STATE"
    REOPEN_PAGE = "REOPEN_PAGE"
    RETRY = "RETRY"
    SWITCH_TASK = "SWITCH_TASK"
    SAFE_STOP = "SAFE_STOP"
    FALLBACK_RULE = "FALLBACK_RULE"
    WAIT = "WAIT"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    blocked: bool
    retry_count: int
    reason: str


class Recovery:
    def __init__(self, max_retries: int = 2) -> None:
        if max_retries < 0 or max_retries > 2:
            raise ValueError("V2 retry budget must be between 0 and 2")
        self.max_retries = max_retries
        self._attempts: dict[tuple[str, FailureType], int] = {}

    def decide(self, skill_id: str, failure: FailureType) -> RecoveryDecision:
        key = (skill_id, failure)
        count = self._attempts.get(key, 0)
        if failure is FailureType.POPUP:
            action = RecoveryAction.DISMISS_POPUP
        elif failure is FailureType.QWEN_BUSY:
            action = RecoveryAction.FALLBACK_RULE
        elif failure in {FailureType.NO_MARCH, FailureType.RESOURCE_NOT_FOUND}:
            return RecoveryDecision(RecoveryAction.SWITCH_TASK, True, count, failure.value)
        elif failure is FailureType.UNKNOWN:
            action = RecoveryAction.REFRESH_SCREEN
        elif failure is FailureType.OCR_FAILED:
            action = RecoveryAction.REFRESH_STATE
        elif failure is FailureType.PAGE_NOT_FOUND:
            action = RecoveryAction.REOPEN_PAGE
        elif failure is FailureType.DEVICE_BUSY:
            action = RecoveryAction.WAIT
        else:
            action = RecoveryAction.RETRY
        if count >= self.max_retries:
            return RecoveryDecision(RecoveryAction.SWITCH_TASK, True, count, "RETRY_EXHAUSTED")
        count += 1
        self._attempts[key] = count
        return RecoveryDecision(action, False, count, failure.value)

    def success(self, skill_id: str) -> None:
        for key in [key for key in self._attempts if key[0] == skill_id]:
            del self._attempts[key]
