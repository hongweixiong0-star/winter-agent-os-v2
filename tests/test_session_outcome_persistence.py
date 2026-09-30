"""The session outcome must survive to the ledger, and must not be relabelled on the way.

Measured 2026-09-30 against the production stream (see
``dataset/truth_audit/loop_detector_20260930/audit_outcome_persistence.py``):

* the engine's five-way verdict was computed, passed to the writer, and dropped -- ``Episode``
  had no field for it, so ``result`` was the only durable trace;
* ``STILL_PENDING`` was not in the set that fold admitted, so it fell through to the
  ``"FAILURE"`` default: 44 rows called a cast that was still swimming a failed cast, with
  ``failure_type="NO_EXECUTION"``;
* ``session_host.record_step`` fabricated ``verifier_ok=False`` for those steps, which reads as
  a verification that was made and rejected -- the opposite of what ``verify_step``'s own
  docstring says to do.

These tests pin the three corrections, and pin that the four cases the old mapping already got
right still behave.
"""
from __future__ import annotations

import json
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.models import Action, Decision, ExecutionResult, Page, VerificationResult, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.session_engine import (
    STEP_OBSERVE_ONLY, SessionState, StepOutcome, StepReport,
)
from winter_agent_v2.session_host import LiveRuntimeSessionHost, SessionRunBinding


def _runtime(tmp_path: Path) -> SimpleNamespace:
    runtime = SimpleNamespace(
        _multi_role_enabled=False,
        _fold_control_experience=lambda **kw: None,
        _collect_ui_evidence=lambda **kw: None,
        _failure_type_from=lambda execution: "NO_EXECUTION",
        episode_store=EpisodeStore(tmp_path / "episodes.jsonl"),
        task_completion_store=None,
        capture_dir=tmp_path,
        device=SimpleNamespace(),
        code_revision="test",
        role_id="A",
        role_scope="ROLE_A",
        execution_mode="PRODUCTION",
        trace_id="",
        job_id="",
        capability="",
        expected_after_version="",
    )
    # ``record_step`` reaches for ``self.runtime._record_episode`` and *swallows* anything it
    # raises (the record is evidence; a defect in it must not repeat a physical action), so a
    # stub missing this method fails silently -- it notes ``session_episode_failed`` and
    # returns, leaving a test that asserts on a file which was never written.  Binding the
    # real writer keeps the test honest about which layer is under test.
    runtime._record_episode = partial(LiveRuntime._record_episode, runtime)
    return runtime


def _record(runtime, *, outcome: str, sent: bool, verified: bool | None = True) -> dict:
    LiveRuntime._record_episode(
        runtime,
        decision=Decision("OBSERVE_ONLY", "session:S1:FISHING_RESULT_PENDING", 1, ""),
        before=WorldState(page=Page.EVENT),
        after=WorldState(page=Page.EVENT),
        execution=(ExecutionResult(True, False, Action("TAP", "normal_stage")) if sent else None),
        verification=(None if verified is None else VerificationResult(verified, "R", {})),
        started_at=time.monotonic(),
        session_outcome=outcome,
    )
    return json.loads(runtime.episode_store.path.read_text(encoding="utf-8").splitlines()[-1])


# --------------------------------------------------------------- the outcome is persisted

@pytest.mark.parametrize("outcome", [o.value for o in StepOutcome])
def test_every_verdict_reaches_the_ledger_verbatim(tmp_path, outcome):
    """The five-way verdict is the fact; ``result`` is only a coarse class of it."""
    row = _record(_runtime(tmp_path), outcome=outcome, sent=True)
    assert row["session_outcome"] == outcome, (
        f"{outcome} was folded into result={row['result']!r} and lost; the ledger must carry "
        "the verdict itself"
    )


def test_a_goal_driven_step_records_no_session_outcome(tmp_path):
    """``""`` means 'this was not a session step' -- never a guessed verdict."""
    row = _record(_runtime(tmp_path), outcome="", sent=True)
    assert row["session_outcome"] == ""


# -------------------------------------------------- a pending step is not a failed step

def test_still_pending_is_not_written_as_a_failure(tmp_path):
    """The measured defect: 44 production rows called an in-flight cast a failed cast."""
    row = _record(_runtime(tmp_path), outcome="STILL_PENDING", sent=False, verified=None)
    assert row["result"] != "FAILURE", (
        "a STILL_PENDING step is honest work in flight; writing FAILURE is what made the "
        "outcome unmeasurable and what fired the panel's own VERIFIER_CONFLICT detector"
    )
    assert row["result"] == "INCOMPLETE"
    assert row["failure_type"] is None, (
        "nothing failed, so there is no failure to name -- NO_EXECUTION described the step's "
        "kind, not a verdict"
    )


def test_ambiguous_and_still_pending_share_the_result_class_but_not_the_verdict(tmp_path):
    """One column stops carrying two facts: the class in ``result``, the verdict in its own."""
    pending = _record(_runtime(tmp_path), outcome="STILL_PENDING", sent=False, verified=None)
    ambiguous = _record(_runtime(tmp_path), outcome="AMBIGUOUS", sent=False, verified=None)
    assert pending["result"] == ambiguous["result"] == "INCOMPLETE"
    assert pending["session_outcome"] != ambiguous["session_outcome"]
    assert (pending["session_outcome"], ambiguous["session_outcome"]) == (
        "STILL_PENDING", "AMBIGUOUS")


