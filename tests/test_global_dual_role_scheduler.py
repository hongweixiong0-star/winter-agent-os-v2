from datetime import datetime, timedelta, timezone

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.executor import Executor
from winter_agent_v2.goal_library import (
    GoalState, GoalStatus, GoalStateStore, newly_completed_goal_ids,
)
from winter_agent_v2.models import Action, Decision, ExecutionResult, Page, VerificationResult, WorldState
from winter_agent_v2.scheduler import ActiveRoleLiveState, RoleObservation, Scheduler
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2 import event_schedule


def _scheduler(global_state_store=None) -> Scheduler:
    scheduler = Scheduler(RuleBrain(), v2_registry(), Executor(),
                          global_state_store=global_state_store)
    scheduler._schedule = {}
    return scheduler


def _role(role_id, *, now, decision, goals=(), next_action_at=None,
          confirmed_role_id=None, switch_cost=0.0):
    world = WorldState(page=Page.HOME, timestamp=now.isoformat())
    return RoleObservation(
        role_id=role_id,
        confirmed_role_id=confirmed_role_id or role_id,
        world=world,
        observed_at=now,
        decision=decision,
        goals=tuple(goals),
        next_action_at=next_action_at,
        switch_cost=switch_cost,
    )


def _goal(goal_id, skill, value, *, remaining_seconds=None):
    return GoalState(
        goal_id=goal_id,
        status=GoalStatus.READY,
        reward_value=value,
        remaining_seconds=remaining_seconds,
        available_skills=(skill,),
        evidence={"progress": {"current": 2, "target": 4}},
    )


def test_role_a_waiting_selects_role_b_runnable_goal():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    roles = (
        _role("A", now=now, decision=Decision("SAFE_STOP", "research_wait_40m", 1, "wait"),
              next_action_at=now + timedelta(minutes=40)),
        _role("B", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "daily_ready", 1, "claimed"),
              goals=(_goal("DAILY_REWARD", "DAILY_CLAIM_REWARDS", 250),)),
    )

    selected = _scheduler().select_next(roles, current_role_id="A", now=now)

    assert selected.role_id == "B"
    assert selected.goal_id == "DAILY_REWARD"
    assert selected.selection_reason.startswith("SWITCH A→B")


def test_role_a_failure_does_not_stop_role_b():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    roles = (
        _role("A", now=now, decision=Decision("SAFE_STOP", "skill_failed", 1, "switch_task")),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "training_ready", 1, "training"),
              goals=(_goal("KEEP_TRAINING_PRODUCTIVE", "TRAIN_TROOPS", 100),)),
    )

    selected = _scheduler().select_global(roles, current_role_id="A", now=now)

    assert selected.role_id == "B"
    assert selected.decision.skill == "TRAIN_TROOPS"
    assert any("skill_failed" in item.reason for item in selected.skipped)


def test_other_roles_t5_event_overrides_minimum_dwell_and_switch_cost():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    scheduler = _scheduler()
    scheduler._schedule = {
        "A|BEAR_HUNT": event_schedule.RoleSchedule(
            role_id="A", event_id="BEAR_HUNT",
            reserved_start=(now + timedelta(minutes=4)).isoformat(),
            source="LIVE_CLIENT",
        )
    }
    roles = (
        _role("A", now=now, decision=Decision("START_RALLY", "bear_t5", 1, "rally_started"),
              goals=(_goal("PARTICIPATE_BEAR", "START_RALLY", 100),), switch_cost=10000),
        _role("B", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "daily_ready", 1, "claimed"),
              goals=(_goal("DAILY_REWARD", "DAILY_CLAIM_REWARDS", 1000),)),
    )

    selected = scheduler.select_global(
        roles, current_role_id="B", now=now,
        last_switch_at=now - timedelta(seconds=5), min_role_dwell_seconds=180,
    )

    assert selected.role_id == "A"
    assert "hard deadline/event phase" in selected.selection_reason


