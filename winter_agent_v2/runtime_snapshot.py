from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AgentState(str, Enum):
    AUTO_RUNNING = "AUTO_RUNNING"
    IDLE = "IDLE"
    GOAL_RUNNING = "GOAL_RUNNING"
    RECOVERING = "RECOVERING"
    DEGRADED = "DEGRADED"
    SAFE_STOP = "SAFE_STOP"
    FATAL_STOPPED = "FATAL_STOPPED"
    PAUSED = "PAUSED"


class StopCategory(str, Enum):
    """Why a runtime cycle ended, kept separate from whether AUTO is healthy."""

    EXPECTED_NO_ACTION = "EXPECTED_NO_ACTION"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    COMPLETED = "COMPLETED"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


@dataclass
class RuntimeSnapshot:
    agent_state: str = AgentState.IDLE.value
    runtime_thread_alive: bool = False
    scheduler_loop_alive: bool = False
    last_tick_time: str | None = None
    last_action_time: str | None = None
    last_success_time: str | None = None
    last_fatal_error: str | None = None
    watchdog_restart_count: int = 0
    unexpected_worker_exits: int = 0
    page: str = "UNKNOWN"
    role_id: str | None = None
    current_goal: str | None = None
    current_skill: str | None = None
    reason: str | None = None
    preconditions: list[str] = field(default_factory=list)
    verifier: str | None = None
    next_action: str | None = None
    risk: str = "UNKNOWN"
    confidence: float = 0.0
    device: str = "UNKNOWN"
    game: str = "UNKNOWN"
    mode: str = "AUTO"
    qwen: str = "ON_DEMAND"
    vision: str = "UNKNOWN"
    screenshot_path: str | None = None
    march_used: int | None = None
    march_max: int | None = None
    queues: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    stop_category: str | None = None
    # The goal paths the scheduler refused to re-enter this run, with the evidence for
    # refusing (goal, capability, state, reason, streak).  Declared here because
    # ``update`` filters unknown keys -- measured 2026-09-18: the runtime's write of
    # this field was silently dropped, so the one place an operator looks to ask "why
    # is AUTO not doing that" would have said nothing.
    deferred_goals: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


NON_FATAL_STOPS = {
    "NOT_PROVEN", "NOT_VERIFIED", "SEMANTIC_NOT_FOUND", "SEMANTIC_TARGET_NOT_VERIFIED",
    "QUEUE_FULL", "NO_ATTEMPT", "RALLY_FULL", "NOT_REFRESHED", "EVENT_CLOSED",
    "no_idle_march", "reserved_march_for_stamina", "mail_all_clear",
    "exploration_income_not_ready", "daily_no_claimable_rewards",
    "daily_state_unknown_or_not_actionable", "alliance_action_not_needed",
    "training_queue_busy", "research_queue_busy", "intel_state_unknown",
    "intel_available_no_claim", "verified_beast_target_not_visible", "unknown_page",
    "goal_page_mismatch", "SKILL_NOT_ENABLED_FOR_LIVE_LOOP", "MAX_ACTIONS_REACHED",
    "TARGET_SKILL_VERIFIED",
    # Honest end of a run whose march counter stayed unreadable.  Kept next to
    # SKILL_NOT_ENABLED_FOR_LIVE_LOOP on purpose: that reason used to be what
    # this state produced, and it described a wiring hole rather than the game.
    "MARCH_COUNT_NOT_READ", "intel_no_untried_pins",
    # The client is sitting on a guided tutorial step over the infantry camp, which
    # issue #82 identified from the frames on 2026-09-21 (see brain.py: the ring is on
    # the ground, the hand points at the 2-badged action block, and three consecutive
    # frames show nothing progressing toward a menu).  A guided step is a precondition
    # the training route cannot satisfy by tapping or waiting, so it is a statement
    # about THAT goal only -- exactly like a busy queue.  Without this entry it would
    # be classified as a heading it does not start with (FATAL_/ACCOUNT_/PAYMENT_) and
    # could end a cycle that still had other goals to run.  Named alongside
    # ``training_queue_busy`` because it is the same kind of answer: this entry point
    # is not usable right now, and another goal is allowed to take the turn.
    "camp_entry_is_a_guided_step_not_a_selection",
    # The honest end of a run that has stood on every page it can reach and been offered
    # nothing on any of them (``LiveRuntime._stop_instead_of_looking_again``, measured
    # 2026-09-23: 18 of 75 runs were OPEN_MAP / OPEN_HOME / OPEN_MAP and nothing else).
    # Registered here rather than left to the FATAL_/ACCOUNT_/PAYMENT_ prefix test for the
    # same reason ``camp_entry_is_a_guided_step_not_a_selection`` is: it is an answer about
    # this run's search, not about any goal and not about the device, so a reader of this
    # table should find it here instead of inferring it from what it does not start with.
    "every_page_this_run_was_fruitless", "GLOBAL_WAIT",
    # Sibling of ``GLOBAL_WAIT``: an honest "nothing planned this tick", not a device fault.
    "ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE",
    # LOOP_DETECTOR_V1 exhausted its recovery ladder inside one Goal's session and handed
    # that Goal back (``session_engine.SESSION_DOMAIN_STUCK``).  Registered here for the same
    # reason ``SEMANTIC_TARGET_NOT_VERIFIED`` is: §7 requires Recover -> Bounded Retry ->
    # Defer/Skip -> Next Goal, never a stopped AUTO.  The whole point of the defer rung is
    # that the *other* Goals still get their turn, so a reason that deferred would be a
    # reason that stopped the agent if it were classified as a system failure -- the exact
    # contradiction the directive forbids ("Loop Detector 不得停止整个AUTO").
    "SESSION_DOMAIN_STUCK",
}

