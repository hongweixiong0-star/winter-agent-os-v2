"""ROLE SESSION PRODUCTION V2 -- the ordinary-switch gate (operator directive 2026-09-30).

Pins the whole point of the directive: after the old dwell expired, any other role whose
*ordinary* Goal scored ``+switch_margin`` higher took the device.  These tests hold the
line that "time passed" and "another role scores more" are no longer switching reasons,
while a genuine deadline still preempts.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.executor import Executor
from winter_agent_v2.global_scheduler_state import GlobalSchedulerStateStore
from winter_agent_v2.goal_library import GoalState, GoalStatus, GoalStateStore
from winter_agent_v2.models import Decision, Page, WorldState
from winter_agent_v2.role_session import (
    HARD_EVENT_PREEMPT,
    NO_RUNNABLE_WORK,
    ROLE_SESSION_POLICY_DEFAULTS,
    SESSION_COMPLETE,
    RoleSessionState,
    classify_switch_reason,
    evaluate_role_session_gate,
    new_session,
    resolve_policy,
    role_switch_quality_metrics,
)
from winter_agent_v2.scheduler import RoleObservation, Scheduler
from winter_agent_v2.skills import v2_registry


NOW = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ fixtures

def _scheduler(tmp_path, active_role_id: str = "A") -> tuple[Scheduler, GlobalSchedulerStateStore]:
    store = GlobalSchedulerStateStore(tmp_path / "global_scheduler_state.json")
    store.register_role_catalog(
        [{"role_id": "A", "display_name": "ROLE_A"},
         {"role_id": "B", "display_name": "ROLE_B"}],
        active_role_id=active_role_id,
    )
    scheduler = Scheduler(RuleBrain(), v2_registry(), Executor(), global_state_store=store)
    scheduler._schedule = {}
    return scheduler, store


def _role(role_id, *, now, decision, goals=(), switch_cost=0.0, world=None):
    return RoleObservation(
        role_id=role_id,
        confirmed_role_id=role_id,
        world=world if world is not None else WorldState(page=Page.HOME, timestamp=now.isoformat()),
        observed_at=now,
        decision=decision,
        goals=tuple(goals),
        switch_cost=switch_cost,
    )


def _goal(goal_id, skill, value, *, status=GoalStatus.READY, remaining_seconds=None):
    return GoalState(
        goal_id=goal_id,
        status=status,
        reward_value=value,
        remaining_seconds=remaining_seconds,
        available_skills=(skill,),
    )


def _board_row(role_id: str, goals) -> dict:
    """The shape Scheduler publishes in ``role_statuses``, built here without the loop."""
    def status(goal):
        return str(getattr(getattr(goal, "status", ""), "value", goal.status)).upper()

    registry = v2_registry()
    runnable = [g for g in goals if status(g) in {"READY", "DISCOVERED", "RUNNABLE"}]
    return {
        "role_id": role_id,
        "ready_goal_count": len(runnable),
        "runnable_goal_count": sum(
            1 for g in runnable
            if any(registry.get(str(skill)) is not None for skill in (g.available_skills or ()))
        ),
        "waiting_goal_count": sum(1 for g in goals if status(g) == "SCHEDULED_NOT_OPEN"),
        "blocked_count": sum(1 for g in goals
                             if status(g) in {"BLOCKED", "UNKNOWN", "DEFERRED",
                                              "WAITING_GAME_CONDITION"}),
        "capability_gap_count": 0,
        "board_goal_ids": [str(g.goal_id) for g in goals],
        "board_settled_goal_ids": [str(g.goal_id) for g in goals
                                   if status(g) in {"IN_PROGRESS", "COMPLETE"}],
        "board_runnable_goal_ids": [str(g.goal_id) for g in runnable],
    }


def _session_with_board(role_id: str, goals) -> RoleSessionState:
    """A session that has already folded one board -- the realistic steady state."""
    session = new_session(role_id, at=NOW - timedelta(minutes=12))
    row = _board_row(role_id, goals)
    session.note_board(goal_ids=row["board_goal_ids"],
                       settled_goal_ids=row["board_settled_goal_ids"],
                       runnable_goal_ids=row["board_runnable_goal_ids"])
    session.ready_now = row["ready_goal_count"]
    session.runnable_now = row["runnable_goal_count"]
    return session


# ------------------------------------------------------- §4 gate conditions

def test_gate_allows_a_switch_when_nothing_is_runnable():
    gate = evaluate_role_session_gate(
        None, current_role_id="A", runnable_now=0, ready_now=0,
        waiting_now=1, blocked_now=2,
    )
    assert gate.allowed
    assert gate.reason_class == NO_RUNNABLE_WORK
    # C is the same fact: nothing runnable, only parked work.
    assert gate.detail == "ONLY_PARKED_WORK_LEFT"


def test_gate_locks_the_session_while_the_batch_is_unfinished():
    goals = [
        _goal("TRAIN", "TRAIN_TROOPS", 100),
        _goal("RESEARCH", "RESEARCH", 100),
        _goal("INTEL", "INTEL_CLAIM_REWARDS", 100),
    ]
    session = _session_with_board("A", goals)
    gate = evaluate_role_session_gate(
        session, current_role_id="A", runnable_now=3, ready_now=3,
    )
    assert not gate.allowed
    assert gate.detail == "ROLE_SESSION_ACTIVE"
    assert gate.reason_class == ""


def test_gate_allows_once_the_batch_is_mostly_done():
    """Directive §5's own example: 10 discovered, 8 done/started, 1 READY, 1 WAIT."""
    goals = [_goal(f"G{i}", "TRAIN_TROOPS", 100, status=GoalStatus.IN_PROGRESS) for i in range(1, 9)]
    goals.append(_goal("G9", "TRAIN_TROOPS", 100))
    goals.append(_goal("G10", "TRAIN_TROOPS", 100, status=GoalStatus.SCHEDULED_NOT_OPEN))
    session = _session_with_board("A", goals)

    gate = evaluate_role_session_gate(
        session, current_role_id="A", runnable_now=1, ready_now=1, waiting_now=1,
    )

    assert session.completion_ratio == pytest.approx(0.8)
    assert gate.allowed
    assert gate.reason_class == SESSION_COMPLETE
    assert gate.detail == "FINISH_CURRENT_ROLE_BATCH"


