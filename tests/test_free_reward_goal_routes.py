from types import SimpleNamespace

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.goal_library import GoalLibrary, route_for
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry


@pytest.mark.parametrize("page,reading,skill", [
    (Page.MAIL, {"mail": {"status": "CLAIMABLE"}}, "MAIL_CLAIM_REWARDS"),
    (Page.DAILY, {"daily": {"status": "CLAIMABLE", "tab": "DAILY"}}, "DAILY_CLAIM_REWARDS"),
    (Page.ALLIANCE, {"alliance": {"section": "GIFTS", "status": "CLAIMABLE", "tab": "ALLY_GIFT"}}, "ALLIANCE_ALLY_GIFT_CLAIM"),
    (Page.EXPLORATION, {"exploration": {"status": "CLAIMABLE"}}, "EXPLORATION_IDLE_CLAIM"),
    (Page.INTEL, {"intel": {"status": "CLAIMABLE", "claimable_count": 1}}, "INTEL_CLAIM_REWARDS"),
    (Page.EVENT, {"events": {"panel": "LOGIN_GIFT", "day_claim_visible": True}}, "CLAIM_LOGIN_GIFT"),
])
def test_current_claimable_page_goal_reaches_existing_claim_skill(page, reading, skill):
    world = WorldState(page=page, **reading, rewards={
        "verified_claimable": [page.value], "skills": {page.value: [skill]},
    })
    library = GoalLibrary()
    reward = next(goal for goal in library.discover(world)
                  if goal.goal_id == f"CLAIM_FREE_{page.value}")
    selected = library.best([reward], world)
    assert selected is reward
    runtime = object.__new__(LiveRuntime)
    runtime.brain = RuleBrain()
    runtime._sync_brain_goal(selected, SimpleNamespace())
    assert runtime.brain.current_goal == page.value
    assert runtime.brain.goal_id == reward.goal_id
    decision = runtime.brain.decide(world, v2_registry())
    assert decision.skill == skill
    assert decision.skill in LiveRuntime.VERIFIED_ATOMIC


@pytest.mark.parametrize("goal_id", ["CLAIM_FREE_UNKNOWN", "CLAIM_FREE_MAP", "CLAIM_FREE_REWARDS", "CLAIM_FREE_FAKE_PAGE"])
def test_unrecognized_reward_page_never_inherits_an_unrelated_route(goal_id):
    assert route_for(goal_id) is None
