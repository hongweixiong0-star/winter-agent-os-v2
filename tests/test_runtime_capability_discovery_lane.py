from datetime import datetime, timedelta, timezone

import pytest

from winter_agent_v2.capability_bootstrap import project_runtime_discovery
from winter_agent_v2.goal_library import GoalState, GoalStatus
from winter_agent_v2.models import Page, WorldState


NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


def project(goal=None, *, step=None, elements=None, **kwargs):
    goal = goal or GoalState("UNLEARNED_FREE_FEATURE", GoalStatus.UNKNOWN,
                            evidence={"role_id": "A", "required_observation": "live feature state"})
    step = step if step is not None else {
        "skill_id": "TRY_ORDINARY_CONTROL", "action_type": "OPEN", "target_id": "E1",
        "semantic_target": "FEATURE_DETAILS", "frame_id": "fresh", "role_id": "A",
    }
    elements = elements if elements is not None else [{
        "id": "E1", "kind": "INTERACTIVE_CONTROL", "executable": True,
        "semantic": "FEATURE_DETAILS", "frame_id": "fresh", "role_id": "A",
    }]
    args = dict(role_id="A", frame_id="fresh", current_frame_elements=elements,
                safe_steps_by_goal={goal.goal_id: step}, registry_ids={step["skill_id"]},
                verifier_bindings={step["skill_id"]}, now=NOW)
    args.update(kwargs)
    return project_runtime_discovery([goal], WorldState(page=Page.HOME), **args)


def test_missing_skill_goal_becomes_same_goal_safe_discovery_candidate():
    result = project()
    goal = result.goals[0]
    assert goal.goal_id == "UNLEARNED_FREE_FEATURE"
    assert goal.status is GoalStatus.DISCOVERED
    assert goal.available_skills == ("TRY_ORDINARY_CONTROL",)
    assert result.diagnostics[0]["reason"] == "BOOTSTRAP_READY"
    assert goal.evidence["bootstrap_original_status"] == "UNKNOWN"
    assert goal.evidence["bootstrap_gap"] == "OBSERVATION_GAP"
    assert goal.evidence["bootstrap_role_id"] == "A"
    assert goal.evidence["bootstrap_frame_id"] == "fresh"
    assert goal.evidence["bootstrap_budget"]["max_model_calls"] == 2
    assert goal.evidence["bootstrap_budget"]["max_navigation_steps"] == 4
    assert goal.evidence["bootstrap_participation_authorized"] is False


def test_observation_does_not_need_click_target_but_still_binds_current_frame():
    step = {"skill_id": "READ_CURRENT_FEATURE", "action_type": "OBSERVE",
            "frame_id": "fresh", "role_id": "A"}
    assert project(step=step, elements=[]).diagnostics[0]["reason"] == "BOOTSTRAP_READY"
    assert project(step={**step, "frame_id": "old"}, elements=[]).diagnostics[0]["reason"] == "MISSING_OBSERVATION"


@pytest.mark.parametrize("changed", [
    {"frame_id": "old"}, {"role_id": "B"}, {"executable": False}, {"kind": "TEXT_LABEL"},
    {"semantic": "OTHER_FEATURE"},
])
def test_stale_other_role_label_or_other_target_cannot_be_bootstrap(changed):
    element = {"id": "E1", "kind": "INTERACTIVE_CONTROL", "executable": True,
               "semantic": "FEATURE_DETAILS", "frame_id": "fresh", "role_id": "A", **changed}
    result = project(elements=[element])
    assert result.goals[0].status is GoalStatus.UNKNOWN
    assert result.diagnostics[0]["reason"] == "MISSING_OBSERVATION"


def test_packet_element_frame_mismatch_is_not_current_frame():
    result = project(elements={"frame_id": "old", "role_id": "A", "elements": []})
    assert result.goals[0].status is GoalStatus.UNKNOWN


@pytest.mark.parametrize("action", ["ATTACK", "START_RALLY", "JOIN_RALLY", "TRAIN", "USE_ITEM", "PURCHASE", "RECALL"])
def test_bootstrap_does_not_authorize_consumption_or_rally(action):
    step = {"skill_id": action, "action_type": action, "frame_id": "fresh", "role_id": "A"}
    assert project(step=step).goals[0].status is GoalStatus.UNKNOWN


def test_mislabeled_safe_action_cannot_enable_actual_rally_skill():
    step = {"skill_id": "START_RALLY", "action_type": "OPEN", "frame_id": "fresh", "role_id": "A",
            "target_id": "E1", "semantic_target": "FEATURE_DETAILS"}
    assert project(step=step).goals[0].status is GoalStatus.UNKNOWN


