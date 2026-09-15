"""Persistent record of when the free stamina gift becomes claimable.

Why this exists
---------------
The free 丰盛的招待 gift (+150 stamina) is only offered at a fixed cadence, and
the panel shows the wait as an absolute countdown (``下次补给 06:47:35``).
Measured 2026-09-15, three independent frames:

    ==========================  =========  ============  ==============
    frame (UTC)                 countdown  implies       confidence
    ==========================  =========  ============  ==============
    03:46:43                    00:13:18   04:00:01Z     0.963
    03:59:46.7                  00:00:15   04:00:01.7Z   0.965
    04:12:26 (just claimed)     06:47:35   11:00:01Z     0.936
    ==========================  =========  ============  ==============

The first two are 13 minutes apart and agree to within a second, so the
countdown is a real absolute time, not an animation.  The first and third are
exactly 7 hours apart (04:00:01 / 11:00:01 UTC), so the supply is not daily --
it is 3-4 times a day.

Why it matters: the check that finds the gift lives in the world-map branch of
the brain, but the unattended intel loop spends its whole run on the intel page
(measured 2026-09-15T04:10Z: a run that started on an intel pin popup never
stood on the map once).  Without knowing *when* to go to the map, either the
check never runs at all, or it would have to be attempted on every single cycle
-- about 40 wasted actions an hour for something available three times a day.

Storing the instant makes the detour a dated event: don't go unless the supply
is actually due.

A missing or corrupt file means "unknown", never "due": this is an
optimisation, and an unknown answer must not spend the operator's actions.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_PATH = Path("learning/stamina_supply.json")


class StaminaSupplyStore:
    """Persist the instant the free gift becomes claimable.

    Deliberately tiny and defensive: like :class:`ResourceRotationStore`, this
    state is learned from the client and is an optimisation, not a source of
    truth.  A damaged file must never break a run.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def next_supply_at(self) -> datetime | None:
        payload = self._read()
        raw = payload.get("next_supply_at")
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        # A naive timestamp cannot be compared against "now"; treat it as absent
        # rather than guessing a timezone.
        return parsed if parsed.tzinfo is not None else None

    def record(self, countdown_seconds: int, *, at: datetime | None = None) -> datetime:
        """Save the instant implied by a countdown read from the panel."""
        now = at or datetime.now(timezone.utc)
        instant = now + timedelta(seconds=max(0, int(countdown_seconds)))
        self._write({"next_supply_at": instant.isoformat(), "recorded_at": now.isoformat()})
        return instant

    def is_due(self, *, at: datetime | None = None) -> bool:
        """True only when the supply instant is known *and* has passed.

        Unknown is not due.  Going to the map on a guess is exactly the waste
        this store exists to prevent.
        """
        now = at or datetime.now(timezone.utc)
        instant = self.next_supply_at()
        return instant is not None and now >= instant

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            # Losing this optimisation must never lose a run.
            pass
