# -*- coding: utf-8 -*-
"""Semantic Action Executor — click reliability for AUTHORIZED actions.

Operator directive (2026-09-29, UNIFIED SEMANTIC CLICK RETRY):

    Once an action passed Policy + Risk Gate + Preconditions + Target Verification
    (ACTION_AUTHORIZED = true), the execution layer has exactly one job: make sure
    the authorized action is actually received by the game.

    It must NOT refuse to retry merely because the action is 出征/攻击/领奖/用道具/确认.
    Never click an unauthorized action; always ensure an authorized one lands.

Model
-----
    AUTHORIZED_ACTION -> locate target on CURRENT frame -> click -> bounded settle
                      -> fresh observe -> evaluate postcondition
    outcome in {SUCCESS, PROGRESS, STILL_PENDING, AMBIGUOUS, FAILED}

Retry policy
------------
    STILL_PENDING (same context, same target, same button still actionable, no
    success evidence, no context switch, policy still authorized)
        -> FRESH frame -> re-locate -> re-click.   MAX_SEMANTIC_CLICK_RETRY = 2
    SUCCESS   -> stop immediately (success evidence wins)
    PROGRESS  -> wait (loading / transition), do not re-click yet
    AMBIGUOUS -> observe more, never blind-click
    FAILED    -> stop, report

Coordinates are NEVER reused: every attempt re-locates on a fresh frame.

Metrics persist to learning/semantic_click_metrics.jsonl and per-action counters:
CLICK_FIRST_TRY_SUCCESS / CLICK_RETRY_SUCCESS / CLICK_RETRY_EXHAUSTED /
CLICK_AMBIGUOUS_DEFERRED / CLICK_BLOCKED_UNAUTHORIZED.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / "learning" / "semantic_click_metrics.jsonl"
COUNTERS_PATH = ROOT / "learning" / "semantic_click_counters.json"

#: default bounded retry budget for one authorized semantic action
MAX_SEMANTIC_CLICK_RETRY = 2

SUCCESS = "SUCCESS"
PROGRESS = "PROGRESS"
STILL_PENDING = "STILL_PENDING"
AMBIGUOUS = "AMBIGUOUS"
FAILED = "FAILED"


@dataclass
class Observation:
    frame: Any
    state: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class SemanticAction:
    """One authorized semantic action plus how to locate and how to judge it."""

    name: str
    locate: Callable[[Observation], Optional[Tuple[int, int]]]
    postcondition: Callable[[Observation, Observation], str]
    settle_s: float = 1.6
    max_retry: int = MAX_SEMANTIC_CLICK_RETRY
    authorized: bool = True
    context_key: Callable[[Observation], Any] = field(default=lambda o: None)


@dataclass
class ExecutionResult:
    action: str
    outcome: str
    attempts: int
    retries: int
    outcomes: List[str] = field(default_factory=list)
    points: List[Tuple[int, int]] = field(default_factory=list)
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == SUCCESS


def classify_postcondition(before: Observation, after: Observation, action: SemanticAction) -> str:
    """Call the action's postcondition evaluator and normalise its verdict."""
    try:
        verdict = (action.postcondition(before, after) or AMBIGUOUS).upper()
    except Exception:
        return AMBIGUOUS
    if verdict not in (SUCCESS, PROGRESS, STILL_PENDING, AMBIGUOUS, FAILED):
        return AMBIGUOUS
    return verdict


def is_same_action_still_pending(before: Observation, after: Observation,
                                 action: SemanticAction) -> Optional[bool]:
    """TRUE = safe to re-locate and click again.

    Implemented on top of the action's own postcondition so all skills share one
    decision rule (directive §十):
        STILL_PENDING -> TRUE
        SUCCESS       -> FALSE
        anything else -> None (UNKNOWN: fresh observe / defer, never blind click)
    """
    v = classify_postcondition(before, after, action)
    if v == STILL_PENDING:
        return True
    if v in (SUCCESS, FAILED):
        return False
    return None


def _bump(kind: str) -> None:
    try:
        data = json.loads(COUNTERS_PATH.read_text(encoding="utf-8")) if COUNTERS_PATH.exists() else {}
    except Exception:
        data = {}
    data[kind] = int(data.get(kind, 0)) + 1
    try:
        COUNTERS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _log(record: Dict[str, Any]) -> None:
    try:
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with METRICS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


