"""Escalation queue: AUTO finds the wall, the queue decides, WorkBuddy does the work.

The shape the operator asked for, and why it is shaped this way
----------------------------------------------------------------
::

    AUTO runtime          -> discovers a wall, records it, keeps playing
    escalation queue      -> dedup, concurrency, budget, cooldown, state
    WorkBuddy bridge      -> dispatches, asynchronously, never waited on
    WorkBuddy agent       -> Reuse Check .. Live Verify .. Commit/Push

The one rule everything else follows from: **AUTO never waits for WorkBuddy.**
A cycle that stopped to await a development agent would trade a game runtime for
a build server, so the AUTO hook does exactly two things -- reconcile jobs that
already finished, and hand off *at most* a decision to submit -- then returns.
The agent works in its own process while the game keeps being played.

No second scheduler, manager, registry or orchestrator.  This module is a queue
adapter over one append-only ledger (:data:`DEFAULT_LEDGER`, reused from the
bridge's first iteration), and every state it reports is a **fold over that
event stream** rather than a second copy of the truth.  That is deliberate: this
project has been bitten by plausible-looking stores nobody reads, and a second
registry would make "is this capability already being worked on" answerable from
two places that can disagree.

What it is careful about
------------------------
* **Dedup** is by ``capability | failure_type | skill``.  One active job per key,
  ever.  The operator's rule, and the reason a recurring failure does not spawn
  one agent per cycle.
* **Concurrency cap** ``max_concurrent_jobs = 1``: two agents must not edit the
  same repository at once.
* **Budget and cooldown** stop the ``Runtime <-> WorkBuddy`` repair loop.  The
  budget counts *post-fix* attempts, so the first honest shot is always free and
  a signature that keeps failing eventually becomes ``BLOCKED + COOLDOWN`` and
  AUTO moves on to another capability.
* **Ordinary weather never escalates.**  ``mail_all_clear``, a full queue, an
  unrefreshed event, a rally that is full -- those are correct observations, not
  defects, and they are refused by name.
* **A successful job is not a successful capability.**  Reconciliation measures
  the repository and the episode stream locally and reports
  ``CODE_CHANGED`` / ``TEST_PASS`` / ``LIVE_VERIFIED`` / ``BLOCKED`` /
  ``NO_IMPROVEMENT``.  ``LIVE_VERIFIED`` requires a production episode with
  ``recorded_at``, ``verifier_ok`` and evidence that appeared *after* the job was
  submitted -- an agent's own summary is never enough.
"""

from __future__ import annotations

from .winproc import hidden_kwargs
from .workbuddy_bridge import JobLost
from .version_identity import canonical_revision

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ----------------------------------------------------------------- conditions

CAPABILITY_MISSING = "CAPABILITY_MISSING"
UNKNOWN_UI = "UNKNOWN_UI"
UNKNOWN_GAME_MECHANIC = "UNKNOWN_GAME_MECHANIC"
REPEATED_LIVE_FAILURE = "REPEATED_LIVE_FAILURE"
STUCK_15_MIN = "STUCK_15_MIN"

AUTO_ESCALATION_CONDITIONS: tuple[str, ...] = (
    CAPABILITY_MISSING,
    UNKNOWN_UI,
    UNKNOWN_GAME_MECHANIC,
    REPEATED_LIVE_FAILURE,
    STUCK_15_MIN,
)

# Stops that mean "nothing to do right now".  These are the normal weather of a
# live loop and must never summon a development agent -- the operator named them
# explicitly.  Matching is by exact ``stop_reason``; anything not listed here is
# only escalated if an actual failed episode backs it.
# The stop reason the continuous pump hands ``_drain``.  Deliberately a name that
# is in neither ``NON_ESCALATABLE_STOP_REASONS`` nor ``STOP_REASON_WALLS``: a pump
# has no run behind it, so it may only settle what is in flight and consume what
# is already owed.  If it ever matched a wall entry it would manufacture a
# candidate out of thin air on every tick.
PUMP_STOP_REASON = "PENDING_CONSUMER_PUMP"

# How stale the panel's heartbeat may be before this process stops treating it as a
# live consumer of the device.  Three pump intervals (30 s each): below that a stale
# file means the window is gone, and asking for the device would make V2 stand down
# with nobody to drive the validation.
PANEL_HEARTBEAT_MAX_AGE_SECONDS = 90.0

# Failure types whose proof is the measurement that was missing, not the step's own
# verifier.  ``NO_GOAL_PROGRESS`` is by definition "the step worked and the goal did
# not move", so a verifier-passing episode in which the goal still does not move is
# the same observation again -- not a fix for it.  Measured 2026-09-18 01:43: the
# reconciler granted LIVE_VERIFIED on six such episodes.
PROOF_IS_GOAL_PROGRESS = frozenset({"NO_GOAL_PROGRESS"})

NON_ESCALATABLE_STOP_REASONS = frozenset({
    "mail_all_clear",
    "no_idle_march",
    "reserved_march_for_stamina",
    "intel_available_no_claim",
    "intel_not_available",
    "intel_expired",
    "intel_no_untried_pins",
    "exploration_income_not_ready",
    "daily_no_claimable_rewards",
    "daily_state_unknown_or_not_actionable",
    "daily_panel_already_read_not_actionable",
    "alliance_action_not_needed",
    "research_queue_busy",
    "research_page_no_startable_node",
    "research_page_already_read_not_actionable",
    "training_queue_busy",
    "training_page_already_read_not_actionable",
    "MAX_ACTIONS_REACHED",
    "TARGET_SKILL_VERIFIED",
    # the operator's own non-escalatable list, as live stop reasons
    "NOT_REFRESHED",
    "QUEUE_BUSY",
    "RESOURCE_SHORTAGE",
    "EVENT_CLOSED",
    "RALLY_FULL",
    "WAITING_FOR_NATURAL_STATE",
    # Operator §2 A: the device is not available to gameplay because a development
    # validation owns it.  That is a condition, not a capability gap -- escalating it
    # would spend a development agent on the fact that a development agent is working.
    "device_leased_for_development",
    # Added 2026-09-17 with the architecture freeze (operator section 9): these are
    # conditions the runtime should DEFER / SKIP / RECOVER / move to the next Goal
    # on, not reasons to spend a development agent.  A busy emulator is not a
    # defect, and a cooldown is a mechanic working as designed.
    "DEVICE_TEMPORARILY_BUSY",
    "DEVICE_BUSY",
    "COOLDOWN",
    "ABILITY_ON_COOLDOWN",
    "QUEUE_FULL",
    "SKILL_ON_COOLDOWN",
})

# What the runtime should do instead of escalating.  Named so a reader can see the
# alternative rather than only the refusal, and so a future caller has somewhere
# to look when it hits one of the reasons above.
ORDINARY_WEATHER_RESPONSES: dict[str, str] = {
    "NOT_REFRESHED": "DEFER",
    "QUEUE_BUSY": "NEXT_GOAL",
    "QUEUE_FULL": "NEXT_GOAL",
    "RESOURCE_SHORTAGE": "NEXT_GOAL",
    "EVENT_CLOSED": "SKIP",
    "RALLY_FULL": "SKIP",
    "WAITING_FOR_NATURAL_STATE": "DEFER",
    "DEVICE_TEMPORARILY_BUSY": "RECOVER",
    "DEVICE_BUSY": "RECOVER",
    "COOLDOWN": "DEFER",
    "ABILITY_ON_COOLDOWN": "DEFER",
    "SKILL_ON_COOLDOWN": "DEFER",
}


def ordinary_weather_response(stop_reason: str) -> str | None:
    """``DEFER`` / ``SKIP`` / ``RECOVER`` / ``NEXT_GOAL`` for a non-escalatable stop."""
    return ORDINARY_WEATHER_RESPONSES.get(str(stop_reason))

# Failure types whose meaning is "the client did something we did not model" --
# the inputs or the outcome of a mechanic are unknown.  Narrower than the UI set
# below on purpose, and checked first: a wrong guess here would send an agent
# chasing the wrong problem.
GAMEPLAY_UNKNOWN_FAILURE_TYPES = frozenset({
    "DISPATCH_NOT_PROVEN",
    "INTEL_HERO_DISPATCH_NOT_PROVEN",
    "INTEL_RESCUE_START_NOT_PROVEN",
    "STAMINA_SOURCES_NOT_OPEN",
})

# Failure types whose meaning is "we could not read or locate what the client is
# showing" -- the UI is unknown to us, which is what a development agent can fix.
#
# Matched by *shape*, not by an exhaustive list.  A list was tried first and was
# already wrong the day it was written: it named the six reasons that dominated
# the live distribution (SEMANTIC_TARGET_NOT_VERIFIED 99, MARCH_PAGE_NOT_OPEN 60,
# RESOURCE_NOT_FOUND 30, POPUP_CLOSE_NOT_PROVEN 5, OPEN_MAP_NOT_PROVEN 4,
# NO_EXECUTION 5) and then missed TRAINING_PAGE_NOT_PROVEN, which was newer.  The
# project's failure types name themselves consistently, so the suffix is the
# signal -- and a genuinely new shape still falls through to "no condition", which
# is the safe answer.
UI_UNREAD_SUFFIXES = ("_NOT_VERIFIED", "_NOT_PROVEN", "_NOT_OPEN", "_NOT_FOUND")

# Kept for the reasons whose names do not follow the convention.
UI_UNREAD_EXPLICIT = frozenset({"NO_EXECUTION", "RESOURCE_NOT_FOUND"})

# Walls that arrive as a *stop reason only*: the runtime looks at the client,
# decides it cannot proceed, and issues no action -- so the episode stream carries
# no failed step and the failure-type tables above never see it.
#
# Without this map the pipeline would be blind to this project's most frequent
# blocker: ``verified_beast_target_not_visible`` has ended a run on most cycles
# since 2026-09-17 and was named as the current top failure in the handoff, yet it
# produces zero failed episodes.  Listed one at a time on purpose -- each entry
# claims "this stop is a wall, not the weather", and that claim has to be earned.
STOP_REASON_WALLS: dict[str, tuple[str, str, str]] = {
    "verified_beast_target_not_visible": (
        UNKNOWN_UI,
        "SELECT_BEAST_TARGET",
        "the run stops because the beast target card cannot be verified on the map, "
        "so no beast can be dispatched at all",
    ),
}

# --------------------------------------------------------------------- states

NEW = "NEW"
QUEUED = "QUEUED"
SUBMITTED = "SUBMITTED"
WORKING = "WORKING"
DONE = "DONE"
FAILED = "FAILED"
BLOCKED = "BLOCKED"
COOLDOWN = "COOLDOWN"
# A gateway state, not a lifecycle state: a job that was stopped is settled as FAILED
# (see the ``job_state`` branch in ``fold``).  Named here because the reconciler writes
# it into the ledger verbatim.
STOPPED = "STOPPED"

# The version the job produced has not been exercised yet, so the capability is
# waiting for its live examination rather than for a developer.  Deliberately in
# neither ACTIVE_STATES nor TERMINAL_STATES: it must not hold the single agent slot
# (no agent is working), and it must not be settled (the next tick still has to
# measure it).  Leaving it out of ACTIVE_STATES is what keeps a pending verification
# from starving the queue the way a stopped job once did.
LIVE_VERIFY_PENDING = "LIVE_VERIFY_PENDING"

# The two rungs the operator added on 2026-09-18 evening (§一/§八).  Declared here, above
# ``ALL_STATES``, because that tuple is evaluated at import time and names them; the reasoning
# for each is written out beside ``VERSION_ACTIVATION_PENDING`` below.
#
#   VERSION_ACTIVE  the new version has been *loaded and run* by a fresh process, and a real
#                   episode whose ``repo_revision`` equals ``after_version`` says so.
#   REJOINED        the capability has been exercised on the real device, released its lease,
#                   and gone back into normal play.
VERSION_ACTIVE = "VERSION_ACTIVE"
REJOINED = "REJOINED"

ALL_STATES: tuple[str, ...] = (
    NEW, QUEUED, SUBMITTED, WORKING, LIVE_VERIFY_PENDING, VERSION_ACTIVE, REJOINED,
    DONE, FAILED, BLOCKED, COOLDOWN,
)
# A key in one of these is "being worked on": no second job for it.
ACTIVE_STATES = frozenset({NEW, QUEUED, SUBMITTED, WORKING})
TERMINAL_STATES = frozenset({DONE, FAILED, BLOCKED, COOLDOWN})

# ------------------------------------------------------------------- outcomes

# The operator's full ladder of what a finished job may have achieved.  The order
# matters: each rung implies the ones before it, and only the last one means the
# capability actually works in the game.
#
# The operator's full ladder of what a finished job may have achieved.  The order
# matters: each rung implies the ones before it, and only the last one means the
# capability actually works in the game.
#
#   CODE_CHANGED                 files differ; nothing else verified
#   TEST_PASS                    and the fast gate is green
#   VERSION_ACTIVATION_PENDING   and the new version has not been exercised yet
#   REPLAY_PASS                  and a recorded frame replays correctly
#   LIVE_TRIED                   and a real device attempt was made (success unknown)
#   LIVE_VERIFIED                and a production episode proves it, with a passing verifier
#   BLOCKED / NO_IMPROVEMENT     the honest ends when none of that happened
#
# "WorkBuddy says done" appears nowhere in this list, on purpose.
CODE_CHANGED = "CODE_CHANGED"
TEST_PASS = "TEST_PASS"
# The correction the operator made on 2026-09-18: LIVE_VERIFIED cannot be granted to a
# version that has not run yet, so the rung between "the gate is green" and "a
# production episode proves it" is "the new version is actually what is running".
# Without it the ladder read CODE_CHANGED -> LIVE_VERIFIED -> Reload, which credits a
# fix that the measuring process had never loaded.
VERSION_ACTIVATION_PENDING = "VERSION_ACTIVATION_PENDING"
# ``VERSION_ACTIVE`` and ``REJOINED`` are declared above ``ALL_STATES``, which names them.
#
# VERSION_ACTIVE has to be a lifecycle state rather than a GUI inference: every rung above it
# (LIVE_VERIFY_PENDING, LIVE_TRIED, LIVE_VERIFIED, REJOINED, DONE) is gated on "the version
# under test is the version that ran", and a value the window computed for display could never
# gate anything.  It is neither active (no agent is working, and the single slot must stay
# free) nor terminal (the next pass still has to measure it), which is why it is in neither
# set -- the same reasoning as LIVE_VERIFY_PENDING.
#
# Its only lawful evidence is: job settled AND after_version known AND a real episode AND
# episode.repo_revision == after_version.  Not "files changed", not "the agent said DONE",
# not "the tests passed" -- all three are facts about the tree, and none of them is evidence
# that anything loaded it.
REPLAY_PASS = "REPLAY_PASS"
LIVE_TRIED = "LIVE_TRIED"
LIVE_VERIFIED = "LIVE_VERIFIED"
OUTCOME_BLOCKED = "BLOCKED"
NO_IMPROVEMENT = "NO_IMPROVEMENT"
# The gateway is up and reports the job does not exist (measured 2026-09-18: HTTP 404
# ``JOB_NOT_FOUND`` for a job the ledger still had as WORKING).  Kept as an *outcome* rather
# than as a tenth lifecycle state: the record folds to FAILED, which is terminal and frees
# the single concurrency slot, while this name preserves the cause -- "the work did not
# finish" and "the work did not finish because it vanished" lead to different next actions.
JOB_LOST = "JOB_LOST"

# ------------------------------------------------------------------- unfinished traces

#: States in which a capability's development trace is still open, even though **no agent is
#: editing anything**.  Operator §0B, and the distinction is the whole point:
#:
#:     one agent slot  !=  one unfinished capability
#:
#: VERSION_ACTIVE and LIVE_VERIFY_PENDING must NOT hold the single WorkBuddy slot -- a version
#: awaiting measurement is not work in progress, and holding the slot for it would stop every
#: other capability from being developed.  They must still stop a *second job for the same
#: capability*: the capability's previous loop has not finished, so a new gap for it is more
#: evidence for that loop, not a reason to open another one.
UNFINISHED_TRACE_STATES = frozenset({
    *ACTIVE_STATES, LIVE_VERIFY_PENDING, VERSION_ACTIVE, REJOINED,
})

#: Outcomes that keep a trace open even though the lifecycle state looks terminal.  A job that
#: reached LIVE_VERIFIED is waiting to be re-joined into normal play, and one that reached
#: LIVE_TRIED is waiting to be verified or repaired; both are mid-loop.
UNFINISHED_TRACE_OUTCOMES = frozenset({LIVE_TRIED, LIVE_VERIFIED})


def unfinished_trace(record: "EscalationRecord") -> bool:
    """Is this capability's development loop still running?

    True for a job in flight, for a version awaiting measurement, for a capability that has
    been verified but not yet re-joined -- and for one whose lifecycle looks terminal while
    its outcome says the loop has not closed.  False for a genuinely finished or abandoned
    trace (DONE, BLOCKED, COOLDOWN, a plain failure), which is what lets a new gap open a new
    job for the same capability.
    """
    if record.state in UNFINISHED_TRACE_STATES:
        return True
    return record.state in TERMINAL_STATES and record.outcome in UNFINISHED_TRACE_OUTCOMES

