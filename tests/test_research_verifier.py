from pathlib import Path
import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_research_queue, verify_research_started
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class ResearchVerifierTests(unittest.TestCase):
    def test_live_research_queue_is_recognized_as_busy(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "live_research_queue_busy.png")
        self.assertIs(state.page, Page.RESEARCH)
        self.assertEqual(state.research["node"], "WARD_EXPANSION_VII")
        self.assertTrue(verify_research_queue(state).ok)
        decision = RuleBrain().decide(state, v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "research_queue_busy")

    def test_live_research_recheck_remains_busy(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "live_research_recheck_active.png")
        self.assertIs(state.page, Page.RESEARCH)
        self.assertEqual(state.research["timer"], "5d00:55:44")
        self.assertTrue(verify_research_queue(state).ok)
        decision = RuleBrain().decide(state, v2_registry())
        self.assertEqual((decision.skill, decision.reason), ("SAFE_STOP", "research_queue_busy"))

    def test_current_home_research_queue_is_recognized_busy(self) -> None:
        from winter_agent_v2.vision import SemanticWorldVision
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        state = vision.observe(ROOT / "dataset/raw/live_20260908_research_navigation_current.png")
        self.assertIs(state.page, Page.HOME)
        self.assertFalse(state.research["queue_available"])
        decision = RuleBrain(current_goal="RESEARCH").decide(state, v2_registry())
        self.assertEqual((decision.skill, decision.reason), ("SAFE_STOP", "research_queue_busy"))

    def test_research_start_requires_available_to_busy_transition(self) -> None:
        before = WorldState(page=Page.RESEARCH, research={"queue_available": True, "researchable": True})
        after = WorldState(
            page=Page.RESEARCH,
            research={
                "node": "WARD_EXPANSION_VII",
                "status": "IN_PROGRESS",
                "timer": "6d05:20:54",
                "queue_available": False,
            },
        )
        self.assertTrue(verify_research_started(before, after, "WARD_EXPANSION_VII").ok)
