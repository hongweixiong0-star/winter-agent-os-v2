import unittest
from pathlib import Path

from winter_agent_v2.models import Page
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_all_training_queues_busy, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_training_queue, verify_training_started
from winter_agent_v2.vision import ReplayVision, SemanticWorldVision


ROOT = Path(__file__).resolve().parents[1]


class TrainingVerifierTests(unittest.TestCase):
    def test_current_training_navigation_chain(self) -> None:
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        home = vision.observe(ROOT / "dataset/raw/live_20260908_next_batch_home.png")
        overview = vision.observe(ROOT / "dataset/raw/live_20260908_power_entry.png")
        details = vision.observe(ROOT / "dataset/raw/live_20260908_power_details.png")
        highlighted = vision.observe(ROOT / "dataset/raw/live_20260908_training_navigation_settled.png")
        selected = vision.observe(ROOT / "dataset/raw/live_20260908_training_menu_current.png")
        training = vision.observe(ROOT / "dataset/raw/live_20260908_training_available_current.png")
        self.assertTrue(verify_power_overview_open(home, overview).ok)
        self.assertTrue(verify_power_details_open(overview, details).ok)
        self.assertTrue(verify_infantry_camp_highlighted(details, highlighted).ok)
        self.assertTrue(verify_infantry_camp_selected(highlighted, selected).ok)
        self.assertTrue(verify_training_page_open(selected, training).ok)
        expected = ("OPEN_POWER_OVERVIEW", "OPEN_POWER_DETAILS", "NAVIGATE_INFANTRY_CAMP", "SELECT_INFANTRY_CAMP", "OPEN_INFANTRY_TRAINING", "TRAIN_TROOPS")
        states = (home, overview, details, highlighted, selected, training)
        self.assertEqual(tuple(RuleBrain(current_goal="TRAIN").decide(s, v2_registry()).skill for s in states), expected)

    def test_live_three_training_queues_are_busy(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        paths = [
            ROOT / "dataset" / "raw" / "live_train_queue_busy.png",
            ROOT / "dataset" / "raw" / "live_train_lancer_tab.png",
            ROOT / "dataset" / "raw" / "live_train_marksman_tab.png",
        ]
        states = tuple(vision.observe(path) for path in paths)
        self.assertTrue(all(state.page is Page.TRAINING for state in states))
        self.assertTrue(verify_training_queue(states[0], "INFANTRY").ok)
        self.assertTrue(verify_all_training_queues_busy(states).ok)

    def test_single_busy_queue_does_not_prove_all_three(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "live_train_queue_busy.png")
        self.assertFalse(verify_all_training_queues_busy((state,)).ok)

    def test_live_infantry_training_start(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        before = vision.observe(ROOT / "dataset/raw/live_train_selection_available.png")
        after = vision.observe(ROOT / "dataset/raw/live_train_started.png")
        self.assertEqual(RuleBrain().decide(before, v2_registry()).skill, "TRAIN_TROOPS")
        self.assertTrue(verify_training_started(before, after, "INFANTRY").ok)
        self.assertEqual(after.training["batch_count"], 806)
