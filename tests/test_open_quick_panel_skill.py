from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry


def _collapsed_home() -> WorldState:
    return WorldState(
        page=Page.HOME,
        quick_panel={
            "open": False,
            "handle": {
                "state": "COLLAPSED",
                "point_norm": [0.03, 0.50],
                "basis": "HANDLE_TRIANGLE_SCAN",
            },
        },
        confidence=0.99,
    )


def test_quick_panel_has_a_named_reusable_navigation_skill():
    skill = v2_registry().get("OPEN_QUICK_PANEL")

    assert skill.action.target == "QUICK_PANEL_HANDLE"
    assert skill.ready(_collapsed_home()) is True


def test_panel_discovery_uses_named_navigation_instead_of_unknown_budget():
    goal = next(
        goal
        for goal in GoalLibrary().discover(_collapsed_home(), observations={})
        if goal.goal_id == "DISCOVER_QUICK_PANEL_TASKS"
    )

    assert goal.available_skills == ("OPEN_QUICK_PANEL",)


def test_research_reopens_panel_after_another_goal_used_it():
    brain = RuleBrain()
    brain.goal_id = "KEEP_RESEARCH_PRODUCTIVE"
    brain.current_goal = "RESEARCH"
    brain.ordinary_attempts = brain.MAX_ORDINARY_ATTEMPTS

    decision = brain.decide(_collapsed_home(), v2_registry())

    assert decision.skill == "OPEN_QUICK_PANEL"
