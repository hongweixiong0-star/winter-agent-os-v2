"""Which goal paths AUTO must stop re-entering, and why.

A project the agent cannot do yet must not be a project the agent does forever.
Measured 2026-09-18 08:20 local: 58 of the last 60 production episodes were
``AVOID_STAMINA_WASTE / SCAN_MAP_FOR_BEAST`` with ``verifier_ok=True`` and the
stamina reading never leaving 457.  Every step passed its verifier, the goal made no
progress for twenty minutes, the escalation for that very capability was already
sitting in ``COOLDOWN`` (``SPEND_STAMINA_ON_BEAST``, ``TEST_PASS``, repair budget
spent) -- and the loop went on selecting the same goal every 30 seconds, because
nothing connected the queue's verdict back to the scheduler.

This module is that connection, and it is a **projection**: it stores nothing.  Its
inputs are artifacts the project already keeps -- the escalation ledger and the
episode stream -- and its output is a set of :class:`Deferral` rows.  There is one
scheduler, one registry, one world state and one escalation queue; this only answers
a question the scheduler was never asking:

    "is this the same path that already failed, and has anything really changed?"

Three rules decide a deferral, in this order:

1. **The path a development agent is already working on.**  While a capability has a
   job in ``SUBMITTED``/``WORKING`` it is ``DEVELOPMENT_PENDING`` and the goal that
   routes through it is deferred unconditionally -- a probe would only hit the same
   wall the agent is being paid to remove.  Matched through the goal's own attempted
   skills via ``capability_skill_map.json``, so "the same failing path" is a measured
   fact rather than a guess about which capability a route belongs to.
2. **Every path the goal has.**  ``SEQUENCE`` goals are deferred when any required
   capability is unavailable; ``ANY_OF`` goals only when *all* of their capabilities
   are, because one unavailable path must not switch off the sibling routes that
   reach the same goal.
3. **No goal progress.**  Consecutive production episodes of the same goal whose
   measured ``goal_progress`` is ``False`` -- the count that says "this path is not
   advancing the goal", which is invisible in the verifier's own answer.

Re-entry is never "30 seconds later".  A deferral either waits for a real change (a
job settling, a reload completing) or expires into a deliberate low-frequency probe,
so a broken path is neither retried in a soft loop nor starved forever.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .goal_library import GoalComposition, GoalState, goal_compositions

# The capability run states the operator asked for.  ``RUNNABLE`` and
# ``LIVE_VERIFIED`` are the two that permit scheduling; the rest defer.
RUNNABLE = "RUNNABLE"
DEVELOPMENT_PENDING = "DEVELOPMENT_PENDING"
DEFERRED = "DEFERRED"
COOLDOWN = "COOLDOWN"
BLOCKED = "BLOCKED"
LIVE_VERIFIED = "LIVE_VERIFIED"

DEFERRING_STATES = frozenset({DEVELOPMENT_PENDING, DEFERRED, COOLDOWN, BLOCKED})
#: States in which a path cannot run at all, as opposed to waiting for a job to finish.
#: Used for the ANY_OF exemption in ``_capability_deferral``: a goal with another runnable path
#: may proceed when this one is blocked or cooling down, but not while a job is inside it.
PATH_CANNOT_RUN = frozenset({COOLDOWN, BLOCKED})

SOURCE_QUEUE = "ESCALATION_QUEUE"
SOURCE_NO_PROGRESS = "NO_GOAL_PROGRESS"
#: "This run may not execute this goal" is deliberately NOT a Deferral source.  A Deferral in
#: ``run.deferrals`` means "the deferral gate refused this path", and that list is read as such
#: by the escalation hook, the deferred-goal board and four tests -- so a run-level execution
#: limit filed there would put non-gaps on the board the operator reads as gaps.  Yields are
#: narrated into the run log instead (see ``LiveRuntime._narrate_once``).

# How long a deferral holds before one probe run is permitted again.  Both exist so
# that "deferred" cannot become "abandoned": a path the development agent has given
# up on is re-probed every three hours, a path that is merely not advancing every
# half hour.  Neither is anywhere near the 30-second loop that produced this module.
BLOCKED_PROBE_MINUTES = 180
NO_PROGRESS_PROBE_MINUTES = 30

# Consecutive measured-no-progress episodes of one goal before it steps aside.
# Three is one full bounded run of the beast route (``max_beast_scans``), so an
# ordinary single failure is still AUTO's own business to retry.
NO_PROGRESS_STREAK = 3

# How far back the deferral projection reads, in hours.
#
# The gate reads episodes, not a queue, so the window is the whole of its memory: a goal
# whose attempts all sit outside it is not "not stalled", it is **invisible**, and no rule
# here can say anything about it.  Measured 2026-10-08 on the live ledger: the old
# 400-row read returned 138 rows spanning **1 h 50 m of a single goal**
# (``AVOID_STAMINA_WASTE``), so ``attempted`` held exactly one goal out of the 24 that had
# really run, ``streaks`` held one entry, and the no-progress rule could only ever fire
# for whichever goal happened to dominate the tail.  The 34-alternation
# ``SUBMIT_RESOURCE_SEARCH`` <-> ``BACK`` loop that burned 6.5 minutes under
# ``KEEP_MARCHES_PRODUCTIVE`` on 2026-10-08 00:42 could not be deferred, because
# ``KEEP_MARCHES_PRODUCTIVE`` was not in the window at all.
#
# 24 h is not a round number, it is where the answer stops changing.  Replayed over the
# same ledger (``E:/experiments/gate_window_replay.py``): 6 h reaches 15 goals and defers
# 5; 24 h reaches 24 goals and defers 9; 72 h reaches the same 24 and defers the same 9.
# So past a day the projection is already saturated, and a longer window buys nothing but
# parse time.  Cost at 24 h: 2,586 rows and 0.56-0.72 s for the read, once per run.
EPISODE_WINDOW_HOURS = 24

# The most episode rows one read keeps.
#
# This is the **cost cap, not the definition** of the window.  Measured, 24 h of this
# ledger is ~2,600 rows and bursts reach ~4,200 rows/day, so 4,000 covers a day on the
# history this was measured against.
EPISODE_TAIL = 4000

# The most bytes one read touches, so a ledger of unusually fat rows cannot make the gate
# slow.  When this binds it returns *fewer* rows, which can only make the window smaller
# and therefore quieter -- a cap can never invent a deferral.  Measured mean row: 13,508 B
# (2026-10-08), i.e. 4,000 rows ~= 54 MB.
EPISODE_TAIL_BYTES = 64 * 1024 * 1024

# The size of one backwards step while looking for the tail.
EPISODE_TAIL_CHUNK = 1 << 20

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Skill -> capability memo, so a per-step deferral check does not re-read the table.
_SKILL_CAPABILITY_CACHE: dict[str, str] = {}


@dataclass(frozen=True)
class Deferral:
    """One goal path the scheduler must not select, with the evidence for it.

    ``until`` is **the moment this deferral stops applying** -- the single meaning the
    board renders as "至".  It is not the escalation ledger's ``cooldown_until``: for a
    capability whose repair budget is spent, the gate re-admits the goal on a probe
    window measured from the goal's *own* newest attempt, so the ledger's deadline can
    be days in the past while the path is still held.  Measured 2026-10-05: the board
    printed ``至 2026-09-23`` for ``DAILY_ACTIVITY_TARGET`` while that goal had run 28
    minutes earlier and would be admitted again 180 minutes after it.  Reporting the
    ledger field made a working probe look like a permanent stall -- see
    ``blocks()``, which now fills this with the deadline it actually applies.
    """

    goal_id: str
    state: str
    reason: str
    capability: str = ""
    source: str = SOURCE_QUEUE
    failure_signature: str = ""
    until: datetime | None = None
    probe_minutes: int = 0
    streak: int = 0
    last_attempt: datetime | None = None
    last_skill: str = ""

    def describe(self) -> str:
        scope = f" on {self.capability}" if self.capability else ""
        upto = f" until {self.until.isoformat()}" if self.until else ""
        streak = f" after {self.streak} episode(s) without progress" if self.streak else ""
        return f"{self.goal_id} -> {self.state}{scope}: {self.reason}{streak}{upto}"

    def as_row(self) -> dict[str, Any]:
        """Serialisable form, for the runtime snapshot and the escalation hook."""
        return {
            "goal_id": self.goal_id,
            "capability": self.capability,
            "state": self.state,
            "reason": self.reason,
            "source": self.source,
            "failure_signature": self.failure_signature,
            "streak": self.streak,
            "until": self.until.isoformat() if self.until else "",
            "last_skill": self.last_skill,
        }


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _first_line_stamp(blob: bytes, offset: int) -> datetime | None:
    """``recorded_at`` of the oldest complete line in ``blob``, or ``None``.

    ``blob`` was read backwards, so its first line is the tail of a record that starts
    before the read whenever ``offset > 0``; that partial line is skipped rather than
    parsed.  ``None`` means "could not read this one", and every caller treats it as
    "keep going" rather than as a boundary: one unreadable line must not be able to cut
    the window short.
    """
    parts = blob.split(b"\n", 2)
    index = 1 if offset else 0
    if len(parts) <= index:
        return None
    try:
        payload = json.loads(parts[index].decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _moment(payload.get("recorded_at"))


def _episode_tail(
    path: Path,
    limit: int = EPISODE_TAIL,
    *,
    hours: float | None = EPISODE_WINDOW_HOURS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """The newest episode rows within ``hours``, at most ``limit`` of them.

    **The old reader did not return what it said it did, and the gap was the whole
    window.**  It seeked back ``limit * 4096`` bytes and its own comment called 4 KiB "a
    generous upper bound" for an episode.  Measured 2026-10-08: the live ledger's mean row
    is **13,508 B** -- 3.3x the claimed bound -- so ``limit=400`` returned **138 rows**,
    1 h 50 m of one goal.  Nothing downstream could tell: ``CapabilityGate.load`` asked for
    400 rows, got 138, and every rule that says "this goal is not advancing" silently
    became a rule about ``AVOID_STAMINA_WASTE`` alone.

    So the read grows backwards in chunks until it really has ``limit`` rows, reaches the
    start of the file, or is older than the window.  Growing rather than guessing is the
    standard shape for this problem (there is no stdlib helper for it), and it is the only
    shape that holds for any row length, including rows this project has never written.
    The chunks are joined once at the end: prepending each 1 MiB chunk onto the buffer
    copies the whole buffer every step, which measured 1.7 s for a 54 MB read against
    0.27 s spent parsing it -- most of the cost of the read was the read.

    Three bounds keep it finite, and none can over-report:

    * ``hours`` -- the window itself.  It is checked as the read grows, so the read stops
      at the window instead of at a row count that only approximates it;
    * ``limit`` rows -- a hard count, the backstop for a burst of very short rows;
    * ``EPISODE_TAIL_BYTES`` -- a hard byte budget.  When this one binds, the read returns
      *fewer* rows than asked for, which shrinks the window and can only make the gate
      quieter.  A cap must never be able to invent a deferral, and this one cannot.

    A row with no readable timestamp is kept rather than dropped: this function cannot place
    it in time, and silently discarding evidence it cannot read is how the count would drift
    away from the ledger without anyone noticing.  Live episodes always carry
    ``recorded_at``, so this is a guard, not a case.

    **One assumption, named once.**  Reading from the end and stopping when a bound is
    reached returns "the newest rows in *file* order".  That is the same set as "the newest
    rows in time" only while ``recorded_at`` is non-decreasing in file order -- an
    append-only ledger written by one loop.  Measured over the whole live ledger
    (2026-10-08): **0 inversions in 10,179 stamped rows**.  It is not an extra assumption
    this read introduces; the row cap and the byte cap already rest on it, because both also
    drop rows from the old end.  Where it can bite matters, though -- a dropped row that
    showed *progress* would hold a streak open -- so the equivalence is pinned by a test that
    reads the same fixture with the early stop and with it disabled, and compares.

    Unreadable file -> empty, unchanged: a gate that cannot read its evidence defers
    nothing, which is yesterday's behaviour and never a refusal to play.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= 0:
        return []

    clock = now or datetime.now(timezone.utc)
    cutoff = (
        clock - timedelta(hours=float(hours)) if hours and hours > 0 else None
    )
    budget = min(size, EPISODE_TAIL_BYTES)
    chunks: list[bytes] = []
    newlines = 0
    read = 0
    offset = size
    try:
        with path.open("rb") as handle:
            while offset > 0:
                step = min(EPISODE_TAIL_CHUNK, offset, budget - read)
                if step <= 0:
                    break
                offset -= step
                handle.seek(offset)
                chunk = handle.read(step)
                chunks.append(chunk)
                read += step
                newlines += chunk.count(b"\n")
                if newlines > limit:
                    break
                if cutoff is not None:
                    # The chunks were read newest-first, so the oldest bytes read are in
                    # the *last* chunk.  Checking that one chunk rather than the joined
                    # buffer keeps this check O(1) per step instead of O(read so far).
                    # Stopping here is exact only while ``recorded_at`` rises with file
                    # order -- the same assumption the caps below rest on; the docstring
                    # carries the measurement and the test that pins it.
                    oldest = _first_line_stamp(chunks[-1], offset)
                    if oldest is not None and oldest < cutoff:
                        break
    except OSError:
        return []

    blob = b"".join(reversed(chunks))
    lines = blob.decode("utf-8", errors="replace").splitlines()
    if offset and lines:
        # The first line is the tail of a record that starts before the read, so it is
        # not a JSON object and parsing it would fail rather than mislead -- drop it
        # explicitly so the count below is rows really read.
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    rows = rows[-limit:]
    if cutoff is None:
        return rows
    return [
        row for row in rows
        if (stamp := _moment(row.get("recorded_at"))) is None or stamp >= cutoff
    ]


