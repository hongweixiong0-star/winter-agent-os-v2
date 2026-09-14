import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.event_goal import DeadlineLevel, EventGoalPlanner, EventState, ScoringAction, deadline_level
from winter_agent_v2.executor import Executor
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_event_points_increased


class EventGoalTests(unittest.TestCase):
    def test_live_event_points_must_actually_increase(self):
        before = WorldState(page=Page.EVENT, events={"minimum_guarantee":{"event_id":"KOP","current_points":0}})
        after = WorldState(page=Page.EVENT, events={"minimum_guarantee":{"event_id":"KOP","current_points":11250}})
        result = verify_event_points_increased(before, after)
        self.assertTrue(result.ok)
        self.assertEqual(result.evidence["verified_gain"], 11250)

    def test_deadline_under_two_hours_is_p0(self):
        self.assertEqual(deadline_level(7199), DeadlineLevel.P0)

    def test_planner_uses_current_event_actions_not_event_name_table(self):
        event = EventState(
            "UNKNOWN_NEW_EVENT", "新活动", 1000, 5000, 3600,
            (ScoringAction("NORMAL_TRAIN", 100, 50, "TRAIN_TROOPS", effective_cost=1, normal_value=1),),
        )
        plan = EventGoalPlanner().plan(event, {"TRAIN_TROOPS"})
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.actions[0].units, 40)

    def test_planner_reports_blocked_when_no_reasonable_action_exists(self):
        event = EventState("EVENT", "活动", 0, 38000, 1000, (ScoringAction("MITHRIL", 28800, 1, None, allowed=False),))
        plan = EventGoalPlanner().plan(event, set())
        self.assertFalse(plan.feasible)
        self.assertEqual(plan.status, "EVENT_TARGET_BLOCKED")

    def test_points_complete_still_requires_claim(self):
        event = EventState("EVENT", "活动", 64000, 38000, 1000, (), completed_tiers=(1300, 38000), claimed_tiers=(1300,))
        self.assertFalse(event.minimum_guarantee_complete)
        self.assertEqual(EventGoalPlanner().plan(event, set()).status, "CLAIM_REQUIRED")

    def test_single_scheduler_prefers_deadline_scoring_skill(self):
        event = {"minimum_guarantee": {"remaining_seconds": 1000, "points_missing": 5000,
            "scoring_actions": [{"skill_id": "TRAIN_TROOPS", "event_value": 100},
                                {"skill_id": "BUILDING_UPGRADE", "event_value": 10}]}}
        build = WorldState(page=Page.BUILDING, building={"upgradeable": True}, events=event, confidence=1)
        train = WorldState(page=Page.TRAINING, training={"trainable": True}, events=event, confidence=1)
        selection = Scheduler(RuleBrain(), v2_registry(), Executor()).select_next((build, train))
        self.assertEqual(selection.index, 1)
        self.assertEqual(selection.decision.skill, "TRAIN_TROOPS")


if __name__ == "__main__":
    unittest.main()