def test_global_wait_uses_earliest_role_wakeup():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    roles = (
        _role("A", now=now, decision=Decision("SAFE_STOP", "all_goals_waiting", 1, "wait"),
              next_action_at=now + timedelta(minutes=20)),
        _role("B", now=now, decision=Decision("SAFE_STOP", "no_runnable_goal", 1, "wait"),
              next_action_at=now + timedelta(minutes=7)),
    )

    scheduler = _scheduler()
    scheduler.goals.discover = lambda *_args, **_kwargs: ()
    selected = scheduler.select_global(roles, current_role_id="A", now=now)

    assert selected.index is None
    assert selected.decision.reason == "GLOBAL_WAIT"
    assert selected.next_wakeup == (now + timedelta(minutes=7)).isoformat()


def test_recent_inactive_logical_board_allows_global_wait_without_authorizing_an_action():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    active = _role("A", now=now,
                   decision=Decision("SAFE_STOP", "all_goals_waiting", 1, "wait"),
                   next_action_at=now + timedelta(minutes=20))
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None,
        observed_at=now - timedelta(minutes=4),
        goals=(GoalState("B_DONE", GoalStatus.COMPLETE),),
        next_action_at=now + timedelta(minutes=7),
    )

    scheduler = _scheduler()
    scheduler.goals.discover = lambda *_args, **_kwargs: ()
    selected = scheduler.select_global((active, inactive), current_role_id="A", now=now)

    assert selected.index is None
    assert selected.decision.reason == "GLOBAL_WAIT"
    assert selected.next_wakeup == (now + timedelta(minutes=7)).isoformat()
    assert selected.role_statuses[1]["logical_snapshot_usable"] is True


def test_failed_switch_cooldown_waits_until_retry_and_does_not_report_missing_brain_candidate():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    active = _role("A", now=now,
                   decision=Decision("SAFE_STOP", "current_role_has_no_work", 1, "wait"))
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None,
        observed_at=now - timedelta(minutes=2),
        goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 500),),
        switch_blocked_until=now + timedelta(seconds=15),
        failure_streak=1,
    )

    scheduler = _scheduler()
    # This test isolates switch-backoff behavior. The minimal HOME world fixture
    # otherwise causes GoalLibrary to infer unrelated runnable goals.
    scheduler.goals.discover = lambda *_args, **_kwargs: ()
    during_backoff = scheduler.select_global((active, inactive), current_role_id="A", now=now)
    after_backoff = scheduler.select_global(
        (active, inactive), current_role_id="A", now=now + timedelta(seconds=16),
    )

    assert during_backoff.index is None
    assert during_backoff.decision.reason == "GLOBAL_WAIT"
    assert during_backoff.next_wakeup == (now + timedelta(seconds=15)).isoformat()
    assert during_backoff.role_statuses[1]["switch_cooldown_active"] is True
    assert after_backoff.role_id == "B"
    assert after_backoff.requires_role_refresh is True


def test_role_refresh_request_still_switches_when_inactive_role_has_no_cached_board():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    active = _role("A", now=now,
                   decision=Decision("SAFE_STOP", "all_goals_waiting", 1, "wait"))
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None,
        observed_at=now - timedelta(hours=2), needs_initial_refresh=True,
    )

    selected = _scheduler().select_global((active, inactive), current_role_id="A", now=now)

    assert selected.role_id == "B"
    assert selected.requires_role_refresh is True
    assert selected.index is None


def test_role_dwell_suppresses_ordinary_switch_but_measured_gain_can_switch_after_dwell():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    roles = (
        _role("A", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "claim", 1, "claimed"),
              goals=(_goal("A_DAILY", "DAILY_CLAIM_REWARDS", 200),)),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("B_TRAINING", "TRAIN_TROOPS", 500),), switch_cost=80),
    )
    scheduler = _scheduler()

    within_dwell = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(seconds=20), min_role_dwell_seconds=120,
    )
    after_dwell = scheduler.select_global(
        roles, current_role_id="A", now=now,
        last_switch_at=now - timedelta(minutes=5), min_role_dwell_seconds=120,
    )

    assert within_dwell.role_id == "A"
    assert within_dwell.selection_reason.startswith("KEEP_CURRENT_ROLE")
    assert after_dwell.role_id == "B"
    assert after_dwell.selection_reason.startswith("SWITCH A→B")


