from winter_agent_v2.goal_library import GoalLibrary, GoalStatus
from winter_agent_v2.models import WorldState, Page


def discover(bear):
    return {g.goal_id: g for g in GoalLibrary().discover(
        WorldState(page=Page.ALLIANCE, events={"bear": bear}), role_id="ROLE_CURRENT")}


def test_future_alliance_event_projects_waiting_window_without_duplicate_execution():
    goals = discover({"status": "SCHEDULED", "seconds_to_start": 3600})
    provider = goals["ALLIANCE_TIMED_EVENTS"]
    assert provider.status == GoalStatus.SCHEDULED_NOT_OPEN
    assert provider.evidence["provider_state"] == "WAITING_WINDOW"
    assert provider.evidence["linked_goal_ids"] == ["PARTICIPATE_BEAR"]
    assert provider.available_skills == ()


def test_current_open_event_keeps_participation_in_the_existing_goal():
    goals = discover({"status": "ACTIVE", "remaining_seconds": 500, "auto_join_enabled": True})
    provider = goals["ALLIANCE_TIMED_EVENTS"]
    assert provider.evidence["provider_state"] == "READY"
    assert goals["PARTICIPATE_BEAR"].status == GoalStatus.READY
    assert "JOIN_RALLY" in goals["PARTICIPATE_BEAR"].available_skills
    assert provider.available_skills == ()


def test_missing_live_time_stays_registered_and_arena_debt_names_actual_missing_wiring():
    goals = {g.goal_id: g for g in GoalLibrary().discover(WorldState(page=Page.HOME), role_id="A")}
    assert goals["ALLIANCE_TIMED_EVENTS"].evidence["provider_state"] == "REGISTERED"
    arena = goals["USE_FREE_ARENA_ATTEMPTS"]
    assert arena.evidence["missing_page_identity"] is True
    assert "READ_FREE_ATTEMPTS" in arena.evidence["missing_registry_skills"]