EXPECTED_NO_ACTION_STOPS = frozenset({
    # A development lease ends gameplay at a safe boundary intentionally. The
    # lease still blocks inputs; releasing it lets the existing AUTO cycle resume.
    "device_leased_for_development",
    "every_page_this_run_was_fruitless",
    # TASK THROUGHPUT V1 §24.  The Scheduler's "nothing to do now; wake at the next event"
    # verdict is a keep-current role decision, and the panel already plans a scheduled wakeup
    # for it (``_global_wait_delay_ms`` -> ``event_schedule.bounded_poll_delay_seconds``).  It
    # was listed as NON_FATAL but never as EXPECTED, so ``classify_stop_reason`` fell through
    # to SYSTEM_FAILURE and the panel's ``healthy`` became false -- which stopped AUTO, so that
    # scheduled wakeup could never run.  Found by
    # ``test_every_keep_current_reason_survives_the_classifier``.
    "GLOBAL_WAIT",
    "no_idle_march", "reserved_march_for_stamina",
    "mail_all_clear", "exploration_income_not_ready",
    "daily_no_claimable_rewards", "daily_state_unknown_or_not_actionable",
    "alliance_action_not_needed", "training_queue_busy", "research_queue_busy",
    "intel_available_no_claim", "intel_no_untried_pins",
    "verified_beast_target_not_visible",
})
CAPABILITY_GAP_STOPS = frozenset({
    "unknown_page", "goal_page_mismatch", "SKILL_NOT_ENABLED_FOR_LIVE_LOOP",
    "live_event_fallback_budget_exhausted", "selected_daily_task_row_not_currently_actionable",
    "daily_quick_panel_row_has_no_registered_skill", "daily_panel_already_read_not_actionable",
    "daily_tab_not_confirmed_after_task_board", "skill_not_ready", "no_ready_skill",
    "GLOBAL_REFRESH_REQUIRED_NO_SAFE_CANDIDATE",
    "GLOBAL_CAPABILITY_GAP_NO_EXECUTABLE_CANDIDATE",
    "GLOBAL_CANDIDATE_GENERATION_GAP", "ROLE_IDENTITY_UNCONFIRMED",
    "all_tasks_unavailable", "SEMANTIC_NOT_FOUND", "SEMANTIC_TARGET_NOT_VERIFIED",
    # The active role's Brain answered SAFE_STOP/WAIT for one tick, so the Scheduler produced
    # no candidate for it and asked for the same account to be observed again.  It belongs with
    # ``GLOBAL_CANDIDATE_GENERATION_GAP`` -- both are "this scheduling planned nothing", neither
    # is a statement about the device.  Missing from this set, it fell through
    # ``classify_stop_reason`` to SYSTEM_FAILURE, which made the panel's ``healthy`` false and
    # stopped AUTO entirely; measured on pin 7055f02, 2026-09-30, the device then sat idle.
    "ACTIVE_ROLE_NO_CANDIDATE_REOBSERVE",
    # LOOP_DETECTOR_V1's ladder ran out and handed the Goal back.  It belongs with
    # ``SEMANTIC_TARGET_NOT_VERIFIED`` -- §7's "Recover -> Bounded Retry -> Defer/Skip -> Next
    # Goal" is exactly what the ladder already did, so the ending is the *successful* outcome
    # of the remedy rather than a fault.  Listed here as well as in ``NON_FATAL_STOPS``
    # because the two tables answer different questions (this one decides the category, that
    # one decides fatality), and a reader should not have to infer either.
    "SESSION_DOMAIN_STUCK",
})
COMPLETED_STOPS = frozenset({"MAX_ACTIONS_REACHED", "TARGET_SKILL_VERIFIED"})


