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

import json
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
})

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

ALL_STATES: tuple[str, ...] = (NEW, QUEUED, SUBMITTED, WORKING, DONE, FAILED, BLOCKED, COOLDOWN)
# A key in one of these is "being worked on": no second job for it.
ACTIVE_STATES = frozenset({NEW, QUEUED, SUBMITTED, WORKING})
TERMINAL_STATES = frozenset({DONE, FAILED, BLOCKED, COOLDOWN})

# ------------------------------------------------------------------- outcomes

CODE_CHANGED = "CODE_CHANGED"
TEST_PASS = "TEST_PASS"
LIVE_VERIFIED = "LIVE_VERIFIED"
OUTCOME_BLOCKED = "BLOCKED"
NO_IMPROVEMENT = "NO_IMPROVEMENT"

ALL_OUTCOMES: tuple[str, ...] = (
    CODE_CHANGED, TEST_PASS, LIVE_VERIFIED, OUTCOME_BLOCKED, NO_IMPROVEMENT,
)

# --------------------------------------------------------------- model routing

# The operator's ladder, cheapest first.  Measured 2026-09-17: all four ids are
# accepted by ``POST /api/v1/jobs`` and ``deepseek-v4.1-flash`` was confirmed end
# to end (a dispatched job came back ``done`` with its token).
MODEL_FLASH = "deepseek-v4.1-flash"
MODEL_GLM_FLASH = "glm-5.3-flash"
MODEL_HY4 = "hy4-preview-f"
MODEL_STRONG = "deepseek-v4-pro"

MODEL_LADDER: tuple[str, ...] = (MODEL_FLASH, MODEL_GLM_FLASH, MODEL_HY4, MODEL_STRONG)

# What each rung is *for*.  Used to pick a starting rung from the shape of the
# problem instead of always paying for the top one.
MODEL_HINTS: dict[str, str] = {
    MODEL_FLASH: "default: any ordinary capability, UI or navigation defect",
    MODEL_GLM_FLASH: "long context -- huge logs, many files, cross-file analysis",
    MODEL_HY4: "vision-heavy -- image understanding, or a second opinion after "
               "the first two rungs failed",
    MODEL_STRONG: "last resort: architecture conflict, or a fix budget already spent",
}


def model_ladder_report() -> str:
    """The ladder, cheapest first, with what each rung is for."""
    lines = ["model ladder (cheapest first; a rung is only climbed after the one "
             "below it produced no live improvement):"]
    for index, model in enumerate(MODEL_LADDER, start=1):
        lines.append(f"  {index}. {model:20s} {MODEL_HINTS[model]}")
    return "\n".join(lines)


@dataclass(frozen=True)
class ModelChoice:
    """One routing decision, with the reason recorded next to it."""

    model: str
    reason: str
    escalated_from: str = ""

    @property
    def is_escalated(self) -> bool:
        return bool(self.escalated_from)


