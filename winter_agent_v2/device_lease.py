"""Single Device / Single UI Owner, as a lease and nothing else.

The operator's §8/§19: at any moment MuMu has exactly one input owner.  Normally that is
gameplay; while a development validation is running it is the validator.  Two owners
clicking at once is the failure this exists to make impossible, and it is a *lock*, not a
lifecycle: one file, one record, one predicate.

What it is not: a second runtime manager, a second executor, or a scheduler.  Nothing here
runs anything.  It records who owns the device, hands the device over at a safe point, and
expires a lease whose owner died.

Why a file and not a thread lock
--------------------------------
The two owners are separate processes (``tools/run_live.py`` for gameplay, and whatever the
validation path launches), and they are launched minutes apart by a panel that may itself
have been restarted.  An in-process lock cannot express "the parser holding this died"; a
record with an ``expires_at`` can, and that is the operator's §11 requirement that a
crashed validator must not hold MuMu forever.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEASE_FILE = "learning/DEVICE_LEASE.json"

OWNER_GAMEPLAY = "GAMEPLAY"
OWNER_DEVELOPMENT_VALIDATION = "DEVELOPMENT_VALIDATION"

# The operator's four words for the device row in the window.
DEVICE_IDLE = "V2控制中"
DEVICE_WAITING_SAFE_POINT = "等待安全点"
DEVICE_VALIDATING = "开发验证控制中"
DEVICE_RECOVERING = "恢复AUTO"

# How long a validation lease survives without being renewed.  Long enough for a real
# bounded verification run to finish (``max_actions`` at a few seconds each), short enough
# that a crashed process does not own the device for a working day.
DEFAULT_TTL_SECONDS = 900.0


@dataclass(frozen=True)
class LeaseRecord:
    owner: str
    trace_id: str = ""
    job_id: str = ""
    capability_id: str = ""
    reason: str = ""
    acquired_at: datetime | None = None
    expires_at: datetime | None = None
    released_at: datetime | None = None
    result: str = ""
    process: int = 0

    def expired(self, now: datetime | None = None) -> bool:
        """Has this lease's window passed *while it was still held*?

        A released lease is over, not expired.  Measured 2026-09-18: without this the
        window printed, verbatim, "lease by DEVELOPMENT_VALIDATION expired ... without
        being released (its process is gone or hung)" for a lease whose ``released_at``
        and ``result`` were both set -- it had been released three seconds after it was
        taken.  The device was fine; the sentence was the defect.
        """
        if self.released_at is not None:
            return False
        if self.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def as_row(self) -> dict:
        return {
            "owner": self.owner,
            "trace_id": self.trace_id,
            "job_id": self.job_id,
            "capability_id": self.capability_id,
            "reason": self.reason,
            "acquired_at": self.acquired_at.isoformat() if self.acquired_at else "",
            "expires_at": self.expires_at.isoformat() if self.expires_at else "",
            "released_at": self.released_at.isoformat() if self.released_at else "",
            "result": self.result,
            "process": self.process,
        }


def _moment(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class DeviceLease:
    """The lock.  Every method is safe to call from either owner's process."""

    def __init__(self, root: Path | str | None = None, *, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.root = Path(root) if root else Path(__file__).resolve().parents[1]
        self.path = self.root / LEASE_FILE
        self.ttl_seconds = float(ttl_seconds)

    # -- read -------------------------------------------------------------

    def holder(self, *, now: datetime | None = None) -> LeaseRecord | None:
        """Who owns the device right now, or ``None``.

        An expired lease is not a holder: it is a process that died or hung, and the
        operator's §11 says that must not lock MuMu.  The expiry is *reported* rather
        than hidden -- the caller can see it in ``state()`` -- because a lease that
        silently vanished is indistinguishable from one that was never taken.
        """
        record = self._read()
        if record is None:
            return None
        # A released record is history, not a holder.  Measured 2026-09-18: without this
        # the record stayed in the file with ``released_at`` set and ``holder()`` kept
        # returning it, so releasing the device did not actually return it -- which would
        # have broken §15 exactly where the protocol has to work.
        if record.released_at is not None:
            return None
        if record.expired(now):
            return None
        return record

    def state(self, *, now: datetime | None = None) -> str:
        """One of the operator's four words for the device row.

        The order is the operator's: a live validation outranks a waiting request, which
        outranks idle, and an expired lease reads as 恢复AUTO because that is what
        happens next -- gameplay takes the device back on its own.
        """
        moment = now or datetime.now(timezone.utc)
        record = self._read()
        if record is not None and record.released_at is None and record.expired(moment):
            return DEVICE_RECOVERING
        if (record is not None and record.released_at is None
                and record.owner == OWNER_DEVELOPMENT_VALIDATION):
            return DEVICE_VALIDATING
        if self.pending_request(now=moment) is not None:
            return DEVICE_WAITING_SAFE_POINT
        return DEVICE_IDLE

    def pending_request(self, *, now: datetime | None = None) -> LeaseRecord | None:
        """A request that has not been granted: gameplay still owns the device.

        This is the operator's 等待安全点: the validation asked, the current atomic
        action has not finished, and nobody may click until it does.  It is read from the
        audit trail rather than stored separately, so the request and the grant cannot
        disagree about which came first.
        """
        record = self._read()
        if record is not None and not record.expired(now or datetime.now(timezone.utc)):
            return None
        last_request = None
        for row in reversed(self._trail()[-20:]):
            if row.get("event") == "requested":
                last_request = _moment(row.get("recorded_at"))
                break
            if row.get("event") in ("acquired", "released", "release_noop"):
                break
        if last_request is None:
            return None
        return LeaseRecord(owner=OWNER_DEVELOPMENT_VALIDATION, acquired_at=last_request)

    def request(
        self,
        *,
        capability_id: str = "",
        job_id: str = "",
        trace_id: str = "",
        reason: str = "",
        now: datetime | None = None,
    ) -> tuple[LeaseRecord | None, str]:
        """Ask for the device without taking it.

        §8's order: request, wait for the current atomic Skill to finish, reach the safe
        point, and only then acquire.  Recording the request is what makes 等待安全点 a
        real state rather than an inference from a click that has not happened yet.
        """
        self._append({
            "event": "requested",
            "owner": OWNER_DEVELOPMENT_VALIDATION,
            "capability_id": capability_id,
            "job_id": job_id,
            "trace_id": trace_id,
            "reason": reason,
        })
        moment = now or datetime.now(timezone.utc)
        current = self.holder(now=moment)
        if current is not None:
            return None, f"requested; {current.owner} still owns the device"
        return self.acquire(
            owner=OWNER_DEVELOPMENT_VALIDATION, capability_id=capability_id,
            job_id=job_id, trace_id=trace_id, reason=reason, now=moment,
        )

    def describe(self, *, now: datetime | None = None) -> str:
        record = self._read()
        if record is None:
            return "no lease: gameplay owns the device"
        if record.released_at is not None:
            # Released is history, and it must be described as history.  Checking expiry
            # first printed the orphan sentence for a lease that had been handed back.
            return (f"{record.owner} released the device for {record.capability_id or '(unnamed)'}"
                    f" (job={record.job_id or '-'}, result={record.result or '-'},"
                    f" released_at={record.released_at.isoformat()})")
        if record.expired(now):
            return (f"lease by {record.owner} expired at {record.expires_at.isoformat()} "
                    f"without being released (its process is gone or hung)")
        return (f"{record.owner} owns the device for {record.capability_id or '(unnamed)'}"
                f" (job={record.job_id or '-'}, since {record.acquired_at.isoformat() if record.acquired_at else '-'})")

    # -- write ------------------------------------------------------------

    def acquire(
        self,
        *,
        owner: str,
        capability_id: str = "",
        job_id: str = "",
        trace_id: str = "",
        reason: str = "",
        ttl_seconds: float | None = None,
        now: datetime | None = None,
    ) -> tuple[LeaseRecord | None, str]:
        """Take the device, or explain who has it.

        Returns ``(record, reason)``.  A refusal is not an error: it is the device being
        busy, which the caller must handle by waiting for the safe point the operator
        describes in §8 rather than by clicking anyway.
        """
        moment = now or datetime.now(timezone.utc)
        current = self.holder(now=moment)
        if current is not None and current.owner != owner:
            return None, f"{current.owner} holds it: {current.reason or current.capability_id}"
        if current is not None and current.owner == owner:
            return current, "already held by the same owner"
        ttl = self.ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        record = LeaseRecord(
            owner=owner,
            trace_id=trace_id,
            job_id=job_id,
            capability_id=capability_id,
            reason=reason,
            acquired_at=moment,
            expires_at=moment + timedelta(seconds=ttl),
            process=os.getpid(),
        )
        self._write(record, event="acquired")
        return record, "acquired"

    def release(self, *, result: str, reason: str = "", now: datetime | None = None) -> bool:
        """Give the device back.  Idempotent, and never raises.

        §15: the release happens regardless of PASS / FAIL / BLOCKED, so the caller is
        expected to use it in a ``finally``.  Releasing when nothing is held is a no-op
        that still writes a row, because "who released what when" is the audit trail.
        """
        moment = now or datetime.now(timezone.utc)
        record = self._read()
        if record is None or record.released_at is not None:
            self._append({"event": "release_noop", "reason": reason, "result": result})
            return False
        released = LeaseRecord(
            owner=record.owner, trace_id=record.trace_id, job_id=record.job_id,
            capability_id=record.capability_id, reason=record.reason,
            acquired_at=record.acquired_at, expires_at=record.expires_at,
            released_at=moment, result=result, process=record.process,
        )
        self._write(released, event="released")
        return True

    def renew(self, *, now: datetime | None = None) -> bool:
        """Push the expiry out for a validation that is still legitimately running."""
        record = self._read()
        if record is None:
            return False
        moment = now or datetime.now(timezone.utc)
        # The lease keeps the duration it was granted with, so renewing a short
        # validation lease does not silently upgrade it to the module default.
        span = (record.expires_at - record.acquired_at
                if record.expires_at and record.acquired_at
                else timedelta(seconds=self.ttl_seconds))
        renewed = LeaseRecord(
            owner=record.owner, trace_id=record.trace_id, job_id=record.job_id,
            capability_id=record.capability_id, reason=record.reason,
            acquired_at=record.acquired_at,
            expires_at=moment + span,
            released_at=record.released_at, result=record.result, process=record.process,
        )
        self._write(renewed, event="renewed")
        return True

    # -- plumbing ---------------------------------------------------------

    def _read(self) -> LeaseRecord | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return LeaseRecord(
            owner=str(payload.get("owner") or ""),
            trace_id=str(payload.get("trace_id") or ""),
            job_id=str(payload.get("job_id") or ""),
            capability_id=str(payload.get("capability_id") or ""),
            reason=str(payload.get("reason") or ""),
            acquired_at=_moment(payload.get("acquired_at")),
            expires_at=_moment(payload.get("expires_at")),
            released_at=_moment(payload.get("released_at")),
            result=str(payload.get("result") or ""),
            process=int(payload.get("process") or 0),
        )

    def _write(self, record: LeaseRecord, *, event: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(record.as_row(), ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass
        self._append({"event": event, **record.as_row()})

    def _trail(self) -> list[dict]:
        """The audit rows, oldest first.  An unreadable file is an empty trail."""
        try:
            lines = (self.root / "learning/device_leases.jsonl").read_text(
                encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _append(self, row: dict) -> None:
        """The audit trail: §19 requires trace_id, job_id, capability, both times, result."""
        try:
            path = self.root / "learning/device_leases.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(
                    {"recorded_at": datetime.now(timezone.utc).isoformat(), **row},
                    ensure_ascii=False,
                ) + "\n")
        except OSError:
            pass
