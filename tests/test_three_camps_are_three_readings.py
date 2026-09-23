"""One barracks being busy must not close the training check for the other two.

Open issue #86, operator P0 2026-09-21::

    某个兵营正在训练、入口暂时不可用或识别失败，不得直接宣布整个训练 Goal 完成，
    也不得阻止检查另外两个兵营。

Before this, ``KEEP_TRAINING_PRODUCTIVE`` was decided from a single ``world.training``
reading, and ``_append_queue_goal`` marked the whole goal COMPLETE as soon as that one
queue looked busy.  The client has three barracks on one page, so the shield camp running
was enough to make 矛兵营 and 射手营 unreadable-in-practice: nothing ever opened their tabs.

The frame these tests are built from is a real one -- the same picture the OCR readings
were measured on::

    dataset/truth_audit/training_three_barracks_20260921/key/
        03_training_page_infantry_002515_250_20260921T015321.png

live 2026-09-21T01:53:21Z, page=TRAINING, 训练中, 盾兵营, 正在训练250位英勇盾兵, 00:25:15.
It is the only kind of training frame in the whole corpus: all eight are the shield camp.

What is pinned here
-------------------
* the three camps are three readings, and a frame showing one says nothing about the other
  two -- not "idle", not "busy", just not read;
* a busy camp closes **its own** goal and nothing else;
* a camp that was never opened stays schedulable, so the loop goes and looks;
* merging keeps a camp's reading when another camp is looked at next;
* a non-training frame produces no camps at all;
* the page's own countdown/batch belong to the camp that was open on it, and to no other.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.camp_training import (  # noqa: E402
    CAMP_LABELS,
    CAMP_ORDER,
    CampReading,
    camp_from_selected_label,
    merge_camps,
    observe_camps,
    summarise_camps,
)
from winter_agent_v2.goal_library import CAMP_GOAL_FOR, GoalLibrary, GoalStatus  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402

#: The real reading the OCR classifier produced on the frame named in the docstring.
SHIELD_BUSY = {
    "status": "IN_PROGRESS",
    "queue_available": False,
    "troop_type": "INFANTRY",
    "timer": "00:25:15",
    "batch_count": 250,
    "camp_selected_label": "盾兵营",
}


class TheFrameNamesItsCampTests(unittest.TestCase):
    """Which barracks a frame is about, read from the tab the client draws as selected."""

    def test_the_real_shield_frame_names_the_shield_camp(self):
        camps = observe_camps(page_is_training=True, training=SHIELD_BUSY)
        self.assertEqual(list(camps), ["SHIELD_CAMP"])
        self.assertEqual(camps["SHIELD_CAMP"]["label"], "盾兵营")
        self.assertIs(camps["SHIELD_CAMP"]["busy"], True)
        self.assertEqual(camps["SHIELD_CAMP"]["timer"], "00:25:15")
        self.assertEqual(camps["SHIELD_CAMP"]["batch_count"], 250)

    def test_only_the_open_camp_is_reported(self):
        """A frame that shows 盾兵营 says nothing about the other two, and does not guess."""
        camps = observe_camps(page_is_training=True, training=SHIELD_BUSY)
        self.assertNotIn("LANCER_CAMP", camps)
        self.assertNotIn("MARKSMAN_CAMP", camps)

    def test_a_frame_that_is_not_the_training_page_produces_no_camps(self):
        """The page test comes first; a map frame cannot invent a queue state."""
        self.assertEqual(observe_camps(page_is_training=False, training=SHIELD_BUSY), {})

    def test_a_frame_that_names_no_camp_produces_no_reading(self):
        """No page title, no selected tab: nothing to attribute the numbers to."""
        self.assertEqual(observe_camps(page_is_training=True, training={"status": "IN_PROGRESS"}), {})

    def test_the_selected_label_decides_between_the_three(self):
        self.assertEqual(camp_from_selected_label(["盾兵营"]), "SHIELD_CAMP")
        self.assertEqual(camp_from_selected_label(["矛兵营"]), "LANCER_CAMP")
        self.assertEqual(camp_from_selected_label(["射手营"]), "MARKSMAN_CAMP")

    def test_two_selected_labels_are_ambiguous_and_answer_nothing(self):
        """All three names are drawn at once, so 'two selected' is an unread frame."""
        self.assertIsNone(camp_from_selected_label(["盾兵营", "矛兵营"]))
        self.assertIsNone(camp_from_selected_label([]))

    def test_an_available_queue_is_a_free_queue_not_an_unknown_one(self):
        camps = observe_camps(
            page_is_training=True, selected_camp="LANCER_CAMP",
            training={"status": "AVAILABLE", "troop_type": "LANCER", "queue_available": True},
        )
        self.assertIs(camps["LANCER_CAMP"]["busy"], False)
        self.assertIs(camps["LANCER_CAMP"]["queue_available"], True)


class OneCampIsNotTheOtherTwoTests(unittest.TestCase):
    """The goal layer: three tickets, and a busy one closes only itself."""

    def _goals(self, camps):
        world = WorldState(page=Page.TRAINING, training=SHIELD_BUSY, camps=camps)
        return {goal.goal_id: goal for goal in GoalLibrary().discover(world)}

    def test_a_busy_shield_camp_does_not_close_the_other_two(self):
        camps = observe_camps(page_is_training=True, training=SHIELD_BUSY)
        goals = self._goals(camps)
        # BLOCKED, not COMPLETE: a camp the client is already training is §一's
        # WAITING_GAME_CONDITION -- the work exists and the client is doing it -- while COMPLETE is
        # "本次任务实际完成".  The two were the same record until 2026-09-23, and the cost is visible
        # wherever someone asks why a barracks was not started.  Nothing about *selection* changed:
        # both statuses are in ``NOT_ACTIONABLE``, so neither can be picked; the label is now true,
        # and the camp's own countdown travels with it as ``retry_after``.
        self.assertIs(goals[CAMP_GOAL_FOR["SHIELD_CAMP"]].status, GoalStatus.BLOCKED)
        self.assertEqual(goals[CAMP_GOAL_FOR["SHIELD_CAMP"]].evidence["condition"], "camp_queue_busy")
        # The point of the whole module: these two are still work, not "done".
        self.assertIsNot(goals[CAMP_GOAL_FOR["LANCER_CAMP"]].status, GoalStatus.COMPLETE)
        self.assertIsNot(goals[CAMP_GOAL_FOR["MARKSMAN_CAMP"]].status, GoalStatus.COMPLETE)
        self.assertTrue(goals[CAMP_GOAL_FOR["LANCER_CAMP"]].available_skills)
        self.assertTrue(goals[CAMP_GOAL_FOR["MARKSMAN_CAMP"]].available_skills)

    def test_a_camp_that_was_never_opened_stays_schedulable(self):
        """DISCOVERED, not COMPLETE and not absent: the loop has to go and look."""
        camps = observe_camps(page_is_training=True, training=SHIELD_BUSY)
        goals = self._goals(camps)
        for camp in ("LANCER_CAMP", "MARKSMAN_CAMP"):
            goal = goals[CAMP_GOAL_FOR[camp]]
            self.assertIs(goal.status, GoalStatus.DISCOVERED)
            self.assertEqual(goal.available_skills, ("TRAIN_TROOPS",))
            self.assertEqual(goal.evidence["reason"], "this_camp_has_never_been_opened")

    def test_a_free_camp_is_ready_work(self):
        camps = observe_camps(
            page_is_training=True, selected_camp="MARKSMAN_CAMP",
            training={"status": "AVAILABLE", "troop_type": "MARKSMAN"},
        )
        goals = self._goals(camps)
        goal = goals[CAMP_GOAL_FOR["MARKSMAN_CAMP"]]
        self.assertIs(goal.status, GoalStatus.READY)
        self.assertEqual(goal.evidence["reason"], "this_camp_has_a_free_queue")

    def test_each_camp_keeps_its_own_answer_when_all_three_have_been_seen(self):
        """Three visits, three answers, none of them standing in for another."""
        camps = {}
        camps = merge_camps(camps, observe_camps(
            page_is_training=True, selected_camp="SHIELD_CAMP", training=SHIELD_BUSY))
        camps = merge_camps(camps, observe_camps(
            page_is_training=True, selected_camp="LANCER_CAMP",
            training={"status": "AVAILABLE", "troop_type": "LANCER"}))
        camps = merge_camps(camps, observe_camps(
            page_is_training=True, selected_camp="MARKSMAN_CAMP",
            training={"status": "AVAILABLE", "troop_type": "MARKSMAN"}))
        goals = self._goals(camps)
        self.assertIs(goals[CAMP_GOAL_FOR["SHIELD_CAMP"]].status, GoalStatus.BLOCKED)
        self.assertIs(goals[CAMP_GOAL_FOR["LANCER_CAMP"]].status, GoalStatus.READY)
        self.assertIs(goals[CAMP_GOAL_FOR["MARKSMAN_CAMP"]].status, GoalStatus.READY)

    def test_looking_at_one_camp_does_not_erase_what_another_taught_us(self):
        shield = observe_camps(page_is_training=True, selected_camp="SHIELD_CAMP", training=SHIELD_BUSY)
        lancer = observe_camps(
            page_is_training=True, selected_camp="LANCER_CAMP",
            training={"status": "AVAILABLE", "troop_type": "LANCER"})
        merged = merge_camps(shield, lancer)
        self.assertIs(merged["SHIELD_CAMP"]["busy"], True)
        self.assertEqual(merged["SHIELD_CAMP"]["timer"], "00:25:15")
        self.assertIs(merged["LANCER_CAMP"]["busy"], False)

    def test_the_summary_counts_the_three_separately(self):
        camps = observe_camps(page_is_training=True, training=SHIELD_BUSY)
        summary = summarise_camps(camps)
        self.assertEqual(summary["busy"], ["SHIELD_CAMP"])
        self.assertEqual(summary["trainable"], [])
        self.assertEqual(summary["unread"], ["LANCER_CAMP", "MARKSMAN_CAMP"])
        self.assertFalse(summary["all_accounted_for"])

    def test_all_three_accounted_for_only_when_all_three_were_read(self):
        camps = {}
        for camp, label in (("SHIELD_CAMP", "盾兵营"), ("LANCER_CAMP", "矛兵营"),
                            ("MARKSMAN_CAMP", "射手营")):
            troop = {"SHIELD_CAMP": "INFANTRY", "LANCER_CAMP": "LANCER",
                     "MARKSMAN_CAMP": "MARKSMAN"}[camp]
            camps = merge_camps(camps, observe_camps(
                page_is_training=True, selected_camp=camp,
                training={"status": "IN_PROGRESS", "troop_type": troop, "timer": "00:01:00"}))
        summary = summarise_camps(camps)
        self.assertEqual(summary["unread"], [])
        self.assertTrue(summary["all_accounted_for"])
        self.assertEqual(sorted(summary["busy"]), sorted(CAMP_ORDER))


class TheReadingIsHonestAboutWhatItDidNotSeeTests(unittest.TestCase):
    """``None`` is not ``False``: an unread queue is not an empty one."""

    def test_an_unread_camp_reports_no_busy_answer(self):
        reading = CampReading(camp="LANCER_CAMP")
        self.assertIsNone(reading.busy)
        self.assertFalse(reading.observed)

    def test_a_camp_read_as_free_is_distinguishable_from_unread(self):
        free = CampReading(camp="LANCER_CAMP", status="AVAILABLE", queue_available=True)
        self.assertIs(free.busy, False)
        self.assertTrue(free.observed)

    def test_every_camp_has_a_label_and_a_goal(self):
        for camp in CAMP_ORDER:
            self.assertIn(camp, CAMP_LABELS)
            self.assertIn(camp, CAMP_GOAL_FOR)


class TheProductionEntryPointNamesTheSameCampTests(unittest.TestCase):
    """The frame above, read through the door production actually uses.

    Measured 2026-09-21.  Every other test in this file feeds ``observe_camps`` a dictionary
    written by hand, so they pin the camp model and nothing about whether production reaches
    it.  That distinction already cost a day: the OCR training branch was nested behind a
    contradictory guard and never ran in production while its unit test passed, because the
    test called one layer below the entry point.

    Run against the real frame, not a fixture -- a hand-written reading cannot show that the
    client's pixels resolve to the shield camp.
    """

    FRAME = (ROOT / "dataset" / "truth_audit" / "training_three_barracks_20260921" / "key"
             / "03_training_page_infantry_002515_250_20260921T015321.png")

    @classmethod
    def setUpClass(cls):
        import json
        from winter_agent_v2.ocr import (
            HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend,
        )
        from winter_agent_v2.vision import SemanticWorldVision

        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        service = OCRService(
            ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
        )
        cls.hybrid = HybridVision(
            SemanticWorldVision(ROOT / "dataset" / "candidate" / "template_manifest.json"),
            service,
        )

    def test_the_real_frame_resolves_to_the_shield_camp(self):
        """盾兵营 was open on this frame, and that is the answer the camp model must carry."""
        state = self.hybrid.observe(self.FRAME)
        self.assertIs(state.page, Page.TRAINING)
        self.assertIn("SHIELD_CAMP", state.camps,
                      "the page title names 英勇盾兵 -- a pixel test on the tabs once put this "
                      "frame in MARKSMAN_CAMP, which is why the title is the primary signal")
        self.assertIs(state.camps["SHIELD_CAMP"]["busy"], True)
        self.assertEqual(state.camps["SHIELD_CAMP"]["timer"], "00:25:15")

    def test_the_numbers_belong_to_the_camp_that_was_open(self):
        state = self.hybrid.observe(self.FRAME)
        for other in ("LANCER_CAMP", "MARKSMAN_CAMP"):
            self.assertNotIn(other, state.camps,
                             "nobody opened this barracks, so it has no reading to carry")

    def test_three_goals_are_discovered_from_what_production_saw(self):
        """End to end: real pixels in, three independently-scheduled tickets out."""
        state = self.hybrid.observe(self.FRAME)
        goals = {goal.goal_id: goal for goal in GoalLibrary().discover(state)}
        for camp in CAMP_ORDER:
            self.assertIn(CAMP_GOAL_FOR[camp], goals, f"{camp} must have its own ticket")
        self.assertIs(goals[CAMP_GOAL_FOR["SHIELD_CAMP"]].status, GoalStatus.BLOCKED)
        for camp in ("LANCER_CAMP", "MARKSMAN_CAMP"):
            self.assertIs(goals[CAMP_GOAL_FOR[camp]].status, GoalStatus.DISCOVERED)
            self.assertTrue(goals[CAMP_GOAL_FOR[camp]].available_skills,
                            "a barracks nobody opened is work, not a finished goal")


class TheOldSingleReadingIsStillReportedTests(unittest.TestCase):
    """A reading that names no camp is kept and labelled, never silently attributed."""

    def test_a_legacy_reading_with_a_known_troop_type_names_its_camp(self):
        world = WorldState(
            page=Page.TRAINING,
            training={"troop_type": "INFANTRY", "status": "IN_PROGRESS", "queue_available": False},
        )
        goals = {goal.goal_id: goal for goal in GoalLibrary().discover(world)}
        self.assertIn(CAMP_GOAL_FOR["SHIELD_CAMP"], goals)
        self.assertIs(goals[CAMP_GOAL_FOR["SHIELD_CAMP"]].status, GoalStatus.BLOCKED)

    def test_an_unreadable_training_page_is_still_one_discovery_ticket(self):
        """Exactly one, not two: the camp branch and SWEEP_ROUTINES must not both emit it."""
        world = WorldState(page=Page.MAP)
        ids = [goal.goal_id for goal in GoalLibrary().discover(world)
               if goal.goal_id == "KEEP_TRAINING_PRODUCTIVE"]
        self.assertEqual(len(ids), 1, "one page, one ticket")


if __name__ == "__main__":
    unittest.main()