def capability_states(
    snapshot,
    *,
    now: datetime,
    policy,
) -> dict[str, tuple[str, str, datetime | None]]:
    """Capability -> (state, reason, until), folded from the escalation ledger.

    The ledger is the only place escalation state lives, so this reads it instead of
    keeping a second copy.  ``LIVE_VERIFIED`` is checked first on purpose: it is the
    one thing that releases a capability, and it has to win over a stale ``COOLDOWN``
    or a spent repair budget -- otherwise a capability the development agent actually
    fixed could never rejoin the pool.
    """
    out: dict[str, tuple[str, str, datetime | None]] = {}
    for record in snapshot.records.values():
        capability = record.capability or record.skill
        if not capability:
            continue
        if record.outcome == LIVE_VERIFIED:
            out[capability] = (LIVE_VERIFIED, "live-verified production evidence after the job", None)
            continue
        if record.state in ("SUBMITTED", "WORKING"):
            out[capability] = (
                DEVELOPMENT_PENDING,
                f"a development job owns it (job={record.job_id or 'not submitted yet'})",
                None,
            )
            continue
        if record.state == "LIVE_VERIFY_PENDING":
            # The one case a deferring gate would deadlock, and the operator names it in
            # section 4: gameplay may not re-enter the failed path, and validation has no
            # *other* executor in this project, so if both refused, the proof that closes
            # the loop could never be produced.  The operator's own words are "允许 A 进行
            # 受控真机验证"; the only executor that exists is V2's own loop, so allowing the
            # goal *is* the controlled verification.  It is deliberately not deferred and
            # deliberately not active: no agent is working, so the agent slot stays free.
            out[capability] = (
                RUNNABLE,
                f"new version waiting for live verification (job={record.job_id or 'unknown'})",
                record.settled_at,
            )
            continue
        if record.state == "COOLDOWN":
            if record.cooldown_until and record.cooldown_until > now:
                out[capability] = (
                    COOLDOWN,
                    f"cooling down after {record.repairs_used} repair shot(s), "
                    f"outcome {record.outcome or 'unknown'}",
                    record.cooldown_until,
                )
                continue
            if record.repairs_used >= policy.repair_budget:
                # The cooldown ran out but the budget that paid for it did not.
                # This is the operator's ``BUDGET_EXHAUSTED`` case: the queue will
                # refuse another job, so re-entering the game path every cycle is
                # pure repetition -- it is probed rarely instead.
                out[capability] = (
                    BLOCKED,
                    f"repair budget exhausted ({record.repairs_used}/"
                    f"{policy.repair_budget}) after {record.outcome or 'no outcome'}",
                    record.cooldown_until,
                )
                continue
            out[capability] = (RUNNABLE, "cooldown expired with repair budget left", None)
            continue
        if record.state == "BLOCKED":
            out[capability] = (BLOCKED, "escalation is blocked", record.settled_at)
            continue
        if record.state in ("DONE", "FAILED"):
            # Settled without live verification.  The job is not proof of anything
            # (operator section 9), so the capability is schedulable -- but a path that
            # is merely not learned is handled by the no-progress rule, which uses the
            # device's own answer instead of a job's summary.
            out[capability] = (
                RUNNABLE,
                f"job settled as {record.outcome or 'no outcome'} without live verification",
                record.settled_at,
            )
            continue
    return out


