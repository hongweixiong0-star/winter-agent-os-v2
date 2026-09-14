from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.verifier import verify_building_upgrade
from winter_agent_v2.vision import ReplayVision, SemanticWorldVision
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry


ROOT = Path(__file__).resolve().parents[1]


class BuildVerifierTests(unittest.TestCase):
    def test_live_warehouse_upgrade_started(self) -> None:
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_build_warehouse_upgrade_dialog.png")
        after = vision.observe(ROOT / "dataset/raw/live_build_warehouse_started.png")
        result = verify_building_upgrade(before, after, "STOREHOUSE")
        self.assertTrue(result.ok, result)

    def test_brain_selects_verified_build_skill(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset/candidate/templates_manifest.json")
        state = vision.observe(ROOT / "dataset/raw/live_build_warehouse_upgrade_dialog.png")
        decision = RuleBrain().decide(state, v2_registry())
        self.assertEqual(decision.skill, "BUILDING_UPGRADE")


if __name__ == "__main__":
    unittest.main()