def test_stale_or_mismatched_role_state_cannot_be_dispatched():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    wrong_identity = _role(
        "A", now=now, confirmed_role_id="B",
        decision=Decision("TRAIN_TROOPS", "stale_account_action", 1, "training"),
        goals=(_goal("TRAINING", "TRAIN_TROOPS", 100),),
    )
    old = _role(
        "B", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "stale_frame", 1, "claimed"),
        goals=(_goal("DAILY", "DAILY_CLAIM_REWARDS", 100),),
    )
    old = RoleObservation(**{
        **old.__dict__,
        "observed_at": now - timedelta(minutes=6),
    })

    selected = _scheduler().select_global((wrong_identity, old), now=now)

    assert selected.index is None
    assert "role_identity_not_confirmed" in " ".join(item.reason for item in selected.skipped)
    assert "role_observation_stale" in " ".join(item.reason for item in selected.skipped)


def test_shared_action_credits_all_matching_goals_in_one_dispatch():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    roles = (_role(
        "A", now=now, decision=Decision("TRAIN_TROOPS", "training_action", 1, "training"),
        goals=(
            _goal("KEEP_TRAINING_PRODUCTIVE", "TRAIN_TROOPS", 100),
            _goal("DAILY_TRAINING", "TRAIN_TROOPS", 80),
            _goal("ALLIANCE_MOBILIZATION", "TRAIN_TROOPS", 60),
        ),
    ),)

    selected = _scheduler().select_global(roles, current_role_id="A", now=now)

    assert selected.goal_id == "KEEP_TRAINING_PRODUCTIVE"
    assert selected.credited_goal_ids == (
        "KEEP_TRAINING_PRODUCTIVE", "DAILY_TRAINING", "ALLIANCE_MOBILIZATION",
    )


def test_live_mobilization_provider_goal_competes_in_the_existing_global_pool():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    from winter_agent_v2.goal_library import GoalLibrary

    event = {
        "recognized": True,
        "status": "ACTIVE",
        "role_id": "B",
        "source": "LIVE_CLIENT_OCR",
        "tasks": [{
            "task_id": "mobi-training-120k",
            "task_type": "TROOP_TRAINING_120K",
            "status": "ACCEPTED",
            "accepted": True,
            "progress": 0,
            "target": 120000,
        }],
    }
    b_world = WorldState(page=Page.HOME, timestamp=now.isoformat(),
                         events={"alliance_mobilization": event})
    b_goal = next(
        goal for goal in GoalLibrary().discover(b_world, role_id="B")
        if goal.goal_id == "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K"
    )
    roles = (
        _role("A", now=now,
              decision=Decision("DAILY_CLAIM_REWARDS", "ordinary daily", 1, "claimed"),
              goals=(_goal("A_DAILY", "DAILY_CLAIM_REWARDS", 250),)),
        RoleObservation(
            role_id="B", confirmed_role_id="B", world=b_world, observed_at=now,
            decision=Decision("TRAIN_TROOPS", "mobilization training task", 1, "training_started"),
            goals=(b_goal,),
        ),
    )

    selected = _scheduler().select_global(roles, current_role_id="A", now=now)

    assert selected.role_id == "B"
    assert selected.decision.skill == "TRAIN_TROOPS"
    assert selected.goal_id == "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K"
    assert selected.credited_goal_ids == ("ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K",)


def test_runtime_preflight_waits_nonwinners_without_marking_winner_attempted():
    class Pool:
        def __init__(self):
            self.attempted_skills = []
            self.waiting_skills = []

        def eligible(self, _skill):
            return True

        def starved(self, _skill):
            return False

        def attempted(self, skill):
            self.attempted_skills.append(skill.id)

        def wait_cycle(self, skill):
            self.waiting_skills.append(skill.id)

    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    pool = Pool()
    scheduler = Scheduler(RuleBrain(), v2_registry(), Executor(), candidate_pool=pool)
    scheduler._schedule = {}
    roles = (
        _role("A", now=now, decision=Decision("DAILY_CLAIM_REWARDS", "claim", 1, "claimed"),
              goals=(_goal("A_REWARD", "DAILY_CLAIM_REWARDS", 500),)),
        _role("B", now=now, decision=Decision("TRAIN_TROOPS", "train", 1, "training"),
              goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 400),)),
    )

    selected = scheduler.select_global(
        roles, current_role_id="A", now=now, mark_candidate_attempts=False,
    )

    assert selected.role_id == "A"
    assert pool.attempted_skills == []
    assert pool.waiting_skills == ["TRAIN_TROOPS"]