@pytest.mark.parametrize("outcome,verified,sent,expected", [
    ("SUCCESS", True, True, "SUCCESS"),
    ("PROGRESS", True, True, "PROGRESS"),
    ("FAILED", False, True, "FAILURE"),
    ("SUCCESS", False, True, "FAILURE"),
])
def test_the_cases_the_old_mapping_already_had_right_still_hold(
        tmp_path, outcome, verified, sent, expected):
    """The correction must not quietly re-label the four cases that were already correct."""
    row = _record(_runtime(tmp_path), outcome=outcome, sent=sent, verified=verified)
    assert row["result"] == expected


# ------------------------------------------------- no fabricated verifier verdict for a wait

def test_a_pending_step_does_not_fabricate_a_rejected_verification(tmp_path):
    """``None`` means nobody judged; ``False`` means a verifier judged and said no.

    ``session_host.verify_step``'s own docstring states the rule, and ``record_step`` broke it
    for every pending step: an observe-only wait has no atomic verifier, so the substituted
    ``VerificationResult`` turned 'no answer yet' into 'the verifier said no'.
    """
    runtime = _runtime(tmp_path)
    host = LiveRuntimeSessionHost(runtime, SessionRunBinding(
        1, "USE_NORMAL_FISHING_BAIT", "B", WorldState(page=Page.EVENT), tmp_path / "before.png"))
    host._verification = None
    host._execution = None

    host.record_step(StepReport(
        session_id="S1", goal_id="USE_NORMAL_FISHING_BAIT", role_id="B", index=2,
        skill_id="OBSERVE_ONLY", outcome="STILL_PENDING", reason="FISHING_RESULT_PENDING",
        executed=False, backend="", latency_ms=None, tap_point=None, kind=STEP_OBSERVE_ONLY))

    row = json.loads(runtime.episode_store.path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["verifier_ok"] is None, (
        "no verifier ran for a wait, so the row must say so rather than record a rejection"
    )
    assert row["session_outcome"] == "STILL_PENDING"
    assert row["goal_progress"] is False, (
        "the honest statement about a pending step is that it advanced nothing yet"
    )


def test_an_answered_step_still_records_the_verifier_it_had(tmp_path):
    """The change is narrow: a step that *was* answered keeps its real verdict."""
    runtime = _runtime(tmp_path)
    host = LiveRuntimeSessionHost(runtime, SessionRunBinding(
        1, "USE_NORMAL_FISHING_BAIT", "B", WorldState(page=Page.EVENT), tmp_path / "before.png"))
    host._verification = VerificationResult(True, "CAST_VERIFIED", {})
    host._execution = ExecutionResult(True, True, Action("TAP", "normal_stage"))

    host.record_step(StepReport(
        session_id="S1", goal_id="USE_NORMAL_FISHING_BAIT", role_id="B", index=3,
        skill_id="OBSERVE_ONLY", outcome="SUCCESS", reason="FISHING_CAST_VERIFIED",
        executed=True, backend="MAA", latency_ms=None, tap_point=None, kind=STEP_OBSERVE_ONLY))

    row = json.loads(runtime.episode_store.path.read_text(encoding="utf-8").splitlines()[-1])
    assert row["verifier_ok"] is True
    assert row["result"] == "SUCCESS"


# ----------------------------------------------------------------- the counter exists

def test_the_session_counts_its_pending_steps_separately():
    """A bound needs a count, and a count must not be folded into the step total.

    Measured: the fishing wait spends one step of the budget per look with no delay, so ten
    looks cost 0.3 s of a 150 s budget and the session dies at the step ceiling with every
    existing counter still reading zero.  ``SESSION_STILL_PENDING`` is what makes that
    visible on the next run, and it is deliberately not merged with ``observes`` (a
    different question) nor with ``loop_recoveries`` (a pending step is not a detected loop).
    """
    state = SessionState()
    assert state.still_pending == 0
    state.still_pending += 4
    assert state.still_pending == 4

    metrics = vars(state)
    assert "still_pending" in metrics
    assert "observes" in metrics and "loop_recoveries" in metrics


def test_metrics_block_reports_the_pending_count(tmp_path):
    """The panel reads ``session_result``; the count has to be able to reach it."""
    from winter_agent_v2.session_engine import SessionContext, SessionEngine, SessionSpec
    context = SessionContext(spec=SessionSpec(goal_id="G", adapter="fishing",
                                              session_id="S1", role_id="A"))
    state = SessionState()
    state.still_pending = 7
    metrics = SessionEngine._metrics(context, state, 0.0, 0.0, [])
    assert metrics["SESSION_STILL_PENDING"] == 7
    assert metrics["SESSION_STILL_PENDING"] != metrics["SESSION_STEPS"], (
        "the whole point of the separate key: a session that used ten steps waiting must not "
        "look like a session that took ten actions"
    )
