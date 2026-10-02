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
        """Every goal that comes home must close the panel first, not hope the door is there.

        OPEN_HOME's control is the 回城 door on the map HUD and the resource-search panel covers it.
        Measured 2026-09-23 (issue #101): the step failed 44 times in 323, every one with
        page_before=MAP, 37 of them `SEMANTIC_TARGET_NOT_VERIFIED` -- and on the runtime's own frames
        the failing one draws the panel (`BTN_RESOURCE_SEARCH_SUBMIT` d=0) with the door absent, while
        a successful one draws no panel and the door at d=2.  Three goals had this guard and four did
        not, which is what this list pins.

        Completed 2026-10-02, and the way it had been wrong is the point.  The list was written from
        the *seven branches that had the guard*, not from the branches that emit ``OPEN_HOME`` -- so
        the two added later (BUILDING and FISHING) were never in it and stayed unguarded.  Measured
        that day: ``OPEN_HOME`` answered from the map 69 times and failed 10, and the split is total
        rather than statistical -- 59/59 successes had ``resource_search_open=False``, 10/10 failures
        had it ``True``, and every one of the 10 belongs to these two routes (FISHING 8,
        ``fishing_entry_requires_city_hud``; BUILDING 2, ``building_goal_requires_home``).  Eight of
        the ten were recovered by exactly one Back on the next step, which is what this guard emits
        directly.  ``test_the_family_is_discovered_from_the_brain`` below is the durable half: it
        finds the family by asking the brain instead of trusting this tuple.
        """
        for goal, reason in (("MAIL", "close_resource_search_for_mail_goal"),
                             ("TRAIN", "close_resource_search_for_training_goal"),
                             ("RESEARCH", "close_resource_search_for_research_goal"),
                             ("EXPLORATION", "close_resource_search_for_exploration_goal"),
                             ("DAILY", "close_resource_search_for_daily_goal"),
                             ("ALLIANCE", "close_resource_search_for_alliance_goal"),
                             ("HOME", "close_resource_search_to_go_home"),
                             ("FISHING", "close_resource_search_for_fishing_goal"),
                             ("BUILDING", "close_resource_search_for_building_goal")):
            with self.subTest(goal=goal):
                world = WorldState(page=Page.MAP, resource_search_open=True, confidence=0.99)
                decision = decide(goal, world)
                self.assertEqual(decision.skill, "BACK", goal)
                self.assertEqual(decision.reason, reason, goal)
                # ...and the door is taken once the panel is gone, so the guard is a detour and not
                # a replacement: the same goal on the same page without the panel still goes home.
                cleared = decide(goal, WorldState(page=Page.MAP, confidence=0.99))
                self.assertEqual(cleared.skill, "OPEN_HOME", goal)

    def test_the_family_is_discovered_from_the_brain(self):
        """The same invariant, with the membership found rather than typed.

        The tuple above is a hand-written list, and a hand-written list is exactly how FISHING and
        BUILDING stayed unguarded: it was copied from the branches that already had the guard.  This
        test asks the brain which routes come home from the map and then requires *each of them* to
        close the panel first, so a twelfth branch cannot be added without one -- the failure it
        produces is about a route nobody remembered to add here.

        ``OPEN_HOME``'s control is the 回城 door on the HUD and the search panel is drawn over it, so
        "comes home from the map" is the whole membership condition; there is nothing else to decide.
        """
        routes = ("MAIL", "TRAIN", "RESEARCH", "EXPLORATION", "DAILY", "ALLIANCE", "HOME",
                  "FISHING", "BUILDING", "INTEL", "GATHER_RESOURCE", "BEAST_HUNT", "TRAIN_TROOPS")
        comers = [route for route in routes
                  if decide(route, WorldState(page=Page.MAP, confidence=0.99)).skill == "OPEN_HOME"]
        # A scan that found nobody would pass the loop below vacuously -- the failure mode this
        # repository keeps hitting when it tests a set it built itself.
        self.assertIn("FISHING", comers)
        self.assertIn("BUILDING", comers)
        for route in comers:
            with self.subTest(route=route):
                decision = decide(route, WorldState(page=Page.MAP, resource_search_open=True,
                                                    confidence=0.99))
                self.assertEqual(decision.skill, "BACK", route)
                self.assertTrue(str(decision.reason or "").startswith("close_resource_search"),
                                f"{route} closed the panel for the wrong reason: {decision.reason}")