def test_runtime_builds_active_live_and_other_role_cached_observations_separately(tmp_path):
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    store = GoalStateStore(tmp_path / "goal_state.json")
    role_a_goal = _goal("A_RESEARCH", "OPEN_RESEARCH", 100)
    role_b_goal = _goal("B_REWARD", "DAILY_CLAIM_REWARDS", 200)
    store.write(WorldState(page=Page.HOME, timestamp=now.isoformat()), (role_a_goal,), role_id="A")
    store.write(WorldState(page=Page.DAILY, timestamp=now.isoformat()), (role_b_goal,), role_id="B")

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = True
    runtime.role_id = "A"
    runtime.role_scope = "FRESH_RUNTIME"
    runtime.role_catalog = ({"role_id": "A"}, {"role_id": "B"})
    runtime._role_catalog_by_id = {"A": {"role_id": "A"}, "B": {"role_id": "B"}}
    runtime.role_switch_cost = 30.0
    runtime.goal_store = store
    runtime.global_scheduler_state_store = None
    active_world = WorldState(page=Page.HOME, timestamp=now.isoformat())

    observations = runtime._global_role_observations(
        active_world, (role_a_goal,), Decision("OPEN_RESEARCH", "active", 1, "research"),
        role_switch_cost=45.0,
    )

    assert [row.role_id for row in observations] == ["A", "B"]
    assert observations[0].world is active_world
    assert observations[0].goals == (role_a_goal,)
    assert observations[1].world is None
    assert observations[1].goals[0].goal_id == "B_REWARD"
    assert observations[1].confirmed_role_id == "B"
    assert observations[0].switch_cost == 0.0
    assert observations[1].switch_cost == 45.0


def test_runtime_goal_discovery_passes_confirmed_role_and_live_calendar_snapshot():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    captured = {}

    class Library:
        def discover(self, world, **kwargs):
            captured.update(kwargs)
            return ()

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._record_observations = lambda *_args, **_kwargs: None
    runtime._observations_for_engine = lambda: {}
    runtime._calendar_role_id = lambda: "B"
    runtime.goal_library = Library()
    runtime.goal_store = None
    world = WorldState(
        page=Page.HOME,
        timestamp=now.isoformat(),
        events={"calendar": {"recognized": True, "entries": [{"event_id": "BEAR_HUNT"}]}},
    )

    runtime._record_goals(world)

    assert captured["role_id"] == "B"
    assert captured["calendar_snapshot"]["role_id"] == "B"
    assert captured["calendar_snapshot"]["entries"][0]["event_id"] == "BEAR_HUNT"


def test_runtime_persists_shared_action_outcome_and_episode_progress_by_goal(tmp_path):
    from types import SimpleNamespace

    from winter_agent_v2.global_scheduler_state import GlobalSchedulerStateStore
    from winter_agent_v2.learning import EpisodeStore

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = True
    runtime._calendar_role_id = lambda: "A"
    runtime.global_scheduler_state_store = GlobalSchedulerStateStore(tmp_path / "global.json")
    runtime.episode_store = EpisodeStore(tmp_path / "episodes.jsonl")
    runtime.capture_dir = tmp_path / "episode-42"
    runtime.device = SimpleNamespace(capture_backend="MAA")
    runtime.code_revision = "test-revision"
    runtime.role_id = "A"
    runtime.role_scope = "FRESH_RUNTIME"
    runtime.execution_mode = "PRODUCTION"
    runtime.trace_id = runtime.job_id = runtime.capability = runtime.expected_after_version = ""
    runtime._fold_control_experience = lambda **_kwargs: None
    runtime._collect_ui_evidence = lambda **_kwargs: None
    runtime._collect_page_evidence = lambda **_kwargs: None

    before = WorldState(page=Page.HOME)
    after = WorldState(page=Page.HOME)
    runtime._record_episode(
        decision=Decision("TRAIN_TROOPS", "shared training", 1.0, "training started"),
        before=before,
        execution=ExecutionResult(True, False, Action("TAP", "BTN_TRAIN"), backend="MAA"),
        after=after,
        verification=VerificationResult(True, "verified", evidence={"change": "TRAINING_STARTED"}),
        started_at=0.0,
        step_id=3,
        goal_id="KEEP_TRAINING_PRODUCTIVE",
        goal_progress=True,
        attached_goal_ids=("KEEP_TRAINING_PRODUCTIVE", "DAILY_TRAINING"),
        goal_progress_by_id={"KEEP_TRAINING_PRODUCTIVE": True, "DAILY_TRAINING": False},
        completed_goal_ids=("KEEP_TRAINING_PRODUCTIVE",),
    )

    state = runtime.global_scheduler_state_store.load()
    outcome = state.latest_action_outcome
    episode = __import__("json").loads((tmp_path / "episodes.jsonl").read_text(encoding="utf-8"))

    assert outcome["action_sent"] is True
    assert outcome["post_action_observed"] is True
    assert outcome["verifier_result"] == "PASS"
    assert outcome["credited_goal_ids"] == ["KEEP_TRAINING_PRODUCTIVE"]
    assert outcome["goal_progress_by_id"]["DAILY_TRAINING"] is False
    assert episode["attached_goal_ids"] == ["KEEP_TRAINING_PRODUCTIVE", "DAILY_TRAINING"]
    assert episode["goal_progress_by_id"] == {
        "KEEP_TRAINING_PRODUCTIVE": True, "DAILY_TRAINING": False,
    }