ALL_OUTCOMES: tuple[str, ...] = (
    CODE_CHANGED, TEST_PASS, VERSION_ACTIVATION_PENDING, REPLAY_PASS, LIVE_TRIED,
    LIVE_VERIFIED, OUTCOME_BLOCKED, NO_IMPROVEMENT,
)

# Outcomes that mean a real device produced evidence.  Only these may be used to
# promote a capability, and only LIVE_VERIFIED may set it to LIVE_VERIFIED.
OUTCOMES_WITH_DEVICE_EVIDENCE: frozenset[str] = frozenset({LIVE_TRIED, LIVE_VERIFIED})

# --------------------------------------------------------------- model routing
#
# Deliberately *not* here.  Which model to spend is WorkBuddy's own strategy, and
# the operator's architecture puts models below WorkBuddy as replaceable compute --
# V2 must not perceive them at all.  This queue therefore never names a model: it
# asks ``winter_agent_v2.workbuddy_model_router`` for a choice and records whatever
# it returns.  ``tests/test_workbuddy_model_router.py`` asserts that no model
# literal appears anywhere in ``winter_agent_v2/`` outside that module, which turns
# "V2 does not depend on a model" into something checkable rather than promised.
from .workbuddy_model_router import (  # noqa: E402  (kept near its use on purpose)
    ModelOutcome,
    ModelRouter,
    ModelStatsStore,
    default_stats_path as model_stats_path,
    task_type_for,
)

# --------------------------------------------------------------- policy & keys


@dataclass(frozen=True)
class EscalationPolicy:
    """The limits the operator set.  Values are defaults, not magic."""

    max_concurrent_jobs: int = 1
    # Post-fix attempts allowed per signature.  The first attempt is always free,
    # so this is "repair shots", not "total jobs".
    repair_budget: int = 2
    cooldown_minutes: int = 60
    # A signature seen this many times is labelled REPEATED_LIVE_FAILURE rather
    # than a first-sighting UI/gameplay problem.
    repeat_threshold: int = 2
    # "15 分钟仍无法解决": a signature whose first sighting is this old and which
    # still has no verified episode.
    stuck_minutes: int = 15
    # The timebox a job is *told* it has, in the work order itself.  Enforced as
    # well as stated: a job that outlives it while records are waiting behind it
    # holds the only concurrency slot, and no amount of pumping can get the queue
    # past that.  Measured 2026-09-18: job 2934e9cd ran for ~55 minutes against
    # this box with two records queued behind it.
    job_timebox_minutes: int = 45


@dataclass(frozen=True)
class FailureSignature:
    """``capability | failure_type | skill`` -- the dedup key."""

    capability: str
    failure_type: str
    skill: str = ""

    @property
    def key(self) -> str:
        return f"{self.capability}|{self.failure_type}|{self.skill}"

    def describe(self) -> str:
        return f"{self.capability} / {self.failure_type}" + (f" / {self.skill}" if self.skill else "")


@dataclass(frozen=True)
class EscalationCandidate:
    """A wall AUTO actually hit, with the evidence that says so."""

    signature: FailureSignature
    condition: str
    reason: str
    goal: str = ""
    evidence: tuple[str, ...] = ()
    world_state: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------- ledger

DEFAULT_LEDGER = "learning/workbuddy_escalations.jsonl"