def runs(episodes: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Group the tail into runs, in order.

    ``episode_id`` is the capture directory of one worker launch, so consecutive
    rows sharing it are one run.  Grouping matters because "no goal progress" is a
    statement about an *attempt*: a six-step route that starts a training batch
    produces five steps that move no distance and one that finishes the job, and
    judging those five individually would defer a route that is working exactly as
    designed.
    """
    out: list[list[Mapping[str, Any]]] = []
    seen: dict[str, int] = {}
    for row in episodes:
        key = str(row.get("episode_id") or "")
        if not key:
            out.append([row])
            continue
        if key not in seen:
            seen[key] = len(out)
            out.append([])
        out[seen[key]].append(row)
    return out


def attempted_skills(rows: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    """Goal -> the **skills** production used for it, with the ledger's non-skill values removed.

    The ledger's ``skill`` field carries three vocabularies (see ``skills.NON_SKILL_LEDGER_VALUES``),
    and this function used to collect all of them:

        attempted.setdefault(goal_id, set()).add(skill)          # no filter

    That set feeds ``reached``, then ``touched``, and then this comparison, which moves a Goal's
    restart boundary -- i.e. **resets its no-progress streak** and hands it a fresh repair budget:

        if record.capability in touched or record.skill in touched:
            boundaries[goal_id] = max(boundaries.get(goal_id, _EPOCH), record.settled_at)

    ``capability_for_skill`` returns an unknown name unchanged, so a non-skill became a *capability
    name*, and the escalation ledger really does carry such records: measured 2026-10-10 over 17,413
    rows, ``skill`` holds ``SAFE_STOP`` 90 times, ``capability`` holds it 11 times.  A decision to
    stop was therefore able to reset a failure streak.

    The filter is by declaration, not by inference: the four values are the ones named in
    ``skills.NON_SKILL_LEDGER_VALUES``, each with what it really is.  A value that is neither
    registered nor declared is still collected -- dropping unknown names silently would hide the next
    vocabulary rather than expose it, and the vocabulary guard is what reports those.
    """
    from .skills import NON_SKILL_LEDGER_VALUES

    out: dict[str, set[str]] = {}
    for row in rows:
        goal_id = str(row.get("goal_id") or "")
        skill = str(row.get("skill") or "")
        if goal_id and skill and skill not in NON_SKILL_LEDGER_VALUES:
            out.setdefault(goal_id, set()).add(skill)
    return out


def _streak_and_last(
    grouped: Sequence[Sequence[Mapping[str, Any]]],
    goal_id: str,
    *,
    since: datetime | None,
) -> tuple[int, datetime | None, str, tuple[int, int, int] | None]:
    """Consecutive runs that attempted ``goal_id`` and advanced no part of it.

    Walks backwards over runs and *skips* the ones that never attempted this goal.
    Skipping is the difference between a deferral that holds and a soft loop:
    measured 2026-09-18, a deferred beast route produced a run of navigation steps
    with no beast episode in it, and counting that as "the streak is over" would have
    sent the next run straight back to the same wall.

    Stops at a run that shows real progress, and at a run where the goal was not
    observable at all: ``goal_progress is None`` on both frames means the goal was
    not measured (a queue goal does not exist while its page is off screen), and
    calling unmeasured work stalled would defer goals for being unwatched.

    ``since`` is the restart boundary: the moment a development job touching this
    goal's capabilities settled.  The code changed at that moment, so a streak that
    described the old code says nothing about the new one.

    The fourth field says *what those episodes actually did*, as counts of
    ``(no action, rejected by its verifier, passed its verifier)`` over the counted
    runs.  A goal can fail to advance for more than one reason and the deferral's
    reason has to name the right one: ``verifier_ok`` is ``True`` only when an action
    was issued and judged, ``None`` when nothing was issued at all (measured
    2026-09-20: 30 and then 29 consecutive episodes of one goal that never resolved
    its tap target).
    """
    streak = 0
    last: datetime | None = None
    last_skill = ""
    no_action = 0
    rejected = 0
    verified = 0
    for group in reversed(grouped):
        mine = [row for row in group if str(row.get("goal_id") or "") == goal_id]
        if not mine:
            continue
        stamps = [stamp for stamp in (_moment(row.get("recorded_at")) for row in mine) if stamp]
        newest = max(stamps) if stamps else None
        if last is None:
            last = newest
            last_skill = str(mine[-1].get("skill") or "")
        if since is not None and (newest is None or newest <= since):
            break
        measured = [row.get("goal_progress") for row in mine]
        if any(value is True for value in measured):
            break
        if all(value is None for value in measured):
            break
        streak += 1
        verdicts = [row.get("verifier_ok") for row in mine]
        if any(value is True for value in verdicts):
            verified += 1
        elif any(value is not None for value in verdicts):
            rejected += 1
        else:
            no_action += 1
    return streak, last, last_skill, (no_action, rejected, verified)


def _streak_record(value: Sequence[Any]) -> tuple[int, datetime | None, str, tuple[int, int, int] | None]:
    """Read one entry of ``CapabilityGate.streaks``.

    A hand-built gate may still carry the older three-field record, which says
    nothing about what the episodes did; that is answered with ``None`` rather than
    guessed at, because a reason the episodes contradict is worse than one that
    says less.
    """
    streak = int(value[0]) if len(value) > 0 else 0
    last = value[1] if len(value) > 1 else None
    skill = str(value[2] or "") if len(value) > 2 else ""
    evidence = tuple(value[3]) if len(value) > 3 and value[3] is not None else None
    return streak, last, skill, evidence


def _no_progress_reason(streak: int, evidence: tuple[int, int, int] | None) -> str:
    """Why these episodes are a streak, in words the episodes themselves support.

    This sentence used to claim unconditionally that the episodes "passed their
    verifier", which is true only of the case it was written for (2026-09-18: 58
    beast scans that landed and moved nothing).  A goal also fails to advance when
    the executor never issued an action, and then no verifier judged anything, so
    the claim was false in the ledger.  The cause is therefore read off the
    episodes, and an unmeasured cause is left unnamed.
    """
    if evidence is None:
        return f"{streak} consecutive production episodes advanced no part of this goal"
    no_action, rejected, verified = evidence
    if verified == streak:
        return (
            f"{streak} consecutive production episodes passed their verifier and "
            f"advanced no part of this goal"
        )
    if no_action == streak:
        return (
            f"{streak} consecutive production episodes issued no action at all -- "
            f"the tap target never resolved, so no verifier judged them -- and "
            f"advanced no part of this goal"
        )
    if rejected == streak:
        return (
            f"{streak} consecutive production episodes issued an action that its "
            f"verifier rejected and advanced no part of this goal"
        )
    return (
        f"{streak} consecutive production episodes advanced no part of this goal "
        f"({verified} passed their verifier, {rejected} were rejected by it, "
        f"{no_action} issued no action)"
    )


class CapabilityGate:
    """The scheduler's input: which goals it may select, and which it may not."""

    def __init__(
        self,
        *,
        compositions: Mapping[str, GoalComposition] | None = None,
        capabilities: Mapping[str, tuple[str, str, datetime | None]] | None = None,
        streaks: Mapping[str, Sequence[Any]] | None = None,
        attempted: Mapping[str, frozenset[str]] | None = None,
        reached: Mapping[str, frozenset[str]] | None = None,
        reload_pending: bool = False,
        no_progress_threshold: int = NO_PROGRESS_STREAK,
        no_progress_probe_minutes: int = NO_PROGRESS_PROBE_MINUTES,
        blocked_probe_minutes: int = BLOCKED_PROBE_MINUTES,
    ) -> None:
        self.compositions = dict(compositions or {})
        self.capabilities = dict(capabilities or {})
        self.streaks = dict(streaks or {})
        self.attempted = dict(attempted or {})
        self.reached = dict(reached or {})
        self.reload_pending = bool(reload_pending)
        self.no_progress_threshold = int(no_progress_threshold)
        self.no_progress_probe_minutes = int(no_progress_probe_minutes)
        self.blocked_probe_minutes = int(blocked_probe_minutes)

    # -- construction -----------------------------------------------------

    @classmethod
    def empty(cls) -> "CapabilityGate":
        """A gate that defers nothing: for tests, and for callers with no evidence."""
        return cls()

    @classmethod
    def load(
        cls,
        root: Path | str | None = None,
        *,
        now: datetime | None = None,
        policy=None,
        snapshot=None,
        episodes: Sequence[Mapping[str, Any]] | None = None,
        no_progress_threshold: int = NO_PROGRESS_STREAK,
        no_progress_probe_minutes: int = NO_PROGRESS_PROBE_MINUTES,
        blocked_probe_minutes: int = BLOCKED_PROBE_MINUTES,
        active_revision: str = "",
    ) -> "CapabilityGate":
        """Read the two existing artifacts and project them into a gate.

        Never raises: a gate that cannot read its evidence defers nothing, which is
        the safe direction -- the worst case is yesterday's behaviour, not a system
        that refuses to play because a JSON file was mid-write.
        """
        from . import runtime_reload
        from .escalation_queue import EscalationLedger, EscalationPolicy, capability_for_skill

        base = Path(root) if root else Path(__file__).resolve().parents[1]
        moment = now or datetime.now(timezone.utc)
        policy = policy or EscalationPolicy()

        if snapshot is None:
            try:
                snapshot = EscalationLedger(base / "learning/workbuddy_escalations.jsonl").snapshot()
            except Exception:  # noqa: BLE001 - evidence problems must not stop play
                snapshot = None

        states = capability_states(snapshot, now=moment, policy=policy) if snapshot else {}
        compositions = goal_compositions(base)
        rows: Sequence[Mapping[str, Any]] = (
            list(episodes) if episodes is not None
            # The window's clock is the gate's own ``moment``, not a second reading of the
            # wall clock taken a few lines later.  Two clocks in one projection is how a
            # boundary and the rows it bounds disagree about which side of it they are on.
            else _episode_tail(base / "learning/episodes.jsonl", now=moment)
        )

        # A no-progress cooldown describes one version of the code. If the live
        # process is now running a different frozen version, give each affected
        # goal one probe on that version before carrying the old streak forward.
        # The boundary is per goal, based on its newest actual production episode;
        # unrelated goals keep their own history and one failed probe on the new
        # version immediately starts a fresh streak.
        revision_tails: dict[str, tuple[datetime, str, datetime | None]] = {}
        ordered_rows = sorted(
            (row for row in rows if _moment(row.get("recorded_at")) is not None),
            key=lambda row: _moment(row.get("recorded_at")) or _EPOCH,
        )
        for row in ordered_rows:
            goal_id = str(row.get("goal_id") or "")
            stamp = _moment(row.get("recorded_at"))
            revision = str(row.get("repo_revision") or "")
            if not goal_id or stamp is None or not revision:
                continue
            previous = revision_tails.get(goal_id)
            active_start = (
                (previous[2] if previous and previous[1] == active_revision else stamp)
                if active_revision and revision == active_revision
                else None
            )
            revision_tails[goal_id] = (stamp, revision, active_start)

        # Goal -> the skills production really used for it.  This is what makes
        # "the same failing path" measurable instead of assumed.
        grouped = runs(rows)
        attempted = attempted_skills(rows)

        cache: dict[str, str] = {}

        def resolve(skill: str) -> str:
            if skill not in cache:
                cache[skill] = capability_for_skill(skill, root=base)
            return cache[skill]

        reached = {goal: frozenset(resolve(skill) for skill in skills) for goal, skills in attempted.items()}

        # Restart boundary per goal: the newest moment a development job touched any
        # capability or skill that goal is driven by.
        boundaries: dict[str, datetime] = {}
        records = list(snapshot.records.values()) if snapshot else []
        for goal_id, skills in attempted.items():
            touched = reached[goal_id] | frozenset(skills)
            for record in records:
                if record.settled_at is None:
                    continue
                if record.capability in touched or record.skill in touched:
                    boundaries[goal_id] = max(boundaries.get(goal_id, _EPOCH), record.settled_at)

            newest = revision_tails.get(goal_id)
            if active_revision and newest is not None:
                if newest[1] != active_revision:
                    # No production episode has yet tried this loaded version.
                    boundaries[goal_id] = max(boundaries.get(goal_id, _EPOCH), moment)
                elif newest[2] is not None:
                    # Keep only the consecutive tail that ran this exact version.
                    # One microsecond before its first episode makes that episode
                    # count while ending the old-version streak immediately before it.
                    version_start = newest[2] - timedelta(microseconds=1)
                    boundaries[goal_id] = max(boundaries.get(goal_id, _EPOCH), version_start)

        streaks = {
            goal_id: _streak_and_last(grouped, goal_id, since=boundaries.get(goal_id))
            for goal_id in attempted
        }

        try:
            reload_pending = runtime_reload.ReloadSignal(runtime_reload.default_path(base)).pending() is not None
        except Exception:  # noqa: BLE001
            reload_pending = False

        return cls(
            compositions=compositions,
            capabilities=states,
            streaks=streaks,
            attempted={goal: frozenset(value) for goal, value in attempted.items()},
            reached=reached,
            reload_pending=reload_pending,
            no_progress_threshold=no_progress_threshold,
            no_progress_probe_minutes=no_progress_probe_minutes,
            blocked_probe_minutes=blocked_probe_minutes,
        )

    # -- the decision -----------------------------------------------------

    def _capability_deferral(self, goal_id: str) -> Deferral | None:
        composition = self.compositions.get(goal_id)
        if composition is None or not composition.capabilities:
            return None

        def entry(capability: str) -> Deferral | None:
            found = self.capabilities.get(capability)
            if found is None:
                return None
            state, reason, until = found
            if state not in DEFERRING_STATES:
                return None
            return Deferral(
                goal_id=goal_id,
                state=state,
                reason=reason,
                capability=capability,
                source=SOURCE_QUEUE,
                until=until,
            )

        # 1. The path this goal is actually being driven along, matched through the
        #    project's own skill -> capability table.
        #
        #    Except for ANY_OF when the reached path is BLOCKED or on COOLDOWN: a path that
        #    cannot run is not a goal that cannot run.  The operator's map declares three ways to
        #    satisfy AVOID_STAMINA_WASTE (beast / intel / rally) and only the beast one carries a
        #    block; returning here hid the two runnable paths and kept the goal off the board
        #    entirely -- measured 2026-09-19 with stamina at 457 and the requirement being "keep
        #    it under 30".  DEVELOPMENT_PENDING is deliberately not exempted: a job is inside that
        #    code right now, and the existing rule that such a path waits (rather than measuring
        #    the tree it is about to replace) is worth more than the parallelism it would buy.
        reached = self.reached.get(goal_id, frozenset())
        exempt = composition.composition == "ANY_OF"
        for capability in composition.capabilities:
            if capability not in reached:
                continue
            found = entry(capability)
            if found is not None:
                if exempt and found.state in PATH_CANNOT_RUN:
                    break
                return found

        # 2. Otherwise the whole goal: any path for SEQUENCE, all paths for ANY_OF.
        blocked = [item for item in (entry(capability) for capability in composition.capabilities) if item]
        if not blocked:
            return None
        if composition.composition == "ANY_OF" and len(blocked) < len(composition.capabilities):
            return None
        return max(blocked, key=lambda item: _severity(item.state))

    def _probe_anchor(
        self,
        goal_id: str,
        *,
        fallback_anchor: datetime | None = None,
        capability_scope: frozenset[str] = frozenset(),
    ) -> datetime | None:
        """The moment this path's probe timer starts from, or ``None`` if it has none.

        A no-progress deferral with no recorded attempt does not lapse: nothing has
        been measured. For a capability blocked by an exhausted repair budget, use the
        ledger's cooldown or settlement deadline until the current code version has its
        first production attempt. Otherwise a version change can erase the current
        episode tail and leave an expired blocker permanent.

        This is one function rather than two callers each deriving it, because
        ``blocks()`` has to publish the same anchor it judges with: two derivations is
        exactly how the board and the gate start disagreeing (measured 2026-10-05).
        """
        _streak, last, last_skill, _evidence = _streak_record(self.streaks.get(goal_id, ()))
        anchor = last or fallback_anchor
        if fallback_anchor is not None and capability_scope and last is not None and last_skill:
            # Goal episodes also contain navigation, safe stops, and actions taken before
            # reaching the blocked capability. Those steps do not restart that capability's
            # probe timer. Keep the goal-level timestamp only when the last step actually
            # touched one of this goal's mapped capabilities; otherwise use the escalation's
            # own cooldown/settlement deadline.
            last_capability = self._capability_of_skill(last_skill)
            if last_capability not in capability_scope:
                anchor = fallback_anchor
        return anchor

    def _probe_lapsed(
        self,
        goal_id: str,
        now: datetime,
        window_minutes: int,
        *,
        fallback_anchor: datetime | None = None,
        capability_scope: frozenset[str] = frozenset(),
    ) -> bool:
        """Has this path's probe window expired?"""
        anchor = self._probe_anchor(
            goal_id,
            fallback_anchor=fallback_anchor,
            capability_scope=capability_scope,
        )
        if anchor is None:
            return False
        return (now - anchor).total_seconds() / 60.0 >= window_minutes

    def _no_progress_deferral(self, goal: GoalState, now: datetime) -> Deferral | None:
        goal_id = goal.goal_id
        streak, last, last_skill, evidence = _streak_record(self.streaks.get(goal_id, ()))
        if streak < self.no_progress_threshold:
            return None
        capability = self._route_capability(goal_id, goal.available_skills)
        return Deferral(
            goal_id=goal_id,
            state=DEFERRED,
            capability=capability,
            reason=_no_progress_reason(streak, evidence),
            source=SOURCE_NO_PROGRESS,
            # The signature is positional: ``<capability>|<failure_type>|<skill>``,
            # with the capability field allowed to be empty.  Filtering the empty
            # fields out made a two-field signature of it, and the escalation queue
            # then read the *failure type* as the capability -- measured 2026-09-18:
            # ``NO_GOAL_PROGRESS`` was filed as a capability and took a development
            # job that no goal can ever route back to (see ``_route_capability``).
            failure_signature=f"{capability}|NO_GOAL_PROGRESS|{last_skill}",
            probe_minutes=self.no_progress_probe_minutes,
            streak=streak,
            last_attempt=last,
            last_skill=last_skill,
        )

    def _route_capability(self, goal_id: str, declared_skills: Iterable[str] = ()) -> str:
        """The capability name a deferral should be handed off under.

        For a ``SEQUENCE`` goal, the first composition entry the route has *not*
        reached -- the frontier, which is where the route actually stops.  For an
        ``ANY_OF`` goal, the first reached alternative, because any of them is a
        path the goal is genuinely driven along.  Then the capability the goal's
        *declared* skills resolve to: a route can be
        attempted entirely through steps the capability table does not name (measured
        2026-09-18: ``AVOID_STAMINA_WASTE``'s stalled route ran ``SCAN_MAP_FOR_BEAST``,
        a navigation step that resolves to itself), and the goal still says which
        capabilities would satisfy it.  ``BEAST_HUNT`` is one of those and the project
        already maps it to ``SPEND_STAMINA_ON_BEAST``, which is the honest name for
        that wall and the one the earlier escalation in the ledger already used.
        Failing that, the capability of this goal that is already in the worst state:
        that is the name the development pipeline already knows this project by, and
        naming a *skill* as if it were a capability would file the request under a
        label nobody has ever worked on.
        """
        composition = self.compositions.get(goal_id)
        if composition is None:
            return ""
        reached = self.reached.get(goal_id, frozenset())
        if composition.composition == "SEQUENCE":
            # The wall of a required-everything route is its *frontier*: the first
            # capability the route has never reached.  Naming the first *reached* one
            # instead measured 2026-09-18 as ``NAVIGATE_TO_MAP`` for a
            # ``KEEP_MARCHES_PRODUCTIVE`` route that had reached it and stopped at
            # ``SUBMIT_RESOURCE_SEARCH`` -- index 0 is reached on every cycle, so
            # every no-progress wall in that goal was filed against a capability that
            # is already ``LIVE_VERIFIED``, and the development agent was handed a
            # navigation wall with no live symptom to fix.
            for capability in composition.capabilities:
                if capability not in reached:
                    return capability
        else:
            # ANY_OF: "the path this goal is actually driven along" is any reached
            # alternative; there is no ordered frontier to be stuck behind.
            for capability in composition.capabilities:
                if capability in reached:
                    return capability
        for skill in declared_skills:
            routed = self._capability_of_skill(str(skill))
            if routed in composition.capabilities:
                return routed
        blocked = [
            (capability, self.capabilities[capability][0])
            for capability in composition.capabilities
            if capability in self.capabilities and self.capabilities[capability][0] in DEFERRING_STATES
        ]
        if blocked:
            return max(blocked, key=lambda item: _severity(item[1]))[0]
        if len(composition.capabilities) == 1:
            return composition.capabilities[0]
        return ""

    @staticmethod
    def _capability_of_skill(skill: str) -> str:
        """Skill -> capability, through the project's own table (never a second one)."""
        if not skill:
            return ""
        cached = _SKILL_CAPABILITY_CACHE.get(skill)
        if cached is not None:
            return cached
        from .escalation_queue import capability_for_skill

        resolved = capability_for_skill(skill)
        _SKILL_CAPABILITY_CACHE[skill] = resolved
        return resolved

    def blocks(
        self, goal: GoalState, *, now: datetime | None = None,
        validation_goal_id: str = "",
    ) -> Deferral | None:
        """Why this goal must step aside, or ``None`` when it may be selected.

        A caller owning a development validation lease may explicitly probe its
        exact Goal despite historical no-progress evidence. This only lifts that
        local retry cooldown; capability blockers, pending reloads and the normal
        runtime authorization checks still apply. Production passes no Goal ID.

        The returned row's ``until`` is the deadline **this** decision applies -- the
        probe window measured from the anchor ``_probe_anchor`` chose. The escalation
        ledger's own ``cooldown_until`` is only one of the two possible anchors and can
        be days stale, so publishing it verbatim made the board describe a working
        probe as a permanent stall (measured 2026-10-05).
        """
        moment = now or datetime.now(timezone.utc)
        found = self._capability_deferral(goal.goal_id)
        if found is None:
            found = self._no_progress_deferral(goal, moment)
            if found is None:
                return None
            if (validation_goal_id and goal.goal_id == validation_goal_id
                    and not self.reload_pending):
                return None
            window = self.no_progress_probe_minutes
        else:
            if found.state == DEVELOPMENT_PENDING:
                # A job is inside the code right now; a probe would measure the tree
                # it is about to replace.
                return found
            if found.state == COOLDOWN and not self.reload_pending:
                return found
            window = self.blocked_probe_minutes
        scope = (
            frozenset(self.compositions.get(goal.goal_id).capabilities)
            if found.source == SOURCE_QUEUE
            and self.compositions.get(goal.goal_id) is not None
            else frozenset()
        )
        anchor = self._probe_anchor(
            goal.goal_id, fallback_anchor=found.until, capability_scope=scope,
        )
        if not self.reload_pending and self._probe_lapsed(
            goal.goal_id,
            moment,
            window,
            fallback_anchor=found.until,
            capability_scope=scope,
        ):
            return None
        horizon = anchor + timedelta(minutes=window) if anchor is not None else None
        reason = (
            found.reason + "; a runtime reload is pending"
            if self.reload_pending
            else found.reason
        )
        return replace(found, reason=reason, until=horizon, probe_minutes=window)

    def allows(self, goal: GoalState, *, now: datetime | None = None) -> bool:
        return self.blocks(goal, now=now) is None

    def blocked(self, goals: Iterable[GoalState]) -> tuple[Deferral, ...]:
        """Every deferral among ``goals``, in the order they were offered."""
        return tuple(found for found in (self.blocks(goal) for goal in goals) if found is not None)


def _severity(state: str) -> int:
    """Which state to report when several paths are unavailable at once."""
    return {
        BLOCKED: 4,
        DEVELOPMENT_PENDING: 3,
        COOLDOWN: 2,
        DEFERRED: 1,
    }.get(state, 0)