def _declares(token: str, declared: "frozenset[str] | set[str]") -> bool:
    """Is this reason one the table declares, allowing a ``TOKEN:detail`` suffix?

    Reasons in this project carry detail after a colon, and the oldest example is
    ``ROLE_SWITCHED_TO:``.  Matching only the bare token means a reason can be *declared*
    and still fall through to SYSTEM_FAILURE -- which the panel reads as ``healthy=False``,
    which stops AUTO.  Measured 2026-09-30 on LOOP_DETECTOR_V1's own ending: the engine
    emits ``SESSION_DOMAIN_STUCK:AAA: the same signature 3x running (ab12cd34ef)`` and the
    bare-token test called it a system failure, so the first version of the loop detector
    would have stopped the agent at exactly the moment it had successfully handed a stuck
    Goal back.

    Only the colon form is accepted.  A *prefix* match on arbitrary text would make
    ``SEMANTIC_NOT_FOUND_BECAUSE_X`` match ``SEMANTIC_NOT_FOUND``, and widening a "do not
    stop" table into a substring test is how a classifier starts excusing real faults.
    """
    want = {item.upper() for item in declared}
    if token in want:
        return True
    head, sep, _detail = token.partition(":")
    return bool(sep) and head.strip() in want


def classify_stop_reason(
    reason: str | None,
    *,
    decision_skill: str | None = None,
    action_executed: bool = False,
    verifier_failed: bool = False,
    verifier_reasons: "tuple[str, ...] | frozenset[str]" = (),
    last_step_verifier_failed: bool = False,
) -> StopCategory:
    """Classify a cycle result without treating every safe stop as a failure.

    Two different questions live here, and conflating them stopped AUTO three times on
    2026-09-30: *why did the round end* (the stop reason), and *did a step inside it fail*
    (``verifier_failed``).  A step failure is recorded per episode and must not relabel a round
    that ended on a reason this module declares recoverable -- but it must not be ignored either
    when it IS what ended the round.

    ``verifier_reasons`` is the set of step-level verifier failure reasons in the round and
    ``last_step_verifier_failed`` says whether the final step was one of them.  Together they
    answer "did a verifier failure cause this stop", which is the only case that turns a
    verifier reason into a recoverable ending.
    """
    normalized = str(reason or "").strip()
    token = normalized.upper()
    if is_fatal_stop(normalized):
        return StopCategory.SYSTEM_FAILURE
    # A verifier miss is evidence about a *step*; the stop reason is evidence about *why the
    # round ended*.  So the declared classes of stop reason are tested first, and ``verifier_failed``
    # only decides a round whose stop reason nothing declares.
    #
    # Measured 2026-09-30 11:21 local (pin b2cb6f1).  Round ``20260930_111430_903715`` issued
    # 24 actions, 23 verified, with one BEAST_SEARCH_TAB miss at step 005; it then kept working
    # for nineteen more steps and ended MAX_ACTIONS_REACHED.  ``verifier_failed`` fired first,
    # so the snapshot recorded ``stop_category=SYSTEM_FAILURE`` / ``agent_state=DEGRADED``; the
    # panel's ``healthy`` went false, ``should_continue_auto_cycle`` declined, and AUTO stopped
    # while the device sat idle -- and the panel logged no reason at all.
    if token == "MAX_ACTIONS_REACHED":
        return StopCategory.COMPLETED
    if normalized.startswith(("ROLE_SWITCHED_TO:", "ROLE_IDENTITY_CHANGED:",
                              "ROLE_SWITCH_FAILED:")):
        # A role handoff ends this process intentionally. The control plane starts a
        # fresh cycle, whose first frame must identify the new account before acting.
        return StopCategory.EXPECTED_NO_ACTION
    if _declares(token, EXPECTED_NO_ACTION_STOPS):
        return StopCategory.EXPECTED_NO_ACTION
    if _declares(token, CAPABILITY_GAP_STOPS):
        return StopCategory.CAPABILITY_GAP
    # A verifier miss AND a stop reason nothing declares: only then is this round a system
    # failure.  The blanket short-circuit used to sit above the two sets, so one miss anywhere
    # relabelled a round that ended on a stop reason this module itself declares recoverable --
    # and the panel reads that label as ``healthy``, so AUTO stopped.
    #
    # Measured 2026-09-30, the same mislabelling through two different doors, both live:
    #   11:53  MAX_ACTIONS_REACHED + one miss  -> SYSTEM_FAILURE -> AUTO stopped at 11:58:23
    #   12:48  SEMANTIC_TARGET_NOT_VERIFIED with every verifier PASSING, so a false ``healthy``
    #          again -> AUTO stopped at 12:48:39
    # ``SEMANTIC_TARGET_NOT_VERIFIED`` is in CAPABILITY_GAP_STOPS above and §7 requires
    # "Recover -> Bounded Retry -> Defer/Skip -> Next Goal" for it, never a stop.  The miss stays
    # visible: it is a per-step episode and the panel's run summary still counts it.
    # A verifier reason is not a declaration that the system broke.  The verifier names the
    # step-level contract it could not prove, and the runtime's own recovery loop consumes
    # exactly this class: it hands the failing goal to the next one and keeps going.  When that
    # loop is out of budget the run ends honestly *with that reason* -- and until this line the
    # classifier called the ending a SYSTEM_FAILURE, so the panel refused the next round and AUTO
    # stopped on a step the project had already decided was recoverable.
    #
    # Measured 2026-09-30 05:14:35 UTC, live: ``DAILY_REWARD_ADVANCE_NOT_PROVEN`` spent the run's
    # handover budget (``max_verification_retries``) and AUTO stopped with the operator's intent
    # still RUNNING.  §7 lists this whole family -- NOT_VERIFIED / VERIFY_FAILED -- as things that
    # must not stop the Agent: "Recover -> Bounded Retry -> Defer/Skip -> Next Goal".
    #
    # Deliberately narrow: only a verifier failure that IS the terminal reason downgrades.  Two
    # cases keep SYSTEM_FAILURE, and both are pinned in ``tests/test_runtime_snapshot.py``: a stop
    # that names something other than the failure (``TARGET_SKILL_VERIFIED`` alongside an
    # unrelated miss -- the stop is a success token, so the miss is not what ended the round), and
    # a stop nobody can name with no verifier miss at all.
    if verifier_failed:
        if str(normalized) in {str(item).strip() for item in verifier_reasons if str(item).strip()}:
            return StopCategory.CAPABILITY_GAP
        if last_step_verifier_failed:
            return StopCategory.CAPABILITY_GAP
        return StopCategory.SYSTEM_FAILURE
    if token in {item.upper() for item in COMPLETED_STOPS}:
        return StopCategory.COMPLETED
    if str(decision_skill or "") == "SAFE_STOP" and not action_executed:
        return StopCategory.CAPABILITY_GAP
    return StopCategory.SYSTEM_FAILURE


