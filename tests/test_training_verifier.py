import unittest
from pathlib import Path

from winter_agent_v2.models import Page
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_all_training_queues_busy, verify_infantry_camp_highlighted, verify_infantry_camp_selected, verify_power_details_open, verify_power_overview_open, verify_training_page_open, verify_training_queue, verify_training_started
from winter_agent_v2.vision import ReplayVision, SemanticROIVision, SemanticWorldVision


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
        # Step 4 is WAIT_FOR_CAMP_MENU, and this is a measured retreat rather than the old
        # position it held before 2026-09-21.
        #
        # It was SELECT_INFANTRY_CAMP, aimed at the template's own centre -- tried live and
        # failed three times at (346, 682), one of them ending on the world map.  On 2026-09-21
        # the reason given for never tapping (a tutorial finger over the camp) was falsified and
        # the point was shown to be 103 px off, on bare ground 37 px below the ring, so the tap
        # was restored aimed at the ring's centre read from the frame.
        #
        # THEN IT WAS TRIED ON THE DEVICE, and it failed.  Live 2026-09-20T18:43:51Z:
        # action_backend ADB, the tap went out at (317, 583) -- inside the ring -- and the
        # outcome was FAILURE / INFANTRY_CAMP_MENU_NOT_PROVEN with after.training EMPTY: no
        # menu, and the ring gone as well, which is what the client does when a tap lands on
        # nothing.  Four live taps, four failures, one of them inside the ring.
        #
        # So aiming was not the problem, the tap is withdrawn, and what this state IS stays
        # open (issue #82).  The hypothesis worth testing next is that the gold ellipse means
        # "guided step", not "this camp is selected" -- in which case accepting it in
        # verify_infantry_camp_highlighted would be a FALSE ARRIVAL, and the training route's
        # first half has been reporting a success it never had.
        # Step 4 stopped being a wait on 2026-09-23 (issue #92): the ring that state is read from
        # is drawn by the client on its own schedule, so waiting on it waits on an animation.  The
        # blocker is the same one, reached at once.
        expected = ("OPEN_POWER_OVERVIEW", "OPEN_POWER_DETAILS", "NAVIGATE_INFANTRY_CAMP", "SAFE_STOP", "OPEN_INFANTRY_TRAINING", "TRAIN_TROOPS")
        states = (home, overview, details, highlighted, selected, training)
        self.assertEqual(tuple(RuleBrain(current_goal="TRAIN").decide(s, v2_registry()).skill for s in states), expected)

    def test_the_camp_highlight_signal_cannot_tell_the_two_states_apart(self) -> None:
        """The template distance cannot tell the two states apart -- and that is why the ring is used.

        Two real frames both report ``navigation == "INFANTRY_CAMP_HIGHLIGHTED"``
        while tapping the camp has two different outcomes -- menu versus world
        map.  ``TARGET_INFANTRY_CAMP_HIGHLIGHTED`` is 0.59 x 0.285 of the screen,
        i.e. it frames the *building*, and the building is in both frames; the
        highlight is only a light effect on top of it.  So the semantic separates
        the two states by a few distance levels, and the 2026-09-17 frame sits
        exactly ON the production ``max_distance``.

        Still true, and still worth pinning: this is a fact about the template, and the
        assertions below are about the template.

        What 2026-09-21 added is the answer to the question this docstring used to leave open
        ("if someone tightens the crop -- the real fix -- this test fails").  The fix was not a
        tighter crop: it is that the two frames differ in a *different* quantity entirely.  The
        menu frame carries a 205x112 gold selection ring; the map frame carries a 7x15 fleck
        (an officer badge's edge).  ``camp_ring.py`` measures that ring, so the route can now
        tell the two apart and taps only where a ring is actually drawn -- see
        tests/test_training_stage_a_tap.py, which pins one frame each way.
        """
        with_ring = (ROOT / "dataset/truth_audit/training_camp_highlight_ambiguity_20260917"
                     / "camp_with_gold_ring__click_opens_menu__20260908.png")
        with_badge = (ROOT / "dataset/truth_audit/training_camp_highlight_ambiguity_20260917"
                      / "camp_with_officer_badge__click_jumps_to_map__20260917.png")
        for frame in (with_ring, with_badge):
            if not frame.is_file():
                self.skipTest(f"evidence frame rotated away by retention: {frame.name}")

        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        # Both frames are read as "the camp is highlighted", though a tap does two
        # different things.
        self.assertEqual(vision.observe(with_ring).training.get("navigation"),
                         "INFANTRY_CAMP_HIGHLIGHTED")
        self.assertEqual(vision.observe(with_badge).training.get("navigation"),
                         "INFANTRY_CAMP_HIGHLIGHTED")

        # Read raw distances with the threshold lifted, so the measurement is
        # visible rather than clipped to "matched / not matched".
        raw = SemanticROIVision(ROOT / "dataset/candidate/template_manifest.json",
                                max_distance=64)
        distances = {}
        for label, frame in (("ring", with_ring), ("badge", with_badge)):
            match = raw.find(frame, "TARGET_INFANTRY_CAMP_HIGHLIGHTED")
            self.assertIsNotNone(match, label)
            distances[label] = match.distance

        self.assertLessEqual(distances["ring"], 2,
                             "the frame the template was cropped from must match closely")
        # The frame that must NOT read as highlighted is within the production
        # threshold.  That is the defect; a threshold tweak would only move the
        # knife edge, so the crop has to change instead.
        self.assertGreaterEqual(
            distances["badge"], SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json").semantic.max_distance,
            "if this now separates the two states, tighten nothing -- revisit the chain above",
        )

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