def test_completed_goal_credit_counts_only_a_verified_status_transition():
    before = (
        GoalState("NEWLY_DONE", GoalStatus.IN_PROGRESS),
        GoalState("ALREADY_DONE", GoalStatus.COMPLETE),
        GoalState("UNKNOWN_BEFORE", GoalStatus.UNKNOWN),
    )
    after = (
        GoalState("NEWLY_DONE", GoalStatus.COMPLETE),
        GoalState("ALREADY_DONE", GoalStatus.COMPLETE),
        GoalState("UNKNOWN_BEFORE", GoalStatus.COMPLETE),
        GoalState("NO_BASELINE", GoalStatus.COMPLETE),
    )

    assert newly_completed_goal_ids(
        before, after,
        ("NEWLY_DONE", "ALREADY_DONE", "UNKNOWN_BEFORE", "NO_BASELINE"),
    ) == ("NEWLY_DONE",)


def test_switch_cost_uses_measured_median_latency_with_a_safe_cap():
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_switch_cost = 30.0
    measured = type("Measured", (), {"role_switch_durations_ms": [42000, 91000, 65000]})()
    slow = type("Slow", (), {"role_switch_durations_ms": [200000, 300000]})()

    assert runtime._measured_role_switch_cost(measured) == 65.0
    assert runtime._measured_role_switch_cost(slow) == 180.0
    assert runtime._measured_role_switch_cost(None) == 30.0


def test_cached_countdown_becomes_role_scoped_global_wakeup(tmp_path):
    now = datetime.now(timezone.utc)
    store = GoalStateStore(tmp_path / "goal_state.json")
    waiting_goal = GoalState(
        "B_TRAINING", GoalStatus.BLOCKED, remaining_seconds=420,
        available_skills=(), retry_after="00:07:00",
        evidence={"condition": "queue_busy"},
    )
    store.write(WorldState(page=Page.TRAINING, timestamp=now.isoformat()),
                (waiting_goal,), role_id="B")

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = True
    runtime.role_id = "A"
    runtime.role_scope = "FRESH_RUNTIME"
    runtime.role_catalog = ({"role_id": "A"}, {"role_id": "B"})
    runtime._role_catalog_by_id = {"A": {"role_id": "A"}, "B": {"role_id": "B"}}
    runtime.role_switch_cost = 30.0
    runtime.goal_store = store
    runtime.global_scheduler_state_store = None

    observations = runtime._global_role_observations(
        WorldState(page=Page.HOME, timestamp=now.isoformat()), (),
        Decision("SAFE_STOP", "no_action", 1, "wait"),
    )
    wake = datetime.fromisoformat(str(observations[1].next_action_at))

    assert abs((wake - (now + timedelta(minutes=7))).total_seconds()) < 2