def test_mostly_done_still_needs_a_small_ready_tail():
    """A high ratio with a large READY tail is not "mostly done" (directive §15)."""
    goals = [_goal(f"S{i}", "TRAIN_TROOPS", 100, status=GoalStatus.IN_PROGRESS)
             for i in range(9)]
    goals.extend([_goal(f"R{i}", "TRAIN_TROOPS", 100) for i in range(5)])
    session = _session_with_board("A", goals)

    gate = evaluate_role_session_gate(
        session, current_role_id="A", runnable_now=5, ready_now=5,
    )

    assert session.completion_ratio == pytest.approx(9 / 14)
    assert not gate.allowed


def test_no_work_streak_ends_the_session():
    """D: repeated schedulings that found nothing runnable."""
    session = RoleSessionState(role_id="A", started_at=NOW.isoformat(), no_work_streak=2,
                              session_goal_ids=["G1"], session_done_goal_ids=[])
    gate = evaluate_role_session_gate(
        session, current_role_id="A", runnable_now=1, ready_now=1,
    )
    assert gate.allowed
    assert gate.detail == "NO_WORK_STREAK"
    assert gate.reason_class == NO_RUNNABLE_WORK


def test_a_recurring_goal_acted_on_but_still_ready_is_not_consumed_batch():
    """The pathological case the directive's ratio must not reward.

    One Goal, tapped, still READY afterwards (training/research recur).  A naive
    8/8 = 100% would hand the device away after a single action; the numerator excludes
    anything still sitting in the runnable set, so the session stays locked.
    """
    session = RoleSessionState(role_id="A", started_at=NOW.isoformat())
    session.note_board(goal_ids=["KEEP_TRAINING_PRODUCTIVE"],
                       settled_goal_ids=["KEEP_TRAINING_PRODUCTIVE"],
                       runnable_goal_ids=["KEEP_TRAINING_PRODUCTIVE"])
    session.goals_completed = 1
    session.actions_verified = 1

    gate = evaluate_role_session_gate(
        session, current_role_id="A", runnable_now=1, ready_now=1,
    )

    assert session.completion_ratio == 0.0
    assert not gate.allowed