class EscalationLedger:
    """Append-only event log.  ``snapshot()`` folds it; nothing else stores state."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        record = dict(event)
        record.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def events(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                out.append(payload)
        return out

    def snapshot(self) -> "EscalationSnapshot":
        return fold(self.events())


# ------------------------------------------------------------------ state fold


@dataclass
class EscalationRecord:
    key: str
    capability: str = ""
    failure_type: str = ""
    skill: str = ""
    condition: str = ""
    goal: str = ""
    # What produced this record: ``queue`` for a wall AUTO actually hit, ``bootstrap``
    # for a capability preloaded before any encounter.  Folded like ``task_type`` -- the
    # panel and the reconciler need to tell "we were blocked here" from "we prepared
    # this in advance", and an unwritten field reads as empty, which is how the first
    # version of ``task_type`` silently recorded blanks.
    origin: str = ""
    state: str = NEW
    attempts: int = 0
    repairs_used: int = 0
    outcome: str = ""
    job_id: str = ""
    model: str = ""
    model_reason: str = ""
    escalated_from: str = ""
    # Which bucket of work this was, so the router's evidence accumulates per task
    # type instead of per capability.  Folded from the submitted event like
    # repo_head -- a field that is written but never folded reads as empty, which
    # is how the first version of this silently recorded blank task types.
    task_type: str = ""
    # Why this record was not dispatched when it was created (``CONCURRENCY_WAIT`` and
    # its reason, for instance).  Folded for the same reason as ``task_type``, and it is
    # what the consumer quotes back when it re-offers a record it inherited.
    dispatch_reason: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    submitted_at: datetime | None = None
    settled_at: datetime | None = None
    # The moment the gateway says the job actually ended, as opposed to when this
    # process happened to observe it.  It is the boundary the activation rung measures
    # against ("has anything run the code this job produced"), and it has to be the
    # job's own time: a reconcile that runs an hour later must not push the boundary
    # forward, or the episodes that closed the rung would fall on the wrong side of it.
    version_since: datetime | None = None
    # The version the new code became.  ``before_version`` is the tree the job started
    # against and ``after_version`` the tree it produced; ``active_version`` is the version a
    # *measured episode* proves was actually loaded, which is the only one of the three that
    # says anything about what ran.  Operator §三: HEAD only describes the disk.
    before_version: str = ""
    after_version: str = ""
    active_version: str = ""
    activation_episode_id: str = ""
    activated_at: datetime | None = None
    # The episode a REJOINED/Production-Reuse step is credited to (operator §九).
    production_reuse_episode_id: str = ""
    # The examination's own evidence: the episode that *attempted* the capability (LIVE_TRIED)
    # and the one that passed it (LIVE_VERIFIED).  Two fields rather than one because they are
    # different facts and a failure must still leave a trace of having tried.
    live_try_episode_id: str = ""
    live_verify_episode_id: str = ""
    verified_at: datetime | None = None
    #: When the capability went back into the production pool.  The reuse detector needs it:
    #: only an episode recorded *after* this moment is ordinary play using the new version.
    rejoined_at: datetime | None = None
    # The agent's own words at settle time, carried forward so the re-measure does not
    # have to re-ask the gateway -- and so the corroboration behind a later LIVE_VERIFIED
    # is the same sentence the first measurement used, not a fresh guess.
    agent_report: str = ""
    cooldown_until: datetime | None = None
    code_changed: bool = False
    # The repository revision at dispatch time, so reconciliation can tell whether
    # the agent changed anything.  Captured here rather than re-read later: the
    # whole point is to compare against the state *before* the job ran.
    repo_head: str = ""
    repo_dirty: int = 0
    evidence: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def in_cooldown(self, now: datetime | None = None) -> bool:
        if self.state != COOLDOWN:
            return False
        if self.cooldown_until is None:
            return True
        return self.cooldown_until > (now or datetime.now(timezone.utc))


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _from_millis(value: Any) -> datetime | None:
    """A gateway timestamp (milliseconds since epoch) as an aware datetime.

    The jobs API reports ``firstTerminalAt`` in milliseconds, and passing that int
    where a datetime belongs compares an int to a datetime -- measured 2026-09-18, when
    ``settled_at`` silently accepted it and the activation rung never fired.  Named
    explicitly so the two shapes cannot be confused again.
    """
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000.0, timezone.utc)


def fold(events: Iterable[Mapping[str, Any]]) -> "EscalationSnapshot":
    """Replay the ledger into current state.  Deterministic; no side effects.

    Rows without a ``key`` are ignored: the bridge writes transport-level audit
    rows (``source: "bridge"``) into the same file, and folding those as queue
    state would invent records for jobs the queue never created -- which is
    exactly how a second, disagreeing source of truth starts.
    """
    records: dict[str, EscalationRecord] = {}

    def get(key: str) -> EscalationRecord:
        if key not in records:
            records[key] = EscalationRecord(key=key)
        return records[key]

    for event in events:
        kind = str(event.get("event", ""))
        key = str(event.get("key") or "")
        if not key:
            continue

        if kind == "escalation_created":
            record = get(key)
            record.capability = str(event.get("capability", record.capability))
            record.failure_type = str(event.get("failure_type", record.failure_type))
            record.skill = str(event.get("skill", record.skill))
            record.condition = str(event.get("condition", record.condition))
            record.goal = str(event.get("goal", record.goal))
            record.origin = str(event.get("origin", record.origin))
            record.dispatch_reason = str(event.get("dispatch_reason", record.dispatch_reason))
            record.first_seen = record.first_seen or _moment(event.get("recorded_at"))
            record.last_seen = _moment(event.get("recorded_at")) or record.last_seen
            record.evidence = tuple(str(e) for e in (event.get("evidence") or record.evidence))
            if record.state in ("", NEW):
                record.state = NEW
            continue

        if kind == "queued":
            record = get(key)
            if record.state not in TERMINAL_STATES:
                record.state = QUEUED
            record.notes.append(f"queued: {event.get('reason', '')}")
            continue

        if kind == "submitted":
            record = get(key)
            record.state = SUBMITTED
            record.job_id = str(event.get("job_id", record.job_id))
            record.model = str(event.get("model", record.model))
            record.model_reason = str(event.get("model_reason", record.model_reason))
            record.escalated_from = str(event.get("escalated_from", record.escalated_from))
            record.task_type = str(event.get("task_type", record.task_type))
            record.attempts = int(event.get("attempt", record.attempts + 1))
            record.submitted_at = _moment(event.get("recorded_at"))
            if event.get("repo_head"):
                record.repo_head = str(event["repo_head"])
                record.repo_dirty = int(event.get("repo_dirty") or 0)
            continue

        if kind == "job_state":
            record = get(key)
            state = str(event.get("state", ""))
            if state == WORKING:
                record.state = WORKING
            elif state in (DONE, FAILED, STOPPED) and record.state != COOLDOWN:
                # SUBMITTED -> DONE/FAILED/STOPPED; reconciliation may still overwrite
                # the *outcome*, but the lifecycle state is honest from here.
                #
                # STOPPED is settled like FAILED on purpose.  A job that was stopped will
                # never report again, and the gateway already maps "stopped" to a terminal
                # verdict -- but the fold only knew two states, so a cancelled job stayed
                # ``WORKING`` and held the one concurrency slot forever.  Measured while
                # tracing why a NEW record was never consumed: with one slot, a stranded
                # record starves every pending escalation behind it.
                record.state = DONE if state == DONE else FAILED
                record.settled_at = _moment(event.get("recorded_at"))
            continue

        if kind == "live_verify_pending":
            record = get(key)
            # The version exists and has not run.  Not terminal (the next pass still has
            # to measure it) and not active (no agent is working, and the single slot
            # must stay free), which is exactly why this state is in neither set.
            record.state = LIVE_VERIFY_PENDING
            # The outcome is folded too, so the panel can say "等待真机验证" from the
            # record rather than from a sentence someone has to parse.
            record.outcome = str(event.get("outcome") or record.outcome)
            record.version_since = _moment(event.get("version_since")) or record.version_since
            record.agent_report = str(event.get("agent_report") or record.agent_report)
            record.notes.append(
                f"version not active yet: {str(event.get('reason') or '')[:160]}"
            )
            continue

        if kind == "reconciled":
            record = get(key)
            record.outcome = str(event.get("outcome", record.outcome))
            record.code_changed = bool(event.get("code_changed", record.code_changed))
            record.settled_at = _moment(event.get("recorded_at")) or record.settled_at
            # The two versions the job produced.  Folded here because every rung above this
            # one is gated on them: without ``after_version`` on the record, "is the version
            # under test the version that ran" cannot be asked at all, and the activation
            # step would have nothing to compare an episode against.
            record.before_version = str(event.get("before_version") or record.before_version)
            record.after_version = str(event.get("after_version") or record.after_version)
            job_state = str(event.get("job_state", ""))
            if job_state in (DONE, FAILED):
                record.state = job_state
            if event.get("repair_used"):
                record.repairs_used += 1
            continue

        if kind == "version_active":
            # Operator §二/§三: the new version has been *loaded*.  The evidence is a real
            # episode recorded after the job settled whose ``repo_revision`` equals
            # ``after_version`` -- not a git HEAD read, which only describes the disk, and
            # not the agent's own word.
            record = get(key)
            record.state = VERSION_ACTIVE
            record.active_version = str(event.get("active_version")
                                        or event.get("after_version")
                                        or record.after_version)
            record.activation_episode_id = str(event.get("activation_episode_id") or "")
            record.activated_at = _moment(event.get("activated_at")) or _moment(
                event.get("recorded_at"))
            record.notes.append(
                f"version active: {record.active_version or 'unknown'} "
                f"(episode {record.activation_episode_id or 'unrecorded'})"
            )
            continue

        if kind == "rejoined":
            record = get(key)
            record.state = REJOINED
            # When it re-joined, kept because the reuse detector needs it: §9's evidence is an
            # episode recorded *after* the capability went back into the production pool.  A
            # production episode from before the rejoin is ordinary play that happened while the
            # job was still being examined, and it proves nothing about the new version.
            record.rejoined_at = _moment(event.get("rejoined_at")) or _moment(
                event.get("recorded_at"))
            record.notes.append(
                f"rejoined normal gameplay on {record.after_version or 'unknown'}"
            )
            continue

        if kind == "validation_result":
            # One examination's result when it is not a pass.  Recorded as its own event rather
            # than as a generic error, because the outcome decides the next action and the three
            # cases genuinely differ (operator §6/§7).
            record = get(key)
            outcome = str(event.get("outcome") or VALIDATION_NO_PROOF)
            record.outcome = outcome
            record.notes.append(
                f"validation: {outcome} -- {str(event.get('reason') or '')[:200]}"
            )
            if event.get("validation_episode_id"):
                record.live_try_episode_id = str(event["validation_episode_id"])
            if outcome == VALIDATION_VERSION_MISMATCH:
                # Not a failed capability -- a failed *measurement*.  The attempt proved
                # something about the wrong code, so the version under test has still not been
                # exercised: route back to the activation rung, where a later episode running
                # the right revision can move it forward again.  Parking it as a failure would
                # spend the repair budget on a code problem that does not exist.
                record.outcome = VERSION_ACTIVATION_PENDING
                record.state = LIVE_VERIFY_PENDING
            continue

        if kind == "live_tried":
            # The capability really ran on the version under test.  Success unknown, and the
            # operator's rule is that a start, a screenshot or a SAFE_STOP is not a try.
            record = get(key)
            record.outcome = LIVE_TRIED
            record.live_try_episode_id = str(event.get("validation_episode_id") or "")
            record.notes.append(
                f"live tried: {str(event.get('skill') or '')} "
                f"(episode {record.live_try_episode_id or 'unrecorded'}, "
                f"verifier_ok={event.get('verifier_ok')!r}, "
                f"goal_progress={event.get('goal_progress')!r})"
            )
            continue

        if kind == "live_verified":
            record = get(key)
            # Deliberately still LIVE_VERIFY_PENDING: a verified capability has not yet
            # re-joined normal play, and the operator's §8 rule is that those are two different
            # facts.  REJOINED -- appended once the device has actually been given back -- is
            # the state that says it is back in the production pool.  Neither is terminal while
            # production reuse is still unproven, which is what keeps the capability in
            # ``UNFINISHED_TRACE_STATES`` and stops a second job for it.
            record.state = LIVE_VERIFY_PENDING
            record.outcome = LIVE_VERIFIED
            record.live_verify_episode_id = str(event.get("validation_episode_id") or "")
            record.verified_at = _moment(event.get("verified_at")) or _moment(
                event.get("recorded_at"))
            record.notes.append(
                f"live verified on {record.active_version or record.after_version or 'unknown'}"
                f" (episode {record.live_verify_episode_id or 'unrecorded'})"
            )
            continue

        if kind == "production_reuse":
            # The end of the chain, and the only rung that distinguishes "WorkBuddy taught V2
            # the capability" from "the capability passed its exam".  Terminal on purpose: the
            # capability is back in normal play and no longer owes anything, which is what
            # releases it from UNFINISHED_TRACE_STATES so a future gap for it may open a new
            # job on its own merits.
            record = get(key)
            record.state = DONE
            record.production_reuse_episode_id = str(
                event.get("production_reuse_episode_id") or "")
            record.notes.append(
                f"production reuse on {record.after_version or 'unknown'}"
                f" (episode {record.production_reuse_episode_id or 'unrecorded'})"
            )
            continue

        if kind == "job_lost":
            # The gateway is up and says this job does not exist (HTTP 404 JOB_NOT_FOUND).
            # Measured 2026-09-18 20:20: record ``SPEND_STAMINA_ON_BEAST`` held the single
            # concurrency slot with job d8ea0e44, and the gateway answered JOB_NOT_FOUND --
            # so every escalation behind it was refused with CONCURRENCY_WAIT by a job that
            # could never finish.  Jobs do not survive their gateway instance, so a restart
            # strands the ledger pointing at work that is gone.
            #
            # Folded to FAILED (terminal) rather than to a tenth lifecycle state: this is the
            # same shape as STOPPED above -- a job that will never report again and must not
            # keep holding the slot -- and a new state would have to be taught to every
            # consumer (the fold, the panel strips, the truth projection) for no extra
            # decision.  The *cause* is kept, in the outcome and in the notes, because "the
            # work did not finish" and "the work did not finish because it vanished" lead to
            # different next actions: the second one is re-submitted from the budget, not
            # repaired.
            record = get(key)
            record.state = FAILED
            record.outcome = JOB_LOST
            record.settled_at = _moment(event.get("recorded_at")) or record.settled_at
            record.notes.append(f"job lost: {str(event.get('reason') or '')[:200]}")
            continue

        if kind == "blocked":
            record = get(key)
            record.state = BLOCKED
            record.notes.append(f"blocked: {event.get('reason', '')}")
            continue

        if kind == "cooldown_started":
            record = get(key)
            record.state = COOLDOWN
            record.cooldown_until = _moment(event.get("until"))
            record.notes.append(f"cooldown: {event.get('reason', '')}")
            continue

        if kind == "reload_required":
            record = get(key)
            record.notes.append(f"reload required: {event.get('reason', '')}")
            continue

        if kind == "evidence_appended":
            # A real gameplay failure that belongs to a job already in flight.  The
            # operator's rule is explicit: no second job, append the evidence and raise
            # the priority -- two agents editing one capability is what this prevents.
            record = get(key)
            record.evidence = tuple(str(e) for e in (
                *(event.get("evidence") or ()), *record.evidence
            ))
            record.notes.append(
                "real failure appended: "
                f"{event.get('failure_type', '')}/{event.get('skill', '')} "
                f"-- {str(event.get('reason') or '')[:180]}"
            )
            continue

        if kind == "priority_raised":
            record = get(key)
            record.notes.append(
                f"priority raised to {event.get('tier') or 'P0'}: {event.get('reason', '')}"
            )
            continue

        if kind == "knowledge_updated":
            record = get(key)
            record.notes.append(
                f"knowledge {event.get('outcome', '')}: {str(event.get('summary') or '')[:180]}"
            )
            continue

        if kind in ("cancel", "submit_failed"):
            record = get(key) if key else None
            if record is not None and record.state in (NEW, QUEUED, SUBMITTED, WORKING):
                record.state = QUEUED if kind == "submit_failed" else record.state
                record.notes.append(f"{kind}: {event.get('error') or event.get('http_status') or ''}")
            continue

    return EscalationSnapshot(records)


@dataclass(frozen=True)
class EscalationSnapshot:
    records: Mapping[str, EscalationRecord]

    def get(self, key: str) -> EscalationRecord | None:
        return self.records.get(key)

    def active(self) -> tuple[EscalationRecord, ...]:
        return tuple(r for r in self.records.values() if r.active)

    def active_jobs(self) -> tuple[EscalationRecord, ...]:
        return tuple(r for r in self.records.values() if r.state in (SUBMITTED, WORKING))

    def count_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records.values():
            counts[record.state] = counts.get(record.state, 0) + 1
        return counts

    def recoverable(self) -> tuple[EscalationRecord, ...]:
        """Records whose outcome was not measured yet (crash between events)."""
        return tuple(
            r for r in self.records.values()
            if r.state in (SUBMITTED, WORKING) and not r.settled_at
        )


# ---------------------------------------------------------------- dispatching


SUBMIT = "SUBMIT"
DEDUP_SKIP = "DEDUP_SKIP"
CONCURRENCY_WAIT = "CONCURRENCY_WAIT"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
IN_COOLDOWN = "IN_COOLDOWN"
NOT_ESCALATABLE = "NOT_ESCALATABLE"


@dataclass(frozen=True)
class Dispatch:
    """What to do about one candidate.  Pure decision; no I/O happens here."""

    action: str
    reason: str
    model: str = ""
    model_reason: str = ""
    escalated_from: str = ""
    attempt: int = 0
    task_type: str = ""

    @property
    def should_submit(self) -> bool:
        return self.action == SUBMIT


def decide(
    candidate: EscalationCandidate,
    snapshot: EscalationSnapshot,
    policy: EscalationPolicy,
    *,
    now: datetime | None = None,
    router: ModelRouter | None = None,
) -> Dispatch:
    """The whole throttle, as one pure function.

    Order matters and is deliberate: a condition that is not allowed is refused
    before anything else, then an existing job for the same key short-circuits,
    then the global concurrency cap, then the repair budget.  Anything else would
    let a recurring failure slip past one of the limits.
    """
    moment = now or datetime.now(timezone.utc)

    if candidate.condition not in AUTO_ESCALATION_CONDITIONS:
        return Dispatch(NOT_ESCALATABLE, f"{candidate.condition} is not an escalation condition")

    record = snapshot.get(candidate.signature.key)

    # Dedup is about *dispatched* work.  ``QUEUED`` means "decided but never sent"
    # -- the gateway was unreachable -- and treating that as active would let one
    # outage strand the escalation permanently: the key would be skipped forever
    # while no job ever existed.  Live proof: the unattended loop recorded
    # ``queued: gateway unavailable`` for
    # SPEND_STAMINA_ON_BEAST|VERIFIED_BEAST_TARGET_NOT_VISIBLE|SELECT_BEAST_TARGET
    # and had no path back.
    if record is not None and record.state in (SUBMITTED, WORKING):
        return Dispatch(
            DEDUP_SKIP,
            f"{candidate.signature.describe()} already has an active escalation "
            f"(state={record.state}, job={record.job_id or 'not submitted yet'})",
        )

    # The operator's §九: two WorkBuddy jobs must never edit one capability.  A signature
    # key is per-*failure*, not per-capability, and the resolver that builds it is
    # order-dependent (`_merge_into_active_job` carries the measurement), so key equality
    # cannot enforce this rule.  Enforced here -- in the one throttle every path goes
    # through -- so a re-key cannot open a second job on a capability already in flight.
    capability = candidate.signature.capability or candidate.signature.skill
    sibling = next(
        (
            other for other in snapshot.records.values()
            if other.key != candidate.signature.key
            # §0B: ``unfinished_trace`` rather than a bare state test.  A capability waiting on
            # a device, or verified but not yet re-joined, is mid-loop even though no agent is
            # working -- and opening a second job for it would be two jobs on one capability,
            # which is the rule this whole check exists to enforce.  Meanwhile the *slot* stays
            # free, so this does not stop a different capability from being developed.
            and unfinished_trace(other)
            and capability
            and capability in {other.capability, other.skill}
        ),
        None,
    )
    if sibling is not None:
        return Dispatch(
            DEDUP_SKIP,
            f"{candidate.signature.describe()} is the same capability as {sibling.key} "
            f"(state={sibling.state}, job={sibling.job_id or 'not submitted yet'}); one "
            f"capability must not have two jobs",
        )

    if record is not None and record.state == COOLDOWN:
        if record.cooldown_until and record.cooldown_until > moment:
            remaining = (record.cooldown_until - moment).total_seconds() / 60.0
            return Dispatch(
                IN_COOLDOWN,
                f"{candidate.signature.describe()} is in cooldown for another "
                f"{remaining:.0f} min after {record.repairs_used} repair shot(s)",
            )

    if len(snapshot.active_jobs()) >= policy.max_concurrent_jobs:
        holders = ", ".join(r.job_id or r.key for r in snapshot.active_jobs())
        return Dispatch(
            CONCURRENCY_WAIT,
            f"max_concurrent_jobs={policy.max_concurrent_jobs} is already used by "
            f"{holders}; two agents must not edit this repository at once",
        )

    # Repair budget: the first shot is free, later ones are counted after a
    # previous job finished without a live improvement.
    prior_repairs = record.repairs_used if record else 0
    if prior_repairs >= policy.repair_budget:
        return Dispatch(
            BUDGET_EXHAUSTED,
            f"{candidate.signature.describe()} has already spent "
            f"{prior_repairs} repair shot(s) without a live improvement",
        )

    attempt = prior_repairs
    needs = _needs_hint(candidate)
    choice = (router or default_router()).choose(
        task_type_for(candidate.condition, needs=needs),
        attempt=attempt,
        needs=needs,
        previous_model=record.model if record else "",
    )
    return Dispatch(
        SUBMIT,
        f"attempt {attempt + 1}/{policy.repair_budget + 1} for "
        f"{candidate.signature.describe()} ({candidate.condition}, {choice.task_type})",
        model=choice.model,
        model_reason=choice.reason,
        escalated_from=choice.escalated_from,
        attempt=attempt,
        task_type=choice.task_type,
    )


_DEFAULT_ROUTER: ModelRouter | None = None


def default_router(root: Path | str | None = None) -> ModelRouter:
    """The process-wide router, reading this project's recorded outcomes.

    Lazy so importing the queue does not touch the disk, and injectable so tests
    never depend on the developer's local stats file.
    """
    global _DEFAULT_ROUTER
    if root is not None:
        return ModelRouter(model_stats_path(root))
    if _DEFAULT_ROUTER is None:
        base = Path(__file__).resolve().parents[1]
        _DEFAULT_ROUTER = ModelRouter(model_stats_path(base))
    return _DEFAULT_ROUTER


def _needs_hint(candidate: EscalationCandidate) -> str:
    """Coarse problem shape, so a known-hard case can start higher."""
    text = f"{candidate.reason} {candidate.signature.failure_type}".lower()
    if any(word in text for word in ("vision", "template", "roi", "crop", "phash")):
        return "vision"
    if any(word in text for word in ("cross-file", "architecture", "refactor")):
        return "architecture"
    if any(word in text for word in ("log", "episodes", "many files")):
        return "logs"
    return ""


# ------------------------------------------------------------------ detection


def capability_for_skill(
    skill: str,
    *,
    root: Path | str | None = None,
) -> str:
    """Resolve a skill to the capability the project already says it implements.

    Reads ``knowledge/goals/capability_skill_map.json`` -- the existing model of
    Goal -> Capability -> Skill -> Evidence -- rather than building a second
    mapping.  An unknown skill resolves to itself, which is honest: it is a name
    we have no better label for, not a capability we invent.
    """
    if not skill:
        return ""
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    try:
        payload = json.loads((base / "knowledge/goals/capability_skill_map.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return skill
    for goal in payload.get("goals") or ():
        for entry in goal.get("capabilities") or ():
            if skill in (entry.get("implemented_by"), entry.get("live_verified_by")):
                return str(entry.get("capability") or skill)
            if skill in (entry.get("alternatives") or ()):
                return str(entry.get("capability") or skill)
    return skill


def classify_condition(
    signature: FailureSignature,
    *,
    occurrences: int,
    first_seen: datetime | None,
    now: datetime | None,
    policy: EscalationPolicy,
    unimplemented: bool = False,
    verified_episodes: int = 0,
) -> tuple[str, str] | None:
    """Choose one of the five conditions, or ``None`` to leave it alone.

    ``None`` is a real answer and the common one: most failures are an ordinary
    step not landing, which AUTO retries by itself.  Only the shapes the operator
    listed get a development agent, and an unknown shape gets none -- guessing a
    condition would send an agent after the wrong problem.

    ``verified_episodes`` is the count of production episodes for this signature's
    capability, with a passing verifier, recorded between ``first_seen`` and now.
    ``STUCK_15_MIN`` means "15+ minutes and *still no verified episode*", so a
    non-zero count decides it: the capability is demonstrably working on the real
    client and what happened is an ordinary transient AUTO already retried past.
    Leaving it alone is the honest answer -- escalating it sends an agent to fix
    something that is not broken.  Measured 2026-09-17:
    ``SCAN_MAP_FOR_BEAST|BEAST_SCAN_NOT_PROVEN`` was escalated ``STUCK_15_MIN``
    at 14:56 as "no verified episode" while 130 verifier-passing episodes of that
    very skill had been recorded since the 13:42 failure.
    """
    moment = now or datetime.now(timezone.utc)

    if unimplemented:
        return CAPABILITY_MISSING, (
            f"{signature.skill or signature.capability} has no implementation or no "
            f"reachable verifier, so no amount of retrying will make it pass"
        )

    if first_seen is not None:
        age_minutes = (moment - first_seen).total_seconds() / 60.0
        if age_minutes >= policy.stuck_minutes:
            if verified_episodes:
                return None
            return STUCK_15_MIN, (
                f"{signature.describe()} has been failing for {age_minutes:.0f} min "
                f"(>= {policy.stuck_minutes}) with no verified episode"
            )

    if occurrences >= policy.repeat_threshold:
        return REPEATED_LIVE_FAILURE, (
            f"{signature.describe()} has now failed {occurrences} times on the device"
        )

    # Gameplay first: ``DISPATCH_NOT_PROVEN`` matches the UI suffix too, and it
    # means something different.
    if signature.failure_type in GAMEPLAY_UNKNOWN_FAILURE_TYPES:
        return UNKNOWN_GAME_MECHANIC, (
            f"{signature.failure_type}: the client did something the model does not "
            f"describe"
        )

    if is_ui_unread(signature.failure_type):
        return UNKNOWN_UI, (
            f"{signature.failure_type}: the client showed something V2 could not "
            f"read or locate"
        )

    return None


def is_ui_unread(failure_type: str) -> bool:
    """Does this failure type mean "the UI could not be read"?"""
    text = str(failure_type)
    if text in UI_UNREAD_EXPLICIT:
        return True
    return any(text.endswith(suffix) for suffix in UI_UNREAD_SUFFIXES)


def candidates_from_run(
    *,
    stop_reason: str,
    failures: Iterable[Mapping[str, Any]],
    snapshot: EscalationSnapshot,
    policy: EscalationPolicy,
    now: datetime | None = None,
    unimplemented: Iterable[str] = (),
    root: Path | str | None = None,
    episodes_path: Path | str | None = None,
    deferrals: Iterable[Mapping[str, Any]] = (),
) -> tuple[EscalationCandidate, ...]:
    """Turn one run's failed episodes into at most a few escalation candidates.

    ``failures`` are episode-shaped mappings for *this run* (``failure_type``,
    ``skill``, ``goal_id``, screenshots).  A run that stopped for one of the
    ordinary-weather reasons yields nothing even if a step failed, because the
    stop reason is the runtime saying "there was nothing to do" -- escalating
    that would spend a development agent on a mailbox that is simply empty.

    When there are no failed episodes, a stop reason that :data:`STOP_REASON_WALLS`
    names is still a wall: the runtime looked, gave up, and issued no action, so
    nothing reached the episode stream.  Without that path the pipeline would be
    blind to this project's most frequent blocker.

    ``deferrals`` are the goal paths the scheduler itself refused to re-enter this
    run, with the evidence for refusing.  They are the third blind spot: a goal that
    steps aside produces no failure and no wall, so without this the queue would see
    a run in which nothing at all happened and never learn why.  Only
    ``NO_GOAL_PROGRESS`` deferrals become candidates -- a capability already sitting
    in ``DEVELOPMENT_PENDING``/``COOLDOWN``/``BLOCKED`` is the queue's own business
    and it must not receive a second job through a different name.
    """
    moment = now or datetime.now(timezone.utc)

    unimplemented_set = {str(x) for x in unimplemented}
    seen: set[str] = set()
    out: list[EscalationCandidate] = []

    # The deferred-goal path runs *before* the ordinary-weather gate, because that
    # gate exists to keep a mailbox that is simply empty out of the queue, and a run
    # whose goal stepped aside is not empty -- it is a wall the scheduler reported by
    # name.  Everything below this block keeps the behaviour it had.
    for deferral in deferrals:
        if str(deferral.get("source") or "") != "NO_GOAL_PROGRESS":
            continue
        fields = str(deferral.get("failure_signature") or "").split("|")
        # Positional, with empty fields kept: ``<capability>|<failure_type>|<skill>``.
        # Dropping the empties made this a two-field string and the failure type then
        # read as the capability -- measured 2026-09-18, ``NO_GOAL_PROGRESS`` was
        # escalated as a capability of its own, which is a name no goal can route to
        # and a dedup key that does not match the wall it describes.  The failure
        # type is the anchor, so the field that equals it is never the capability.
        failure_type = "NO_GOAL_PROGRESS"
        if failure_type not in fields:
            continue
        at = fields.index(failure_type)
        capability = "|".join(fields[:at]).strip()
        skill = fields[at + 1].strip() if len(fields) > at + 1 else ""
        if not capability:
            # Nothing to hand a development agent, and inventing a name is exactly
            # the defect above; the deferral stays visible in the runtime snapshot.
            continue
        signature = FailureSignature(capability=capability, failure_type=failure_type, skill=skill)
        if signature.key in seen:
            continue
        seen.add(signature.key)
        goal = str(deferral.get("goal_id") or "")
        streak = deferral.get("streak") or 0
        out.append(
            EscalationCandidate(
                signature=signature,
                condition=REPEATED_LIVE_FAILURE,
                reason=(
                    f"{goal or capability} was attempted {streak} time(s) in a row and no part "
                    f"of it advanced, while every step passed its own verifier: the route is "
                    f"running but it cannot reach the goal.  This is not a retry that will "
                    f"succeed on the next cycle, and it is not the same failure shape the "
                    f"capability was previously escalated for"
                ),
                goal=goal,
                evidence=(f"deferral:{goal}:{streak}",),
            )
        )

    if stop_reason in NON_ESCALATABLE_STOP_REASONS:
        return tuple(out)

    # One read of the episode stream per distinct ``first_seen``, only for a
    # signature old enough to be a STUCK_15_MIN candidate at all.  The capability
    # is asked the same question reconciliation asks it -- "is there a production
    # episode with a passing verifier after this moment" -- through the existing
    # reader rather than a second one.
    proven_cache: dict[datetime, int] = {}

    def proven_since(record: EscalationRecord) -> int:
        assert record.first_seen is not None
        if record.first_seen not in proven_cache:
            proven_cache[record.first_seen] = len(new_live_episodes(
                record.capability or record.skill,
                skill=record.skill,
                since=record.first_seen,
                root=root,
                episodes_path=episodes_path,
            ))
        return proven_cache[record.first_seen]

    failure_list = list(failures)
    if not failure_list and stop_reason in STOP_REASON_WALLS:
        condition, skill, reason = STOP_REASON_WALLS[stop_reason]
        wall = EscalationCandidate(
            signature=FailureSignature(
                capability=capability_for_skill(skill, root=root),
                failure_type=stop_reason.upper(),
                skill=skill,
            ),
            condition=condition,
            reason=reason,
        )
        # Appended rather than returned so a run can report both a wall and a
        # deferral; the failure loop below has nothing to do in this branch.
        if wall.signature.key not in seen:
            seen.add(wall.signature.key)
            out.append(wall)
        return tuple(out)

    for failure in failure_list:
        failure_type = str(failure.get("failure_type") or "")
        skill = str(failure.get("skill") or "")
        if not failure_type:
            continue

        capability = capability_for_skill(skill, root=root)
        signature = FailureSignature(capability=capability, failure_type=failure_type, skill=skill)
        if signature.key in seen:
            continue
        seen.add(signature.key)

        # Occurrences are counted across the whole ledger plus this run, from real
        # device episodes only.
        record = snapshot.get(signature.key)
        occurrences = (record.attempts if record else 0) + 1
        first_seen = (record.first_seen if record else None) or moment

        # Only ask (and only pay for the read) when the elapsed-time branch could
        # fire: a signature with no record, or a young one, has nothing to prove.
        verified = 0
        if record is not None and record.first_seen is not None:
            age_minutes = (moment - record.first_seen).total_seconds() / 60.0
            if age_minutes >= policy.stuck_minutes:
                verified = proven_since(record)

        verdict = classify_condition(
            signature,
            occurrences=occurrences,
            first_seen=first_seen if record else None,
            now=moment,
            policy=policy,
            unimplemented=skill in unimplemented_set,
            verified_episodes=verified,
        )
        if verdict is None:
            continue
        condition, reason = verdict

        shots = [failure.get("before_screenshot"), failure.get("after_screenshot")]
        episode_dir = _episode_dir(failure)
        evidence = tuple(str(s) for s in (*shots, episode_dir) if s)
        out.append(
            EscalationCandidate(
                signature=signature,
                condition=condition,
                reason=reason,
                goal=str(failure.get("goal_id") or ""),
                evidence=evidence,
                world_state=dict(failure.get("state_before") or {}),
            )
        )

    return tuple(out)


def _episode_dir(failure: Mapping[str, Any]) -> str:
    """The evidence directory behind an episode's frame, when it has one."""
    shot = failure.get("before_screenshot")
    if not shot:
        return ""
    parent = Path(str(shot)).parent
    return "" if str(parent) in (".", "") else str(parent)