def select_model(
    attempt: int,
    *,
    needs: str = "",
    previous_model: str = "",
) -> ModelChoice:
    """Pick a rung.  ``attempt`` is 0 for the first honest try.

    Cheap first, and only climb when the rung below has been spent: the operator's
    rule is that a normal capability must not open with the most expensive model,
    and that escalation should be driven by real failure rather than taste.
    ``needs`` is a coarse hint (``"logs"`` / ``"vision"`` / ``"architecture"``)
    that can start higher for a problem whose shape is known up front.
    """
    if attempt <= 0:
        if needs == "logs":
            return ModelChoice(MODEL_GLM_FLASH, f"long-context problem stated up front ({MODEL_HINTS[MODEL_GLM_FLASH]})")
        if needs == "vision":
            return ModelChoice(MODEL_HY4, f"vision problem stated up front ({MODEL_HINTS[MODEL_HY4]})")
        return ModelChoice(MODEL_FLASH, f"first attempt; cheapest rung ({MODEL_HINTS[MODEL_FLASH]})")

    index = 0
    if previous_model in MODEL_LADDER:
        index = MODEL_LADDER.index(previous_model)
    step = min(index + 1, len(MODEL_LADDER) - 1)
    model = MODEL_LADDER[step]
    return ModelChoice(
        model=model,
        reason=(
            f"attempt {attempt + 1}: the rung below did not produce a live "
            f"improvement, so climbing to {model} ({MODEL_HINTS[model]})"
        ),
        escalated_from=previous_model or MODEL_LADDER[max(step - 1, 0)],
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
    state: str = NEW
    attempts: int = 0
    repairs_used: int = 0
    outcome: str = ""
    job_id: str = ""
    model: str = ""
    model_reason: str = ""
    escalated_from: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    submitted_at: datetime | None = None
    settled_at: datetime | None = None
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
            elif state in (DONE, FAILED) and record.state != COOLDOWN:
                # SUBMITTED -> DONE/FAILED; reconciliation may still overwrite
                # the *outcome*, but the lifecycle state is honest from here.
                record.state = state
                record.settled_at = _moment(event.get("recorded_at"))
            continue

        if kind == "reconciled":
            record = get(key)
            record.outcome = str(event.get("outcome", record.outcome))
            record.code_changed = bool(event.get("code_changed", record.code_changed))
            record.settled_at = _moment(event.get("recorded_at")) or record.settled_at
            job_state = str(event.get("job_state", ""))
            if job_state in (DONE, FAILED):
                record.state = job_state
            if event.get("repair_used"):
                record.repairs_used += 1
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

    @property
    def should_submit(self) -> bool:
        return self.action == SUBMIT


def decide(
    candidate: EscalationCandidate,
    snapshot: EscalationSnapshot,
    policy: EscalationPolicy,
    *,
    now: datetime | None = None,
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

    if record is not None and record.state in (SUBMITTED, WORKING, QUEUED, NEW):
        return Dispatch(
            DEDUP_SKIP,
            f"{candidate.signature.describe()} already has an active escalation "
            f"(state={record.state}, job={record.job_id or 'not submitted yet'})",
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
    choice = select_model(
        attempt,
        needs=_needs_hint(candidate),
        previous_model=record.model if record else "",
    )
    return Dispatch(
        SUBMIT,
        f"attempt {attempt + 1}/{policy.repair_budget + 1} for "
        f"{candidate.signature.describe()} ({candidate.condition})",
        model=choice.model,
        model_reason=choice.reason,
        escalated_from=choice.escalated_from,
        attempt=attempt,
    )


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
) -> tuple[str, str] | None:
    """Choose one of the five conditions, or ``None`` to leave it alone.

    ``None`` is a real answer and the common one: most failures are an ordinary
    step not landing, which AUTO retries by itself.  Only the shapes the operator
    listed get a development agent, and an unknown shape gets none -- guessing a
    condition would send an agent after the wrong problem.
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
    """
    moment = now or datetime.now(timezone.utc)

    if stop_reason in NON_ESCALATABLE_STOP_REASONS:
        return ()

    unimplemented_set = {str(x) for x in unimplemented}
    seen: set[str] = set()
    out: list[EscalationCandidate] = []

    failure_list = list(failures)
    if not failure_list and stop_reason in STOP_REASON_WALLS:
        condition, skill, reason = STOP_REASON_WALLS[stop_reason]
        return (
            EscalationCandidate(
                signature=FailureSignature(
                    capability=capability_for_skill(skill, root=root),
                    failure_type=stop_reason.upper(),
                    skill=skill,
                ),
                condition=condition,
                reason=reason,
            ),
        )

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

        verdict = classify_condition(
            signature,
            occurrences=occurrences,
            first_seen=first_seen if record else None,
            now=moment,
            policy=policy,
            unimplemented=skill in unimplemented_set,
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
    shot = failure.get("before_screenshot")
    return str(Path(str(shot)).parent) if shot else ""


# ---------------------------------------------------------------- reconciling


@dataclass(frozen=True)
class RepoRevision:
    """What the working tree looked like at one moment."""

    head: str = ""
    dirty: int = 0
    ok: bool = False

    def differs_from(self, other: "RepoRevision") -> bool:
        if not (self.ok and other.ok):
            return False
        return self.head != other.head or self.dirty != other.dirty


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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (result.stdout or "").strip()

    head = run(["rev-parse", "HEAD"])
    status = run(["status", "--porcelain"])
    if not head:
        return RepoRevision(ok=False)
    dirty = len([line for line in status.splitlines() if line.strip()])
    return RepoRevision(head=head, dirty=dirty, ok=True)


def new_live_episodes(
    capability: str,
    *,
    skill: str = "",
    since: datetime | None,
    root: Path | str | None = None,
    episodes_path: Path | str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Production episodes proving the capability after ``since``.

    Only ``recorded_at`` rows count (the project's rule: imported history is
    indistinguishable otherwise) and only ``verifier_ok`` rows count, and evidence
    paths must be present.  This is the gate that keeps ``LIVE_VERIFIED`` from
    being something an agent can claim.
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
        if skill and row.get("skill") != skill:
            continue
        if not skill and capability:
            if capability_for_skill(str(row.get("skill") or ""), root=base) != capability:
                continue
        if not (row.get("before_screenshot") and row.get("after_screenshot")):
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
    root: Path | str | None = None,
    episodes_path: Path | str | None = None,
) -> tuple[str, str, tuple[dict[str, Any], ...]]:
    """Decide what the job actually achieved, from local measurements only.

    Returns ``(outcome, explanation, evidence_episodes)``.  ``job_verdict`` is the
    gateway's word for the job (``DONE``/``FAILED``/``STOPPED``) and is used only
    to distinguish "the agent did nothing" from "the agent failed"; it is never
    treated as proof of a fixed capability.
    """
    episodes = new_live_episodes(capability, skill=skill, since=submitted_at,
                                root=root, episodes_path=episodes_path)
    if episodes:
        latest = episodes[-1]
        return (
            LIVE_VERIFIED,
            f"{len(episodes)} production episode(s) with verifier_ok after the job "
            f"(latest {latest.get('recorded_at')}), evidence "
            f"{Path(str(latest.get('before_screenshot'))).name}",
            episodes,
        )

    changed = before.differs_from(after)
    if changed and wiring_problems == 0:
        return (
            TEST_PASS,
            f"tree changed (HEAD {before.head[:8] if before.ok else '?'}->"
            f"{after.head[:8] if after.ok else '?'}, dirty {before.dirty}->{after.dirty}) "
            f"and check_wiring reports problems: 0. NOT a verified capability: no new "
            f"production episode with a passing verifier exists.",
            (),
        )
    if changed:
        return (
            CODE_CHANGED,
            f"tree changed but the wiring gate reported "
            f"{'not run' if wiring_problems is None else f'{wiring_problems} problem(s)'}",
            (),
        )
    if job_verdict in ("FAILED", "STOPPED"):
        return OUTCOME_BLOCKED, f"job ended {job_verdict} and nothing changed in the tree", ()
    return NO_IMPROVEMENT, "job finished, no code change and no new verified episode", ()


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
    errors: tuple[str, ...] = ()
    reload_requested_for: str = ""

    @property
    def line(self) -> str:
        parts = []
        if self.reconciled:
            parts.append(f"reconciled {len(self.reconciled)}")
        if self.submitted:
            parts.append(f"submitted {len(self.submitted)}")
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        if self.errors:
            parts.append(f"errors {len(self.errors)}")
        if self.reload_requested_for:
            parts.append(f"reload requested ({self.reload_requested_for})")
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
        self._build_request = escalation_request_from_project

    # -- the AUTO hook ----------------------------------------------------

    def observe_run(
        self,
        *,
        stop_reason: str,
        failures: Sequence[Mapping[str, Any]] = (),
        now: datetime | None = None,
        reconcile: bool = True,
    ) -> RunObservation:
        """Reconcile finished jobs, then hand off at most a few decisions.

        Deliberately non-blocking.  The only HTTP calls are short reads, and a
        gateway that is down is recorded as an observation rather than raised:
        AUTO keeps playing with a development agent unreachable, and the
        escalation simply stays ``QUEUED`` until the gateway is back.
        """
        moment = now or datetime.now(timezone.utc)
        errors: list[str] = []
        reconciled: list[str] = []
        submitted: list[str] = []
        skipped: list[tuple[str, str]] = []

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
            )
            for candidate in candidates:
                # Re-fold each time: a submission inside this loop changes the
                # concurrency answer for the next candidate.
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
        except Exception as exc:  # noqa: BLE001
            errors.append(f"dispatch failed: {type(exc).__name__}: {exc}")

        pending = self.reload_signal.pending()
        return RunObservation(
            reconciled=tuple(reconciled),
            submitted=tuple(submitted),
            skipped=tuple(skipped),
            errors=tuple(errors),
            reload_requested_for=pending.job_id if pending else "",
        )

    # -- ledger helpers ---------------------------------------------------

    def _record(self, candidate: EscalationCandidate, dispatch: Dispatch) -> None:
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

    def _submit(self, candidate: EscalationCandidate, dispatch: Dispatch) -> str:
        availability = self.bridge.is_available()
        revision = repo_revision(self.root)
        self._record(candidate, dispatch)

        if not availability:
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
            ),
            timebox_minutes=max(self.policy.stuck_minutes, 45),
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
        return submission.job_id

    # -- reconciliation ---------------------------------------------------

    def reconcile(self, *, now: datetime | None = None) -> tuple[list[str], list[str]]:
        """Poll every in-flight job and measure what it achieved.

        A job the gateway no longer knows about becomes ``FAILED`` rather than
        staying ``WORKING`` forever: a gateway restart must not leave a row that
        permanently occupies the concurrency slot.
        """
        moment = now or datetime.now(timezone.utc)
        snapshot = self.ledger.snapshot()
        settled: list[str] = []
        errors: list[str] = []

        for record in snapshot.records.values():
            if record.state not in (SUBMITTED, WORKING) or not record.job_id:
                continue
            try:
                status = self.bridge.status(record.job_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{record.key}: status({record.job_id}) failed: {exc}")
                continue

            live_state = (
                status.verdict if status.verdict in (WORKING, DONE, FAILED)
                else (status.gateway_state or "UNKNOWN").upper()
            )
            self.ledger.append({
                "event": "job_state",
                "key": record.key,
                "job_id": record.job_id,
                "state": live_state,
                "job_detail": status.detail,
            })
            if not status.terminal:
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
                job_verdict=status.verdict,
                before=before,
                after=after,
                wiring_problems=wiring,
                root=self.root,
            )
            code_changed = after.differs_from(before)
            self.ledger.append({
                "event": "reconciled",
                "key": record.key,
                "job_id": record.job_id,
                "job_state": DONE if status.verdict == "DONE" else FAILED,
                "job_detail": status.detail,
                "outcome": outcome,
                "explanation": explanation,
                "code_changed": code_changed,
                "wiring_problems": wiring,
                "verified_episodes": len(episodes),
                "model": record.model,
                "duration_seconds": _duration(record.submitted_at, status.first_terminal_at),
                "live_improvement": outcome == LIVE_VERIFIED,
                "repair_used": outcome != LIVE_VERIFIED,
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

        return settled, errors

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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