def state_for_stop_reason(
    reason: str | None,
    *,
    decision_skill: str | None = None,
    action_executed: bool = False,
    verifier_failed: bool = False,
    verifier_reasons: "tuple[str, ...] | frozenset[str]" = (),
    last_step_verifier_failed: bool = False,
) -> tuple[StopCategory, AgentState]:
    """Map a completed runtime cycle to the operator-facing health state."""
    category = classify_stop_reason(
        reason,
        decision_skill=decision_skill,
        action_executed=action_executed,
        verifier_failed=verifier_failed,
        verifier_reasons=verifier_reasons,
        last_step_verifier_failed=last_step_verifier_failed,
    )
    if category is StopCategory.SYSTEM_FAILURE:
        state = AgentState.FATAL_STOPPED if is_fatal_stop(reason) else AgentState.DEGRADED
    elif category is StopCategory.CAPABILITY_GAP:
        state = AgentState.SAFE_STOP
    else:
        state = AgentState.IDLE
    return category, state


def is_fatal_stop(reason: str | None) -> bool:
    if not reason:
        return False
    normalized = str(reason).strip()
    if normalized in NON_FATAL_STOPS:
        return False
    return normalized.startswith(("FATAL_", "ACCOUNT_", "PAYMENT_"))


# ---------------------------------------------------------------------------
# The single rule for `unexpected_worker_exits`.
#
# Origin: RR-001 / WB-R19-RUNTIME-EXIT-SEMANTICS (2026-09-16).  The counter had
# two writers in tools/control_panel.py with different rules -- the classified
# path counted only a genuine WORKER_CRASH, while the unclassified fallback
# counted every non-fatal error.  So an emulator dropout or an operator stop
# incremented a counter that the 72-hour gate requires to be zero, which made
# that gate unreachable by fixing crashes.  The rule now lives here, next to
# `is_fatal_stop`, and both writers call it: same question, one answer.
#
# Why it is a free function rather than a method: the semantics belong to the
# snapshot, not to the GUI.  A rule that can only be exercised by starting a
# Tk window is a rule that will not be tested, and this one already went wrong
# once for exactly that reason.
# ---------------------------------------------------------------------------