def test_a_newly_discovered_goal_joins_this_sessions_denominator():
    goals = [_goal("G1", "TRAIN_TROOPS", 100, status=GoalStatus.IN_PROGRESS),
             _goal("G2", "TRAIN_TROOPS", 100, status=GoalStatus.IN_PROGRESS)]
    session = _session_with_board("A", goals)
    assert len(session.session_goal_ids) == 2
    assert session.completion_ratio == pytest.approx(1.0)

    # A third Goal appears mid-session. It joins the batch, so the ratio drops and the
    # session does NOT end on the stale 2/2.
    session.note_board(goal_ids=["G1", "G2", "G3"],
                       settled_goal_ids=["G1", "G2"], runnable_goal_ids=["G3"])

    assert len(session.session_goal_ids) == 3
    assert session.completion_ratio == pytest.approx(2 / 3)
    gate = evaluate_role_session_gate(
        session, current_role_id="A", runnable_now=1, ready_now=1,
    )
    assert not gate.allowed


def test_policy_defaults_match_the_directives_first_version():
    assert ROLE_SESSION_POLICY_DEFAULTS["mostly_done_ratio"] == 0.75
    assert ROLE_SESSION_POLICY_DEFAULTS["max_ready_before_switch"] == 2
    assert ROLE_SESSION_POLICY_DEFAULTS["no_work_streak_to_end_session"] == 2
    # §15: retained as a floor only, raised from 120 to 300.
    assert ROLE_SESSION_POLICY_DEFAULTS["min_role_dwell_seconds"] == 300.0
    assert ROLE_SESSION_POLICY_DEFAULTS["switch_margin"] == 30.0


def test_overrides_merge_onto_the_defaults_and_ignore_junk():
    resolved = resolve_policy({"mostly_done_ratio": 0.5, "note": "prose", "switch_margin": "bad"})
    assert resolved["mostly_done_ratio"] == 0.5
    assert resolved["switch_margin"] == 30.0
    assert resolved["min_role_dwell_seconds"] == 300.0


# --------------------------------------------- §3/§10/§11 through the Scheduler

def test_a_higher_scoring_ordinary_goal_cannot_take_the_device(tmp_path):
    """Directive §3's forbidden behaviour, asserted directly.

    ``ROLE_A TRAIN = 200`` and ``ROLE_B TRAIN = 5000`` -- B clears the margin many times
    over, and the dwell long expired.  A still has runnable work, so A keeps the device.
    """
    now = NOW
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("A_TRAIN", "TRAIN_TROOPS", 200),)),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 5000),), switch_cost=0.0),
    )
    scheduler, store = _scheduler(tmp_path, "A")

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(hours=1), min_role_dwell_seconds=300,
    )

    assert selected.role_id == "A"
    assert selected.switch_reason_class == ""
    assert not selected.session_gate["allowed"]
    assert "ROLE_SESSION_LOCKED" in selected.selection_reason
    b_candidate = next(row for row in selected.candidate_explanations
                       if row["role_id"] == "B")
    assert b_candidate["rejected_reason"] == "role_session_locked"
    # The store folded the arbitration into the session, so the panel and the gate agree.
    assert not store.load().role_session.switch_allowed


def test_dwell_expiry_alone_is_not_a_licence_to_switch(tmp_path):
    """§10: the dwell guard is a floor, not a permit."""
    now = NOW
    goals = [_goal("A_TRAIN", "TRAIN_TROOPS", 200)]
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=tuple(goals)),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 9000),)),
    )
    scheduler, _ = _scheduler(tmp_path, "A")
    session = _session_with_board("A", goals)

    for age in (timedelta(seconds=10), timedelta(minutes=30)):
        selected = scheduler.select_global(
            roles, current_role_id="A", now=now,
            last_switch_at=now - age, min_role_dwell_seconds=300,
            role_session=session,
        )
        assert selected.role_id == "A"
        assert selected.switch_reason_class == ""