def test_role_switch_invalidates_every_live_ui_field_until_new_identity_observed():
    state = ActiveRoleLiveState()
    state.switch_to("A")
    state.observe("A", {"page": "HOME", "frame": "a.png", "queue_state": {"research": "IDLE"}})

    invalidated = state.switch_to("B")

    assert set(invalidated) == set(state.invalidated_fields)
    assert all(state.live.get(field) is None for field in state.invalidated_fields)
    with pytest.raises(ValueError, match="does not match active role"):
        state.observe("A", {"page": "HOME"})
    assert all(state.live.get(field) is None for field in state.invalidated_fields)


def test_runtime_requires_a_fresh_avatar_match_before_using_role_scoped_state():
    class Controller:
        def identify_current_role(self, _frame):
            return None

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = False
    runtime._role_identity_bootstrapped = False
    runtime.role_id = "A"  # persisted startup hint is not a live confirmation
    runtime.role_scope = "FRESH_RUNTIME"
    runtime.role_switch_controller = Controller()
    runtime._role_catalog_by_id = {"A": {"role_id": "A"}, "B": {"role_id": "B"}}
    runtime.global_scheduler_state_store = None
    runtime._activate_role_persistent_state = lambda _role_id: None

    ok, reason = runtime._confirm_live_role("frame.png")

    assert not ok
    assert reason == "ROLE_IDENTITY_UNCONFIRMED"
    assert runtime._calendar_role_id() == ""


def test_runtime_retains_confirmed_role_when_modal_occludes_avatar_within_same_run():
    class Controller:
        def __init__(self):
            self.matches = iter([("A", 0.94), None])

        def identify_current_role(self, _frame):
            return next(self.matches)

    class Store:
        def __init__(self):
            self.recovered = []

        def recover_after_restart(self, **values):
            self.recovered.append(values)

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = False
    runtime._role_identity_bootstrapped = False
    runtime.role_id = "B"
    runtime.role_scope = "UNKNOWN"
    runtime.role_switch_controller = Controller()
    runtime._role_catalog_by_id = {
        "A": {"role_id": "A", "display_name": "Role A"},
        "B": {"role_id": "B", "display_name": "Role B"},
    }
    runtime.global_scheduler_state_store = Store()
    runtime._activate_role_persistent_state = lambda _role_id: None

    first_ok, first_reason = runtime._confirm_live_role("visible-avatar.png")
    second_ok, second_reason = runtime._confirm_live_role("modal-blurred-avatar.png")

    assert first_ok and first_reason == "ROLE_IDENTITY_CONFIRMED"
    assert second_ok and second_reason == "ROLE_IDENTITY_RETAINED_FRAME_UNREADABLE"
    assert runtime._calendar_role_id() == "A"
    assert runtime.global_scheduler_state_store.recovered == [{
        "actual_role_id": "A",
        "actual_role_name": "Role A",
        "observed_at": runtime.global_scheduler_state_store.recovered[0]["observed_at"],
    }]


def test_runtime_stops_if_a_different_role_avatar_is_uniquely_observed_mid_run():
    class Controller:
        def __init__(self):
            self.matches = iter([("A", 0.94), ("B", 0.96)])

        def identify_current_role(self, _frame):
            return next(self.matches)

    class Store:
        def __init__(self):
            self.recovered = []

        def recover_after_restart(self, **values):
            self.recovered.append(values)

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = False
    runtime._role_identity_bootstrapped = False
    runtime.role_id = "A"
    runtime.role_scope = "UNKNOWN"
    runtime.role_switch_controller = Controller()
    runtime._role_catalog_by_id = {"A": {"role_id": "A"}, "B": {"role_id": "B"}}
    runtime.global_scheduler_state_store = Store()
    runtime._activate_role_persistent_state = lambda _role_id: None

    assert runtime._confirm_live_role("role-a.png")[0]
    ok, reason = runtime._confirm_live_role("role-b.png")

    assert not ok
    assert reason == "ROLE_IDENTITY_CHANGED:B"
    assert runtime.role_id == "B"
    assert runtime.global_scheduler_state_store.recovered[-1]["actual_role_id"] == "B"