# ---------------------------------------------------------------- reconciling


@dataclass(frozen=True)
class RepoRevision:
    """What the working tree looked like at one moment.

    ``digest`` is a content fingerprint of the uncommitted changes, and it exists because a
    count is not an identity.  Measured reasoning (operator §0A): two different working trees
    can share a commit, share the *number* of modified files, and contain entirely different
    code -- so ``head + dirty_count`` answered "same version" about two different trees, and
    every rung that trusts a version identity (activation, validation binding, production
    reuse) would have been comparing nothing.
    """

    head: str = ""
    dirty: int = 0
    ok: bool = False
    #: sha256 over the staged diff, the unstaged diff and the manifest of untracked files.
    #: Empty for a clean tree, where the commit alone is the identity.
    digest: str = ""

    @property
    def token(self) -> str:
        """The comparable form of this revision.

        A clean tree is identified by its **full** commit sha: a prefix is a display
        convenience and collisions in twelve hex characters are not something a version
        identity should be built on.  A dirty tree is the commit *plus* the content digest,
        because the uncommitted edit is part of the version.

        The old form was ``head[:12] + "+" + dirty_count``, which the operator named as a
        correctness hole: the count says how many files differ, never *how*.
        """
        if not self.ok:
            return ""
        if not self.dirty:
            return self.head
        return f"{self.head}+{self.digest[:16]}"

    def differs_from(self, other: "RepoRevision") -> bool:
        """Do these two describe different code?  Asked of the token, not of the parts.

        Comparing ``head`` and ``dirty`` separately is what made a same-head, same-count,
        different-content pair look unchanged.
        """
        if not (self.ok and other.ok):
            return False
        return self.token != other.token


def repo_revision(root: Path | str, *, timeout: float = 20.0) -> RepoRevision:
    """``git rev-parse HEAD`` plus a dirty count.  Objective, local, cheap.

    Used instead of parsing an agent's summary: whether the tree changed is a
    fact this machine can measure, and "the agent said it edited files" is not.
    """
    base = Path(root)

    def run(args: Sequence[str]) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(base),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **hidden_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (result.stdout or "").strip()

    head = run(["rev-parse", "HEAD"])
    status = run(["status", "--porcelain"])
    if not head:
        return RepoRevision(ok=False)
    dirty = len([line for line in status.splitlines() if line.strip()])
    digest = ""
    if dirty:
        # The canonical fingerprint lives in ``version_identity`` so the queue, the live
        # runtime and the process bootstrap all compute the same thing; a second copy here is
        # a second answer to "which version is this", and the two would drift.  Only the
        # version-*relevant* dirty paths are covered -- a log line must not create a version.
        canonical = canonical_revision(base)
        dirty = canonical.dirty
        digest = canonical.digest
        if not canonical.ok:
            return RepoRevision(ok=False)
    return RepoRevision(head=head, dirty=dirty, ok=True, digest=digest)


def new_live_episodes(
    capability: str,
    *,
    skill: str = "",
    since: datetime | None,
    root: Path | str | None = None,
    episodes_path: Path | str | None = None,
    version_changed_from: str = "",
    require_goal_progress: bool = False,
    after: datetime | None = None,
) -> tuple[dict[str, Any], ...]:
    """Production episodes proving the capability after ``since``.

    Only ``recorded_at`` rows count (the project's rule: imported history is
    indistinguishable otherwise) and only ``verifier_ok`` rows count, and evidence
    paths must be present.  This is the gate that keeps ``LIVE_VERIFIED`` from
    being something an agent can claim.

    ``after`` is the correction the operator made on 2026-09-18, and it is the half
    that was missing: an episode must have been recorded *after the job finished*,
    because each cycle is a fresh process that imports the package from disk, so a
    cycle that started after the job terminated is a cycle running the code the job
    produced.  Without it the ladder credited a fix to episodes recorded while the
    developer was still working -- which is the difference between "a different tree"
    and "the new version".

    ``version_changed_from`` is the tree revision at dispatch time, and it is the
    second half of that gate: an episode only counts when it ran a *different* tree
    than the one the job started against.  Without it, AUTO's own concurrent work on
    the same skill is credited to the job -- measured 2026-09-18, the NAVIGATE_TO_MAP
    reconciliation counted three episodes recorded while the job was still WORKING,
    i.e. against the code it was about to replace.  An episode with no recorded
    ``repo_revision`` cannot show a version change and therefore cannot prove one.

    ``require_goal_progress`` is the third half, and it exists because the first two
    were not enough.  Measured 2026-09-18 01:43: the reconciler granted LIVE_VERIFIED
    to job 2934e9cd on six SCAN_MAP_FOR_BEAST episodes that had ``verifier_ok=True``
    and ``goal_progress=False`` on all six -- i.e. on exactly the observation that
    *defines* the failure.  The job's own report said the opposite ("criterion 2 ...
    does not hold").  A proof has to show the wall is gone; when the wall is "the
    goal does not move", the proof is a measured move.
    """
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    path = Path(episodes_path) if episodes_path else base / "learning/episodes.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()

    found: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("recorded_at") or row.get("verifier_ok") is not True:
            continue
        recorded = _moment(row.get("recorded_at"))
        if since is not None and (recorded is None or recorded <= since):
            continue
        if after is not None and (recorded is None or recorded <= after):
            continue
        if skill and row.get("skill") != skill:
            continue
        if not skill and capability:
            if capability_for_skill(str(row.get("skill") or ""), root=base) != capability:
                continue
        if not (row.get("before_screenshot") and row.get("after_screenshot")):
            continue
        if require_goal_progress and row.get("goal_progress") is not True:
            continue
        if version_changed_from:
            revision = str(row.get("repo_revision") or "")
            if not revision or revision == version_changed_from:
                continue
        found.append(row)
    return tuple(found)


