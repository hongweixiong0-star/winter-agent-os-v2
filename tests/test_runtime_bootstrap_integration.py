"""Safe discovery uses the real production Goal/role arbitration path.

All runtime stores and frames belong to tmp_path. No device, model, production
lease, or live mutable store is used by these regressions.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from winter_agent_v2 import runtime as runtime_module
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.capability_gate import CapabilityGate, Deferral
from winter_agent_v2.executor import Executor
from winter_agent_v2.goal_library import GoalLibrary, GoalState, GoalStatus, route_for
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.ui_venus_online import FrameIdentity


ARENA_GOAL = "USE_FREE_ARENA_ATTEMPTS"


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    # Use the production methods without LiveRuntime.__init__ loading live assets.
    runtime = object.__new__(LiveRuntime)
    runtime.registry = v2_registry()
    runtime.brain = RuleBrain()
    runtime.role_id = "A"
    runtime.role_scope = "FRESH_RUNTIME"
    runtime._multi_role_enabled = True
    runtime._role_identity_confirmed = True
    runtime._role_catalog_by_id = {"A": {"role_id": "A"}, "B": {"role_id": "B"}}
    runtime.role_switch_cost = 20.0
    runtime.goal_store = None
    runtime.global_scheduler_state_store = None
    runtime.episode_store = None
    runtime.bootstrap_state_path = tmp_path / "bootstrap.json"
    runtime._bootstrap_cooldowns = {}
    runtime._yielded_goals = set()
    runtime.capability_gate = CapabilityGate.empty()
    runtime.execution_mode = "PRODUCTION"
    runtime.device_lease = None
    runtime._policy_allows = Mock(return_value=True)
    runtime._runtime = Mock()
    runtime._ocr_service = Mock(return_value=object())
    runtime._quick_panel_advice_regions = Mock(return_value=([], []))
    runtime._resolve_semantic_target = Mock(return_value=None)
    runtime._record_session_timeline = Mock()
    frame = tmp_path / "fresh-frame.png"
    frame.write_bytes(b"isolated current screenshot bytes")
    now = datetime.now(timezone.utc)
    world = WorldState(page=Page.HOME, confidence=0.99, timestamp=now.isoformat())
    entry = {"id": "CURRENT_ARENA", "kind": "INTERACTIVE_CONTROL",
             "executable": True, "semantic": "ARENA_ENTRY", "text": "竞技场"}
    table = Mock(return_value=[entry])
    monkeypatch.setattr(runtime_module.ui_collection, "build_element_table", table)
    unknown = GoalState(ARENA_GOAL, GoalStatus.UNKNOWN, evidence={
        "role_id": "A", "required_observation": "current arena attempts",
        "missing_page_identity": True,
    })
    return SimpleNamespace(runtime=runtime, frame=frame, world=world, now=now,
                           unknown=unknown, entry=entry, table=table)


def projected(discovery, goals=None):
    return discovery.runtime._project_capability_discovery(
        goals if goals is not None else [discovery.unknown], discovery.world, discovery.frame)


def scheduler_for(discovery):
    scheduler = Scheduler(discovery.runtime.brain, discovery.runtime.registry, Executor())
    scheduler._schedule = {}  # Never read production event reservations.
    return scheduler


def test_unrouted_arena_discovery_reaches_real_rank_and_global_scheduler(discovery):
    runtime = discovery.runtime
    assert route_for(ARENA_GOAL) is None
    goals = projected(discovery)
    arena = goals[0]
    assert arena.goal_id == ARENA_GOAL
    assert arena.status is GoalStatus.DISCOVERED
    assert arena.available_skills == ("TRY_ORDINARY_CONTROL",)
    assert arena.evidence["bootstrap_participation_authorized"] is False
    assert arena.evidence["bootstrap_entry_label"] == "竞技场"
    assert arena.evidence["bootstrap_frame_id"] == FrameIdentity.of(discovery.frame).frame_id

    board = GoalLibrary().rank(runtime._selectable(goals, []), discovery.world, fairness={})
    assert board[0][0].goal_id == ARENA_GOAL
    runtime._sync_brain_goal(board[0][0], runtime._gate())
    assert runtime.brain.current_goal is None  # No invented production route.
    assert runtime.brain.goal_id == ARENA_GOAL
    decision = runtime._bootstrap_decision(board[0][0], discovery.world)
    roles = runtime._global_role_observations(discovery.world, goals, decision)
    selected = scheduler_for(discovery).select_global(
        roles, current_role_id="A", now=discovery.now, mark_candidate_attempts=False)
    assert selected.role_id == "A"
    assert selected.goal_id == ARENA_GOAL
    assert selected.decision.skill == "TRY_ORDINARY_CONTROL"
    assert selected.requires_role_refresh is False
    assert ARENA_GOAL in selected.credited_goal_ids


def test_known_ready_work_keeps_priority_despite_one_bounded_learning_window(discovery):
    known = GoalState("MAIL_ROUTINE", GoalStatus.READY, reward_value=10000,
                      available_skills=("OPEN_MAIL",))
    goals = projected(discovery, [discovery.unknown, known])
    assert goals[1] is known
    assert discovery.table.call_count == 1  # Current once/run policy prepares discovery.
    board = GoalLibrary().rank(discovery.runtime._selectable(goals, []),
                               discovery.world, fairness={})
    assert board[0][0] is known
    assert discovery.runtime._bootstrap_decision(known, discovery.world) is None
    assert "bootstrap_stage" not in known.evidence
    # Preparing the next board must not pay for a second full element-table scan.
    projected(discovery, [discovery.unknown, known])
    assert discovery.table.call_count == 1


@pytest.mark.parametrize("changes", [
    {"role_id": "B"}, {"frame_id": "stale"}, {"kind": "TEXT_LABEL"},
    {"executable": False},
])
def test_current_role_and_interactive_frame_identity_are_required(discovery, changes):
    discovery.table.return_value = [{**discovery.entry, **changes}]
    arena = projected(discovery)[0]
    assert arena is discovery.unknown
    assert arena.status is GoalStatus.UNKNOWN
    assert discovery.runtime._bootstrap_diagnostics[0]["reason"] == "MISSING_OBSERVATION"


def test_unconfirmed_role_does_not_even_collect_entry_candidates(discovery):
    discovery.runtime._role_identity_confirmed = False
    assert projected(discovery)[0] is discovery.unknown
    discovery.table.assert_not_called()


def test_disabled_goal_cannot_enter_discovery_or_scheduler(discovery):
    discovery.runtime._policy_allows.return_value = False
    goals = projected(discovery)
    assert goals[0] is discovery.unknown
    assert discovery.runtime._bootstrap_diagnostics[0]["reason"] == "POLICY_DISABLED"
    assert discovery.runtime._selectable(goals, []) == []


@pytest.mark.parametrize("state,reload_pending,expected", [
    ("COOLDOWN", False, True), ("DEVELOPMENT_PENDING", False, False),
    ("BLOCKED", True, False),
])
def test_bootstrap_only_lifts_local_gap_not_development_or_reload_gate(
    discovery, state, reload_pending, expected,
):
    arena = projected(discovery)[0]
    gate = CapabilityGate.empty()
    gate.reload_pending = reload_pending
    gate.blocks = Mock(return_value=Deferral(ARENA_GOAL, state, "confirmed blocker"))
    discovery.runtime.capability_gate = gate
    deferrals = []
    selected = discovery.runtime._selectable([arena], deferrals)
    assert bool(selected) is expected
    assert bool(deferrals) is not expected


def test_attempt_budget_is_persisted_only_to_test_store_and_blocks_reentry(discovery):
    arena = projected(discovery)[0]
    discovery.runtime._mark_bootstrap_attempt(arena)
    assert discovery.runtime.bootstrap_state_path.exists()
    assert discovery.runtime._bootstrap_cooldowns["__run__"]["visits_this_run"] == 1
    assert discovery.runtime._bootstrap_cooldowns["A|" + ARENA_GOAL]["attempts_this_run"] == 1
    assert projected(discovery)[0] is discovery.unknown
    assert discovery.runtime._bootstrap_diagnostics[0]["reason"] == "BOOTSTRAP_COOLDOWN"


def test_bootstrap_ordinary_target_cannot_fall_through_to_unrelated_whitelist(discovery):
    runtime = discovery.runtime
    arena = projected(discovery)[0]
    runtime._sync_brain_goal(arena, runtime._gate())
    runtime._committed_goal = ARENA_GOAL
    runtime._ordinary_last = {"semantic": "PREVIOUS_GOAL_CONTROL"}
    runtime._l1_context = {"goal": "PREVIOUS_GOAL"}
    runtime._advised_request_id = "previous-model-request"
    runtime._advised_learn_context = {"goal": "PREVIOUS_GOAL"}
    runtime._advised_control = Mock(return_value=None)
    runtime._declared_textless_control_point = Mock(return_value=(0.1, 0.1))
    runtime._ordinary_word_order = Mock(return_value=("领取", "返回"))
    assert runtime._ordinary_control_candidate(discovery.world, discovery.frame) is None
    runtime._advised_control.assert_called_once()
    runtime._declared_textless_control_point.assert_not_called()
    runtime._ordinary_word_order.assert_not_called()
    assert runtime._unknown_semantic_target == ""
    assert not runtime._ordinary_last
    assert not runtime._l1_context
    assert runtime._advised_request_id == ""
    assert runtime._advised_learn_context == {}


def test_model_budget_exhaustion_still_allows_same_goal_learned_reuse(discovery):
    runtime = discovery.runtime
    arena = projected(discovery)[0]
    runtime._sync_brain_goal(arena, runtime._gate())
    runtime._committed_goal = ARENA_GOAL
    runtime._bootstrap_context["model_calls_this_screen"] = 2
    runtime._advisor = Mock()
    runtime._learned_reuse_point = Mock(return_value=(0.4, 0.5))
    assert runtime._advised_control("HOME", "", discovery.frame, discovery.world, unnamed=False) == (0.4, 0.5)
    assert runtime._learned_reuse_point.call_args.args[2] == ARENA_GOAL
    assert runtime._bootstrap_context["model_calls_this_screen"] == 2
    assert runtime._advisor.mock_calls == []
    # When no current-frame learned target remains, budget exhaustion must defer.
    runtime._learned_reuse_point.return_value = None
    assert runtime._advised_control("HOME", "", discovery.frame, discovery.world, unnamed=False) is None
    assert runtime._advisor.mock_calls == []


def test_bootstrap_advice_identity_gate_rejects_other_function_and_spend(discovery):
    runtime = discovery.runtime
    arena = projected(discovery)[0]
    runtime._sync_brain_goal(arena, runtime._gate())
    advice = SimpleNamespace(target_semantics="ARENA_ENTRY", grounding_ref="CURRENT_ARENA",
                             raw={"action_level": "ENTRY_CONTROL"})
    assert runtime._advice_risk(advice, {"text": "领取", "detail": {}}) == (
        "BOOTSTRAP_SAFE_ENTRY_IDENTITY_MISMATCH")
    assert runtime._advice_risk(advice, {"text": "竞技场", "detail": {"semantic": "ARENA_ENTRY"}}) == ""
    assert runtime._advice_risk(advice, {"text": "确认", "detail": {"semantic": "ARENA_ENTRY"}}) == (
        "BOOTSTRAP_RESOURCE_ACTION_NOT_AUTHORIZED")


def test_bootstrap_different_role_or_goal_never_resolves_click(discovery):
    runtime = discovery.runtime
    arena = projected(discovery)[0]
    runtime._sync_brain_goal(arena, runtime._gate())
    runtime._committed_goal = "OTHER_GOAL"
    runtime._advised_control = Mock(return_value=(0.4, 0.5))
    assert runtime._ordinary_control_candidate(discovery.world, discovery.frame) is None
    runtime._committed_goal = ARENA_GOAL
    runtime.role_id = "B"
    assert runtime._ordinary_control_candidate(discovery.world, discovery.frame) is None
    runtime._advised_control.assert_not_called()
