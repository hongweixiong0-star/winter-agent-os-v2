from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.executor import Executor
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import p0_registry
from winter_agent_v2.verifier import verify_dispatch, verify_gathering
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class ReplayIntegrationTests(unittest.TestCase):
    def test_state_brain_skill_executor_verifier_chain(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        scheduler = Scheduler(RuleBrain(), p0_registry(), Executor())

        home = vision.observe(ROOT / "dataset" / "raw" / "legacy_home.png")
        self.assertEqual(scheduler.tick(home).decision.skill, "OPEN_MAP")

        world_map = vision.observe(ROOT / "dataset" / "raw" / "legacy_wilderness.png")
        self.assertEqual(scheduler.tick(world_map).decision.skill, "SEARCH_RESOURCE")

        search_panel = vision.observe(ROOT / "dataset" / "raw" / "legacy_search_resource_panel.png")
        self.assertEqual(scheduler.tick(search_panel).decision.skill, "SELECT_RESOURCE")

        wood_selected = vision.observe(ROOT / "dataset" / "raw" / "legacy_search_wood_selected.png")
        self.assertEqual(scheduler.tick(wood_selected).decision.skill, "SUBMIT_RESOURCE_SEARCH")

        resource = vision.observe(ROOT / "dataset" / "raw" / "legacy_available_resource_detail.png")
        self.assertEqual(scheduler.tick(resource).decision.skill, "START_GATHER")

        gathering = vision.observe(ROOT / "dataset" / "raw" / "legacy_resource_detail.png")
        tick = scheduler.tick(gathering)
        self.assertEqual(tick.decision.skill, "VERIFY_GATHERING")
        self.assertTrue(tick.execution.executed)
        self.assertTrue(verify_gathering(gathering).ok)

        before = vision.observe(ROOT / "dataset" / "raw" / "legacy_dispatch_before.png")
        after = vision.observe(ROOT / "dataset" / "raw" / "legacy_dispatch_after.png")
        self.assertTrue(verify_dispatch(before, after, "WOOD").ok)


if __name__ == "__main__":
    unittest.main()
