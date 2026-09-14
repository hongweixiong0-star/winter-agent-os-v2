from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.verifier import verify_gather_cycle
from winter_agent_v2.vision import P0SemanticVision


ROOT = Path(__file__).resolve().parents[1]


class LiveGatherVerifierTests(unittest.TestCase):
    def test_attempt8_full_cycle_from_live_screenshots(self) -> None:
        vision = P0SemanticVision(ROOT / "dataset/candidate/templates_manifest.json")
        result = verify_gather_cycle(
            vision.observe(ROOT / "dataset/raw/live_executor_search_open.png"),
            vision.observe(ROOT / "dataset/raw/live_attempt8_marching.png"),
            vision.observe(ROOT / "dataset/raw/live_attempt8_transition.png"),
            vision.observe(ROOT / "dataset/raw/live_attempt8_idle.png"),
            "WOOD",
        )
        self.assertTrue(result.ok, result)


if __name__ == "__main__":
    unittest.main()
