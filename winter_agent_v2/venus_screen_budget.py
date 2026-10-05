"""The half of §48's per-screen budget that has to outlive one run.

§48 (``PRINCIPLES.md``) is explicit:

    同一 Screen：默认最多约 2 次 Venus 尝试。
    超过后：Recovery → Cooldown → Next Goal。
    禁止：Venus → Replan → Venus → Replan 无限循环。

**The within-run half is already implemented, and it works.**  ``ManagedAdvisor`` carries
``max_steps_per_screen`` (2), counts in ``_per_screen``, and ``take_guard`` refuses with
``PLANNER_SCREEN_BUDGET_SPENT``.  ``take_guard`` has exactly one caller and it runs before the model
is asked, so two attempts per screen per run is real.

**The other half is missing, and the arithmetic says so.**  ``runtime.py`` builds the advisor *fresh
per run* -- its own comment says "a factory (called for a fresh advisor with fresh per-run
budgets)" -- so the counter resets every cycle and the same screen is worth two more attempts
forever.  Measured 2026-10-06 in ``learning/ui_venus_online.jsonl``: 228 ``VENUS_CALLED`` rows
across 13 ``request_id``s, one of them (``home__control__36e65c39``) called **84** times, which is
about 42 runs at two per run; ``UNKNOWN_RESOLUTION_RATE`` was 0.0 and
``UNKNOWN_REPEAT_MODEL_CALL_RATE`` 0.7761.

The project answered this shape once already, for the *other* UNKNOWN path:
``unknown_advisor.ask()`` bounds each run at ``MAX_REQUESTS_PER_RUN`` and never repeats the same
(screen, question) inside ``REQUEST_COOLDOWN_SECONDS``, persisted to a file.  The ONLINE path does
not go through that advisor, so this module supplies the same bound rather than inventing a second
vocabulary -- **both constants are imported from ``unknown_advisor``**, and the key is the same
``request_id`` it keys on.

The three states are the canonical circuit breaker (closed / open / half-open), because the
directive's "then Recovery → Cooldown → Next Goal" *is* that pattern:

    under budget                    -> allow
    at budget, inside the cooldown  -> refuse          (the bound that was missing)
    at budget, cooldown elapsed     -> allow one probe  (half-open)

**The probe is what keeps this a deferral rather than a starvation.**  A screen that becomes
readable later must be reconsidered, or the fix would trade a loop for a hole (§36/§38 require
proving liveness alongside safety).  It needs no separate "probe" field: recording the probe as an
attempt moves ``last_at`` to now, which restarts the cooldown, so exactly one probe fits in each
window by construction.

Failures count.  A ``VENUS_CALL_FAILED`` consumed a call, and the ledger shows 66 of the 70
attempts on ``unknown__control__57d12023`` were outright call failures -- if those did not count as
attempts the screen would be retried forever.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from .unknown_advisor import MAX_REQUESTS_PER_RUN, REQUEST_COOLDOWN_SECONDS

#: §48's "默认最多约 2 次".  Kept here as the single number, and ``ui_planner``'s
#: ``max_steps_per_screen`` default now points at it, so the within-run and cross-run halves of the
#: same rule cannot drift apart.  ``MAX_REQUESTS_PER_RUN`` is the sibling bound for the other
#: UNKNOWN path, at the same value, imported rather than restated.
BUDGET_PER_SCREEN = MAX_REQUESTS_PER_RUN

#: Where the attempts outlive the run that made them.
STORE_PATH = Path("learning/venus_screen_attempts.json")

#: How long a screen stays refused once it has spent its budget.  Imported: ``unknown_advisor``
#: already decided this for the same (screen, question) shape, and two cooldowns for one rule is
#: two rules.
COOLDOWN_SECONDS = REQUEST_COOLDOWN_SECONDS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load(path: Path | str = STORE_PATH) -> dict[str, dict]:
    """The attempt record, or an empty one.

    A file that will not parse is treated as empty rather than fatal: the failure direction
    matters, and "cannot read the budget" must not become "refuse every screen" -- that would stop
    the learning path on a corrupted byte.  The next ``record`` overwrites it.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    return {
        str(key): dict(value) for key, value in payload.items()
        if isinstance(value, Mapping)
    }


def _save(state: Mapping[str, dict], path: Path | str = STORE_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)


def allow(
    request_id: str, *, path: Path | str = STORE_PATH, now: datetime | None = None,
    cooldown_seconds: float = COOLDOWN_SECONDS,
    budget: int = BUDGET_PER_SCREEN,
) -> tuple[bool, str]:
    """``(may_ask, why)`` for one screen, across runs.

    ``request_id`` is the project's own identity for a question (the same key
    ``unknown_advisor.ask`` suppresses on), so this is finer than a page: a page carrying several
    distinct unknowns does not over-suppress, which is what keeps the bound from becoming a hole.
    """
    key = str(request_id or "").strip()
    if not key:
        # No identity means no evidence that this is a repeat; refusing would block every
        # anonymous question, so the honest answer is "not my business".
        return True, "no_request_identity"
    record = load(path).get(key)
    if record is None:
        return True, "first_attempt"
    try:
        attempts = int(record.get("attempts") or 0)
    except (TypeError, ValueError):
        return True, "attempts_unreadable"
    if attempts < budget:
        return True, f"attempt_{attempts + 1}_of_{budget}"
    last = _moment(record.get("last_at"))
    if last is None:
        return True, "last_attempt_unreadable"
    elapsed = ((now or _now()) - last).total_seconds()
    if elapsed >= cooldown_seconds:
        return True, "probe_after_cooldown"
    return False, f"screen_cooldown_active:{int(elapsed)}s_of_{int(cooldown_seconds)}s"


def record(
    request_id: str, *, path: Path | str = STORE_PATH, now: datetime | None = None,
    budget: int = BUDGET_PER_SCREEN,
) -> dict:
    """Count one dispatched attempt, successful or not.

    Recorded *before* the call, on purpose: a call that times out or fails still spent the screen's
    budget, and the ledger shows screens whose attempts were almost entirely call failures.  If
    failures were free, the loop §48 forbids would run on them.
    """
    key = str(request_id or "").strip()
    state = load(path)
    if not key:
        return state
    record_row = dict(state.get(key) or {})
    try:
        record_row["attempts"] = int(record_row.get("attempts") or 0) + 1
    except (TypeError, ValueError):
        record_row["attempts"] = 1
    record_row["last_at"] = (now or _now()).isoformat()
    record_row["budget"] = int(budget)
    state[key] = record_row
    # Bounded -- but an entry may only be forgotten once it has **stopped suppressing**.  My first
    # version evicted the oldest entries, and a test caught what that reopens: the oldest attempts
    # are exactly the ones still inside their cooldown, so churn on other screens silently released
    # the loop this module exists to close.
    #
    # So the only entries this ever drops are the expired ones, and it drops all of them: once a
    # screen's cooldown has elapsed it refuses nothing, so keeping some of them would be an
    # arbitrary floor.  The table is therefore exactly "screens attempted inside the cooldown" --
    # bounded by the rate rather than by a constant, and self-cleaning.  In production that set is
    # tiny: the ledger that motivated this module held 13 request_ids in an hour.
    cutoff = (now or _now()) - timedelta(seconds=COOLDOWN_SECONDS)
    expired = [
        other for other, row in state.items()
        if other != key and (_moment(row.get("last_at")) or cutoff) < cutoff
    ]
    for other in expired:
        del state[other]
    _save(state, path)
    return state
