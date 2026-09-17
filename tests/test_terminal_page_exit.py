"""A run must not leave the client standing on a page the next run cannot use.

Defect (hit live twice on 2026-09-17).  ``Page.TRAINING`` and ``Page.RESEARCH``
are leaves: a goal walks to them and no branch moves the client away again.  So a
run that reached one and found nothing to do ended standing on it, and the NEXT
run -- whatever its goal -- answered ``goal_page_mismatch`` within one step.  The
second occurrence was observed directly: the TRAIN round ended on the training
page, and the following ``--goal INTEL`` run stopped immediately without taking a
single action.

The repair reuses what is already there rather than adding machinery (no Manager,
no new page router): one ``BACK``, which ``verify_safe_back`` accepts.

Where BACK goes was measured, not assumed -- ``tools/probe_power_route.py
--leave`` was run from both pages and landed on ``Page.HOME`` each time:

    TRAINING -> HOME   (probe run ``back_from_training``)
    RESEARCH -> HOME   (probe run ``res_rs_back`` / ``res_back2``)

Two things have to hold for this to be a repair rather than a new loop:

* the owning goal must still be able to act on its page (a trainable camp is
  still ``TRAIN_TROOPS``, a startable node is still ``RESEARCH``);
* after the Back the client is on ``HOME``, which is exactly where both goals
  start -- so the same run must stop instead of walking the route again.
"""

from __future__ import annotations

import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_safe_back

TRAINING_BUSY = WorldState(page=Page.TRAINING, training={"queue_available": False},
                           confidence=0.99)
TRAINING_READY = WorldState(
    page=Page.TRAINING, training={"queue_available": True, "trainable": True},
    confidence=0.99)
RESEARCH_IDLE = WorldState(page=Page.RESEARCH, research={}, confidence=0.99)
RESEARCH_READY = WorldState(page=Page.RESEARCH, research={"researchable": True},
                            confidence=0.99)
HOME = WorldState(page=Page.HOME, confidence=0.99)


def _decide(world: WorldState, goal: str, brain: RuleBrain | None = None):
    return (brain or RuleBrain(current_goal=goal)).decide(world, v2_registry())


class EveryOtherGoalLeavesTheLeafPageTests(unittest.TestCase):
    def test_a_train_run_does_not_park_the_client_on_the_training_page(self):
        decision = _decide(TRAINING_BUSY, "TRAIN")
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.expected_result, "home_opened")

    def test_a_research_run_does_not_park_the_client_on_the_research_page(self):
        decision = _decide(RESEARCH_IDLE, "RESEARCH")
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.expected_result, "home_opened")

    def test_a_goal_that_has_nothing_to_do_with_those_pages_leaves_them_too(self):
        """This is the actual failure: the *next* goal, a different one."""
        for goal in ("DAILY", "INTEL", "MAIL", "ALLIANCE", "EXPLORATION",
                     "GATHER_RESOURCE", "HOME"):
            for page in (TRAINING_BUSY, RESEARCH_IDLE):
                with self.subTest(goal=goal, page=page.page.value):
                    decision = _decide(page, goal)
                    self.assertEqual(decision.skill, "BACK")
                    self.assertEqual(decision.expected_result, "home_opened")

    def test_a_goal_less_sweep_keeps_the_stop_so_the_scheduler_still_skips_it(self):
        """SAFE_STOP is how the scheduler is told to skip an observation.

        Turning a busy queue into a Back would make it look like work and displace
        an observation that has real work waiting, which is what
        tests/test_multitask_scheduler.py pins.  So the leave is for a NAMED goal
        only, and a sweep keeps answering exactly what it answered before.
        """
        for page, reason in ((TRAINING_BUSY, "training_queue_busy"),
                             (RESEARCH_IDLE, "research_page_no_startable_node")):
            with self.subTest(page=page.page.value):
                decision = _decide(page, None)
                self.assertEqual(decision.skill, "SAFE_STOP")
                self.assertEqual(decision.reason, reason)

    def test_the_back_lands_on_home_which_the_verifier_accepts(self):
        """The transition is checked, not hoped for."""
        for before in (TRAINING_BUSY, RESEARCH_IDLE):
            with self.subTest(page=before.page.value):
                self.assertTrue(verify_safe_back(before, HOME).ok)


class TheOwningGoalCanStillActTests(unittest.TestCase):
    def test_a_trainable_camp_is_still_trained(self):
        self.assertEqual(_decide(TRAINING_READY, "TRAIN").skill, "TRAIN_TROOPS")

    def test_a_startable_node_is_still_researched(self):
        self.assertEqual(_decide(RESEARCH_READY, "RESEARCH").skill, "RESEARCH")

    def test_a_busy_queue_does_not_hide_a_trainable_one(self):
        """Order preserved: the ready case is decided before the exit."""
        self.assertEqual(
            _decide(WorldState(page=Page.TRAINING,
                               training={"queue_available": True, "trainable": True},
                               confidence=0.99), "TRAIN").skill,
            "TRAIN_TROOPS")


class TheSameRunDoesNotWalkTheRouteAgainTests(unittest.TestCase):
    """After the Back the client is on HOME, which is where both routes start.

    Without the one-shot guard the run would go HOME -> route -> page -> Back ->
    HOME, spending its whole action budget on nothing.
    """

    def test_train_stops_instead_of_re_routing(self):
        brain = RuleBrain(current_goal="TRAIN")
        first = brain.decide(TRAINING_BUSY, v2_registry())
        self.assertEqual(first.skill, "BACK")
        second = brain.decide(HOME, v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, "training_page_already_read_not_actionable")

    def test_research_stops_instead_of_re_routing(self):
        brain = RuleBrain(current_goal="RESEARCH")
        self.assertEqual(brain.decide(RESEARCH_IDLE, v2_registry()).skill, "BACK")
        second = brain.decide(HOME, v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, "research_page_already_read_not_actionable")

    def test_a_back_that_did_not_move_the_client_is_not_repeated(self):
        brain = RuleBrain(current_goal="TRAIN")
        self.assertEqual(brain.decide(TRAINING_BUSY, v2_registry()).skill, "BACK")
        # The client is still on the training page: the flag is already set, so
        # this falls through to the goal's own honest stop rather than tapping
        # Back forever.
        second = brain.decide(TRAINING_BUSY, v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP")

    def test_a_different_goal_recovers_and_continues(self):
        """The point of the repair: the next run does real work, not a mismatch."""
        brain = RuleBrain(current_goal="DAILY")
        self.assertEqual(brain.decide(TRAINING_BUSY, v2_registry()).skill, "BACK")
        second = brain.decide(HOME, v2_registry())
        self.assertEqual(second.skill, "OPEN_DAILY")


if __name__ == "__main__":
    unittest.main()