def test_session_end_is_followed_by_cross_role_arbitration(tmp_path):
    """§12: A finishes its batch -> SESSION_END -> then the global choice is made."""
    now = NOW
    goals = [
        _goal("A_R1", "RESEARCH", 50, status=GoalStatus.IN_PROGRESS),
        _goal("A_B1", "BUILDING_UPGRADE", 50, status=GoalStatus.IN_PROGRESS),
        _goal("A_I1", "INTEL_CLAIM_REWARDS", 50, status=GoalStatus.IN_PROGRESS),
        _goal("A_T1", "TRAIN_TROOPS", 50),
    ]
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=tuple(goals)),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 100000),)),
    )
    scheduler, _ = _scheduler(tmp_path, "A")
    session = _session_with_board("A", goals)

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(hours=1), role_session=session,
    )

    assert selected.session_gate["allowed"] is True
    assert selected.session_gate["detail"] == "FINISH_CURRENT_ROLE_BATCH"
    assert selected.role_id == "B"
    assert selected.switch_reason_class == SESSION_COMPLETE
    assert "ROLE_SESSION_END(FINISH_CURRENT_ROLE_BATCH)" in selected.selection_reason


def test_session_end_still_needs_the_move_to_be_worth_its_cost(tmp_path):
    """§11: ``switch_margin`` now only decides worth after the gate allowed the move."""
    now = NOW
    goals = [
        _goal("A_R1", "RESEARCH", 50, status=GoalStatus.IN_PROGRESS),
        _goal("A_B1", "BUILDING_UPGRADE", 50, status=GoalStatus.IN_PROGRESS),
        _goal("A_I1", "INTEL_CLAIM_REWARDS", 50, status=GoalStatus.IN_PROGRESS),
        _goal("A_T1", "TRAIN_TROOPS", 50),
    ]
    # B is better, but not by the margin -- so the session ends and A still keeps the device.
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=tuple(goals)),
        _role("B", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "claim", 1, "claimed"),
              goals=(_goal("B_DAILY", "DAILY_CLAIM_REWARDS", 55),)),
    )
    scheduler, _ = _scheduler(tmp_path, "A")
    session = _session_with_board("A", goals)

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(hours=1), role_session=session,
        switch_margin=30.0,
    )

    assert selected.session_gate["allowed"] is True
    assert selected.role_id == "A"
    assert "switch gain is below" in selected.selection_reason


# -------------------------------------------------- §14 one failure is not the end

def test_one_failed_goal_does_not_end_the_role_session(tmp_path):
    """§14: TRAIN fails -> CAPABILITY_GAP/DEFER -> A carries on with RESEARCH etc."""
    now = NOW
    goals = [
        _goal("A_TRAIN", "TRAIN_TROOPS", 100),
        _goal("A_RESEARCH", "RESEARCH", 100),
        _goal("A_INTEL", "INTEL_CLAIM_REWARDS", 100),
        _goal("A_MAIL", "MAIL_CLAIM_REWARDS", 100),
    ]
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "camp_busy", 1, "training"),
              goals=tuple(goals)),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 90000),)),
    )
    scheduler, store = _scheduler(tmp_path, "A")

    # The failed action is recorded exactly as the runtime records it: no completed goals,
    # verifier FAIL.  It must not advance the session's numerator.
    store.record_action_outcome({
        "action_id": "run:1", "role_id": "A", "skill_id": "TRAIN_TROOPS",
        "action_sent": True, "verifier_result": "FAIL", "completed_goal_ids": [],
    })
    session = store.load().role_session
    assert session.goals_completed == 0
    assert session.actions_verified == 0

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(hours=2),
    )

    assert selected.role_id == "A"
    assert "ROLE_SESSION_LOCKED" in selected.selection_reason


def test_a_verified_action_advances_the_session_counters(tmp_path):
    _, store = _scheduler(tmp_path, "A")
    store.record_action_outcome({
        "action_id": "run:2", "role_id": "A", "skill_id": "RESEARCH",
        "action_sent": True, "verifier_result": "PASS", "completed_goal_ids": ["KEEP_RESEARCH_PRODUCTIVE"],
    })
    session = store.load().role_session
    assert session.goals_completed == 1
    assert session.actions_verified == 1
    assert "KEEP_RESEARCH_PRODUCTIVE" in session.session_goal_ids


