from types import SimpleNamespace

from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry


def _runtime(mode: str, route: str) -> LiveRuntime:
    runtime = object.__new__(LiveRuntime)
    runtime.execution_mode = mode
    runtime.validation_focus_route = route
    return runtime


def test_exact_goal_scope_excludes_other_training_camps_and_research():
    runtime = _runtime('DEVELOPMENT_VALIDATION', 'TRAIN')
    runtime.validation_scope = {'goal_id': 'LANCER_CAMP_TRAINING'}
    goals = [SimpleNamespace(goal_id=g) for g in ('LANCER_CAMP_TRAINING',
              'SHIELD_CAMP_TRAINING', 'KEEP_RESEARCH_PRODUCTIVE')]
    assert [g.goal_id for g in runtime._focus_validation_goals(goals)] == ['LANCER_CAMP_TRAINING']


def test_start_rally_target_cannot_be_satisfied_by_join_or_donation():
    runtime = _runtime('DEVELOPMENT_VALIDATION', '')
    runtime.validation_scope = {'target_skill': 'START_RALLY'}
    goals = [SimpleNamespace(goal_id=g) for g in ('PARTICIPATE_BEAR', 'ALLIANCE_ROUTINE')]
    assert [g.goal_id for g in runtime._focus_validation_goals(goals)] == ['PARTICIPATE_BEAR']
    assert runtime._validation_skill_allowed('START_RALLY')
    assert runtime._validation_skill_allowed('OPEN_BEAR_RALLY_LIST')
    assert not runtime._validation_skill_allowed('JOIN_RALLY')
    assert not runtime._validation_skill_allowed('ALLIANCE_TECH_CONTRIBUTE')


def test_unavailable_concrete_fishing_target_does_not_synthesize_readonly_completion():
    runtime = _runtime('DEVELOPMENT_VALIDATION', 'FISHING')
    runtime.validation_scope = {'target_skill': 'PLAY_NORMAL_FISHING_LEVEL'}
    assert runtime._focus_validation_goals([]) == []


def test_requested_readonly_fishing_observation_needs_no_bait_goal():
    runtime = _runtime('DEVELOPMENT_VALIDATION', 'FISHING')
    runtime.validation_scope = {'goal_id': 'OBSERVE_FISHING_STATE', 'target_skill': 'READ_FISHING_STATE'}
    selected = runtime._focus_validation_goals([SimpleNamespace(goal_id='DAILY_ACTIVITY_TARGET')])
    assert [g.goal_id for g in selected] == ['OBSERVE_FISHING_STATE']


def test_fishing_navigation_reaches_city_before_starting_local_session():
    brain = RuleBrain()
    brain.current_goal = 'FISHING'
    brain.goal_id = 'OBSERVE_FISHING_STATE'
    registry = v2_registry()
    assert brain.decide(WorldState(page=Page.MAP, confidence=.99), registry).skill == 'OPEN_HOME'
    assert brain.decide(WorldState(page=Page.INTEL, confidence=.99), registry).skill == 'BACK'
    assert brain.decide(WorldState(page=Page.HOME, confidence=.99), registry).skill == 'READ_FISHING_STATE'


def test_scope_role_mismatch_and_production_isolation():
    goals = [SimpleNamespace(goal_id='KEEP_RESEARCH_PRODUCTIVE')]
    runtime = _runtime('DEVELOPMENT_VALIDATION', '')
    runtime.role_id = 'A'
    runtime.validation_scope = {'role_id': 'B'}
    assert runtime._focus_validation_goals(goals) == []
    runtime.execution_mode = 'PRODUCTION'
    assert runtime._focus_validation_goals(goals) is goals
    assert runtime._validation_skill_allowed('JOIN_RALLY')


def test_validation_focus_keeps_all_goals_on_requested_route():
    goals = [
        SimpleNamespace(goal_id="SHIELD_CAMP_TRAINING"),
        SimpleNamespace(goal_id="LANCER_CAMP_TRAINING"),
        SimpleNamespace(goal_id="KEEP_RESEARCH_PRODUCTIVE"),
        SimpleNamespace(goal_id="AVOID_STAMINA_WASTE"),
    ]

    selected = _runtime("DEVELOPMENT_VALIDATION", "TRAIN")._focus_validation_goals(goals)

    assert [goal.goal_id for goal in selected] == [
        "SHIELD_CAMP_TRAINING",
        "LANCER_CAMP_TRAINING",
    ]


def test_production_scheduler_keeps_the_full_goal_board():
    goals = [
        SimpleNamespace(goal_id="SHIELD_CAMP_TRAINING"),
        SimpleNamespace(goal_id="KEEP_RESEARCH_PRODUCTIVE"),
        SimpleNamespace(goal_id="AVOID_STAMINA_WASTE"),
    ]

    selected = _runtime("PRODUCTION", "TRAIN")._focus_validation_goals(goals)

    assert selected is goals


def test_validation_without_requested_route_keeps_scheduler_global():
    goals = [SimpleNamespace(goal_id="SHIELD_CAMP_TRAINING")]

    selected = _runtime("DEVELOPMENT_VALIDATION", "")._focus_validation_goals(goals)

    assert selected is goals


def test_bait_blocked_validation_only_adds_existing_read_only_goal():
    from winter_agent_v2.goal_library import GoalState, GoalStatus
    goal=GoalState('USE_NORMAL_FISHING_BAIT',GoalStatus.BLOCKED)
    selected=_runtime('DEVELOPMENT_VALIDATION','FISHING')._focus_validation_goals([goal])
    assert selected[-1].goal_id=='OBSERVE_FISHING_STATE'
    assert selected[-1].available_skills==('READ_FISHING_STATE',)
    assert selected[0].status is GoalStatus.BLOCKED


def test_validation_route_scope_is_inactive_for_production():
    assert not _runtime("PRODUCTION", "TRAIN")._validation_route_scope_active()


def test_validation_route_scope_is_active_only_when_route_is_named():
    assert _runtime("DEVELOPMENT_VALIDATION", "TRAIN")._validation_route_scope_active()
    assert not _runtime("DEVELOPMENT_VALIDATION", "")._validation_route_scope_active()


def test_daily_validation_focus_keeps_task_board_and_live_daily_task_goals_only():
    goals = [
        SimpleNamespace(goal_id="DAILY_ACTIVITY_TARGET", evidence={}),
        SimpleNamespace(goal_id="ALLIANCE_DONATION", evidence={"source": "LIVE_DAILY_TASK_ROW"}),
        SimpleNamespace(goal_id="PET_TREASURE", evidence={"source": "QUICK_PANEL"}),
    ]
    selected = _runtime("DEVELOPMENT_VALIDATION", "DAILY")._focus_validation_goals(goals)
    assert [goal.goal_id for goal in selected] == ["DAILY_ACTIVITY_TARGET", "ALLIANCE_DONATION"]
