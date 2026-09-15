from __future__ import annotations

from dataclasses import dataclass

from .models import Action


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reason: str


class SafetyPolicy:
    BLOCKED_KINDS = {
        "REAL_MONEY_PAYMENT",
        "REAL_MONEY_PURCHASE",
        "ACCOUNT_DELETE",
        "ROLE_DELETE",
        "ACCOUNT_SECURITY_CHANGE",
        "SYSTEM_DANGEROUS",
    }

    def evaluate(self, action: Action) -> PolicyResult:
        if action.kind in self.BLOCKED_KINDS:
            return PolicyResult(False, f"HARD_SAFETY_BLOCKED:{action.kind}")
        if action.kind == "PURCHASE" and action.payload.get("currency") in {"CNY", "USD", "REAL_MONEY"}:
            return PolicyResult(False, "HARD_SAFETY_BLOCKED:REAL_MONEY_PURCHASE")
        return PolicyResult(True, "OK")