def test_goal_schedule_view_exposes_expected_cross_role_fields():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    role = _role(
        "A", now=now, decision=Decision("TRAIN_TROOPS", "training_action", 1, "training"),
        goals=(_goal("TRAINING", "TRAIN_TROOPS", 100, remaining_seconds=60),),
    )
    selected = _scheduler().select_global((role,), current_role_id="A", now=now)

    assert selected.goal_id == "TRAINING"
    assert selected.score is not None
    assert selected.credited_goal_ids == ("TRAINING",)
    metrics = selected.goal_metrics[0]
    assert metrics.role_id == "A"
    assert metrics.ready_now is True
    assert metrics.deadline == (now + timedelta(seconds=60)).isoformat()
    assert metrics.progress == 0.5
    assert selected.role_statuses[0]["top_goal"] == "TRAINING"


def test_inactive_cached_goal_can_only_request_switch_and_fresh_observation():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None, observed_at=now,
        goals=(_goal("B_DAILY", "DAILY_CLAIM_REWARDS", 500),),
    )
    active = _role(
        "A", now=now,
        decision=Decision("SAFE_STOP", "research_wait", 1, "wait"),
        next_action_at=now + timedelta(minutes=20),
    )

    selected = _scheduler().select_global((active, inactive), current_role_id="A", now=now)

    assert selected.role_id == "B"
    assert selected.goal_id == "B_DAILY"
    assert selected.requires_role_refresh is True
    assert selected.requested_skill == "DAILY_CLAIM_REWARDS"
    assert selected.index is None
    assert selected.decision.skill == "SAFE_STOP"
    assert "observe" in selected.decision.expected_result


def test_inactive_cached_state_older_than_refresh_window_cannot_select_role():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None,
        observed_at=now - timedelta(hours=2),
        goals=(_goal("B_TRAIN", "TRAIN_TROOPS", 10000),),
    )
    active = _role(
        "A", now=now,
        decision=Decision("SAFE_STOP", "nothing_ready", 1, "wait"),
    )

    selected = _scheduler().select_global((active, inactive), current_role_id="A", now=now)

    assert selected.index is None
    assert selected.role_id == ""
    assert selected.requires_role_refresh is False


def test_cached_role_deadline_pressure_overrides_role_dwell():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    active = _role(
        "A", now=now,
        decision=Decision("DAILY_CLAIM_REWARDS", "claim", 1, "claimed"),
        goals=(_goal("A_DAILY", "DAILY_CLAIM_REWARDS", 10),),
    )
    inactive = RoleObservation(
        role_id="B", confirmed_role_id="B", world=None, observed_at=now,
        goals=(_goal("B_BEAR", "START_RALLY", 1, remaining_seconds=240),),
        switch_cost=100000,
    )

    selected = _scheduler().select_global(
        (active, inactive), current_role_id="A", now=now,
        last_switch_at=now - timedelta(seconds=5), min_role_dwell_seconds=600,
    )

    assert selected.role_id == "B"
    assert selected.requires_role_refresh is True
    assert "hard deadline" in selected.selection_reason


def test_global_wait_is_forbidden_when_a_registered_ready_goal_has_no_brain_candidate():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    role = _role(
        "A", now=now,
        decision=Decision("SAFE_STOP", "brain_has_no_action", 1, "wait"),
        goals=(_goal("READY_TRAINING", "TRAIN_TROOPS", 10),),
    )

    selected = _scheduler().select_global((role,), current_role_id="A", now=now)

    assert selected.index is None
    assert selected.decision.reason == "GLOBAL_CANDIDATE_GENERATION_GAP"
    assert selected.decision.reason != "GLOBAL_WAIT"


def test_global_decision_log_persists_candidates_and_selection_reason(tmp_path):
    from winter_agent_v2.global_scheduler_state import GlobalSchedulerStateStore

    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    store = GlobalSchedulerStateStore(tmp_path / "global_scheduler_state.json")
    roles = (
        _role("A", now=now, decision=Decision("SAFE_STOP", "wait", 1, "wait")),
        _role("B", now=now,
              decision=Decision("DAILY_CLAIM_REWARDS", "ready", 1, "claimed"),
              goals=(_goal("B_REWARD", "DAILY_CLAIM_REWARDS", 250),)),
    )

    selected = _scheduler(store).select_global(roles, current_role_id="A", now=now)
    last = store.load().last_decision

    assert selected.role_id == "B"
    assert last["decision"] == "SWITCH_ROLE"
    assert last["selected_goal_id"] == "B_REWARD"
    assert "SWITCH A→B" in last["reason"]
    assert any(row["selected"] for row in last["candidates"])