class SemanticActionExecutor:
    """Runs one authorized semantic action with fresh-locate retries and metrics."""

    def __init__(self, observe: Callable[[], Observation],
                 click: Callable[[int, int], None],
                 settle: Optional[Callable[[float], None]] = None):
        self.observe = observe
        self.click = click
        self.settle = settle or (lambda s: time.sleep(s))

    # ------------------------------------------------------------------ execute
    def execute(self, action: SemanticAction) -> ExecutionResult:
        res = ExecutionResult(action=action.name, outcome=AMBIGUOUS, attempts=0, retries=0)

        # §十五: unauthorized actions are never clicked.
        if not action.authorized:
            res.outcome = FAILED
            res.note = "NOT_AUTHORIZED"
            _bump("CLICK_BLOCKED_UNAUTHORIZED")
            _log({"action": action.name, "outcome": res.outcome, "attempts": 0,
                  "retries": 0, "note": res.note, "ts": time.time()})
            return res

        before = self.observe()
        attempts = 0
        while attempts <= action.max_retry:
            obs = self.observe() if attempts else before      # fresh frame every attempt
            point = action.locate(obs)
            if point is None:
                # target not locatable on the CURRENT frame -> not a click problem
                res.outcome = AMBIGUOUS if attempts == 0 else res.outcome
                res.note = "TARGET_NOT_LOCATED"
                break
            attempts += 1
            self.click(int(point[0]), int(point[1]))
            res.points.append((int(point[0]), int(point[1])))
            self.settle(action.settle_s)

            after = self.observe()
            verdict = classify_postcondition(before, after, action)
            res.outcomes.append(verdict)
            res.attempts = attempts

            if verdict == SUCCESS:                            # §十二 success wins
                res.outcome = SUCCESS
                break
            if verdict == PROGRESS:                           # §十三 settle more, do NOT re-click
                for _ in range(2):
                    self.settle(action.settle_s)
                    after = self.observe()
                    verdict = classify_postcondition(before, after, action)
                    res.outcomes[-1] = verdict
                    if verdict != PROGRESS:
                        break
                if verdict == SUCCESS:
                    res.outcome = SUCCESS
                    break
                if verdict == PROGRESS:
                    # still animating/loading after the bounded wait: observe, never blind-click
                    res.outcome = AMBIGUOUS
                    res.note = "PROGRESS_UNRESOLVED"
                    break
            if verdict in (FAILED, AMBIGUOUS):
                res.outcome = verdict
                break
            # STILL_PENDING -> §二 + §十一: fresh locate then retry
            res.outcome = STILL_PENDING
            if attempts > action.max_retry:
                break
            res.retries += 1

        if res.outcome == SUCCESS:
            _bump("CLICK_FIRST_TRY_SUCCESS" if res.attempts == 1 else "CLICK_RETRY_SUCCESS")
        elif res.outcome == STILL_PENDING:
            _bump("CLICK_RETRY_EXHAUSTED")
        elif res.outcome == AMBIGUOUS:
            _bump("CLICK_AMBIGUOUS_DEFERRED")
        _log({"action": action.name, "outcome": res.outcome, "attempts": res.attempts,
              "retries": res.retries, "outcomes": res.outcomes, "points": res.points,
              "note": res.note, "ts": time.time()})
        return res


# --------------------------------------------------------------------- adapters
# Common postcondition shapes reused by every skill (directive §十四: one rule set).

def march_counter_postcondition(before: Observation, after: Observation) -> str:
    """出征 / DISPATCH: success = the march counter increased (or a march appeared)."""
    b, a = before.state.get("march"), after.state.get("march")
    if a is None:
        return AMBIGUOUS
    if b is not None and a > b:
        return SUCCESS
    if after.state.get("marching") and not before.state.get("marching"):
        return SUCCESS
    if after.state.get("same_button") and after.state.get("same_target"):
        return STILL_PENDING
    return AMBIGUOUS


def page_open_postcondition(target_marker: str) -> Callable[[Observation, Observation], str]:
    """OPEN_PAGE / OPEN_BUILDING / OPEN_BARRACK: success = marker now on screen."""
    def check(before: Observation, after: Observation) -> str:
        if target_marker in (after.state.get("text") or ""):
            return SUCCESS
        if after.state.get("loading") or after.state.get("transition"):
            return PROGRESS
        if after.state.get("same_button"):
            return STILL_PENDING
        return AMBIGUOUS
    return check


def claim_postcondition(before: Observation, after: Observation) -> str:
    """CLAIM: success = the claimable marker disappeared."""
    if before.state.get("claimable") and not after.state.get("claimable"):
        return SUCCESS
    if after.state.get("claimable") and after.state.get("same_button"):
        return STILL_PENDING
    return AMBIGUOUS


