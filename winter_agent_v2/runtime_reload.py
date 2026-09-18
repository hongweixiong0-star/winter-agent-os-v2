"""``RUNTIME_RELOAD_REQUIRED``: a signal, not a second runtime manager.

Why a signal is enough
----------------------
Each AUTO cycle is a **fresh subprocess** -- ``tools/control_panel.py`` re-launches
``tools/run_live.py`` every time (measured: ``self.repeat_after_id =
self.root.after(5000, self.start)``), and that process imports ``vision``,
``brain``, ``skills`` and ``runtime`` from disk at start-up.  So there is nothing
to hot-patch: code that lands on disk is in effect on the *next* cycle by
construction, and inventing a reload manager would be adding a second runtime
manager to solve a problem that does not exist.

What the signal is actually for is the one hazard that does exist: **starting a
cycle while an editor is mid-write.**  A run that reads a half-written
``runtime.py`` can bind a verifier to the wrong function, which this project has
already hit once -- ``run_live.py`` carries a ``VERIFIER_MAPPING_CORRUPT`` guard
for exactly that, and it exists because the tree is edited from more than one
place at a time.

So this module is: a marker file, a recorded time, and one pure predicate that
decides whether the next cycle should wait.  Two rules keep it from becoming a
way to stall the loop:

* it only defers while a reload is *recent* or an escalation job is *active*, and
* it always gives up after :data:`MAX_DEFER_SECONDS`, so a hung agent can never
  stop AUTO.  A stalled development agent must not become a stalled game runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The name is the operator's, and it is written into the marker so a human
# reading the file knows what it means without opening this module.
REQUEST_KIND = "RUNTIME_RELOAD_REQUIRED"

# How long a fresh marker blocks the next cycle on its own.  A WorkBuddy job that
# just wrote files may still be flushing the last one; a couple of seconds is
# enough and keeps the wait invisible.
SETTLE_SECONDS = 20.0

# The hard ceiling.  Past this the marker is ignored (and cleared), because a
# development agent that hangs must not take the runtime down with it.
MAX_DEFER_SECONDS = 900.0


@dataclass(frozen=True)
class ReloadRequest:
    kind: str
    job_id: str
    reason: str
    requested_at: datetime
    evidence: tuple[str, ...] = ()

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or datetime.now(timezone.utc)) - self.requested_at).total_seconds()


@dataclass(frozen=True)
class Deferral:
    """Whether the next cycle should wait, and the sentence to log if so."""

    defer: bool
    reason: str

    def __bool__(self) -> bool:
        return self.defer


class ReloadSignal:
    """The marker file, and nothing else."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    # -- write ------------------------------------------------------------

    def request(self, job_id: str, reason: str, evidence: tuple[str, ...] = ()) -> ReloadRequest:
        """Record that code changed on disk and the next cycle should be careful."""
        request = ReloadRequest(
            kind=REQUEST_KIND,
            job_id=str(job_id),
            reason=str(reason),
            requested_at=datetime.now(timezone.utc),
            evidence=tuple(str(e) for e in evidence),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": request.kind,
            "job_id": request.job_id,
            "reason": request.reason,
            "requested_at": request.requested_at.isoformat(),
            "evidence": list(request.evidence),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return request

    # -- read -------------------------------------------------------------

    def pending(self) -> ReloadRequest | None:
        """The current marker, or ``None``.  A broken marker is treated as absent."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("kind") != REQUEST_KIND:
            return None
        try:
            requested_at = datetime.fromisoformat(str(payload.get("requested_at")))
        except ValueError:
            return None
        if requested_at.tzinfo is None:
            requested_at = requested_at.replace(tzinfo=timezone.utc)
        return ReloadRequest(
            kind=REQUEST_KIND,
            job_id=str(payload.get("job_id", "")),
            reason=str(payload.get("reason", "")),
            requested_at=requested_at,
            evidence=tuple(str(e) for e in (payload.get("evidence") or ())),
        )

    # -- decide -----------------------------------------------------------

    def evaluate(
        self,
        *,
        active_jobs: int = 0,
        now: datetime | None = None,
        settle_seconds: float = SETTLE_SECONDS,
        max_defer_seconds: float = MAX_DEFER_SECONDS,
        newest_write_at: datetime | None = None,
    ) -> Deferral:
        """Should the next cycle wait?  Pure, so the policy is testable.

        It defers for a *write*, and only for seconds.  Two rules, both learned the
        hard way.

        The wait is measured from the newest write to the tree, not from the marker.
        The marker records one instant; a job that keeps editing for the next hour
        would otherwise keep the wait alive on a stale timestamp -- measured
        2026-09-18, the panel logged the identical deferral every five seconds from
        a marker that was already 103 seconds old and could not get older in a way
        that mattered.

        An active job is *reported* and never waited for.  Waiting on "a job is
        active" was the first version of this, and it held AUTO off for up to
        ``max_defer_seconds`` whenever a development agent was working -- which is
        the operator's explicit prohibition ("禁止：等待 Job 完成才继续 AUTO",
        "WorkBuddy 开发不得阻塞 AUTO").  The hazard it guarded is a torn read during
        a write: a seconds-scale risk, contained when it happens (the worker exits
        before acting, and the next cycle runs) and covered where it is dangerous by
        ``run_live.py``'s VERIFIER_MAPPING_CORRUPT guard.  A stalled game is not a
        price worth paying for a rare crashed cycle.
        """
        request = self.pending()
        if request is None:
            return Deferral(False, "no reload pending")

        moment = now or datetime.now(timezone.utc)
        age = request.age_seconds(moment)
        active = f"job {request.job_id} is still working" if active_jobs > 0 else ""

        if age >= max_defer_seconds:
            return Deferral(
                False,
                f"reload marker from job {request.job_id} is {age:.0f}s old "
                f">= {max_defer_seconds:.0f}s ceiling; ignoring it so a hung "
                f"development agent cannot stall AUTO",
            )
        write_age = None if newest_write_at is None else (moment - newest_write_at).total_seconds()
        if write_age is None:
            write_age = age
        if write_age < settle_seconds:
            return Deferral(
                True,
                f"the tree was written {write_age:.0f}s ago"
                + (f" ({active})" if active else "")
                + f"; waiting {settle_seconds - write_age:.0f}s for the write to settle",
            )
        return Deferral(
            False,
            f"reload marker from job {request.job_id} is settled"
            + (f" ({active}, but AUTO is not held for it)" if active else ""),
        )

    # -- clear ------------------------------------------------------------

    def clear(self, reason: str = "consumed") -> bool:
        """Remove the marker.  ``True`` when there was one to remove."""
        if self.pending() is None:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        try:
            self.path.unlink(missing_ok=True)
            self.last_clearance_reason = reason
            return True
        except OSError:
            return False


def default_path(root: Path | str) -> Path:
    return Path(root) / "learning/RUNTIME_RELOAD_REQUIRED.json"


# Where a development agent can write code or a table.  Deliberately excludes
# ``learning/`` and ``dataset/``: an evidence frame landing must never postpone a run,
# and those directories change constantly.
WRITE_PATTERNS: tuple[str, ...] = (
    "winter_agent_v2/*.py",
    "tools/*.py",
    "config/*.json",
    "knowledge/**/*.json",
)


def newest_write(
    root: Path | str,
    patterns: tuple[str, ...] = WRITE_PATTERNS,
) -> datetime | None:
    """The most recent mtime among the files a development agent can change.

    Bounded and cheap (a few hundred stats), and it answers the question the settle
    window actually needs: "did a write just happen", rather than "is the marker
    recent".  Returns ``None`` when nothing matched, which the caller reads as
    "fall back to the marker's own age" instead of "no write ever".
    """
    base = Path(root)
    newest = 0.0
    for pattern in patterns:
        for path in base.glob(pattern):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    if not newest:
        return None
    return datetime.fromtimestamp(newest, timezone.utc)


def cutoff_for(now: datetime, seconds: float = MAX_DEFER_SECONDS) -> datetime:
    """Small helper for callers that want to query the marker by time."""
    return now - timedelta(seconds=seconds)
