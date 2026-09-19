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
from dataclasses import dataclass
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

# Episodes read back when a run asks the gate.  Only the tail matters: every rule is
# "the most recent attempts of this goal".
EPISODE_TAIL = 400
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Skill -> capability memo, so a per-step deferral check does not re-read the table.
_SKILL_CAPABILITY_CACHE: dict[str, str] = {}


@dataclass(frozen=True)
class Deferral:
    """One goal path the scheduler must not select, with the evidence for it."""

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


def _episode_tail(path: Path, limit: int = EPISODE_TAIL) -> list[dict[str, Any]]:
    """The last ``limit`` well-formed episode rows.  Unreadable file -> empty."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            # 4 KiB per row is a generous upper bound for an episode, so this reads
            # about the right amount without parsing all 1,855 rows on every run.
            handle.seek(max(0, size - limit * 4096))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows[-limit:]


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


def _streak_and_last(
    grouped: Sequence[Sequence[Mapping[str, Any]]],
    goal_id: str,
    *,
    since: datetime | None,
) -> tuple[int, datetime | None, str]:
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
    """
    streak = 0
    last: datetime | None = None
    last_skill = ""
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
    return streak, last, last_skill


class CapabilityGate:
    """The scheduler's input: which goals it may select, and which it may not."""

    def __init__(
        self,
        *,
        compositions: Mapping[str, GoalComposition] | None = None,
        capabilities: Mapping[str, tuple[str, str, datetime | None]] | None = None,
        streaks: Mapping[str, tuple[int, datetime | None, str]] | None = None,
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
            list(episodes) if episodes is not None else _episode_tail(base / "learning/episodes.jsonl")
        )

        # Goal -> the skills production really used for it.  This is what makes
        # "the same failing path" measurable instead of assumed.
        grouped = runs(rows)
        attempted: dict[str, set[str]] = {}
        for row in rows:
            goal_id = str(row.get("goal_id") or "")
            skill = str(row.get("skill") or "")
            if goal_id and skill:
                attempted.setdefault(goal_id, set()).add(skill)

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

    def _probe_lapsed(self, goal_id: str, now: datetime, window_minutes: int) -> bool:
        """Has this path's probe window expired?

        A goal with no recorded attempt does *not* lapse: the capability is blocked at
        the development level and there is nothing to probe for.  Only a goal that the
        device has actually tried, longer ago than the window, is offered one more run.
        """
        _streak, last, _skill = self.streaks.get(goal_id, (0, None, ""))
        if last is None:
            return False
        return (now - last).total_seconds() / 60.0 >= window_minutes

    def _no_progress_deferral(self, goal: GoalState, now: datetime) -> Deferral | None:
        goal_id = goal.goal_id
        streak, last, last_skill = self.streaks.get(goal_id, (0, None, ""))
        if streak < self.no_progress_threshold:
            return None
        capability = self._route_capability(goal_id, goal.available_skills)
        return Deferral(
            goal_id=goal_id,
            state=DEFERRED,
            capability=capability,
            reason=(
                f"{streak} consecutive production episodes passed their verifier and "
                f"advanced no part of this goal"
            ),
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

    def blocks(self, goal: GoalState, *, now: datetime | None = None) -> Deferral | None:
        """Why this goal must step aside, or ``None`` when it may be selected."""
        moment = now or datetime.now(timezone.utc)
        found = self._capability_deferral(goal.goal_id)
        if found is None:
            found = self._no_progress_deferral(goal, moment)
            if found is None:
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
        if not self.reload_pending and self._probe_lapsed(goal.goal_id, moment, window):
            return None
        if self.reload_pending:
            found = Deferral(
                goal_id=found.goal_id,
                state=found.state,
                reason=found.reason + "; a runtime reload is pending",
                capability=found.capability,
                source=found.source,
                failure_signature=found.failure_signature,
                until=found.until,
                probe_minutes=window,
                streak=found.streak,
                last_attempt=found.last_attempt,
                last_skill=found.last_skill,
            )
        return found

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