def test_another_roles_verified_action_does_not_credit_this_session(tmp_path):
    _, store = _scheduler(tmp_path, "A")
    store.record_action_outcome({
        "action_id": "run:3", "role_id": "B", "skill_id": "RESEARCH",
        "action_sent": True, "verifier_result": "PASS", "completed_goal_ids": ["X"],
    })
    session = store.load().role_session
    assert session.role_id == "A"
    assert session.goals_completed == 0


# --------------------------------------------------- §7/§8 preemption behaviour

def test_a_real_deadline_preempts_an_active_session(tmp_path):
    """§7: limited-time work is the ONE thing allowed to break a session."""
    now = NOW
    goals = [_goal("A_TRAIN", "TRAIN_TROOPS", 200)]
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=tuple(goals)),
        _role("B", now=now, decision=Decision("START_RALLY", "rally", 1, "rally"),
              goals=(_goal("B_BEAR", "START_RALLY", 10, remaining_seconds=272),)),
    )
    scheduler, _ = _scheduler(tmp_path, "A")
    session = _session_with_board("A", goals)

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(seconds=5), min_role_dwell_seconds=300,
        role_session=session,
    )

    assert selected.role_id == "B"
    assert selected.switch_reason_class == HARD_EVENT_PREEMPT
    assert "HARD_EVENT_PREEMPT" in selected.selection_reason
    # The session really was locked -- the deadline overrode it, it did not "allow" it.
    assert selected.session_gate["allowed"] is False
    assert selected.session_gate["detail"] == "ROLE_SESSION_ACTIVE"


def test_fishing_is_an_ordinary_activity_and_does_not_preempt(tmp_path):
    """§8: bait in hand is not a deadline.  B waits for A's session to end."""
    now = NOW
    goals = [
        _goal("A_TRAIN", "TRAIN_TROOPS", 100),
        _goal("A_RESEARCH", "RESEARCH", 100),
    ]
    roles = (
        _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=tuple(goals)),
        # The fishing tournament Goal carries value but no deadline: the registry gives
        # FISHING_TOURNAMENT no start/end, so nothing can classify it as a hard event.
        _role("B", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "bait", 1, "fished"),
              goals=(_goal("FISHING_TOURNAMENT_USE_BAIT", "DAILY_CLAIM_REWARDS", 90000),)),
    )
    scheduler, _ = _scheduler(tmp_path, "A")
    session = _session_with_board("A", goals)

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now, role_session=session,
        last_switch_at=now - timedelta(hours=3),
    )

    assert selected.role_id == "A"
    assert selected.switch_reason_class == ""
    assert selected.session_gate["allowed"] is False
    assert not selected.session_gate["hard_event"] if "hard_event" in selected.session_gate else True


def test_an_inactive_role_is_not_switched_to_only_for_a_look(tmp_path):
    """§9: no A -> observe B -> nothing -> back to A.  B must wait for real work."""
    now = NOW
    goals = [_goal("A_TRAIN", "TRAIN_TROOPS", 100)]
    active = _role("A", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
                   goals=tuple(goals))
    # B is registered but has never been observed (the classic "switch over and look").
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None,
        observed_at=now - timedelta(hours=3), needs_initial_refresh=True,
    )
    scheduler, _ = _scheduler(tmp_path, "A")
    session = _session_with_board("A", goals)

    selected = scheduler.select_global(
        (active, inactive), current_role_id="A", now=now, role_session=session,
        last_switch_at=now - timedelta(hours=1),
    )

    assert selected.role_id == "A"
    assert selected.requires_role_refresh is False
    assert "ROLE_SESSION_LOCKED" in selected.selection_reason


