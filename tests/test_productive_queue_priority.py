from __future__ import annotations

import unittest

from winter_agent_v2.goal_library import GoalLibrary
from winter_agent_v2.models import Page, WorldState


class ProductiveQueuePriorityTests(unittest.TestCase):
    def test_training_research_and_building_precede_non_deadline_stamina_work(self):
        world = WorldState(
            page=Page.HOME,
            stamina={"current": 218},
            camps={
                "SHIELD_CAMP": {"observed": True, "status": "IDLE", "queue_available": True},
                "LANCER_CAMP": {"observed": True, "status": "IDLE", "queue_available": True},
                "MARKSMAN_CAMP": {"observed": True, "status": "IDLE", "queue_available": True},
            },
            research={"status": "IDLE", "queue_available": True},
            building={"status": "IDLE", "queue_available": True},
        )
        library = GoalLibrary()
        goals = library.discover(world)
        ranked = [goal.goal_id for goal, _ in library.rank(goals, world=world)]
        self.assertLess(ranked.index("SHIELD_CAMP_TRAINING"), ranked.index("AVOID_STAMINA_WASTE"))
        self.assertLess(ranked.index("KEEP_RESEARCH_PRODUCTIVE"), ranked.index("AVOID_STAMINA_WASTE"))
        self.assertLess(ranked.index("KEEP_BUILDING_PRODUCTIVE"), ranked.index("AVOID_STAMINA_WASTE"))
        self.assertEqual(
            ranked[:3],
            ["SHIELD_CAMP_TRAINING", "LANCER_CAMP_TRAINING", "MARKSMAN_CAMP_TRAINING"],
        )


if __name__ == "__main__":
    unittest.main()