def failures_since(
    since: datetime,
    *,
    root: Path | str | None = None,
    episodes_path: Path | str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Episode rows from the run that just finished, failures only.

    Read back from the episode stream rather than from the in-memory run steps,
    so what AUTO escalates about is the same thing the project records as
    evidence -- one source, not two.
    """
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    path = Path(episodes_path) if episodes_path else base / "learning/episodes.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()

    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        recorded = _moment(row.get("recorded_at"))
        if recorded is None or recorded < since:
            continue
        if not row.get("failure_type"):
            continue
        out.append(row)
    return tuple(out)


def reconcile_outcome(
    *,
    capability: str,
    skill: str,
    submitted_at: datetime | None,
    job_verdict: str,
    before: RepoRevision,
    after: RepoRevision,
    wiring_problems: int | None,
    agent_report: str = "",
    root: Path | str | None = None,
    episodes_path: Path | str | None = None,
    failure_type: str = "",
    settled_at: datetime | None = None,
    from_development_job: bool = False,
) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    """Decide what the job actually achieved, from local measurements only.

    Returns ``(outcome, explanation, evidence_episodes)``.  ``job_verdict`` is the
    gateway's word for the job (``DONE``/``FAILED``/``STOPPED``) and is used only
    to distinguish "the agent did nothing" from "the agent failed"; it is never
    treated as proof of a fixed capability.

    ``agent_report`` is the agent's own text, used as **corroboration and nothing
    more**.  A tree that differs from dispatch time is a fact, but attributing it
    to the agent is not: this project is edited from more than one place at once
    (that is why ``run_live.py`` carries a ``VERIFIER_MAPPING_CORRUPT`` guard).
    The first real escalation proved the point -- its agent reported "No code was
    changed" while the reconciler measured a changed tree, and the change was the
    harness's own concurrent edit.  So a code change is only called the agent's
    when the agent also says it made one, and the explanation names the
    corroboration instead of claiming proof.

    ``LIVE_VERIFIED`` needs an episode that ran a *different* tree than the one the
    job started against (see :func:`new_live_episodes`).  AUTO works the same skill
    while a job runs, and those concurrent successes are not the job's; three of them
    were counted for NAVIGATE_TO_MAP on 2026-09-18 while the job was still WORKING.
    ``settled_at`` is the stronger form of the same rule and the operator's correction
    of 2026-09-18: the episode must also have been recorded after the job finished,
    because only then is it a cycle that loaded the code the job produced.
    """
    episodes = new_live_episodes(capability, skill=skill, since=submitted_at,
                                root=root, episodes_path=episodes_path,
                                version_changed_from=before.token,
                                require_goal_progress=str(failure_type).upper() in PROOF_IS_GOAL_PROGRESS,
                                after=settled_at)
    if episodes and not from_development_job:
        latest = episodes[-1]
        return (
            LIVE_VERIFIED,
            f"{len(episodes)} production episode(s) with verifier_ok on a tree that "
            f"differs from dispatch time (latest {latest.get('recorded_at')}, revision "
            f"{str(latest.get('repo_revision'))} vs {before.token or 'unknown'}), "
            f"evidence {Path(str(latest.get('before_screenshot'))).name}",
            episodes,
        )

    if episodes:
        # The shortcut above is the one the operator closed on 2026-09-18, and this branch is
        # what replaces it for a *developed* trace.
        #
        # A production episode proves the capability works on the tree it ran.  It does not
        # prove the capability works on the version the job produced, and it certainly does not
        # prove the job taught V2 anything -- the same episode would exist if the agent had done
        # nothing at all.  So for a trace that came from a WorkBuddy job the ladder is
        # VERSION_ACTIVE -> LIVE_VERIFY_PENDING -> Development Validation -> LIVE_TRIED ->
        # LIVE_VERIFIED, and this returns the rung that routes into it rather than the rung that
        # ends it.
        #
        # ``version_changed_from=before.token`` admits any tree that differs from dispatch time,
        # which includes a *third* version, so "the new version has run" is not established by
        # these episodes even though they pass.  VERSION_ACTIVATION_PENDING is the honest word:
        # it says the produced version has not been shown to be running yet.
        return (
            VERSION_ACTIVATION_PENDING,
            f"{len(episodes)} production episode(s) with verifier_ok exist, but this trace came "
            f"from a development job: a production success is not the job's proof and may not "
            f"certify the version it produced. The capability must be examined on the version "
            f"itself (VERSION_ACTIVE -> LIVE_VERIFY_PENDING -> 真机校准 -> LIVE_TRIED -> "
            f"LIVE_VERIFIED); these episodes ran a tree that differs from dispatch time but is "
            f"not shown to be {after.token[:12] or 'the produced version'}.",
            episodes,
        )

    changed = before.differs_from(after)
    claimed = agent_claims_change(agent_report)
    revision_delta = (
        f"HEAD {before.head[:8] if before.ok else '?'}->{after.head[:8] if after.ok else '?'}, "
        f"dirty {before.dirty}->{after.dirty}"
    )

    if changed and not claimed:
        return (
            CODE_CHANGED,
            f"the tree differs from dispatch time ({revision_delta}) but the agent's "
            f"own report does not claim a change, so the difference may not be the "
            f"agent's -- this repository is edited from more than one place",
            (),
        )
    if changed and wiring_problems == 0:
        # The operator's correction of 2026-09-18: this rung is where the ladder used
        # to jump straight to LIVE_VERIFIED.  A green gate and a changed tree describe
        # the *source*, not what is running; the next cycle is the first process that
        # can have loaded it, so until an episode recorded after the job finished
        # exists, the honest word is "the new version has not been exercised yet".
        ran_after_job = new_live_episodes(
            capability, skill=skill, since=submitted_at, root=root,
            episodes_path=episodes_path, version_changed_from=before.token,
            after=settled_at,
        )
        if settled_at is not None and not ran_after_job:
            return (
                VERSION_ACTIVATION_PENDING,
                f"tree changed ({revision_delta}) with the agent corroborating a change, and "
                f"check_wiring reports problems: 0. The new version has NOT run yet: every "
                f"cycle is a fresh process that imports the package from disk, so the first "
                f"episode recorded after {settled_at.isoformat()} is the first that can carry "
                f"it. LIVE_VERIFIED is not granted to a version nothing has loaded.",
                (),
            )
        return (
            TEST_PASS,
            f"tree changed ({revision_delta}) with the agent corroborating a change, and "
            f"check_wiring reports problems: 0. NOT a verified capability: the version is "
            f"running, but no production episode with a passing verifier exists -- see the "
            f"note below when verifier-passing episodes do exist.",
            (),
        )
    if changed:
        return (
            CODE_CHANGED,
            f"tree changed ({revision_delta}) but the wiring gate reported "
            f"{'not run' if wiring_problems is None else f'{wiring_problems} problem(s)'}",
            (),
        )
    if job_verdict in ("FAILED", "STOPPED"):
        return OUTCOME_BLOCKED, f"job ended {job_verdict} and nothing changed in the tree", ()
    return NO_IMPROVEMENT, "job finished, no code change and no new verified episode", ()


# Phrases an agent uses when it actually changed something.  Coarse on purpose:
# this is corroboration for a fact measured elsewhere, so a false positive costs
# little and a false negative just downgrades TEST_PASS to CODE_CHANGED.
_CHANGE_CLAIM = re.compile(
    r"(?i)(commit\s+hash|committed|files?\s+changed|changed\s+\d+\s+file|"
    r"\bedited\b|\bmodified\b|\bpatched\b|\bwrote\b|\bcreated\b|\bit\s+is\s+fixed\b)"
)
_HEX_COMMIT = re.compile(r"\b[0-9a-f]{7,40}\b")


#: The word used when a validation cycle ran but produced no episode that may be credited.
VALIDATION_NO_PROOF = "VALIDATION_NO_PROOF"
#: The cycle produced episodes, but not for this trace / job / capability.  A refusal, not a
#: failure: nothing about the capability has been learned, and crediting it would be the
#: "first LIVE_VERIFY_PENDING" mistake one layer down.
VALIDATION_CONTEXT_MISMATCH = "VALIDATION_CONTEXT_MISMATCH"
#: The attempt was real but ran the wrong code.  Distinct from a failed capability, and routed
#: back to the activation rung rather than spending the repair budget on a problem that is not
#: in the code.
VALIDATION_VERSION_MISMATCH = "VALIDATION_VERSION_MISMATCH"


#: The order in which an open trace counts as *the* current one.  Operator §7, and it is a
#: ranking rather than a predicate because "which capability is the system working on" has one
#: answer and several candidates.
#:
#: Read from the top: a capability an agent is editing right now outranks one waiting for its
#: examination, which outranks one whose version has loaded but has not been sent, which
#: outranks one that has re-joined and awaits proof of reuse, which outranks a record that has
#: only just been created.  A finished trace is in no bucket at all, so a historical DONE,
#: FAILED or JOB_LOST can never displace an open one.
TRACE_PRIORITY: tuple[tuple[str, ...], ...] = (
    (WORKING, SUBMITTED),
    (LIVE_VERIFY_PENDING,),
    (VERSION_ACTIVE,),
    (REJOINED,),
    (NEW, QUEUED),
)


def current_development_trace(snapshot: "EscalationSnapshot") -> "EscalationRecord | None":
    """The one trace the system is working on, or ``None`` when nothing is open.

    Operator §7's fix for a measured defect: the window had two selectors.  The development
    page took the first active-or-awaiting record; the closed-loop card took whichever chain
    ``unattended_closure`` called newest.  Measured 2026-09-18 23:14, they named different
    capabilities side by side -- ``OPEN_MARCH_FORMATION``/``06271322`` in one region and
    ``SPEND_STAMINA_ON_BEAST``/``5b525aa4`` in the other -- and both said "current".  One
    question, two answers, is a conflict by construction rather than by accident.

    Ties inside a rank go to the most recent activity, using the newest timestamp the fold
    recorded.  ``None`` is a real answer: with nothing open there is no current trace, and a
    reader must not be handed a finished one dressed as the present.
    """
    ranked: list[tuple[int, float, "EscalationRecord"]] = []
    for record in snapshot.records.values():
        for rank, states in enumerate(TRACE_PRIORITY):
            if record.state in states:
                stamps = [m for m in (record.last_seen, record.submitted_at, record.first_seen)
                          if m is not None]
                ranked.append((rank, max(stamps).timestamp() if stamps else 0.0, record))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], -item[1]))
    return ranked[0][2]


def _is_true(value: Any) -> bool:
    """Is this a truthy flag, whether it arrived as a bool or as its JSON spelling?"""
    if value is True:
        return True
    return str(value or "").strip().lower() in ("true", "1")


def validation_settlement(
    *, trace_key: str, job_id: str, capability: str, skill: str,
    after_version: str, failure_type: str = "",
    episodes: Iterable[Mapping[str, Any]], since: datetime | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """What did one Development Validation cycle achieve?  ``(outcome, why, episode)``.

    Operator §5-§7, as one function, because the gates have to be applied together: an
    examination whose episode matches on four of five axes is not "mostly verified", it is
    unusable, and the failure modes are different enough that each needs its own name.

    The ladder this decides between:

        LIVE_VERIFIED          everything matched *and* the capability was proved
        LIVE_TRIED             the capability really ran; success unknown
        VALIDATION_VERSION_MISMATCH    a real attempt, but not on the version under test
        VALIDATION_CONTEXT_MISMATCH    an episode that is not this trace's at all
        VALIDATION_NO_PROOF    nothing ran the target -- a start, a screenshot or a SAFE_STOP
                               is not a try

    Only episodes from a ``DEVELOPMENT_VALIDATION`` cycle count.  A production episode is
    evidence for a different question, and the operator's §8 rule is that it may never be read
    as the examination's result.

    ``LIVE_VERIFIED`` additionally requires the verifier to have passed, the evidence frames to
    exist, and -- for a defect whose proof *is* goal progress -- actual goal progress.  So a
    SAFE_STOP that "succeeded", navigation that completed, or an action that ran while the goal
    did not move cannot become a verified capability.
    """
    seen = [dict(row) for row in episodes]
    ours = [row for row in seen
            if str(row.get("execution_mode") or "").upper() == "DEVELOPMENT_VALIDATION"]
    if not ours:
        return (VALIDATION_NO_PROOF,
                "本轮没有产生 DEVELOPMENT_VALIDATION 模式的 Episode：启动过进程、截图成功或 "
                "SAFE_STOP 都不算真机尝试。",
                {})
    if since is not None:
        ours = [row for row in ours
                if (_moment(row.get("recorded_at")) or datetime.min.replace(tzinfo=timezone.utc))
                >= since] or ours

    # Context first: an episode from another trace says nothing about this one, and treating it
    # as this trace's attempt would be the "first LIVE_VERIFY_PENDING" mistake one layer down.
    trace = str(trace_key or "")
    mine = [row for row in ours
            if (not trace or str(row.get("trace_id") or "") == trace)]
    if not mine:
        got = ", ".join(sorted({str(row.get("trace_id") or "") for row in ours}))[:200]
        return (VALIDATION_CONTEXT_MISMATCH,
                f"找到 {len(ours)} 条 DEVELOPMENT_VALIDATION Episode，但没有一条属于 trace "
                f"{trace or '(未指名)'}（实际来自：{got or '空'}）。不碰设备、不记功。",
                {})
    context_ok = [row for row in mine
                  if str(row.get("job_id") or "") == str(job_id or "")
                  and str(row.get("capability") or "") == str(capability or "")]
    if not context_ok:
        return (VALIDATION_CONTEXT_MISMATCH,
                f"trace 匹配但 job/capability 不匹配：期望 job={job_id or '空'} "
                f"capability={capability or '空'}，实际 job="
                f"{str(mine[0].get('job_id') or '空')} capability="
                f"{str(mine[0].get('capability') or '空')}。",
                dict(mine[0]))

    # Version next, and before anything is credited: an attempt on the wrong code proves
    # something about the wrong code.
    expected = str(after_version or "")
    version_ok = [row for row in context_ok
                  if str(row.get("repo_revision") or "") == expected
                  and str(row.get("expected_after_version") or expected) == expected]
    if not version_ok:
        latest = context_ok[-1]
        return (VALIDATION_VERSION_MISMATCH,
                f"校准跑的不是被测版本：expected={expected or '空'}，"
                f"episode repo_revision={str(latest.get('repo_revision') or '空')}，"
                f"expected_after_version={str(latest.get('expected_after_version') or '空')}。"
                "不得记 LIVE_TRIED / LIVE_VERIFIED，等待正确版本重新激活。",
                dict(latest))

    # Did the *target* run?  A cycle that only navigated, or stopped safely, has not tried.
    target_skill = str(skill or "")
    ran = [row for row in version_ok
           if not target_skill or str(row.get("skill") or "") == target_skill]
    if not ran:
        latest = version_ok[-1]
        return (VALIDATION_NO_PROOF,
                f"版本正确但没有一条 Episode 执行了目标 skill {target_skill or '(未指名)'}"
                f"（实际：{str(latest.get('skill') or '空')}）。仅启动、截图或 SAFE_STOP 不算真机尝试。",
                dict(latest))

    latest = ran[-1]
    needs_goal = str(failure_type).upper() in PROOF_IS_GOAL_PROGRESS
    verifier_ok = latest.get("verifier_ok") is True
    goal_ok = latest.get("goal_progress") is True
    evidence = bool(str(latest.get("before_screenshot") or "")
                    and str(latest.get("after_screenshot") or ""))
    if not verifier_ok:
        return (LIVE_TRIED,
                f"目标 {target_skill} 已在真机执行，但 Verifier 未通过"
                f"（verifier_ok={latest.get('verifier_ok')!r}）。这是真机尝试，不是成功证明。",
                dict(latest))
    if not evidence:
        return (LIVE_TRIED,
                "Verifier 通过但缺 before/after 证据帧，不能算已验证。",
                dict(latest))
    if needs_goal and not goal_ok:
        return (LIVE_TRIED,
                f"Verifier 通过、证据齐全，但该缺陷的证明条件是 Goal Progress，"
                f"而 goal_progress={latest.get('goal_progress')!r}。动作成功不等于目标推进。",
                dict(latest))
    return (LIVE_VERIFIED,
            f"目标 {target_skill} 在被测版本 {expected[:12]} 上真机执行，Verifier 通过，"
            f"证据齐全" + ("，Goal Progress 成立" if needs_goal else "") + "。",
            dict(latest))


def agent_claims_change(report: str) -> bool:
    """Does the agent's own report claim that it changed the tree?

    Used only to corroborate a tree diff the reconciler already measured.  An
    agent that *denies* changing anything is believed about that, because the
    alternative -- attributing any diff in the window to the agent -- silently
    credits it with a human's or a sibling process's edit.
    """
    text = str(report or "")
    if not text:
        return False
    if re.search(r"(?i)no code was changed|did not change|nothing changed|unchanged", text):
        return False
    return bool(_CHANGE_CLAIM.search(text) or _HEX_COMMIT.search(text))


# ------------------------------------------------------------------- adapter


def unimplemented_skills(root: Path | str | None = None) -> frozenset[str]:
    """Skills the project itself records as never implemented.

    Read from ``knowledge/goals/capability_skill_map.json``: a capability whose
    ``implemented_by`` is null (or whose status is ``NEVER_TRIED`` / ``MISSING``)
    is the project's own answer to "there is nothing to retry here", which is what
    ``CAPABILITY_MISSING`` means.  Derived, never guessed.
    """
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    try:
        payload = json.loads(
            (base / "knowledge/goals/capability_skill_map.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return frozenset()
    out: set[str] = set()
    for goal in payload.get("goals") or ():
        for entry in goal.get("capabilities") or ():
            status = str(entry.get("status") or "").upper()
            if status in ("NEVER_TRIED", "MISSING") or not entry.get("implemented_by"):
                out.add(str(entry.get("capability") or ""))
                for alternative in entry.get("alternatives") or ():
                    out.add(str(alternative))
    out.discard("")
    return frozenset(out)


@dataclass(frozen=True)
class RunObservation:
    """What the AUTO hook saw and did.  Printed, never raised."""

    reconciled: tuple[str, ...] = ()
    submitted: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()
    # Records settled because the device proved the capability itself, so no job was
    # needed.  Reported separately from ``reconciled`` because no job was involved.
    released: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    reload_requested_for: str = ""
    # A preload pass reports through the same observation shape: the same adapter,
    # the same throttle, the same ledger.  ``preload_note`` carries the gate's own
    # sentence when nothing was dispatched, so "the mechanism is resting" is a
    # readable state rather than an absence of evidence.
    preloaded: tuple[str, ...] = ()
    preload_note: str = ""
    # A version that just became the thing to examine, so the operator can see the
    # device hand-off happening rather than infer it from a yielded runtime.
    lease_requested_for: str = ""

    @property
    def line(self) -> str:
        parts = []
        if self.reconciled:
            parts.append(f"reconciled {len(self.reconciled)}")
        if self.submitted:
            parts.append(f"submitted {len(self.submitted)}")
        if self.released:
            parts.append(f"released {len(self.released)} (already proven on the device)")
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        if self.errors:
            parts.append(f"errors {len(self.errors)}")
        if self.reload_requested_for:
            parts.append(f"reload requested ({self.reload_requested_for})")
        if self.preloaded:
            parts.append(f"preloaded {len(self.preloaded)}")
        if self.preload_note:
            parts.append(f"preload: {self.preload_note}")
        if self.lease_requested_for:
            parts.append(f"validation lease requested ({self.lease_requested_for})")
        return "[escalation] " + (", ".join(parts) if parts else "nothing to do")


class EscalationQueueAdapter:
    """The only part that touches the network, git, and the marker file.

    Everything it needs is injected, so tests drive it with a scripted bridge and
    a temporary ledger.  :meth:`observe_run` is the AUTO hook: safe to call at the
    end of *any* run, because it never raises and never waits for an agent.
    """

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        ledger: EscalationLedger | None = None,
        bridge: Any | None = None,
        reload_signal: Any | None = None,
        policy: EscalationPolicy | None = None,
    ) -> None:
        from . import runtime_reload
        from .workbuddy_bridge import WorkBuddyBridge, escalation_request_from_project

        self.root = Path(root) if root else Path(__file__).resolve().parents[1]
        self.ledger = ledger or EscalationLedger(self.root / DEFAULT_LEDGER)
        self.bridge = bridge if bridge is not None else WorkBuddyBridge(cwd=self.root)
        self.reload_signal = reload_signal or runtime_reload.ReloadSignal(
            runtime_reload.default_path(self.root)
        )
        self.policy = policy or EscalationPolicy()
        # The only thing the queue knows about models is that a router exists; the
        # names live in workbuddy_model_router.py.
        self.model_stats = ModelStatsStore(model_stats_path(self.root))
        self._build_request = escalation_request_from_project

    # -- the AUTO hook ----------------------------------------------------

    def observe_run(
        self,
        *,
        stop_reason: str,
        failures: Sequence[Mapping[str, Any]] = (),
        deferrals: Sequence[Mapping[str, Any]] = (),
        now: datetime | None = None,
        reconcile: bool = True,
    ) -> RunObservation:
        """Reconcile finished jobs, then hand off at most a few decisions.

        Deliberately non-blocking.  The only HTTP calls are short reads, and a
        gateway that is down is recorded as an observation rather than raised:
        AUTO keeps playing with a development agent unreachable, and the
        escalation simply stays ``QUEUED`` until the gateway is back.
        """
        return self._drain(
            stop_reason=stop_reason, failures=failures, deferrals=deferrals,
            now=now, reconcile=reconcile,
        )

    def pump(self, *, now: datetime | None = None) -> RunObservation:
        """One consume pass with no run behind it -- the continuous queue pump.

        ``observe_run`` runs once per AUTO cycle, and a cycle is minutes long
        (measured 2026-09-18: ten minutes while the run ended in an ordinary
        stop).  A record created near the end of one cycle therefore waited for
        the next one, and if AUTO was stopped or paused it waited forever -- the
        queue had a consumer but no clock.  The panel owns the long-lived
        process, so it calls this on a timer and "created" finally means "will
        reach the bridge", independently of what AUTO is doing.

        Deliberately *not* a second queue: same adapter, same ``decide`` throttle,
        same ledger, same reconcile.  Passing no failures and no stop reason means
        the only work it can do is the work already owed -- settle in-flight jobs,
        and consume ``NEW``/``QUEUED`` records.
        """
        return self._drain(
            stop_reason=PUMP_STOP_REASON, failures=(), deferrals=(),
            now=now, reconcile=True,
        )

    def preload(
        self,
        *,
        now: datetime | None = None,
        plan: Any | None = None,
        mode: str = "PRELOAD",
        questions: Sequence[str] = (),
    ) -> RunObservation:
        """One Capability Bootstrap pass: offer at most one *prepared* capability.

        The second growth path.  ``observe_run``/``pump`` consume walls the device
        already hit; this consumes the capability catalog and prepares a brief for
        something nobody has hit yet, so a capability can be learned *before* the
        encounter instead of after it.

        Deliberately not a second pipeline: the candidate goes through the same
        ``decide()`` throttle, the same one-slot budget, the same ledger and the same
        bridge, and its record is marked ``origin=bootstrap`` so a reader can always
        tell "we were blocked here" from "we prepared this in advance".

        It is also deliberately *last*: :func:`capability_bootstrap.preload_gate`
        refuses while a real gap is owed, while an agent holds the single slot, while
        a development validation owns the device, while V2 is in a REALTIME activity,
        and while the main autonomous-development loop has not been proven once.
        Returns an observation either way -- "resting, because X" is the state the
        operator asked to be able to see.
        """
        from . import capability_bootstrap as bootstrap

        moment = now or datetime.now(timezone.utc)
        try:
            snapshot = self.ledger.snapshot()
            armed, arm_reason, arm_detail = bootstrap.arm_state(self.root)
            scanner = bootstrap.BootstrapScanner.load(
                self.root, ledger_snapshot=snapshot, policy=self.policy, now=moment
            )
            candidates = scanner.candidates()
            gate = bootstrap.preload_gate(
                armed=armed,
                arm_reason=arm_reason,
                arm_detail=arm_detail,
                active_jobs=len(snapshot.active_jobs()),
                pending_records=len(self.pending(snapshot=snapshot)),
                lease_holder=self._device_holder(),
                runtime=self._runtime_view(),
                actionable=len(candidates),
            )
            if not gate.allowed:
                return RunObservation(preload_note=gate.describe)
            if plan is None and not candidates:
                return RunObservation(preload_note="no preloadable capability")

            # The controller may hand in the capability it already selected (same scan,
            # same projection) so there is one selection authority; with no plan this
            # pass selects for itself, which is what the CLI does.
            chosen = plan if plan is not None else candidates[0]
            brief_path = bootstrap.write_brief(self.root, chosen)
            if mode == "TARGETED_RESEARCH":
                reason = (
                    f"TARGETED_RESEARCH (preload path): {chosen.capability_id} {chosen.code} "
                    f"has no implementation and its local knowledge is incomplete. Answer ONLY "
                    f"these questions and write the answers into "
                    f"knowledge/preload/{bootstrap._token_key(chosen.code)}.json "
                    f"(status PRIOR/UNVERIFIED, never CONFIRMED): "
                    + "; ".join(questions or ("identify the missing fields",))
                )
            else:
                reason = (
                    f"PRELOAD_BEFORE_ENCOUNTER: {chosen.capability_id} {chosen.code} is not "
                    f"implemented and nothing has failed here yet. Priority "
                    f"{bootstrap.PRIORITY_TIER.get(chosen.priority, chosen.priority)}; "
                    f"knowledge rung {chosen.knowledge_rank} "
                    f"({chosen.knowledge_source}); plan state {chosen.plan_state}; "
                    f"brief {brief_path.as_posix()}"
                )
            candidate = EscalationCandidate(
                signature=FailureSignature(
                    capability=chosen.code or chosen.capability_id,
                    failure_type=CAPABILITY_MISSING,
                    skill=chosen.skill,
                ),
                condition=CAPABILITY_MISSING,
                reason=reason,
                goal=(chosen.goal.split(",")[0].strip() if chosen.goal else ""),
                evidence=(brief_path.as_posix(),),
            )
            dispatch = decide(candidate, snapshot, self.policy, now=moment)
            if not dispatch.should_submit:
                self._record(candidate, dispatch, origin="bootstrap")
                return RunObservation(
                    preload_note=f"{chosen.code}: {dispatch.action}: {dispatch.reason}"
                )
            job_id = self._submit(
                candidate, dispatch, origin="bootstrap",
                extra_notes=bootstrap.work_order_brief(chosen),
            )
            if not job_id:
                return RunObservation(
                    preload_note=f"{chosen.code}: queued (gateway unavailable)"
                )
            return RunObservation(preloaded=(chosen.code,))
        except Exception as exc:  # noqa: BLE001 - a background pass must never raise
            return RunObservation(preload_note=f"preload failed: {type(exc).__name__}: {exc}")

    def _merge_into_active_job(self, candidate: EscalationCandidate) -> str:
        """Fold a real failure into whichever job already owns its capability.

        The operator's §12: when the runtime hits a capability an agent is already
        working, do **not** create a second job -- append the episode, screenshot,
        failure signature and world state to the existing one, and raise it to P0 when
        it is a preload job.  Two agents editing one capability is a merge conflict by
        construction, and the running job is the one holding the brief.

        Matched on the **capability**, deliberately not on the dedupe key.  Signature
        keys are not stable: ``capability_for_skill`` resolves through a map in which 22
        of 89 skills name two capabilities, and it returns the first match in file order,
        so an edit that adds a skill to an earlier entry silently re-keys every future
        escalation for that skill.  Measured 2026-09-18: adding ``SCAN_MAP_FOR_BEAST`` to
        ``SPEND_STAMINA_ON_BEAST``'s alternatives moved it from resolving to itself to
        resolving to ``SPEND_STAMINA_ON_BEAST`` -- a *different* signature key for the
        same wall, with a WORKING job already open on that very capability.  Key equality
        would have called that a new problem and opened a second job on it.

        Returns the existing record's key, or ``""`` when nothing matched.
        """
        capability = candidate.signature.capability or candidate.signature.skill
        if not capability:
            return ""
        names = {capability, candidate.signature.skill}
        names.discard("")
        for record in self.ledger.snapshot().records.values():
            if record.state not in (*ACTIVE_STATES, LIVE_VERIFY_PENDING):
                continue
            if record.key == candidate.signature.key:
                # The identical signature: ``decide`` owns that answer (dedup, cooldown,
                # budget), and folding it in here would append evidence to itself.
                continue
            if not names & {record.capability, record.skill}:
                continue
            self.ledger.append({
                "source": "queue",
                "event": "evidence_appended",
                "key": record.key,
                "into_key": record.key,
                "from_key": candidate.signature.key,
                "capability": capability,
                "failure_type": candidate.signature.failure_type,
                "skill": candidate.signature.skill,
                "condition": candidate.condition,
                "goal": candidate.goal,
                "reason": candidate.reason,
                "evidence": list(candidate.evidence),
            })
            if record.origin == "bootstrap":
                # Only a preload job has a priority to raise: a runtime escalation is
                # already the P0 it was born as.
                self.ledger.append({
                    "source": "queue",
                    "event": "priority_raised",
                    "key": record.key,
                    "tier": "P0",
                    "reason": (
                        "a real gameplay failure hit a capability this preload job already "
                        "owns; the evidence is appended instead of opening a second job"
                    ),
                })
            return record.key
        return ""

    def validation_lease_consumer(self, *, now: datetime | None = None) -> str:
        """Is anyone actually able to *drive* a validation right now?

        The lease is only requested when the panel owns the clock, because requesting it
        makes V2 yield at the next atomic boundary -- and a device that yields while
        nobody drives it is worse than a version that waits.  The panel therefore has to
        prove it is alive first: its pump heartbeat is the evidence, not its existence.

        ``now`` is the *pass's* clock, not the wall clock.  Reading ``datetime.now()``
        here made the answer irreproducible: a caller replaying a recorded pass got a
        different verdict depending on how long ago the recording was made, and every
        test that pinned a timestamp started failing ninety seconds later.
        """
        try:
            payload = json.loads(
                (Path(self.root) / "learning/control_panel/pump.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return ""
        stamp = _moment(payload.get("written_at"))
        if stamp is None:
            return ""
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        if age > PANEL_HEARTBEAT_MAX_AGE_SECONDS:
            return ""
        return f"panel pid {payload.get('process') or '?'} (heartbeat {int(age)}s ago)"

    def validation_lease_target(self) -> "EscalationRecord | None":
        """The oldest record whose version exists and has not been exercised yet.

        Oldest first on purpose: the version has been waiting the longest, and a queue
        that always validated the newest would starve the one behind it.
        """
        waiting = [
            record for record in self.ledger.snapshot().records.values()
            if record.state == LIVE_VERIFY_PENDING
        ]
        waiting.sort(key=lambda record: (record.settled_at is None, record.settled_at))
        return waiting[0] if waiting else None

    def service_validation_lease(self, *, now: datetime | None = None) -> str:
        """Ask for the device for a version that is waiting to be examined.

        This is the link that was missing: ``LIVE_VERIFY_PENDING`` existed, the lease
        protocol existed, and nothing ever *requested* the device for it -- so the
        operator's chain (new version -> live episode -> verifier -> LIVE_VERIFIED) had
        no one to take the first step.

        The request is deliberate rather than forceful: :meth:`DeviceLease.request`
        records the ask and takes the device only if it is free, and the runtime already
        yields at its atomic boundary when another owner holds it.  A refusal is the
        safe-point wait the operator describes, and it is recorded as such.
        """
        from .device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease

        moment = now or datetime.now(timezone.utc)
        lease = DeviceLease(self.root)
        target = self.validation_lease_target()
        if target is None:
            # Nothing is waiting.  If a validation still holds the device, give it back
            # rather than leaving gameplay frozen for a version nobody has to examine.
            holder = lease.holder(now=moment)
            if holder is not None and holder.owner == OWNER_DEVELOPMENT_VALIDATION:
                lease.release(result="NO_WAITING_VERSION",
                              reason="no LIVE_VERIFY_PENDING record left to examine", now=moment)
                self.ledger.append({
                    "source": "queue", "event": "validation_lease_released",
                    "key": target.key if target else "",
                    "reason": "no version is waiting for its examination",
                })
            return ""
        holder = lease.holder(now=moment)
        if holder is not None and holder.owner == OWNER_DEVELOPMENT_VALIDATION:
            return ""  # already ours; the runtime is standing down for it
        consumer = self.validation_lease_consumer(now=moment)
        if not consumer:
            existing = self.ledger.snapshot().get(target.key)
            if existing is None or not any(
                "validation lease deferred" in note for note in existing.notes
            ):
                self.ledger.append({
                    "source": "queue", "event": "validation_lease_deferred",
                    "key": target.key,
                    "reason": (
                        "no live consumer for the device (no fresh panel heartbeat): asking now "
                        "would make V2 stand down with nobody to drive the validation"
                    ),
                })
            return ""
        record, reason = lease.request(
            capability_id=target.capability or target.skill,
            job_id=target.job_id,
            trace_id=target.key,
            reason=(
                f"examine the version job {target.job_id or '-'} produced for "
                f"{target.capability or target.skill}"
            ),
            now=moment,
        )
        self.ledger.append({
            "source": "queue", "event": "validation_lease_requested",
            "key": target.key,
            "job_id": target.job_id,
            "capability": target.capability,
            "goal": target.goal,
            "acquired": record is not None,
            "reason": reason,
            "consumer": consumer,
        })
        return target.key

    def release_validation_lease(self, *, result: str, reason: str = "",
                                 expect_key: str = "", now: datetime | None = None) -> bool:
        """Give the device back after an examination, whatever it concluded.

        §15: PASS / FAIL / BLOCKED all release.  Called from the settle path and from the
        panel's worker ``finally``, so a validation that dies still returns the device.
        ``expect_key`` refuses to release a lease that belongs to a *different* record --
        otherwise the first record to settle would hand back another one's device.
        """
        from .device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease

        moment = now or datetime.now(timezone.utc)
        lease = DeviceLease(self.root)
        holder = lease.holder(now=moment)
        if holder is None or holder.owner != OWNER_DEVELOPMENT_VALIDATION:
            return False
        if expect_key and holder.trace_id and holder.trace_id != expect_key:
            return False
        released = lease.release(result=result, reason=reason, now=moment)
        if released:
            self.ledger.append({
                "source": "queue", "event": "validation_lease_released",
                "key": holder.trace_id or "",
                "job_id": holder.job_id,
                "result": result,
                "reason": reason,
            })
        return released

    def _device_holder(self) -> str:
        """Who owns the one device right now, if anyone.

        Read through the lease module rather than a second bookkeeping file: the
        operator's Single Device / Single UI Owner rule already has exactly one lock.
        The owner name is what the gate reports; an expired lease is not a holder.
        """
        try:
            from .device_lease import DeviceLease

            record = DeviceLease(self.root).holder()
            return str(getattr(record, "owner", "") or "") if record is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    def _runtime_view(self) -> dict[str, Any]:
        """The runtime's own snapshot, for the gate's REALTIME check."""
        try:
            payload = json.loads(
                (Path(self.root) / "learning/runtime_snapshot.json").read_text(encoding="utf-8")
            )
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _drain(
        self,
        *,
        stop_reason: str,
        failures: Sequence[Mapping[str, Any]],
        deferrals: Sequence[Mapping[str, Any]],
        now: datetime | None,
        reconcile: bool,
    ) -> RunObservation:
        moment = now or datetime.now(timezone.utc)
        errors: list[str] = []
        reconciled: list[str] = []
        submitted: list[str] = []
        skipped: list[tuple[str, str]] = []
        released: list[str] = []
        handled: set[str] = set()

        if reconcile:
            try:
                reconciled, reconcile_errors = self.reconcile(now=moment)
                errors.extend(reconcile_errors)
            except Exception as exc:  # noqa: BLE001 - a hook must not break the loop
                errors.append(f"reconcile failed: {type(exc).__name__}: {exc}")

        try:
            candidates = candidates_from_run(
                stop_reason=stop_reason,
                failures=failures,
                snapshot=self.ledger.snapshot(),
                policy=self.policy,
                now=moment,
                unimplemented=unimplemented_skills(self.root),
                root=self.root,
                deferrals=deferrals,
            )
            for candidate in candidates:
                # Re-fold each time: a submission inside this loop changes the
                # concurrency answer for the next candidate.
                handled.add(candidate.signature.key)
                merged = self._merge_into_active_job(candidate)
                if merged:
                    skipped.append((
                        candidate.signature.key,
                        f"MERGED_INTO_ACTIVE_JOB: {merged} (evidence appended, no second job)",
                    ))
                    continue
                dispatch = decide(candidate, self.ledger.snapshot(), self.policy, now=moment)
                if not dispatch.should_submit:
                    skipped.append((candidate.signature.key, f"{dispatch.action}: {dispatch.reason}"))
                    self._record(candidate, dispatch)
                    continue
                job_id = self._submit(candidate, dispatch)
                if job_id:
                    submitted.append(job_id)
                else:
                    skipped.append((candidate.signature.key, "queued: gateway unavailable"))
                    self._record(candidate, dispatch)

            # The consumer for records that were created but never dispatched.
            #
            # A candidate exists only for the run that produced it, so a record made
            # while the one concurrency slot was busy had nothing to re-offer it later.
            # Measured 2026-09-18: DISPATCH_GATHER_MARCH|SEMANTIC_TARGET_NOT_VERIFIED|
            # DISPATCH_MARCH and DISMISS_REAL_MONEY_OFFER|POPUP_CLOSE_NOT_PROVEN|
            # DISMISS_REAL_MONEY_OFFER both carry `dispatch: CONCURRENCY_WAIT` naming
            # job a7ce58f0, and both sat NEW for 54 minutes after that job finished,
            # with the gateway healthy and the operator watching.  "Created" has to
            # mean "will reach the bridge", not "was noticed once".
            for record in self.pending(snapshot=self.ledger.snapshot()):
                if record.key in handled:
                    continue
                handled.add(record.key)
                proven = self._proven_since(record)
                if proven:
                    # The device already climbed this wall.  Measured 2026-09-18 on the two
                    # records the operator reported stuck: DISPATCH_MARCH had four
                    # verifier-passing episodes after its record was created (two of them
                    # on the current tree, minutes earlier) and the money-offer skill two.
                    # Dispatching a development agent to fix "the dispatch button cannot be
                    # found" while the button has been found four times would be
                    # manufacturing work, which the operator forbids -- so the record is
                    # released, with the episodes named, and the decision is visible
                    # instead of the record silently ageing.
                    self._release(record, proven)
                    released.append(record.key)
                    continue
                candidate = self._candidate_from_record(record)
                dispatch = decide(candidate, self.ledger.snapshot(), self.policy, now=moment)
                if not dispatch.should_submit:
                    skipped.append((record.key, f"{dispatch.action}: {dispatch.reason}"))
                    continue
                job_id = self._submit(candidate, dispatch, pending_since=record.first_seen)
                if job_id:
                    submitted.append(job_id)
                else:
                    skipped.append((record.key, "queued: gateway unavailable"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"dispatch failed: {type(exc).__name__}: {exc}")

        pending = self.reload_signal.pending()
        # After settling, ask for the device for whichever version is now waiting to be
        # examined -- or hand it back when nothing is.  Both entry points come through
        # here, so the AUTO hook and the panel's clock service it identically.
        lease_note = ""
        try:
            lease_note = self.service_validation_lease(now=moment)
        except Exception as exc:  # noqa: BLE001 - the lease must never break the loop
            errors.append(f"validation lease: {type(exc).__name__}: {exc}")
        return RunObservation(
            reconciled=tuple(reconciled),
            submitted=tuple(submitted),
            skipped=tuple(skipped),
            released=tuple(released),
            errors=tuple(errors),
            reload_requested_for=pending.job_id if pending else "",
            lease_requested_for=lease_note,
        )

    def _flat_episode_note(self, record: EscalationRecord, before: RepoRevision) -> str:
        """Why verifier-passing episodes were rejected for a "no progress" signature.

        Without this the ledger says ``TEST_PASS`` next to six episodes and reads as
        "nearly there", when the six are the failure being measured again.  Named
        explicitly because that exact confusion produced a wrong ``LIVE_VERIFIED`` on
        2026-09-18 and the operator should never have to guess what the bar was.
        """
        if str(record.failure_type).upper() not in PROOF_IS_GOAL_PROGRESS:
            return ""
        flat = new_live_episodes(
            record.capability or record.skill, skill=record.skill,
            since=record.submitted_at, root=self.root,
            version_changed_from=before.token,
        )
        if not flat:
            return ""
        return (
            f" NOTE: {len(flat)} verifier-passing production episode(s) exist on a tree "
            f"that differs from dispatch time, but this signature is "
            f"{record.failure_type} -- its proof is the goal actually moving, and none of "
            f"them shows that -- so they do not count and LIVE_VERIFIED is not granted."
        )

    def _proven_since(self, record: EscalationRecord) -> tuple[dict[str, Any], ...]:
        """Production episodes that prove this record's capability since it was created.

        The same bar reconciliation uses to grant LIVE_VERIFIED, asked of a record that
        never reached a job: "is there a verifier-passing production episode of this skill
        after this moment".  Without it a record whose wall the device climbed itself
        stayed NEW forever, which reads as a backlog that is not one.
        """
        if record.first_seen is None:
            return ()
        return new_live_episodes(
            record.capability or record.skill,
            skill=record.skill,
            since=record.first_seen,
            root=self.root,
            # The same bar reconciliation uses, including the progress requirement:
            # releasing a record is the same claim as verifying it, so it cannot be
            # granted on evidence that would fail the other path.
            require_goal_progress=str(record.failure_type).upper() in PROOF_IS_GOAL_PROGRESS,
        )

    def _release(self, record: EscalationRecord, episodes: tuple[dict[str, Any], ...]) -> None:
        """Settle a record the device proved itself, naming the episodes."""
        latest = episodes[-1]
        try:
            self.ledger.append({
                "source": "queue",
                "event": "reconciled",
                "key": record.key,
                "job_id": "",
                # DONE is what makes the fold settle it; the outcome says what the
                # *capability* is, not what a job achieved.
                "job_state": DONE,
                "outcome": LIVE_VERIFIED,
                "released_by": "self_proven",
                "explanation": (
                    f"released without a job: {len(episodes)} verifier-passing production "
                    f"episode(s) of {record.skill} were recorded after this escalation was "
                    f"created, so the device proved the capability itself (latest "
                    f"{latest.get('recorded_at')}, revision {latest.get('repo_revision') or 'unknown'})"
                ),
                "verified_episodes": len(episodes),
                "live_verify_episode": str(latest.get("episode_id") or ""),
                "live_verify_revision": str(latest.get("repo_revision") or ""),
                # No job ran, so nothing here may claim a job's credit or spend its budget.
                "code_changed": False,
                "live_improvement": False,
                "repair_used": False,
            })
        except Exception:  # noqa: BLE001 - audit must not break the hook
            pass

    # -- ledger helpers ---------------------------------------------------

    def pending(self, *, snapshot: EscalationSnapshot | None = None) -> tuple[EscalationRecord, ...]:
        """Records that were created and never reached the bridge, oldest first.

        ``NEW`` means "created, never dispatched"; ``QUEUED`` means "decided, and the
        gateway was unreachable" -- both are work the queue owes the operator, and both
        are invisible to a pipeline that only looks at the current run.

        Records whose condition is not one of the five are left out on purpose: they
        were refused on creation for a reason that has not changed, and re-offering them
        would write the same refusal on every cycle.
        """
        records = (snapshot or self.ledger.snapshot()).records.values()
        waiting = [
            record for record in records
            if record.state in (NEW, QUEUED) and record.condition in AUTO_ESCALATION_CONDITIONS
        ]
        waiting.sort(key=lambda record: (record.first_seen is None, record.first_seen))
        return tuple(waiting)

    def _candidate_from_record(self, record: EscalationRecord) -> EscalationCandidate:
        """Re-offer an existing record as a candidate for the same throttle."""
        created = record.first_seen.isoformat() if record.first_seen else "unknown"
        why = f"; it was first refused with: {record.dispatch_reason}" if record.dispatch_reason else ""
        return EscalationCandidate(
            signature=FailureSignature(
                capability=record.capability or record.skill,
                failure_type=record.failure_type,
                skill=record.skill,
            ),
            condition=record.condition,
            reason=(
                f"pending escalation re-offered: created {created}, state {record.state}, "
                f"never reached the bridge{why}"
            ),
            goal=record.goal,
            evidence=record.evidence,
        )

    def _record(self, candidate: EscalationCandidate, dispatch: Dispatch, *, origin: str = "queue") -> None:
        """One row the first time a key is seen, even when nothing is dispatched.

        Without this the ledger would only contain escalations that happened, and
        "why was this never escalated" would be unanswerable -- the same
        invisibility the backend-axis work fixed one layer down.
        """
        try:
            if self.ledger.snapshot().get(candidate.signature.key) is not None:
                return
            self.ledger.append({
                "source": "queue",
                "event": "escalation_created",
                "origin": origin,
                "key": candidate.signature.key,
                "capability": candidate.signature.capability,
                "failure_type": candidate.signature.failure_type,
                "skill": candidate.signature.skill,
                "condition": candidate.condition,
                "goal": candidate.goal,
                "evidence": list(candidate.evidence),
                "dispatch": dispatch.action,
                "dispatch_reason": dispatch.reason,
            })
        except Exception:  # noqa: BLE001 - audit must not break the hook
            pass

    def _submit(
        self,
        candidate: EscalationCandidate,
        dispatch: Dispatch,
        *,
        pending_since: datetime | None = None,
        origin: str = "queue",
        extra_notes: str = "",
    ) -> str:
        """Send one candidate.  ``pending_since`` records how long it waited for a slot.

        That number is the whole point of the consumer: "created but never dispatched"
        was invisible in the ledger, so a record could sit NEW for an hour while every
        row made it look like nothing was wrong.
        """
        availability = self.bridge.is_available()
        revision = repo_revision(self.root)
        self._record(candidate, dispatch, origin=origin)

        if not availability:
            # One queued row per transition, not one per cycle: the loop retries
            # every run, and rewriting the same line 200 times a day would bury the
            # events that matter in the events that do not.
            existing = self.ledger.snapshot().get(candidate.signature.key)
            if existing is None or existing.state != QUEUED:
                self.ledger.append({
                    "source": "queue",
                    "event": "queued",
                    "key": candidate.signature.key,
                    "reason": f"gateway {availability.reason}",
                })
            return ""

        context = self._build_request(
            candidate.signature.capability or candidate.signature.skill,
            candidate.condition,
            candidate.reason,
            goal=candidate.goal,
            skill=candidate.signature.skill,
            world_state=candidate.world_state or None,
            evidence_paths=candidate.evidence,
            notes=(
                f"Escalation key: {candidate.signature.key}\n"
                f"Model rung: {dispatch.model} -- {dispatch.model_reason}"
                + (f"\n\n{extra_notes}" if extra_notes else "")
            ),
            timebox_minutes=self.policy.job_timebox_minutes,
            root=self.root,
        )
        submission = self.bridge.submit(
            context,
            name=f"V2 escalation: {candidate.signature.capability} [{candidate.condition}]",
            model=dispatch.model,
        )
        self.ledger.append({
            "source": "queue",
            "event": "submitted",
            "key": candidate.signature.key,
            "job_id": submission.job_id,
            "attempt": dispatch.attempt,
            "model": dispatch.model,
            "model_reason": dispatch.model_reason,
            "escalated_from": dispatch.escalated_from,
            "task_type": dispatch.task_type,
            "condition": candidate.condition,
            "capability": candidate.signature.capability,
            "skill": candidate.signature.skill,
            "repo_head": revision.head,
            "repo_dirty": revision.dirty,
            # The jobs API returned no usage field on 2026-09-17 (measured: the
            # job payload carries id/state/output and no tokens or cost), so these
            # stay null with the reason attached rather than being estimated.
            "tokens": None,
            "cost": None,
            "usage_note": "jobs API exposes output.result only; no token/cost field present",
        })
        if pending_since is not None:
            waited = (datetime.now(timezone.utc) - pending_since).total_seconds() / 60.0
            self.ledger.append({
                "source": "queue",
                "event": "pending_consumed",
                "key": candidate.signature.key,
                "job_id": submission.job_id,
                "pending_minutes": round(waited, 1),
                "reason": "created but never dispatched until the consumer re-offered it",
            })
        return submission.job_id

    # -- reconciliation ---------------------------------------------------

    def _reclaim_expired_slot(
        self,
        record: EscalationRecord,
        waiting: Sequence[EscalationRecord],
        moment: datetime,
        errors: list[str],
    ) -> str:
        """Cancel a job that outlived its timebox *while others wait for the slot*.

        Both conditions are required, and each is one half of an operator rule.

        The timebox is what the work order itself told the agent it had ("timebox:
        45 minutes"), so a job past it is off-contract rather than merely slow.

        The queue must have something waiting behind it.  Without that half this
        would be a timer that kills a productive agent for being thorough, and it
        would contradict the standing instruction never to interrupt a valid
        WorkBuddy write operation.  With it, the only job that loses the slot is
        the one actually starving the queue -- which is the stall the operator
        reported: two records sat unfilled behind a single job.

        Cancelling destroys nothing.  ``POST /jobs/{id}/stop`` stops a process; the
        commits the agent already made are in the working tree and stay there, and
        the reconciler measures the tree rather than the agent's exit code.

        A cancel that fails keeps the honest state (still WORKING, error recorded)
        rather than pretending the slot is free.
        """
        if not waiting or record.submitted_at is None:
            return ""
        age_minutes = (moment - record.submitted_at).total_seconds() / 60.0
        box = self.policy.job_timebox_minutes
        if age_minutes < box:
            return ""
        try:
            self.bridge.cancel(record.job_id)
        except Exception as exc:  # noqa: BLE001 - a failed cancel must not free the slot on paper
            errors.append(f"{record.key}: cancel({record.job_id}) failed: {exc}")
            return ""
        return (
            f"job exceeded its {box}-minute timebox ({age_minutes:.0f} min) while "
            f"{len(waiting)} record(s) waited for the single concurrency slot; "
            f"cancelled to free it"
        )

    def reconcile(self, *, now: datetime | None = None) -> tuple[list[str], list[str]]:
        """Poll every in-flight job and measure what it achieved.

        A job the gateway no longer knows about becomes ``FAILED`` rather than
        staying ``WORKING`` forever: a gateway restart must not leave a row that
        permanently occupies the concurrency slot.

        The same slot is why a job past its timebox is cancelled -- but only when
        records are waiting behind it, so a thorough agent with an empty queue is
        left alone.  See :meth:`_reclaim_expired_slot`.
        """
        moment = now or datetime.now(timezone.utc)
        snapshot = self.ledger.snapshot()
        settled: list[str] = []
        errors: list[str] = []
        # Who is waiting for the slot.  Read once, before the loop, because that is
        # the question the reclaim below answers: a job over its timebox only loses
        # the slot when somebody is actually behind it.
        waiting = self.pending(snapshot=snapshot)

        for record in snapshot.records.values():
            if record.state not in (SUBMITTED, WORKING) or not record.job_id:
                continue
            try:
                status = self.bridge.status(record.job_id)
            except JobLost as exc:
                # §六, finally with a branch of its own: the gateway is up and says this job
                # does not exist.  Recording it as "an error" (which is what the generic
                # handler below did) left the record SUBMITTED/WORKING forever, holding the
                # one slot, so no other escalation could be dispatched and the pump reported
                # the same 404 as an error every thirty seconds.  Marked lost so the fold
                # settles it and the slot is freed; the capability is then re-offered from
                # the budget rather than silently duplicated.
                self.ledger.append({
                    "event": "job_lost",
                    "key": record.key,
                    "job_id": record.job_id,
                    "state": FAILED,
                    "reason": str(exc)[:300],
                })
                settled.append(f"{record.key}: JOB_LOST（网关已确认该 Job 不存在，"
                               "按已完成结算并释放并发槽，不重复建同能力 Job）")
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{record.key}: status({record.job_id}) failed: {exc}")
                continue

            reclaimed = ""
            if not status.terminal:
                reclaimed = self._reclaim_expired_slot(record, waiting, moment, errors)

            live_state = (
                STOPPED if reclaimed
                else status.verdict if status.verdict in (WORKING, DONE, FAILED, STOPPED)
                else (status.gateway_state or "UNKNOWN").upper()
            )
            self.ledger.append({
                "event": "job_state",
                "key": record.key,
                "job_id": record.job_id,
                "state": live_state,
                "job_detail": reclaimed or status.detail,
            })
            if not (status.terminal or reclaimed):
                continue

            before = RepoRevision(
                head=str(_submitted(snapshot, record.key, "repo_head") or ""),
                dirty=int(_submitted(snapshot, record.key, "repo_dirty") or 0),
                ok=bool(_submitted(snapshot, record.key, "repo_head")),
            )
            after = repo_revision(self.root)
            wiring = self._wiring_problems()
            outcome, explanation, episodes = reconcile_outcome(
                capability=record.capability,
                skill=record.skill,
                submitted_at=record.submitted_at,
                job_verdict=STOPPED if reclaimed else status.verdict,
                # §4: a trace with a job id is a *developed* trace, and may not be certified
                # by a production episode that merely proves the capability still works.
                from_development_job=bool(record.job_id),
                before=before,
                after=after,
                wiring_problems=wiring,
                agent_report=status.result,
                root=self.root,
                failure_type=record.failure_type,
                settled_at=_from_millis(status.first_terminal_at),
            )
            if reclaimed:
                explanation = f"cancelled: {reclaimed}. " + explanation
            if outcome != LIVE_VERIFIED:
                explanation += self._flat_episode_note(record, before)
            if outcome == VERSION_ACTIVATION_PENDING:
                # Not settled: the version exists but nothing has loaded it, so the
                # honest state is "waiting for its own activation", and the next pass
                # re-measures.  It is deliberately excluded from ACTIVE_STATES, so it
                # does not hold the agent slot while it waits.
                self._note_activation_pending(
                    record, explanation,
                    version_since=_from_millis(status.first_terminal_at),
                    agent_report=status.result,
                )
                continue
            self._settle(
                snapshot=snapshot, record=record, outcome=outcome, explanation=explanation,
                episodes=episodes, before=before, after=after, wiring=wiring,
                moment=moment, detail=status.detail,
                terminal_verdict=DONE if status.verdict == "DONE" else FAILED,
                duration=_duration(record.submitted_at, status.first_terminal_at),
                settled=settled, errors=errors,
            )

        # The activation rung, before anything asks whether the capability works: a version
        # that has not been loaded cannot have been verified, and the operator's §四 is
        # explicit that this must be recoverable after a restart rather than re-triggered by
        # hand -- so it is re-derived from the ledger and the episode stream on every pass.
        activated = self._activate_pending_versions(snapshot, moment)
        just_activated = {key for key, _ in activated}
        for key, message in activated:
            settled.append(message)

        # §一: the rung after activation, requested by the queue itself.  Runs on the folded
        # snapshot, so a record activated by the lines above is picked up on the *next* pass --
        # one rung per pass, which also keeps the ledger readable as a ladder rather than as a
        # burst.  The pump's cadence is thirty seconds, so the delay is one tick.
        for key, message in self._request_validation(snapshot, moment):
            settled.append(message)

        # §5-§10: settle whatever examinations have finished, then look for production reuse.
        # Runs after the request phase so a record activated and requested in this pass has its
        # examination settled on the next one -- one rung per pass, which keeps the ledger
        # readable as a ladder rather than as a burst.
        for message in self.settle_validations(moment):
            settled.append(message)

        # Records whose job is done and whose version has not been exercised yet.  This
        # is the rung the operator added on 2026-09-18 (VERSION_ACTIVATION_PENDING ->
        # VERSION_ACTIVE -> LIVE_VERIFY_PENDING), re-measured on every pass because the
        # evidence that closes it is an episode, and episodes arrive on their own.
        for record in snapshot.records.values():
            if record.state != LIVE_VERIFY_PENDING or not record.job_id:
                continue
            if record.key in just_activated:
                # This pass has just moved it to VERSION_ACTIVE.  ``snapshot`` was folded
                # before that event was appended, so without this guard the record would be
                # re-measured against a state it no longer holds -- and the pass would report
                # both "the version became active" and "the version has not been exercised".
                continue
            before = RepoRevision(
                head=str(_submitted(snapshot, record.key, "repo_head") or ""),
                dirty=int(_submitted(snapshot, record.key, "repo_dirty") or 0),
                ok=bool(_submitted(snapshot, record.key, "repo_head")),
            )
            after = repo_revision(self.root)
            wiring = self._wiring_problems()
            outcome, explanation, episodes = reconcile_outcome(
                capability=record.capability, skill=record.skill,
                submitted_at=record.submitted_at, job_verdict=DONE,
                # Same rule on the re-measure path: a version that has become active still has
                # to be examined, not certified by whatever production episode happens to exist.
                from_development_job=bool(record.job_id),
                before=before, after=after, wiring_problems=wiring,
                agent_report=record.agent_report, root=self.root,
                failure_type=record.failure_type,
                # The gateway's terminal time, carried on the record, not "now": the
                # observation time would put every episode that closed this rung on the
                # wrong side of the boundary.
                settled_at=record.version_since,
            )
            if outcome == VERSION_ACTIVATION_PENDING:
                continue
            explanation = "re-measured after the version became active. " + explanation
            self._settle(
                snapshot=snapshot, record=record, outcome=outcome, explanation=explanation,
                episodes=episodes, before=before, after=after, wiring=wiring,
                moment=moment, detail="measured after the new version ran",
                terminal_verdict=DONE,
                # ``settled_at`` here is a datetime from the fold, not the gateway's
                # millisecond integer, so the duration is a subtraction rather than
                # ``_duration`` -- passing one where the other belongs is the mistake
                # this round already made once.
                duration=(round((record.settled_at - record.submitted_at).total_seconds(), 1)
                          if record.settled_at and record.submitted_at else None),
                settled=settled, errors=errors,
            )

        return settled, errors

    def _note_activation_pending(
        self,
        record: EscalationRecord,
        explanation: str,
        *,
        version_since: datetime | None,
        agent_report: str,
    ) -> None:
        """Record that the tree changed but nothing has loaded it yet.

        The job's own terminal time is written here rather than recomputed later: it is
        the boundary the re-measure has to use, and the only place it is known exactly
        is the moment the gateway first reported it.
        """
        try:
            self.ledger.append({
                "source": "queue",
                "event": "live_verify_pending",
                "key": record.key,
                "job_id": record.job_id,
                "capability": record.capability,
                "failure_signature": record.key,
                "skill": record.skill,
                "reason": explanation[:400],
                "outcome": VERSION_ACTIVATION_PENDING,
                "version_since": version_since.isoformat() if version_since else "",
                "agent_report": (agent_report or "")[:400],
            })
        except Exception:  # noqa: BLE001 - audit must not break the hook
            pass

    def _activate_pending_versions(
        self, snapshot: EscalationSnapshot, moment: datetime,
    ) -> list[tuple[str, str]]:
        """Append ``version_active`` once a fresh episode proves the new version is loaded.

        Returns ``(key, message)`` pairs, so the caller can both report the rung and stop the
        same pass from re-measuring a record it has just moved on.

        Operator §二, and every part of it is load-bearing:

            job settled  +  after_version known  +  a real episode  +
            episode.repo_revision == after_version

        *The job must be settled*, because before that the tree is still being edited and an
        episode is a statement about a version that no longer exists.  *A revision must have
        changed*, because otherwise there is no new version to activate.  *The episode must
        be real* -- ``new_live_episodes`` already refuses rows without ``recorded_at``,
        ``verifier_ok`` and evidence.  And *the revision must match exactly*: every cycle is a
        fresh process that imports the package from disk, so an episode whose
        ``repo_revision`` equals ``after_version`` is the machine saying "this is what ran",
        where git HEAD only says what is on the disk.

        Forbidden, and this is the point: file changed, agent said DONE, and tests passed are
        all facts about the *tree*.  None of them is evidence that anything loaded it.
        """
        activated: list[tuple[str, str]] = []
        for record in list(snapshot.records.values()):
            if record.state != LIVE_VERIFY_PENDING:
                continue
            if str(record.outcome) != VERSION_ACTIVATION_PENDING:
                continue
            if not (record.after_version and record.settled_at):
                continue
            try:
                episodes = new_live_episodes(
                    record.capability, skill=record.skill, since=record.settled_at,
                    root=self.root, after=record.settled_at,
                    version_changed_from=record.before_version,
                )
            except Exception:  # noqa: BLE001 - a measurement failure is a skip, not a crash
                continue
            match = next(
                (row for row in episodes
                 if str(row.get("repo_revision") or "") == record.after_version),
                None,
            )
            if match is None:
                continue
            episode_id = str(match.get("episode_id") or "")
            self.ledger.append({
                "event": "version_active",
                "key": record.key,
                "job_id": record.job_id,
                "capability": record.capability,
                "skill": record.skill,
                "failure_type": record.failure_type,
                "goal": record.goal,
                "origin": record.origin,
                "before_version": record.before_version,
                "after_version": record.after_version,
                "active_version": record.after_version,
                "activation_episode_id": episode_id,
                "activated_at": str(match.get("recorded_at") or ""),
                "recorded_at": moment.isoformat(),
            })
            activated.append((record.key, (
                f"{record.capability}: VERSION_ACTIVE（after_version "
                f"{record.after_version[:12]} 首次被真实 Episode {episode_id} 加载）"
            )))
        return activated

    def _request_validation(
        self, snapshot: EscalationSnapshot, moment: datetime,
    ) -> list[tuple[str, str]]:
        """Append ``live_verify_pending`` for a version that is active and still owes proof.

        Operator §一: no click, no second trigger.  Once a version is provably loaded, the next
        thing owed is real-device examination, and the queue says so itself.

        The outcome recorded on this event is ``VERSION_ACTIVE`` -- the rung that has actually
        been achieved -- which is also what makes the pass idempotent: the activation detector
        only fires while the outcome is still ``VERSION_ACTIVATION_PENDING``, so a record whose
        outcome has moved on cannot be activated twice, and this cannot re-request a validation
        that is already pending.

        The event carries the whole version context (§一's list) so the validation worker can
        be handed the trace without re-deriving anything: which job, which capability, and
        which version it is expected to be running.
        """
        requested: list[tuple[str, str]] = []
        for record in list(snapshot.records.values()):
            if record.state != VERSION_ACTIVE:
                continue
            if str(record.outcome) == VERSION_ACTIVE:
                continue  # already requested; this pass is a no-op for it
            if not record.after_version:
                continue
            if record.active_version and record.active_version != record.after_version:
                # The version that ran is not the version under test.  Asking for validation
                # here would examine the wrong code and then credit the right capability.
                continue
            self.ledger.append({
                "event": "live_verify_pending",
                "key": record.key,
                "job_id": record.job_id,
                "capability": record.capability,
                "skill": record.skill,
                "failure_type": record.failure_type,
                "goal": record.goal,
                "origin": record.origin,
                "outcome": VERSION_ACTIVE,
                "before_version": record.before_version,
                "after_version": record.after_version,
                "active_version": record.active_version or record.after_version,
                "activation_episode_id": record.activation_episode_id,
                "requested_at": moment.isoformat(),
                "reason": "新版本已被真实运行加载，欠一次真机校准（§一自动请求，无需点击）",
                "recorded_at": moment.isoformat(),
            })
            requested.append((record.key, (
                f"{record.capability}: 已自动请求真机校准"
                f"（after_version {record.after_version[:12]}，无人工点击）"
            )))
        return requested

    def _device_returned(self) -> bool:
        """Is the device back in normal play's hands?  Asked of the lease file, never assumed.

        Section 8 hangs on this: a capability may only be recorded as re-joined once nothing is
        holding the device for its examination.  An unreadable lease is treated as "not
        returned", because the failure mode of guessing wrong here is a claim that the scheduler
        has resumed work it is in fact still holding off.
        """
        try:
            from .device_lease import DeviceLease

            return not str(DeviceLease(self.root).holder() or "").strip()
        except Exception:  # noqa: BLE001
            return False

    def _read_episodes(self) -> list[dict[str, Any]]:
        """The episode stream as rows.  Read whole: the gates need mode, trace and version."""
        path = self.root / "learning/episodes.jsonl"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    def settle_validations(self, moment: datetime | None = None) -> list[str]:
        """Turn each finished examination into its rung, then look for production reuse.

        Operator §5-§10, driven from the ledger rather than from the worker's exit code: the
        worker says only that a process ended, and what that process *achieved* is a question
        about the episodes it wrote.  Reading them here also makes the driver restart-proof --
        a GUI that died mid-examination re-derives the same answer from the same rows.

        Two phases, in order, because they answer different questions:

        1. a record waiting for its examination gets ``live_tried``, ``live_verified`` or a
           refusal named after what was actually wrong;
        2. a capability that has re-joined normal play gets ``production_reuse`` -- and only
           from a *production* episode, which is the one thing a validation episode can never
           stand in for.
        """
        now = moment or datetime.now(timezone.utc)
        events: list[str] = []
        snapshot = self.ledger.snapshot()
        episodes = self._read_episodes()

        for record in list(snapshot.records.values()):
            if record.state != LIVE_VERIFY_PENDING:
                continue
            if str(record.outcome) != VERSION_ACTIVE:
                # Not yet handed to an examination; §一's driver is what requests that.
                continue
            outcome, why, episode = validation_settlement(
                trace_key=record.key, job_id=record.job_id, capability=record.capability,
                skill=record.skill, after_version=record.after_version,
                failure_type=record.failure_type, episodes=episodes,
            )
            episode_id = str(episode.get("episode_id") or "")
            if outcome == LIVE_VERIFIED:
                self.ledger.append({
                    "event": "live_verified", "key": record.key, "job_id": record.job_id,
                    "capability": record.capability, "skill": record.skill,
                    "validation_episode_id": episode_id,
                    "after_version": record.after_version, "reason": why,
                    "verified_at": now.isoformat(), "recorded_at": now.isoformat(),
                })
                events.append(f"{record.capability}: LIVE_VERIFIED（episode {episode_id}）")
                # §8: the capability goes back into the production pool, and it is a separate
                # fact from having been verified.  Appended only once the device is *confirmed*
                # returned -- checked rather than assumed, because a rejoin recorded while an
                # examination still held the device would be a claim about scheduling that the
                # scheduler had not made.  The event carries no production_reuse_episode_id:
                # re-joining is not reuse, and the operator's §9 is explicit that conflating
                # them is what makes "the exam passed" read as "the capability works in play".
                if self._device_returned():
                    self.ledger.append({
                        "event": "rejoined", "key": record.key, "job_id": record.job_id,
                        "capability": record.capability, "skill": record.skill,
                        "after_version": record.after_version,
                        "rejoined_at": now.isoformat(), "recorded_at": now.isoformat(),
                    })
                    events.append(f"{record.capability}: REJOINED（已回到普通 Gameplay 池）")
                else:
                    events.append(
                        f"{record.capability}: 已验证但设备尚未归还，等租约释放后再 REJOINED"
                    )
            elif outcome == LIVE_TRIED:
                self.ledger.append({
                    "event": "live_tried", "key": record.key, "job_id": record.job_id,
                    "capability": record.capability, "skill": record.skill,
                    "validation_episode_id": episode_id, "after_version": record.after_version,
                    "verifier_ok": episode.get("verifier_ok"),
                    "goal_progress": episode.get("goal_progress"),
                    "failure_type": record.failure_type, "reason": why,
                    "recorded_at": now.isoformat(),
                })
                events.append(f"{record.capability}: LIVE_TRIED（episode {episode_id}）")
            else:
                self.ledger.append({
                    "event": "validation_result", "key": record.key, "job_id": record.job_id,
                    "capability": record.capability, "skill": record.skill,
                    "outcome": outcome, "validation_episode_id": episode_id,
                    "reason": why, "recorded_at": now.isoformat(),
                })
                events.append(f"{record.capability}: {outcome}")

        events.extend(self.detect_production_reuse(snapshot=self.ledger.snapshot(), moment=now))
        return events

    def detect_production_reuse(self, *, snapshot: EscalationSnapshot | None = None,
                                moment: datetime | None = None) -> list[str]:
        """Has a verified capability been used by ordinary play, on the version it was for?

        The last question in the chain, and the only one that distinguishes "WorkBuddy taught V2
        the capability" from "the capability passed its exam".  The evidence must be a
        *production* episode: same capability, the version the job produced, a passing verifier,
        and goal progress where the defect demands it.  A validation episode is excluded by mode
        on purpose -- the operator's §10 is that it can never count, however well it passed.
        """
        now = moment or datetime.now(timezone.utc)
        snapshot = snapshot or self.ledger.snapshot()
        episodes = self._read_episodes()
        events: list[str] = []

        for record in list(snapshot.records.values()):
            if record.state != REJOINED:
                continue
            if record.production_reuse_episode_id:
                continue
            expected = str(record.after_version or "")
            if not expected:
                continue
            needs_goal = str(record.failure_type).upper() in PROOF_IS_GOAL_PROGRESS
            for row in episodes:
                if str(row.get("execution_mode") or "PRODUCTION").upper() != "PRODUCTION":
                    continue
                if str(row.get("repo_revision") or "") != expected:
                    continue
                # §9: only an episode from *after* the capability re-joined.  A production
                # episode from before it is play that happened while the capability was still
                # being examined -- it may well have run the new version, but it is not evidence
                # that the capability is back in normal use, which is the thing being proved.
                if record.rejoined_at is not None:
                    recorded = _moment(row.get("recorded_at"))
                    if recorded is None or recorded <= record.rejoined_at:
                        continue
                # Accepts a real bool or its JSON spelling: this row may be read back from a
                # file written by an older producer, and a version of this check that insisted
                # on one spelling would silently stop finding reuse rather than failing loudly.
                if not _is_true(row.get("verifier_ok")):
                    continue
                if needs_goal and not _is_true(row.get("goal_progress")):
                    continue
                if not (str(row.get("before_screenshot") or "")
                        and str(row.get("after_screenshot") or "")):
                    continue
                capability = str(row.get("capability") or "")
                skill = str(row.get("skill") or "")
                if record.capability and capability != record.capability \
                        and skill != record.skill:
                    continue
                episode_id = str(row.get("episode_id") or "")
                self.ledger.append({
                    "event": "production_reuse", "key": record.key, "job_id": record.job_id,
                    "capability": record.capability, "skill": skill,
                    "production_reuse_episode_id": episode_id,
                    "after_version": expected,
                    "reused_at": str(row.get("recorded_at") or now.isoformat()),
                    "recorded_at": now.isoformat(),
                    "reason": "普通 PRODUCTION 模式在 after_version 上复用了该能力，非校准模式",
                })
                events.append(
                    f"{record.capability}: PRODUCTION_REUSE（episode {episode_id}）→ DONE")
                break
        return events

    def _settle(
        self, *, snapshot, record, outcome, explanation, episodes, before, after, wiring,
        moment, detail, terminal_verdict, duration, settled, errors,
    ) -> None:
        """Write the terminal outcome for one record, and everything that follows it.

        Extracted so the two measuring paths -- "the job just finished" and "the version
        it produced has now run" -- cannot drift apart on what settling means: the
        reconciled row, the repair budget, the model's own record and the reload signal.
        """
        code_changed = after.differs_from(before)
        self.ledger.append({
            "event": "reconciled",
            "key": record.key,
            "job_id": record.job_id,
            "job_state": terminal_verdict,
            "job_detail": detail,
            "outcome": outcome,
            "explanation": explanation,
            "code_changed": code_changed,
            "wiring_problems": wiring,
            "verified_episodes": len(episodes),
            "model": record.model,
            "duration_seconds": duration,
            "live_improvement": outcome == LIVE_VERIFIED,
            "repair_used": outcome != LIVE_VERIFIED,
            # The causal chain, so one row answers "what proved what" without
            # joining four files by hand: which capability and failure shape the
            # job was for, which tree it started and ended against, and which
            # production episode (if any) is the one that proves the new version
            # works.  ``live_verify_episode`` empty while ``verified_episodes`` is
            # non-zero is the RR-004 shape: episodes exist, none of them ran the
            # new version.
            "capability": record.capability,
            "failure_signature": record.key,
            "skill": record.skill,
            "before_version": before.head,
            "before_dirty": before.dirty,
            "after_version": after.head,
            "after_dirty": after.dirty,
            "live_verify_episode": str((episodes[-1] if episodes else {}).get("episode_id") or ""),
            "live_verify_revision": str((episodes[-1] if episodes else {}).get("repo_revision") or ""),
            "reload_id": str(_submitted(snapshot, record.key, "reload_id") or ""),
        })
        settled.append(record.key)

        if outcome != LIVE_VERIFIED and (record.repairs_used + 1) >= self.policy.repair_budget:
            until = moment + timedelta(minutes=self.policy.cooldown_minutes)
            self.ledger.append({
                "event": "blocked",
                "key": record.key,
                "reason": f"repair budget ({self.policy.repair_budget}) spent, outcome={outcome}",
            })
            self.ledger.append({
                "event": "cooldown_started",
                "key": record.key,
                "until": until.isoformat(),
                "reason": f"repair budget exhausted after {outcome}",
            })

        # One outcome row per finished job, in the router's own vocabulary.
        # "success" here means the job reached a terminal state and produced
        # something measurable; "live_improvement" is the only field that means
        # the capability got better in the game.
        try:
            self.model_stats.append(ModelOutcome(
                model=record.model,
                task_type=str(_submitted(snapshot, record.key, "task_type") or ""),
                duration=duration,
                # Cost is not obtainable: the jobs API exposes no usage field
                # (measured 2026-09-17), so it stays null with the reason rather
                # than an estimate the router might trust.
                cost=None,
                success=outcome not in (OUTCOME_BLOCKED,),
                live_improvement=outcome == LIVE_VERIFIED,
                retry_count=record.repairs_used,
                escalation_count=record.attempts,
                note="cost unavailable: jobs API exposes no usage field",
            ))
        except Exception:  # noqa: BLE001 - learning must never break reconciliation
            errors.append(f"{record.key}: could not record model outcome")

        # A version that has just been examined gives the device back -- PASS, FAIL or
        # BLOCKED alike, because a lease held past its examination is gameplay frozen
        # for no reason.  Placed before the knowledge hook so the device is free even if
        # the hook (which scans the catalog) takes a moment.
        if record.state == LIVE_VERIFY_PENDING:
            try:
                self.release_validation_lease(
                    result=outcome,
                    reason=f"{record.capability or record.skill or record.key}: {outcome}",
                    expect_key=record.key,
                    now=moment,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{record.key}: lease release failed: {type(exc).__name__}: {exc}")

        # The bootstrap completion hook (operator §15).  A preloaded capability that
        # just settled re-enters the loop *here*, whatever the outcome was, so
        # "完成一个 Capability 后不再等指令" is a code path and not a promise.  It runs
        # for bootstrap-origin records only: a runtime escalation already has the
        # runtime as its next step.
        if record.origin == "bootstrap" and record.capability:
            try:
                from .capability_bootstrap import KnowledgeBootstrapController

                summary = KnowledgeBootstrapController(self.root).completion_hook(
                    capability=record.capability,
                    outcome=outcome,
                    evidence=record.evidence,
                    agent_report=record.agent_report,
                    now=moment,
                )
                self.ledger.append({
                    "source": "queue",
                    "event": "knowledge_updated",
                    "key": record.key,
                    "capability": record.capability,
                    "outcome": outcome,
                    "summary": summary,
                })
            except Exception as exc:  # noqa: BLE001 - a hook must not break reconciliation
                errors.append(f"{record.key}: knowledge hook failed: {type(exc).__name__}: {exc}")

        if code_changed:
            request = self.reload_signal.request(
                record.job_id,
                f"{outcome} on {record.key}: the tree changed while the agent ran",
            )
            self.ledger.append({
                "event": "reload_required",
                "key": record.key,
                "job_id": record.job_id,
                "reason": request.reason,
                "requested_at": request.requested_at.isoformat(),
            })

    def _wiring_problems(self) -> int | None:
        """Run the fast wiring gate.  ``None`` when it could not be run.

        This is the only "did the tests pass" signal the reconciler collects, and
        it is named honestly in the outcome explanation instead of being called a
        test run -- the full suite takes ~18 minutes and does not belong inside
        the AUTO hook.
        """
        import sys as _sys

        try:
            result = subprocess.run(
                [_sys.executable, "tools/check_wiring.py"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                **hidden_kwargs(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = f"{result.stdout or ''}\n{result.stderr or ''}"
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("problems:"):
                try:
                    return int(line.split(":", 1)[1].strip())
                except ValueError:
                    return None
        return None


def _submitted(snapshot: EscalationSnapshot, key: str, field_name: str) -> Any:
    record = snapshot.get(key)
    return None if record is None else getattr(record, field_name, None)


def _duration(submitted_at: datetime | None, first_terminal_ms: int | None) -> float | None:
    """Wall-clock job duration in seconds, or ``None`` when it cannot be known."""
    if submitted_at is None or not first_terminal_ms:
        return None
    return round(first_terminal_ms / 1000.0 - submitted_at.timestamp(), 1)
