from types import SimpleNamespace

from winter_agent_v2.runtime import LiveRuntime


def _runtime(mode: str, route: str) -> LiveRuntime:
    runtime = object.__new__(LiveRuntime)
    runtime.execution_mode = mode
    runtime.validation_focus_route = route
    return runtime


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
