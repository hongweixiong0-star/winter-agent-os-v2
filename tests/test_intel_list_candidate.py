import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_intel_list_read
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]


class IntelListCandidateTests(unittest.TestCase):
    def test_live_unknown_sample_is_now_structured_and_verified(self):
        state = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").observe(
            ROOT / "dataset/raw/event_calibration/intel_score_attempt_1/step_002_before.png")
        self.assertEqual(state.intel["status"], "AVAILABLE")
        self.assertEqual(state.intel["mission_type"], "BEAST")
        self.assertTrue(state.intel["list_read"])
        self.assertTrue(verify_intel_list_read(state, state).ok)

    def test_unstructured_known_intel_requests_candidate_read(self):
        state = WorldState(page=Page.INTEL, intel={"status":"AVAILABLE"}, confidence=.9)
        self.assertEqual(RuleBrain(current_goal="INTEL").decide(state, v2_registry()).skill, "READ_INTEL_LIST")


if __name__ == "__main__": unittest.main()