def train_queue_postcondition(before: Observation, after: Observation) -> str:
    """TRAIN: success = the queue shows IN_PROGRESS (or resources were consumed)."""
    if after.state.get("queue_in_progress") and not before.state.get("queue_in_progress"):
        return SUCCESS
    if after.state.get("resource_consumed"):
        return SUCCESS
    if after.state.get("same_button") and after.state.get("same_context"):
        return STILL_PENDING
    return AMBIGUOUS


def item_count_postcondition(before: Observation, after: Observation) -> str:
    """USE_ITEM: success = the item count dropped."""
    b, a = before.state.get("item_count"), after.state.get("item_count")
    if b is not None and a is not None and a < b:
        return SUCCESS
    if after.state.get("same_button") and a == b:
        return STILL_PENDING
    return AMBIGUOUS


def rally_row_postcondition(before: Observation, after: Observation) -> str:
    """JOIN_RALLY / START_RALLY: success = row context changed / own rally appeared."""
    if after.state.get("joined") or after.state.get("own_rally_active"):
        return SUCCESS
    if after.state.get("row_gone") or after.state.get("full"):
        return FAILED
    if after.state.get("same_button") and after.state.get("same_target"):
        return STILL_PENDING
    return AMBIGUOUS


# WorldState adapter used by the ordinary AUTO execution boundary.
from dataclasses import asdict
from enum import Enum
from time import monotonic
from .models import Action, ExecutionResult as DeviceExecutionResult, Page, VerificationResult, WorldState

class ClickOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PROGRESS = "PROGRESS"
    STILL_PENDING = "STILL_PENDING"
    AMBIGUOUS = "AMBIGUOUS"
    FAILED = "FAILED"


