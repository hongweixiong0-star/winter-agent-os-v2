"""The route goals must be able to start from the map.

Regression under test (2026-09-17)
----------------------------------
A named route goal (``RUN --goal TRAIN`` / ``--goal RESEARCH``) begins on HOME: it
taps the power overview, walks 加成总览 -> 实力详情 -> the category row's 提升, and
opens the leaf page.  Four goals had a "get home first" hop for the case where the
client is parked on the map -- MAIL, EXPLORATION, DAILY, ALLIANCE -- and TRAIN and
RESEARCH did not.  The client's resting page *is* the map, so a 训练 or 科研 task
launched after any other task stopped on its very first step:

    run_live --goal TRAIN, live 2026-09-17 17:42 GMT+8
       before.page = MAIL
       step 1: SAFE_STOP  training_entry_not_verified   (no action taken)

That is silent: the run is a success as far as exit codes go, and the goal simply
never gets anywhere -- which is why ``TRAIN_TROOPS`` has never had a live attempt
while every other piece of the training route (vision target, brain route, verifier
binding) is present.

``OPEN_HOME`` is only valid from the map (``verify_open_home`` requires
``before.page is Page.MAP``), so this hop deliberately does not try to rescue the
goal from an arbitrary page: an unrelated page still stops with the same named
reason, which keeps a goal from inheriting another goal's page actions.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402


def decide(goal: str, world: WorldState):
    return RuleBrain(current_goal=goal).decide(world, v2_registry())


class RouteGoalFromMapTest(unittest.TestCase):
    def test_train_goes_home_from_the_map(self):
        decision = decide("TRAIN", WorldState(page=Page.MAP, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_HOME")
        self.assertEqual(decision.reason, "training_goal_requires_home")

    def test_research_goes_home_from_the_map(self):
        decision = decide("RESEARCH", WorldState(page=Page.MAP, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_HOME")
        self.assertEqual(decision.reason, "research_goal_requires_home")

    def test_the_hop_is_dispatchable(self):
        # A decision naming a skill without a verifier binding is never executed
        # (the RR-003 class), so the hop has to be one the loop can actually take.
        self.assertIn("OPEN_HOME", LiveRuntime.VERIFIED_ATOMIC)

    def test_an_open_resource_search_panel_is_closed_first(self):
        # OPEN_HOME's control is the 回城 button on the HUD; the resource-search
        # panel covers it, and MAIL's branch already handles this.
        for goal, reason in (("TRAIN", "close_resource_search_for_training_goal"),
                             ("RESEARCH", "close_resource_search_for_research_goal")):
            world = WorldState(page=Page.MAP, resource_search_open=True, confidence=0.99)
            decision = decide(goal, world)
            self.assertEqual(decision.skill, "BACK", goal)
            self.assertEqual(decision.reason, reason, goal)


class UnrelatedPageStillStopsTest(unittest.TestCase):
    """The hop must not become a licence to act on any page."""

    def test_train_on_an_unrelated_page_still_stops_named(self):
        for page in (Page.MAIL, Page.INTEL, Page.DAILY, Page.EXPLORATION):
            decision = decide("TRAIN", WorldState(page=page, confidence=0.99))
            self.assertEqual(decision.skill, "SAFE_STOP", page)
            self.assertEqual(decision.reason, "training_entry_not_verified", page)

    def test_research_on_an_unrelated_page_still_stops_named(self):
        for page in (Page.MAIL, Page.INTEL, Page.DAILY, Page.EXPLORATION):
            decision = decide("RESEARCH", WorldState(page=page, confidence=0.99))
            self.assertEqual(decision.skill, "SAFE_STOP", page)
            self.assertEqual(decision.reason, "research_entry_not_verified", page)


class HomeBehaviourUnchangedTest(unittest.TestCase):
    """HOME keeps walking its own route; the new hop must not shadow it."""

    def test_train_on_home_starts_the_power_route(self):
        decision = decide("TRAIN", WorldState(page=Page.HOME, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW")
        self.assertEqual(decision.reason, "training_goal_requires_power_route")

    def test_train_on_home_with_a_busy_queue_stops(self):
        world = WorldState(page=Page.HOME, training={"queue_available": False}, confidence=0.99)
        decision = decide("TRAIN", world)
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "training_queue_busy")

    def test_train_on_home_with_the_camp_menu_open_opens_training(self):
        world = WorldState(page=Page.HOME, training={"menu_open": True}, confidence=0.99)
        decision = decide("TRAIN", world)
        self.assertEqual(decision.skill, "OPEN_INFANTRY_TRAINING")

    def test_research_on_home_starts_the_power_route(self):
        decision = decide("RESEARCH", WorldState(page=Page.HOME, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW")
        self.assertEqual(decision.reason, "research_goal_requires_power_route")

    def test_research_on_home_with_a_busy_queue_stops(self):
        world = WorldState(page=Page.HOME, research={"queue_available": False}, confidence=0.99)
        decision = decide("RESEARCH", world)
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "research_queue_busy")

    def test_the_other_four_route_goals_are_untouched(self):
        for goal, reason in (("MAIL", "mail_goal_requires_home"),
                             ("ALLIANCE", "alliance_goal_requires_home"),
                             ("DAILY", "daily_goal_requires_home"),
                             ("EXPLORATION", "exploration_goal_requires_home")):
            decision = decide(goal, WorldState(page=Page.MAP, confidence=0.99))
            self.assertEqual(decision.skill, "OPEN_HOME", goal)
            self.assertEqual(decision.reason, reason, goal)


if __name__ == "__main__":
    unittest.main()
