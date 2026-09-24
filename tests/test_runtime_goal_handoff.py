from types import SimpleNamespace

from winter_agent_v2.goal_library import GoalState, GoalStatus
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.brain import RuleBrain


def test_each_scheduler_tick_replaces_stale_route_and_task_identity():
    runtime = object.__new__(LiveRuntime)
    runtime.brain = RuleBrain()
    gate = SimpleNamespace(capabilities={})
    research = GoalState("KEEP_RESEARCH_PRODUCTIVE", GoalStatus.READY, available_skills=("RESEARCH",))
    lancer = GoalState("LANCER_CAMP_TRAINING", GoalStatus.READY, available_skills=("TRAIN_TROOPS",))

    runtime._sync_brain_goal(research, gate)
    assert runtime.brain.current_goal == "RESEARCH"
    assert runtime.brain.goal_id == "KEEP_RESEARCH_PRODUCTIVE"

    runtime.brain.terminal_page_left = True
    runtime._sync_brain_goal(lancer, gate)
    assert runtime.brain.current_goal == "TRAIN"
    assert runtime.brain.goal_id == "LANCER_CAMP_TRAINING"
    assert runtime.brain.terminal_page_left is False

    runtime._sync_brain_goal(None, gate)
    assert runtime.brain.current_goal is None
    assert runtime.brain.goal_id == ""