def test_a_stale_current_role_releases_the_device(tmp_path):
    """The lock protects real work, not an unobserved role: nothing runnable -> switch."""
    now = NOW
    active = _role("A", now=now, decision=Decision("SAFE_STOP", "no_work", 1, "wait"))
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None, observed_at=now - timedelta(minutes=2),
        goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 500),),
    )
    scheduler, _ = _scheduler(tmp_path, "A")

    selected = scheduler.select_global((active, inactive), current_role_id="A", now=now)

    assert selected.role_id == "B"
    assert selected.requires_role_refresh is True
    assert selected.switch_reason_class == NO_RUNNABLE_WORK


# ------------------------------------------------------ §17 reason classification

def test_a_bare_score_difference_is_not_a_switch_reason():
    assert classify_switch_reason("higher global value (TRAIN_TROOPS)") == ""
    assert classify_switch_reason("KEEP_CURRENT_ROLE: switch gain is below 30.0") == ""


def test_switch_reasons_fold_into_the_fixed_classes():
    assert classify_switch_reason("HARD_EVENT_PREEMPT for START_RALLY") == HARD_EVENT_PREEMPT
    assert classify_switch_reason("SWITCH A→B: ROLE_SESSION_END(FINISH_CURRENT_ROLE_BATCH)") \
        == SESSION_COMPLETE
    assert classify_switch_reason("SWITCH A→B: ROLE_SESSION_END(NO_WORK_STREAK)") \
        == NO_RUNNABLE_WORK
    assert classify_switch_reason("SWITCH A→B: current role has no fresh runnable Goal") \
        == NO_RUNNABLE_WORK
    assert classify_switch_reason("ROLE_SWITCH_FAILED:DEVICE_LEASE") == "ENVIRONMENT"


def test_switch_quality_metrics_report_per_hour_and_averages():
    history = [
        {"at": "2026-09-30T00:00:00+00:00", "reason_class": SESSION_COMPLETE,
         "duration_seconds": 1800.0, "goals_completed": 8},
        {"at": "2026-09-30T01:00:00+00:00", "reason_class": HARD_EVENT_PREEMPT,
         "duration_seconds": 900.0, "goals_completed": 4},
    ]
    metrics = role_switch_quality_metrics(switch_history=history,
                                         session=RoleSessionState(role_id="A", goals_completed=3))
    assert metrics["role_switches_per_hour"] == pytest.approx(2.0)
    assert metrics["avg_role_session_duration_seconds"] == pytest.approx(1350.0)
    assert metrics["avg_goals_per_role_session"] == pytest.approx(6.0)
    assert metrics["last_switch_reasons"] == [SESSION_COMPLETE, HARD_EVENT_PREEMPT]
    assert metrics["current_session_goals_completed"] == 3


# ------------------------------------------------------- §2 storage discipline

def test_the_session_state_is_logical_only(tmp_path):
    """Directive §2: never a dynamic bbox, a page coordinate, or an old-frame target."""
    _, store = _scheduler(tmp_path, "A")
    store.record_decision(decision={
        "decision": "KEEP_ROLE", "current_role_id": "A",
        "role_statuses": [{"role_id": "A", "ready_goal_count": 2, "runnable_goal_count": 2,
                           "blocked_count": 0, "waiting_goal_count": 0, "capability_gap_count": 0,
                           "board_goal_ids": ["G1", "G2"],
                           "board_settled_goal_ids": [],
                           "board_runnable_goal_ids": ["G1", "G2"],
                           # Live fields a caller might mistakenly forward: filtered out.
                           "bbox": [1, 2, 3, 4], "tap_point": [10, 20], "frame": "x.png"}],
        "session_gate": {"allowed": False, "detail": "ROLE_SESSION_ACTIVE"},
    })
    raw = json.loads((tmp_path / "global_scheduler_state.json").read_text(encoding="utf-8"))
    session = raw["role_session"]
    for forbidden in ("bbox", "tap_point", "frame", "frame_path", "coordinates", "ocr_tokens"):
        assert forbidden not in session
    assert session["role_id"] == "A"
    assert session["runnable_now"] == 2
    assert session["no_work_streak"] == 0


