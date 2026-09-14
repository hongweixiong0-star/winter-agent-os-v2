import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_beast_hunt
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class BeastVerifierTests(unittest.TestCase):
    def test_live_beast_intel_hunt_cycle(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        names = [
            "live_beast_intel_world_target.png",
            "live_beast_march_selection.png",
            "live_beast_marching.png",
            "live_beast_return_complete.png",
            "live_beast_intel_completed.png",
        ]
        states = [vision.observe(ROOT / "dataset" / "raw" / name) for name in names]
        self.assertEqual(RuleBrain().decide(states[0], v2_registry()).skill, "BEAST_HUNT")
        self.assertTrue(verify_beast_hunt(*states).ok)

    def test_beast_hunt_rejects_missing_intel_completion(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        target = vision.observe(ROOT / "dataset" / "raw" / "live_beast_intel_world_target.png")
        march = vision.observe(ROOT / "dataset" / "raw" / "live_beast_march_selection.png")
        returning = vision.observe(ROOT / "dataset" / "raw" / "live_beast_marching.png")
        idle = vision.observe(ROOT / "dataset" / "raw" / "live_beast_return_complete.png")
        self.assertFalse(verify_beast_hunt(target, march, returning, idle, idle).ok)
