import unittest
from pathlib import Path

from winter_agent_v2.verifier import verify_alliance_daily_chain, verify_dispatch, verify_gathering, verify_training_started
from winter_agent_v2.vision import ReplayVision, SemanticWorldVision

from tests.live_stack import production_vision


ROOT = Path(__file__).resolve().parents[1]


class MultiTaskProductionChainTests(unittest.TestCase):
    def test_train_then_gather_live_state_chain(self):
        # A dispatch is proven by the march count increasing, so this needs the
        # stack that can actually read it (template + OCR).
        vision = production_vision()
        if vision is None:
            self.skipTest("OCR runtime unavailable; cannot read live march counts")
        train_before = vision.observe(ROOT / "dataset/raw/live_train_selection_available.png")
        train_after = vision.observe(ROOT / "dataset/raw/live_train_started.png")
        gather_before = vision.observe(ROOT / "dataset/raw/live_multitask_gather_map_ready.png")
        marching = vision.observe(ROOT / "dataset/raw/live_multitask_gather_marching.png")
        gathering = vision.observe(ROOT / "dataset/raw/live_multitask_gather_arrived.png")
        self.assertTrue(verify_training_started(train_before, train_after, "INFANTRY").ok)
        self.assertTrue(verify_dispatch(gather_before, marching, "WOOD").ok)
        self.assertTrue(verify_gathering(gathering).ok)

    def test_alliance_contributions_complete_and_claim_daily_task(self):
        vision = ReplayVision(ROOT / "tests/replay/labels.json")
        names = [
            "live_cycle2_daily_tasks.png",
            "live_cycle2_alliance_tech.png",
            "live_cycle2_alliance_before.png",
            "live_cycle2_alliance_result1.png",
            "live_cycle2_alliance_result2.png",
            "live_cycle2_alliance_verified.png",
            "live_cycle2_daily_claimable.png",
            "live_cycle2_daily_reward.png",
            "live_cycle2_daily_after.png",
        ]
        states = [vision.observe(ROOT / "dataset/raw" / name) for name in names]
        self.assertTrue(verify_alliance_daily_chain(states[0], states[1], states[2], tuple(states[3:5]), *states[5:]).ok)

    def test_dynamic_chain_requires_ocr_not_template_only(self):
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        names = [
            "live_cycle2_daily_tasks.png",
            "live_cycle2_alliance_tech.png",
            "live_cycle2_alliance_before.png",
            "live_cycle2_alliance_result1.png",
            "live_cycle2_alliance_result2.png",
            "live_cycle2_alliance_verified.png",
            "live_cycle2_daily_claimable.png",
            "live_cycle2_daily_reward.png",
            "live_cycle2_daily_after.png",
        ]
        states = [vision.observe(ROOT / "dataset/raw" / name) for name in names]
        result = verify_alliance_daily_chain(states[0], states[1], states[2], tuple(states[3:5]), *states[5:])
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