# The classification a caller supplies when the event carries no worker
# verdict at all -- a generic runtime error, for instance.  It is deliberately
# NOT a synonym for WORKER_CRASH: `classify_worker_failure` defaults to
# WORKER_CRASH for any unrecognised text, so reusing that default on a path that
# never sees a worker death would count every stray error as a crash.
UNCLASSIFIED_EVENT = "UNCLASSIFIED"


def counts_as_unexpected_worker_exit(
    *,
    classification: str | None,
    message: str | None,
    stop_requested: bool = False,
) -> bool:
    """Does this event increment ``unexpected_worker_exits``?

    Yes only when all three hold:

    * the event was classified as a genuine crash of the worker itself
      (``WORKER_CRASH``) -- not an environmental failure, not an operator stop,
      not an event that carries no worker verdict;
    * the operator did not ask for the stop; and
    * the reason is not fatal, because a fatal stop is already recorded in
      ``last_fatal_error`` and counting it twice would double-report one event.

    Environmental conditions are recoverable by waiting and retrying and are not
    evidence of a defect, so they must not move a counter whose whole purpose is
    "the worker died for a reason we do not understand".
    """
    if stop_requested:
        return False
    if is_fatal_stop(message):
        return False
    return str(classification or "") == "WORKER_CRASH"


