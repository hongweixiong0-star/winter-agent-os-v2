from dataclasses import replace
from unittest.mock import Mock

import pytest

from winter_agent_v2.models import Action, ExecutionResult, Page, VerificationResult, WorldState
from winter_agent_v2.semantic_executor import (
    ClickObservation, ClickOutcome, Pending, TargetEvidence,
    classify, world_action_still_pending as is_same_action_still_pending, retry_authorized_semantic_click,
)


def observed(*, frame="frame-1", world=None, target="same-target", success=False,
             authorized=True, pending=True, context="same-role-and-object"):
    return ClickObservation(
        world or WorldState(page=Page.MARCH, march_used=1, march_max=3), frame,
        TargetEvidence(target, True, context, pending) if target else None,
        VerificationResult(success, "PASS" if success else "POSTCONDITION_NOT_PROVEN"), authorized,
    )


def delivery(action):
    return ExecutionResult(True, False, action, backend="MAA", tap_point=(20, 30))


@pytest.mark.parametrize("semantic", [
    "OPEN_PAGE", "OPEN_BUILDING", "OPEN_BARRACK", "OPEN_RESEARCH", "TRAIN", "PROMOTE",
    "RESEARCH", "BUILD", "CLAIM", "DISPATCH", "ATTACK", "JOIN_RALLY", "START_RALLY",
    "USE_ITEM", "CONFIRM", "AUTHORIZED_PURCHASE",
])
def test_authorized_action_dropped_touch_is_relocated_and_verified(semantic):
    action = Action("TAP_SEMANTIC", semantic)
    before, after = observed(), observed(frame="frame-2")
    observe = Mock(side_effect=[observed(frame="frame-3"), observed(frame="frame-4", success=True)])
    execute = Mock(return_value=replace(delivery(action), tap_point=(40, 60)))
    result = retry_authorized_semantic_click(action=action, before=before, after=after,
        execution=delivery(action), observe=observe, execute=execute)
    assert result.outcome is ClickOutcome.SUCCESS
    assert result.metric == "CLICK_RETRY_SUCCESS"
    assert result.retries == 1
    assert execute.call_args.args[0].frame == "frame-3"
    assert result.attempts[0]["tap_point"] == (40, 60)


def test_two_retries_exhaust_and_preserve_each_fresh_frame():
    action = Action("TAP_SEMANTIC", "TRAIN")
    snapshots = [observed(frame=f"frame-{i}") for i in range(3, 7)]
    execute = Mock(return_value=delivery(action))
    result = retry_authorized_semantic_click(action=action, before=observed(), after=observed(),
        execution=delivery(action), observe=Mock(side_effect=snapshots), execute=execute)
    assert result.retries == 2 and execute.call_count == 2
    assert result.metric == "CLICK_RETRY_EXHAUSTED"
    assert [call.args[0].frame for call in execute.call_args_list] == ["frame-3", "frame-5"]


def test_late_success_on_pre_retry_frame_prevents_second_submission():
    action = Action("TAP_SEMANTIC", "DISPATCH")
    execute = Mock()
    result = retry_authorized_semantic_click(action=action, before=observed(), after=observed(),
        execution=delivery(action), observe=lambda: observed(success=True), execute=execute)
    assert result.metric == "CLICK_FIRST_TRY_SUCCESS"
    execute.assert_not_called()


@pytest.mark.parametrize("change", [
    {"march_used": 2}, {"resources": {"WOOD": 9}}, {"inventory": {"item_id": "a", "count": 2}},
    {"training": {"status": "IN_PROGRESS"}},
])
def test_effect_without_goal_proof_requires_observation_never_resubmission(change):
    action = Action("TAP_SEMANTIC", "CONFIRM")
    world = WorldState(page=Page.MARCH, march_used=1, march_max=3,
        resources={"WOOD": 10}, inventory={"item_id": "a", "count": 3})
    before, after = observed(world=world), observed(world=replace(world, **change))
    assert classify(before, after, action) is ClickOutcome.PROGRESS
    execute = Mock()
    retry_authorized_semantic_click(action=action, before=before, after=after,
        execution=delivery(action), observe=lambda: after, execute=execute, max_observations=1)
    execute.assert_not_called()


@pytest.mark.parametrize("change,expected", [
    ({"target": None}, Pending.UNKNOWN), ({"pending": False}, Pending.UNKNOWN),
    ({"context": "another-role"}, Pending.FALSE), ({"target": "other-rally"}, Pending.FALSE),
    ({"authorized": False}, Pending.FALSE),
    ({"world": WorldState(page=Page.LOADING)}, Pending.UNKNOWN),
    ({"world": WorldState(page=Page.MAP)}, Pending.FALSE),
])
def test_same_page_is_not_enough_to_retry(change, expected):
    action = Action("TAP_SEMANTIC", "ATTACK")
    assert is_same_action_still_pending(observed(), observed(**change), action) is expected


def test_loading_then_pending_only_retries_after_fresh_stable_observation():
    action = Action("TAP_SEMANTIC", "JOIN_RALLY")
    worlds = [observed(frame="stable-1"), observed(frame="stable-2"), observed(success=True)]
    execute = Mock(return_value=delivery(action))
    result = retry_authorized_semantic_click(action=action, before=observed(),
        after=observed(world=WorldState(page=Page.LOADING)), execution=delivery(action),
        observe=Mock(side_effect=worlds), execute=execute)
    assert execute.call_args.args[0].frame == "stable-2"
    assert result.metric == "CLICK_RETRY_SUCCESS"


def test_unconfirmed_action_never_retries_and_zero_limit_can_disable():
    action = Action("TAP_SEMANTIC", "TRAIN")
    execute = Mock()
    result = retry_authorized_semantic_click(action=action, before=observed(authorized=False),
        after=observed(), execution=replace(delivery(action), executed=False),
        observe=Mock(), execute=execute)
    assert result.stop_reason == "ACTION_NOT_SENT"
    execute.assert_not_called()
    result = retry_authorized_semantic_click(action=action, before=observed(), after=observed(),
        execution=delivery(action), observe=Mock(), execute=execute, max_retries=0)
    assert result.retries == 0


def test_observation_metadata_changes_do_not_look_like_resource_consumption():
    action = Action("TAP_SEMANTIC", "TRAIN")
    before = observed(world=WorldState(page=Page.TRAINING,
        resource_bank={"WOOD": 10, "source_frame": "a"}))
    after = observed(world=replace(before.world, resource_bank={"WOOD": 10, "source_frame": "b"}))
    assert is_same_action_still_pending(before, after, action) is Pending.TRUE
