from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.models import Page, WorldState


def _goal_ids(world: WorldState, continuation: str = "") -> set[str]:
    return {
        goal.goal_id
        for goal in GoalLibrary().discover(
            world,
            observations={},
            alliance_continuation_goal_id=continuation,
        )
    }


def test_alliance_home_continues_the_donation_goal_that_opened_it():
    world = WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "HOME", "status": "UNKNOWN"},
        confidence=0.99,
    )

    assert "ALLIANCE_DONATION" in _goal_ids(world, "ALLIANCE_DONATION")


def test_alliance_home_does_not_invent_donation_for_another_goal():
    world = WorldState(
        page=Page.ALLIANCE,
        alliance={"section": "HOME", "status": "UNKNOWN"},
        confidence=0.99,
    )

    assert "ALLIANCE_DONATION" not in _goal_ids(world, "CLEAR_INTEL")
    assert "ALLIANCE_DONATION" not in _goal_ids(world)