def test_unknown_event_window_only_receives_observation_not_ready_participation():
    goal = GoalState("SCHEDULED_NEW_EVENT", GoalStatus.UNKNOWN, remaining_seconds=60,
                     reward_value=5000, daily_loss=10000, event_synergy=5000,
                     evidence={"role_id": "A", "window": "UNKNOWN"})
    result = project(goal)
    projected = result.goals[0]
    assert projected.status is GoalStatus.DISCOVERED
    assert projected.remaining_seconds is None
    assert projected.priority == 20
    assert projected.evidence["bootstrap_participation_authorized"] is False
    assert goal.status is GoalStatus.UNKNOWN  # projection never mutates its input


@pytest.mark.parametrize("status,reason", [
    (GoalStatus.SCHEDULED_NOT_OPEN, "WAIT_UNTIL"),
    (GoalStatus.COMPLETE, "COMPLETE"), (GoalStatus.IN_PROGRESS, "WAIT_UNTIL"),
])
def test_wait_or_inflight_goal_is_not_reopened(status, reason):
    goal = GoalState("UNLEARNED_FREE_FEATURE", status)
    result = project(goal)
    assert result.goals[0] is goal
    assert result.diagnostics[0]["reason"] == reason


def test_disabled_goal_never_bootstraps_even_with_safe_control():
    result = project(disabled_goal_ids={"UNLEARNED_FREE_FEATURE"})
    assert result.diagnostics[0]["reason"] == "POLICY_DISABLED"
    assert result.goals[0].status is GoalStatus.UNKNOWN


def test_one_visit_per_run_and_cooldown_are_bounded():
    for ledger in ({"__run__": {"visits_this_run": 1}},
                   {"A|UNLEARNED_FREE_FEATURE": {"attempts_this_run": 1}},
                   {"A|UNLEARNED_FREE_FEATURE": {"cooldown_until": (NOW + timedelta(minutes=5)).isoformat()}}):
        result = project(cooldowns=ledger)
        assert result.diagnostics[0]["reason"] == "BOOTSTRAP_COOLDOWN"
        assert result.goals[0].status is GoalStatus.UNKNOWN


def test_model_calls_budget_does_not_disable_model_free_observation():
    step = {"skill_id": "READ_CURRENT_FEATURE", "action_type": "OBSERVE",
            "frame_id": "fresh", "role_id": "A"}
    ledger = {"A|UNLEARNED_FREE_FEATURE": {"model_calls_this_screen": 2}}
    assert project(step={**step, "model_required": True}, cooldowns=ledger).diagnostics[0]["reason"] == "BOOTSTRAP_COOLDOWN"
    assert project(step=step, cooldowns=ledger).diagnostics[0]["reason"] == "BOOTSTRAP_READY"


def test_known_runnable_goal_remains_original_production_work():
    goal = GoalState("MAIL_ROUTINE", GoalStatus.READY, reward_value=250,
                     available_skills=("MAIL_CLAIM_REWARDS",))
    result = project(goal, registry_ids={"MAIL_CLAIM_REWARDS"}, verifier_bindings={"MAIL_CLAIM_REWARDS"})
    assert result.goals[0] is goal
    assert result.diagnostics[0]["reason"] == "READY_EXECUTABLE"


def test_no_verifier_is_named_explicitly_without_fabricating_ready_work():
    goal = GoalState("MAIL_ROUTINE", GoalStatus.READY, available_skills=("MAIL_CLAIM_REWARDS",))
    result = project(goal, registry_ids={"MAIL_CLAIM_REWARDS"}, verifier_bindings=())
    assert result.diagnostics[0]["reason"] == "MISSING_VERIFIER"
    assert result.goals[0] is goal


def test_invalid_cooldown_does_not_grant_another_unbounded_attempt():
    result = project(cooldowns={"A|UNLEARNED_FREE_FEATURE": {"cooldown_until": "not-a-time"}})
    assert result.diagnostics[0]["reason"] == "BOOTSTRAP_COOLDOWN"


def test_confirmed_implementation_risk_remains_explicit_gap():
    goal = GoalState("UNLEARNED_FREE_FEATURE", GoalStatus.UNKNOWN,
                     evidence={"requires_implementation": True})
    result = project(goal)
    assert result.goals[0] is goal
    assert result.diagnostics[0]["reason"] == "RISK_BLOCKED"
    assert result.diagnostics[0]["gap_detail"] == "CAPABILITY_GAP_REQUIRES_IMPLEMENTATION"
