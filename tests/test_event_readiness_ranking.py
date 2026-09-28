from __future__ import annotations

from winter_agent_v2.goal_library import GoalState, GoalStatus
from winter_agent_v2.goal_utility import rank


def test_event_readiness_flows_through_production_goal_ranking():
    goal = GoalState(
        "EVENT_MINIMUM_GUARANTEE",
        GoalStatus.READY,
        available_skills=("START_RALLY",),
    )
    ranked = rank((goal,), event_readiness={goal.goal_id: 1200.0})
    assert ranked[0][1].event_readiness == 1200.0
    assert ranked[0][1].total == goal.priority + 1200.0


def test_negative_event_readiness_is_ignored():
    goal = GoalState("EVENT_MINIMUM_GUARANTEE", GoalStatus.READY, available_skills=("START_RALLY",))
    ranked = rank((goal,), event_readiness={goal.goal_id: -100.0})
    assert ranked[0][1].event_readiness == 0.0