def test_a_no_runnable_scheduling_increments_the_streak(tmp_path):
    _, store = _scheduler(tmp_path, "A")
    for _ in range(2):
        store.record_decision(decision={
            "decision": "GLOBAL_WAIT", "current_role_id": "A",
            "role_statuses": [{"role_id": "A", "ready_goal_count": 0, "runnable_goal_count": 0,
                               "blocked_count": 3, "waiting_goal_count": 1,
                               "capability_gap_count": 0,
                               "board_goal_ids": ["G1", "G2", "G3", "G4"],
                               "board_settled_goal_ids": [], "board_runnable_goal_ids": []}],
            "session_gate": {"allowed": True, "detail": "ONLY_PARKED_WORK_LEFT",
                             "reason_class": NO_RUNNABLE_WORK},
        })
    session = store.load().role_session
    assert session.no_work_streak == 2
    assert session.switch_allowed is True
    assert session.switch_reason == "ONLY_PARKED_WORK_LEFT"


# ------------------------------------------------------------ lifecycle + panel

def test_a_committed_switch_archives_the_session_and_opens_a_new_one(tmp_path):
    _, store = _scheduler(tmp_path, "A")
    store.record_action_outcome({
        "action_id": "run:9", "role_id": "A", "skill_id": "RESEARCH",
        "action_sent": True, "verifier_result": "PASS", "completed_goal_ids": ["KEEP_RESEARCH"],
    })
    store.begin_role_switch(source_role_id="A", target_role_id="B",
                            reason="SWITCH A→B: ROLE_SESSION_END(FINISH_CURRENT_ROLE_BATCH)",
                            reason_class=SESSION_COMPLETE)
    store.commit_role_switch(confirmed_role_id="B", elapsed_ms=42000.0)

    state = store.load()
    assert state.role_session.role_id == "B"
    assert state.role_session.goals_completed == 0
    assert len(state.role_switch_history) == 1
    archived = state.role_switch_history[0]
    assert archived["source_role_id"] == "A"
    assert archived["target_role_id"] == "B"
    assert archived["reason_class"] == SESSION_COMPLETE
    assert archived["goals_completed"] == 1
    assert archived["duration_seconds"] is not None


def test_a_switch_without_a_source_session_does_not_rewrite_an_earlier_history_row(tmp_path):
    """``role_switch_history[-1]`` must never mean "some older switch".

    When there was no session to archive, the commit appends nothing -- so writing the
    target onto ``[-1]`` would silently rewrite a *previous* switch's record.
    """
    _, store = _scheduler(tmp_path, "A")
    store.begin_role_switch(source_role_id="A", target_role_id="B",
                            reason="SWITCH A→B: ROLE_SESSION_END(FINISH_CURRENT_ROLE_BATCH)",
                            reason_class=SESSION_COMPLETE)
    store.commit_role_switch(confirmed_role_id="B")
    first = dict(store.load().role_switch_history[0])
    assert first["target_role_id"] == "B"

    state = store.load()
    state.role_session = None
    store.save(state)

    store.begin_role_switch(source_role_id="B", target_role_id="A",
                            reason="SWITCH B→A: current role has no fresh runnable Goal",
                            reason_class=NO_RUNNABLE_WORK)
    store.commit_role_switch(confirmed_role_id="A")

    history = store.load().role_switch_history
    assert len(history) == 1
    assert history[0] == first


def test_an_aborted_switch_keeps_the_source_session(tmp_path):
    """A failed transition leaves the device where it was, so the batch continues."""
    _, store = _scheduler(tmp_path, "A")
    started = store.load().role_session.started_at
    store.record_action_outcome({
        "action_id": "run:11", "role_id": "A", "skill_id": "RESEARCH",
        "action_sent": True, "verifier_result": "PASS", "completed_goal_ids": ["KEEP_RESEARCH"],
    })
    store.begin_role_switch(source_role_id="A", target_role_id="B",
                            reason="ROLE_SESSION_END", reason_class=SESSION_COMPLETE)
    store.abort_role_switch(actual_role_id="A", reason="PROFILE_AVATAR_NOT_LOCATED")

    session = store.load().role_session
    assert session.role_id == "A"
    assert session.started_at == started
    assert session.goals_completed == 1
    assert store.load().role_switch_history == []


