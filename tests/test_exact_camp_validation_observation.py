from winter_agent_v2.goal_library import GoalState, GoalStatus
from winter_agent_v2.runtime import LiveRuntime


def runtime():
    result = object.__new__(LiveRuntime)
    result.execution_mode = 'DEVELOPMENT_VALIDATION'
    result.validation_focus_route = 'TRAIN'
    result.role_id = 'a'
    result.validation_scope = {'role_id': 'a', 'route': 'TRAIN', 'goal_id': 'MARKSMAN_CAMP_TRAINING'}
    return result


def test_exact_unread_camp_can_observe_without_authorizing_training():
    goals = runtime()._focus_validation_goals([])
    assert len(goals) == 1
    assert goals[0].goal_id == 'MARKSMAN_CAMP_TRAINING'
    assert goals[0].available_skills == ('OPEN_QUICK_PANEL',)
    assert goals[0].evidence['observation_only'] is True


def test_live_busy_camp_is_not_replaced_with_a_ready_training_ticket():
    busy = GoalState('MARKSMAN_CAMP_TRAINING', GoalStatus.BLOCKED, available_skills=())
    assert runtime()._focus_validation_goals([busy]) == [busy]


def test_production_keeps_the_original_board():
    r = runtime()
    r.execution_mode = 'PRODUCTION'
    goals = [GoalState('DAILY_ACTIVITY_TARGET', GoalStatus.READY)]
    assert r._focus_validation_goals(goals) is goals