class Pending(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TargetEvidence:
    identity: str
    enabled: bool | None
    context: Any
    pending_observed: bool = False


@dataclass(frozen=True)
class ClickObservation:
    world: WorldState
    frame: str
    target: TargetEvidence | None
    verification: VerificationResult
    authorized: bool = True


@dataclass
class RetryResult:
    observation: ClickObservation
    execution: DeviceExecutionResult
    outcome: ClickOutcome
    retries: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""

    @property
    def metric(self) -> str | None:
        if self.outcome is ClickOutcome.SUCCESS:
            return "CLICK_RETRY_SUCCESS" if self.retries else "CLICK_FIRST_TRY_SUCCESS"
        if self.stop_reason == "SEMANTIC_CLICK_RETRY_EXHAUSTED":
            return "CLICK_RETRY_EXHAUSTED"
        return None


_VOLATILE = {
    "timestamp", "observed_at", "last_observed", "confidence", "source", "source_frame",
    "repo_revision", "timer", "countdown", "remaining_seconds", "seconds_to_start",
    "row_index", "frame_size", "evidence", "duration_seconds", "queue_finish_at", "bbox", "box",
}


def stable_context(value: Any) -> Any:
    """Remove observation metadata and geometry, never quantities or target identity."""
    if isinstance(value, dict):
        return {k: stable_context(v) for k, v in value.items()
                if k not in _VOLATILE and not k.endswith(("_norm", "_frame", "_bbox", "_box"))}
    if isinstance(value, (tuple, list)):
        return [stable_context(v) for v in value]
    return getattr(value, "value", value)


def _state(world: WorldState) -> dict:
    result = asdict(world)
    return stable_context(result)


def _changing(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"loading", "transition", "animation", "state_changing"} and child is True:
                return True
            if key == "status" and str(child).upper() in {"LOADING", "TRANSITION", "ANIMATING"}:
                return True
            if isinstance(child, (dict, list, tuple)) and _changing(child):
                return True
    if isinstance(value, (list, tuple)):
        return any(_changing(child) for child in value)
    return False


def _effect_seen(before: WorldState, after: WorldState) -> bool:
    # These are acknowledgement signals, not proof of the complete Goal. A mismatch
    # with the bound verifier causes observation, never another resource submission.
    for name in ("resources", "resource_bank", "inventory", "march_used", "normal_idle_slots"):
        b, a = stable_context(getattr(before, name)), stable_context(getattr(after, name))
        if b not in ({}, None) and a not in ({}, None) and b != a:
            return True
    for name in ("training", "research", "building", "rally", "rewards", "stamina", "daily", "mail"):
        b, a = getattr(before, name), getattr(after, name)
        if b.get("claimable") is True and a.get("claimable") is False:
            return True
        if a.get("status") in {"IN_PROGRESS", "JOINED", "MARCHING", "ARRIVED"} and a.get("status") != b.get("status"):
            return True
    return False


def world_action_still_pending(
    before: ClickObservation, after: ClickObservation, semantic_action: Action,
) -> Pending:
    if not before.authorized or not after.authorized or semantic_action.kind != "TAP_SEMANTIC":
        return Pending.FALSE
    if after.verification.ok or _effect_seen(before.world, after.world):
        return Pending.FALSE
    if after.world.page in {Page.UNKNOWN, Page.LOADING, Page.MAINTENANCE} or _changing(asdict(after.world)):
        return Pending.UNKNOWN
    if before.world.page != after.world.page or before.world.popup != after.world.popup:
        return Pending.FALSE
    b, a = before.target, after.target
    if b is None or a is None or b.enabled is None or a.enabled is None:
        return Pending.UNKNOWN
    if b.identity != a.identity or stable_context(b.context) != stable_context(a.context):
        return Pending.FALSE
    if b.enabled is False or a.enabled is False:
        return Pending.FALSE
    if not b.pending_observed or not a.pending_observed:
        return Pending.UNKNOWN
    # Same page alone says nothing about a click. Target identity, executable
    # state and the postcondition's still-pending reading must all be present.
    if _state(before.world) != _state(after.world):
        return Pending.UNKNOWN
    return Pending.TRUE


def classify(before: ClickObservation, after: ClickObservation, action: Action) -> ClickOutcome:
    if after.verification.ok:
        return ClickOutcome.SUCCESS
    if not after.authorized:
        return ClickOutcome.FAILED
    if after.world.page is Page.LOADING or _changing(asdict(after.world)) or _effect_seen(before.world, after.world):
        return ClickOutcome.PROGRESS
    pending = world_action_still_pending(before, after, action)
    if pending is Pending.TRUE:
        return ClickOutcome.STILL_PENDING
    if pending is Pending.FALSE:
        # Context/target changes do not automatically prove an action successful.
        return ClickOutcome.AMBIGUOUS
    return ClickOutcome.AMBIGUOUS


def retry_authorized_semantic_click(
    *, action: Action, before: ClickObservation, after: ClickObservation,
    execution: DeviceExecutionResult,
    observe: Callable[[], ClickObservation],
    execute: Callable[[ClickObservation], DeviceExecutionResult | None],
    max_retries: int = MAX_SEMANTIC_CLICK_RETRY,
    max_observations: int = 2, timeout_seconds: float = 12.0,
    clock: Callable[[], float] = monotonic,
) -> RetryResult:
    """Never authorizes a new action or selects a task; callers retain all gates.

    observe must settle and capture a NEW frame; execute must rebind its resolver
    and recheck Policy/lease/conditions. No historical coordinate is accepted here.
    """
    result = RetryResult(after, execution, classify(before, after, action))
    if not execution.executed or action.kind != "TAP_SEMANTIC":
        result.stop_reason = "ACTION_NOT_SENT"
        return result
    deadline = clock() + max(0.0, timeout_seconds)
    retry_limit = min(MAX_SEMANTIC_CLICK_RETRY, max(0, int(max_retries)))
    observations = 0
    while clock() < deadline:
        if result.outcome in {ClickOutcome.SUCCESS, ClickOutcome.FAILED}:
            break
        if result.outcome is not ClickOutcome.STILL_PENDING:
            if observations >= max(0, max_observations):
                result.stop_reason = "OBSERVATION_BUDGET_EXHAUSTED"
                break
            observations += 1
            result.observation = observe()
            result.outcome = classify(before, result.observation, action)
            continue
        if result.retries >= retry_limit:
            result.stop_reason = "SEMANTIC_CLICK_RETRY_EXHAUSTED"
            break
        # Refresh again immediately before dispatch: the prior after-frame might
        # already be obsolete (a late network response, full/removed rally row).
        fresh = observe()
        verdict = classify(before, fresh, action)
        result.observation, result.outcome = fresh, verdict
        if verdict is not ClickOutcome.STILL_PENDING or clock() >= deadline:
            continue
        retried = execute(fresh)
        if retried is None or not retried.executed:
            result.stop_reason = "RETRY_AUTHORIZATION_OR_TARGET_REVOKED"
            result.outcome = ClickOutcome.FAILED
            break
        result.retries += 1
        result.execution = retried
        result.observation = observe()
        result.outcome = classify(before, result.observation, action)
        result.attempts.append({
            "retry": result.retries, "before_frame": fresh.frame,
            "after_frame": result.observation.frame, "tap_point": retried.tap_point,
            "backend": retried.backend, "outcome": result.outcome.value,
            "verifier": result.observation.verification.reason,
        })
    else:
        if result.outcome in {ClickOutcome.SUCCESS, ClickOutcome.FAILED}:
            return result
        result.stop_reason = "SEMANTIC_CLICK_TIMEBOX_EXHAUSTED"
    return result