def test_a_restart_on_the_same_account_keeps_the_session(tmp_path):
    _, store = _scheduler(tmp_path, "A")
    started = store.load().role_session.started_at
    store.recover_after_restart(actual_role_id="A", actual_role_name="ROLE_A",
                               observed_at=NOW + timedelta(minutes=5))
    assert store.load().role_session.started_at == started


def test_a_restart_on_a_different_account_starts_a_fresh_session(tmp_path):
    _, store = _scheduler(tmp_path, "A")
    store.recover_after_restart(actual_role_id="B", actual_role_name="ROLE_B",
                               observed_at=NOW + timedelta(minutes=5))
    session = store.load().role_session
    assert session.role_id == "B"
    assert session.goals_completed == 0


def test_the_panel_shows_the_real_session_and_the_pending_preemption(tmp_path):
    """§16: dwell, completed/discovered, ratio, READY/WAIT, LOCKED/ALLOWED, reason."""
    from tools.control_panel import global_scheduler_display

    (tmp_path / "learning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge/roles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge/roles/role_inventory.json").write_text(json.dumps({
        "roles": [{"role_id": "A", "role_key": "ROLE_A"},
                  {"role_id": "B", "role_key": "ROLE_B"}],
    }, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "learning/global_scheduler_state.json").write_text(json.dumps({
        "active_role_id": "A",
        "last_decision": {
            "decision": "KEEP_ROLE", "current_role_id": "A", "selected_role_id": "A",
            "role_statuses": [
                {"role_id": "A", "top_goal": "KEEP_TRAINING_PRODUCTIVE", "runnable_count": 3,
                 "blocked_count": 2, "state_fresh": True},
                {"role_id": "B", "top_goal": "START_RALLY", "runnable_count": 1,
                 "blocked_count": 0, "state_fresh": False},
            ],
            "session_gate": {
                "allowed": False, "detail": "ROLE_SESSION_ACTIVE",
                "description": "current role still owns 3 runnable Goal(s)",
                "goals_discovered": 10, "goals_consumed": 8, "completion_ratio": 0.8,
                "ready_now": 1, "waiting_now": 1, "session_elapsed_seconds": 754.0,
            },
            "hard_event_roles": [{"role_id": "B", "skill_id": "START_RALLY",
                                  "event_starts_in_seconds": 272.0}],
        },
        "role_session": {"role_id": "A", "session_goal_count": 10,
                         "session_done_goal_count": 8, "completion_ratio": 0.8},
        "role_switch_history": [
            {"at": "2026-09-30T00:00:00+00:00", "target_role_id": "A",
             "reason_class": "HARD_EVENT_PREEMPT", "duration_seconds": 900.0,
             "goals_completed": 7},
            {"at": "2026-09-30T01:00:00+00:00", "target_role_id": "B",
             "reason_class": "SESSION_COMPLETE", "duration_seconds": 1500.0,
             "goals_completed": 11},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    view = global_scheduler_display(tmp_path)

    assert "ROLE_A" in view["session"]
    assert "12m34s" in view["session"]
    assert "8/10" in view["session"]
    assert "80%" in view["session"]
    assert "READY 1" in view["session"]
    assert "WAIT 1" in view["session"]
    assert "切换 LOCKED" in view["session"]
    assert "ROLE_SESSION_ACTIVE" in view["session"]
    assert "ROLE_B HARD EVENT: START_RALLY" in view["preempt"]
    assert "PREEMPT_PENDING" in view["preempt"]
    assert "ROLE_SWITCHES_PER_HOUR" in view["switch_quality"]
    assert "平均驻留 20m00s" in view["switch_quality"]


def test_the_panel_says_so_when_no_session_exists_yet(tmp_path):
    from tools.control_panel import global_scheduler_display

    (tmp_path / "learning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge/roles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge/roles/role_inventory.json").write_text(
        json.dumps({"roles": [{"role_id": "A", "role_key": "ROLE_A"}]}), encoding="utf-8")
    (tmp_path / "learning/global_scheduler_state.json").write_text(
        json.dumps({"active_role_id": "A"}), encoding="utf-8")

    view = global_scheduler_display(tmp_path)

    assert "尚未建立角色Session" in view["session"]
    assert "暂无跨角色限时抢占评估" in view["preempt"]