class RuntimeSnapshotStore:
    """Atomic single source of truth written by Runtime and read by the GUI."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> RuntimeSnapshot:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return RuntimeSnapshot()
        fields = RuntimeSnapshot.__dataclass_fields__
        return RuntimeSnapshot(**{key: value for key, value in data.items() if key in fields})

    def update(self, **changes: Any) -> RuntimeSnapshot:
        current = self.read()
        data = asdict(current)
        data.update(changes)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        state = str(data.get("agent_state", AgentState.IDLE.value))
        alive = bool(data.get("runtime_thread_alive")) and bool(data.get("scheduler_loop_alive"))
        invalid_running = state in {AgentState.AUTO_RUNNING.value, AgentState.GOAL_RUNNING.value} and not alive
        invalid_recovery = state == AgentState.RECOVERING.value and not bool(data.get("runtime_thread_alive"))
        if invalid_running or invalid_recovery:
            data["agent_state"] = AgentState.DEGRADED.value
        snapshot = RuntimeSnapshot(**{key: value for key, value in data.items() if key in RuntimeSnapshot.__dataclass_fields__})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return snapshot


# ---------------------------------------------------------------------------
# AUTO uptime ledger -- the measurement the 72h acceptance criterion needs
# ---------------------------------------------------------------------------
#
# ACCEPTANCE (03_MASTER_RULES §22) is "AUTO runs >= 72h unattended with
# unexpected_worker_exits = 0".  That sentence had no ledger, so every claim about it was a
# narrative: the snapshot only ever describes the *current* moment, and the 2026-09-30 reports
# could say "5.9 hours with zero episodes" but not "the longest self-continuing AUTO run so far
# is N minutes".  These helpers fold an append-only ledger into that answer, so the criterion is
# computable instead of asserted.
#
# The row is written by the control plane at the one point where it already knows the answer to
# "will there be another round": ``auto_halt_reason`` returned empty.  That is what makes
# ``continues`` a fact about the panel rather than a prediction -- and it is deliberately the
# same value that decides whether the next round starts, so the ledger cannot disagree with the
# behaviour it is measuring.
def uptime_ledger_row(
    *, recorded_at: str, stop_reason: str, stop_category: str, healthy: bool, continues: bool,
    halt_reason: str = "", executed: int = 0, verified: int = 0, failures: int = 0,
    episode_id: str = "", role_id: str = "", repo_revision: str = "", round_ms: int | None = None,
) -> dict[str, Any]:
    """One round, as the acceptance question needs to see it."""
    return {
        "recorded_at": str(recorded_at or ""),
        "stop_reason": str(stop_reason or ""),
        "stop_category": str(stop_category or ""),
        "healthy": bool(healthy),
        "continues": bool(continues),
        "halt_reason": str(halt_reason or ""),
        "executed": int(executed or 0),
        "verified": int(verified or 0),
        "failures": int(failures or 0),
        "episode_id": str(episode_id or ""),
        "role_id": str(role_id or ""),
        "repo_revision": str(repo_revision or ""),
        "round_ms": None if round_ms is None else int(round_ms),
    }


def summarize_uptime(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold the ledger into the numbers an operator actually asks for.

    ``longest_consecutive_continues`` is the acceptance-shaped one: ACCEPTANCE_REQUIRED is 3
    consecutive rounds that each started the next one.  The run window is measured from the
    first round of that streak to the last, so a three-round streak of a five-minute bounded
    budget reads as ~15 minutes and cannot be mistaken for 72 hours.
    """
    wanted = 3
    rounds = [row for row in rows if isinstance(row, dict)]
    current = longest = 0
    current_start: str | None = None
    longest_window: tuple[str, str] | None = None
    for row in rounds:
        if bool(row.get("continues")):
            if current == 0:
                current_start = str(row.get("recorded_at") or "")
            current += 1
            if current > longest:
                longest = current
                longest_window = (current_start or "", str(row.get("recorded_at") or ""))
        else:
            current = 0
            current_start = None

    def _span(window: tuple[str, str] | None) -> float:
        if not window:
            return 0.0
        try:
            start = datetime.fromisoformat(window[0])
            end = datetime.fromisoformat(window[1])
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, (end - start).total_seconds())

    streaks = [row for row in rounds if bool(row.get("continues"))]
    return {
        "rounds": len(rounds),
        "continuing_rounds": len(streaks),
        "halted_rounds": len(rounds) - len(streaks),
        "current_consecutive_continues": current,
        "longest_consecutive_continues": longest,
        "longest_window_seconds": _span(longest_window),
        "last_round_at": str(rounds[-1].get("recorded_at") or "") if rounds else "",
        "last_halt_reason": next(
            (str(row.get("halt_reason")) for row in reversed(rounds) if not bool(row.get("continues"))),
            "",
        ),
        "acceptance_required": wanted,
        "acceptance_met": longest >= wanted,
    }


def read_uptime_ledger(path: str | Path) -> list[dict[str, Any]]:
    """Every readable row, in write order.  A damaged line is skipped, never fatal."""
    rows: list[dict[str, Any]] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_uptime_ledger(path: str | Path, row: dict[str, Any]) -> None:
    """Append one round.  Measurement must never be able to stop the run it measures."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return
