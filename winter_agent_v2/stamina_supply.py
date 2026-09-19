"""Persistent record of when the free stamina gift becomes claimable.

Why this exists
---------------
The free 丰盛的招待 gift (+150 stamina) is only offered at a fixed cadence, and
the panel shows the wait as an absolute countdown (``下次补给 06:47:35``).
Measured 2026-09-15, four independent frames:

    ==========================  =========  ============  ==============
    frame (UTC)                 countdown  implies       confidence
    ==========================  =========  ============  ==============
    03:46:43                    00:13:18   04:00:01Z     0.963
    03:59:46.7                  00:00:15   04:00:01.7Z   0.965
    04:12:26 (just claimed)     06:47:35   11:00:01Z     0.936
    12:31:13 (just claimed)     15:28:49   09-16 04:00:03Z  0.99
    ==========================  =========  ============  ==============

The first two are 13 minutes apart and agree to within a second, so the
countdown is a real absolute time, not an animation.

Do NOT read a fixed cadence out of these samples. The first and third imply a
7-hour gap, but the fourth -- claimed 15.5 hours before its own next tick --
kills that reading; an earlier note here guessed "3-4 times a day" from the
7-hour pair alone and that guess is not supported. Samples 3 and 4 also differ
in another way: at 11:00:01Z the gift was *not* claimable when the panel was
next read, while at 12:31:13 it was. So the countdown is the authority and the
mechanism behind it is still UNKNOWN. The brain never predicts a tick from a
cadence -- it stores the instant the panel reported and asks whether that
instant has passed.

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

#: How long a claim that did not prove suppresses the next attempt.
#:
#: Measured live 2026-09-19T05:17Z (bounded probe, ``popup OPEN_MAP_BACK``): the
#: 丰盛的招待 领取 control is still drawn and still matches its template at
#: distance 0, but a tap on its centre changes nothing -- the panel returns to
#: the same state, so ``FREE_STAMINA_CLAIM_NOT_PROVEN`` is the honest reading and
#: eight consecutive runs proved it is not transient.  Without a bound the brain
#: re-decides the claim from the frame alone on every cycle and the whole agent
#: wedges on the panel (four goals in a row, 2026-09-19T05:07Z..05:15Z).
#:
#: 30 minutes is a *bounded retry*, not a surrender: the gift is still attempted,
#: just not once per run.  The supply cadence is hours (see the module docstring),
#: so this cannot plausibly skip a fresh gift.
DEFAULT_CLAIM_COOLDOWN_SECONDS = 1800.0


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

    def claim_refused_at(self) -> datetime | None:
        """When the free gift was last tapped and the claim did not prove."""
        return self._moment("claim_refused_at")

    def record_claim_refused(self, *, at: datetime | None = None) -> datetime:
        """Remember that tapping the free control did not change the panel.

        This is a *negative* result recorded from production evidence, so it is
        written where the positive countdown lives: the panel is the only place
        either is observable, and the runs in between must not re-learn it by
        tapping the same dead control (see ``DEFAULT_CLAIM_COOLDOWN_SECONDS``).
        """
        now = at or datetime.now(timezone.utc)
        self._write({"claim_refused_at": now.isoformat(), "recorded_at": now.isoformat()})
        return now

    def claim_cooling_down(
        self, *, at: datetime | None = None, cooldown_seconds: float = DEFAULT_CLAIM_COOLDOWN_SECONDS
    ) -> bool:
        """True while a refused claim should not be retried yet.

        Absent is False: an unknown refusal must never suppress a claim that has
        not actually been attempted.  Only a recorded refusal can hold it back.
        """
        refused = self.claim_refused_at()
        if refused is None:
            return False
        now = at or datetime.now(timezone.utc)
        return now - refused < timedelta(seconds=max(0.0, float(cooldown_seconds)))

    def is_due(self, *, at: datetime | None = None) -> bool:
        """True only when the supply instant is known *and* has passed.

        Unknown is not due.  Going to the map on a guess is exactly the waste
        this store exists to prevent.
        """
        now = at or datetime.now(timezone.utc)
        instant = self.next_supply_at()
        return instant is not None and now >= instant

    def _moment(self, key: str) -> datetime | None:
        raw = self._read().get(key)
        if not isinstance(raw, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        # A naive timestamp cannot be compared against "now"; treat it as absent
        # rather than guessing a timezone.
        return parsed if parsed.tzinfo is not None else None

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Merge rather than replace: the supply instant and the refusal are
            # two independent facts about the same panel and each is learned on a
            # different visit, so a plain overwrite would silently drop whichever
            # one this call did not carry.
            merged = self._read()
            merged.update(payload)
            self.path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            # Losing this optimisation must never lose a run.
            pass