class UnrelatedPageStillStopsTest(unittest.TestCase):
    """The hop must not become a licence to act on any page.

    Updated 2026-09-19 with the live evidence that changed the first step.  These used to assert a
    straight SAFE_STOP, and that is what the research goal did on the ALLIANCE page -- except the
    page-driven branch then ran ``OPEN_ALLIANCE_GIFTS`` *under a research goal*, twelve runs in a
    row, without the research page ever being read.  So the first step is now one Back off the
    foreign page, and the goal still stops instead of doing that page's work.

    Updated again 2026-10-02, and here the tests were the stale half.  They asserted a *second*
    foreign-page step (``LEAVE_FOREIGN_LAYER``) on MAIL/INTEL/DAILY/EXPLORATION as well, which is
    what the code did when they were written.  ``cc5894d`` (2026-09-27 00:29) then narrowed that
    second step to the one layer it was measured on -- ALLIANCE, where a Back demonstrably moved
    nothing (``SAFE_BACK_NOT_PROVEN``, page ALLIANCE -> ALLIANCE) and whose declared exit is the
    client's own X rather than a back arrow.  The tests were written 2026-09-25 and never updated,
    so they kept failing for two reasons that have nothing to do with the behaviour they name:
    they asserted the pre-narrowing answer, and they asserted it on the pages the narrowing
    deliberately excluded.  A/B against HEAD (brain.py md5 ``da0f3ba7635aefe4fa3160671584dcbe``)
    reproduces both, so nothing here is a regression -- the assertion simply outlived the decision.

    The sequence asserted below is the measured one, four steps deep: one Back, then (on ALLIANCE
    only) the close, then the goal's own named stop, repeated.  ``test_only_the_measured_layer_gets
    _the_second_step`` pins the narrowing itself rather than leaving it as a comment.
    """

    def test_train_on_an_unrelated_page_leaves_it_once_then_stops_named(self):
        for page in (Page.MAIL, Page.INTEL, Page.DAILY, Page.EXPLORATION):
            brain = RuleBrain(current_goal="TRAIN")
            first = brain.decide(WorldState(page=page, confidence=0.99), v2_registry())
            self.assertEqual(first.skill, "BACK", page)
            self.assertIn("panel_it_does_not_own", first.reason, page)
            second = brain.decide(WorldState(page=page, confidence=0.99), v2_registry())
            self.assertEqual(second.skill, "SAFE_STOP", page)
            self.assertEqual(second.reason, "training_entry_not_verified", page)

    def test_research_on_an_unrelated_page_leaves_it_once_then_stops_named(self):
        for page in (Page.MAIL, Page.INTEL, Page.DAILY, Page.EXPLORATION):
            brain = RuleBrain(current_goal="RESEARCH")
            first = brain.decide(WorldState(page=page, confidence=0.99), v2_registry())
            self.assertEqual(first.skill, "BACK", page)
            self.assertIn("panel_it_does_not_own", first.reason, page)
            second = brain.decide(WorldState(page=page, confidence=0.99), v2_registry())
            self.assertEqual(second.skill, "SAFE_STOP", page)
            self.assertEqual(second.reason, "research_entry_not_verified", page)

    def test_only_the_measured_layer_gets_the_second_step(self):
        """The narrowing ``cc5894d`` made, asserted rather than commented.

        ALLIANCE is the layer the second step was measured on; every other foreign page answers the
        Back and then stops honestly.  Offering the close everywhere would create a registered
        action the runtime cannot execute on pages where that X is not drawn -- which is the exact
        defect the narrowing was made to stop.
        """
        for goal, stop in (("TRAIN", "training_entry_not_verified"),
                           ("RESEARCH", "research_entry_not_verified")):
            for page in (Page.MAIL, Page.INTEL, Page.DAILY, Page.EXPLORATION):
                with self.subTest(goal=goal, page=page, second_step="absent"):
                    brain = RuleBrain(current_goal=goal)
                    brain.decide(WorldState(page=page, confidence=0.99), v2_registry())
                    second = brain.decide(WorldState(page=page, confidence=0.99), v2_registry())
                    self.assertNotEqual(second.skill, "LEAVE_FOREIGN_LAYER", page)
                    self.assertEqual(second.reason, stop, page)
            with self.subTest(goal=goal, page=Page.ALLIANCE, second_step="present"):
                brain = RuleBrain(current_goal=goal)
                brain.decide(WorldState(page=Page.ALLIANCE, confidence=0.99), v2_registry())
                second = brain.decide(WorldState(page=Page.ALLIANCE, confidence=0.99), v2_registry())
                self.assertEqual(second.skill, "LEAVE_FOREIGN_LAYER", goal)
                self.assertIn("a_back_did_not_move", second.reason, goal)


class HomeBehaviourUnchangedTest(unittest.TestCase):
    """HOME keeps walking its own route; the new hop must not shadow it."""

    def test_train_on_home_starts_the_power_route(self):
        decision = decide("TRAIN", WorldState(page=Page.HOME, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW")
        self.assertEqual(decision.reason, "panel_did_not_serve_this_goal_so_the_power_route_is_the_fallback")

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
        self.assertEqual(decision.reason, "panel_did_not_serve_this_goal_so_the_power_route_is_the_fallback")

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
