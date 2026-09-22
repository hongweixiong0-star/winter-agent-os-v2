"""The last step on a page that was reached: two reported faults, pinned on the frames that showed them.

Operator 2026-09-22, two live failures:

    故障 A：已经进入"挂机收益"弹窗，绿色"领取"按钮清楚可见，但游戏停留在弹窗没有完成领取。
    故障 B：已经进入射手营训练页面，蓝色"训练"按钮清楚可见，但 V2 没有点击训练，随后返回主城。

Both were traced to the same class of break -- the page model did not describe the state the frame was
actually in, so the brain had no action to emit and the route left a page it had just reached:

* the 挂机收益 dialog had **no recogniser at all** (``POPUP_EXPLORATION_IDLE_DIALOG`` exists in the
  template manifest with zero templates) while OCR reads its words at 1.00, so the claim verifier
  reported DIALOG_NOT_PROVEN on a tap that had in fact opened it;
* the training page set ``IN_PROGRESS``/``queue_available=False`` before reading a single token, and
  read the training button's **own caption** (the projected duration of the batch it would start) as a
  queue countdown -- and only the template path could ever set ``trainable``, which is the one key the
  brain's TRAIN_TROOPS gate reads.  A camp goal additionally did not *own* the training page at all.

These tests use the archived frames that produced the failures.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ocr as ocr_module  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import verify_exploration_claim_feedback  # noqa: E402

AUTO = ROOT / "dataset/raw/control_panel/runtime_auto"
CONFIG = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))

#: The live frames: the exploration page, the dialog the client answered with, and the 射手营 page the
#: route walked away from.
CLAIM_BEFORE = sorted(AUTO.glob("*/" + "*_step_002_before_20260922T112112745827.png"))[-1]
CLAIM_DIALOG = sorted(AUTO.glob("*/" + "*_step_002_after_refresh_2_20260922T112144508334.png"))[-1]
MARKSMAN_PAGE = sorted(AUTO.glob("*/" + "*_step_010_before_20260922T112451123479.png"))[-1]
LANCER_PAGE = sorted(AUTO.glob("*/" + "*_step_009_before_20260922T112425181244.png"))[-1]

_OCR = None


def _ocr():
    """One OCR service for the whole file: the frames are real and reading them is the point."""
    global _OCR
    if _OCR is None:
        _OCR = ocr_module.OCRService(
            ocr_module.ResilientOCRBackend(
                ocr_module.RapidOCRBackend(Path(CONFIG["ocr"]["module_path"]))
            )
        )
    return _OCR


def _brain(goal_id, goal=None):
    """A brain built the way the runtime builds it: the scheduler sets both fields."""
    brain = RuleBrain(current_goal=goal or goal_id)
    brain.goal_id = goal_id
    return brain


def _tokens(pairs, frame_size=(720, 1280)) -> OCRResult:
    return OCRResult(
        tuple(
            OCRToken(text=text, confidence=0.99, box=((x, y), (x + 40, y), (x + 40, y + 20), (x, y + 20)))
            for text, x, y in pairs
        ),
        "stub",
    )


class TheIdleIncomeDialogTests(unittest.TestCase):
    """故障 A: the dialog the client answers the claim with must be recognised as itself."""

    @classmethod
    def setUpClass(cls):
        cls.before = _ocr().recognize(CLAIM_BEFORE)
        cls.dialog = _ocr().recognize(CLAIM_DIALOG)

    def test_the_dialog_is_named_from_the_words_it_draws(self):
        state = OCRPageClassifier().classify(self.dialog, frame_size=(720, 1280))
        self.assertIs(state.page, Page.POPUP)
        self.assertEqual(state.popup, "EXPLORATION_IDLE_DIALOG")

    def test_the_claim_step_that_opened_it_now_verifies(self):
        """The measured failure: this pair produced EXPLORATION_IDLE_DIALOG_NOT_PROVEN."""
        before = WorldState(page=Page.EXPLORATION, exploration={"status": "CLAIMABLE"})
        from winter_agent_v2.ocr import HybridVision, RapidOCRBackend, ResilientOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision

        vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )
        before = vision.observe(CLAIM_BEFORE)
        after = vision.observe(CLAIM_DIALOG)
        result = verify_exploration_claim_feedback(before, after)
        self.assertTrue(result.ok, f"{result.reason} {result.evidence}")
        self.assertTrue(result.evidence["dialog_visible"])

    def test_the_brain_knows_which_skill_confirms_it(self):
        dialog = WorldState(page=Page.POPUP, popup="EXPLORATION_IDLE_DIALOG")
        decision = _brain("CLAIM_EXPLORATION_IDLE").decide(dialog, v2_registry())
        self.assertEqual(decision.skill, "CONFIRM_EXPLORATION_IDLE_CLAIM")

    def test_a_frame_without_those_words_is_not_this_dialog(self):
        """Only one of the two words is not enough, and neither is a frame that has neither."""
        title_only = _tokens([("挂机收益", 300, 280)])
        state = OCRPageClassifier().classify(title_only, frame_size=(720, 1280))
        self.assertNotEqual(state.popup, "EXPLORATION_IDLE_DIALOG")


class TheTrainingPageTests(unittest.TestCase):
    """故障 B: a barracks that can be started must be readable as startable."""

    @classmethod
    def setUpClass(cls):
        from winter_agent_v2.ocr import HybridVision
        from winter_agent_v2.vision import SemanticWorldVision

        cls.vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )

    def test_the_page_with_a_lit_training_button_is_startable(self):
        state = self.vision.observe(MARKSMAN_PAGE)
        self.assertIs(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("troop_type"), "MARKSMAN")
        self.assertEqual(state.training.get("status"), "AVAILABLE")
        self.assertTrue(state.training.get("queue_available"))
        self.assertTrue(state.training.get("trainable"), "the brain's own gate reads this key")
        self.assertIsNone(
            state.training.get("timer"),
            "the button's projected duration is not a queue countdown",
        )

    def test_a_running_queue_still_reads_as_busy(self):
        """The negative control: the word the client uses for a queue at work.

        Without this the fix would be "always call the camp startable", which is the opposite error
        and would retrain camps that are already working.
        """
        running = _tokens([
            ("英勇盾兵", 282, 20),
            ("盾兵营", 60, 1231),
            ("正在训练806位王牌盾兵", 200, 700),
            ("训练中", 200, 760),
        ])
        state = OCRPageClassifier().classify(running, frame_size=(720, 1280))
        self.assertIs(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("status"), "IN_PROGRESS")
        self.assertFalse(state.training.get("queue_available"))
        self.assertEqual(state.training.get("batch_count"), 806)
        self.assertIsNot(state.training.get("trainable"), True)

    def test_a_countdown_above_the_action_bar_is_still_a_queue_timer(self):
        """A queue's own countdown is drawn above the bar; the button's caption is inside it.

        Read on the real frame with one token added, so this isolates the one rule it is about: every
        other token is the frame the client actually drew.
        """
        base = _ocr().recognize(MARKSMAN_PAGE)
        with_countdown = OCRResult(
            tuple(base.tokens)
            + (OCRToken(text="02:33:11", confidence=0.99,
                        box=((520.0, 800.0), (560.0, 800.0), (560.0, 820.0), (520.0, 820.0))),),
            "real+one",
        )
        state = OCRPageClassifier().classify(with_countdown, frame_size=(720, 1280))
        self.assertIs(state.page, Page.TRAINING)
        self.assertEqual(state.training.get("timer"), "02:33:11")
        self.assertEqual(state.training.get("status"), "IN_PROGRESS")
        self.assertFalse(state.training.get("queue_available"))


class TheCampGoalOwnsThePageTests(unittest.TestCase):
    """故障 B's second half: a camp goal may act on the page it navigated to."""

    @classmethod
    def setUpClass(cls):
        from winter_agent_v2.ocr import HybridVision
        from winter_agent_v2.vision import SemanticWorldVision

        cls.vision = HybridVision(
            SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"), _ocr()
        )
        cls.marksman = cls.vision.observe(MARKSMAN_PAGE)
        cls.lancer = cls.vision.observe(LANCER_PAGE)

    def test_the_goal_whose_camp_is_open_trains(self):
        for goal, state in (("MARKSMAN_CAMP_TRAINING", self.marksman),
                            ("LANCER_CAMP_TRAINING", self.lancer)):
            decision = _brain(goal).decide(state, v2_registry())
            self.assertEqual(decision.skill, "TRAIN_TROOPS", f"{goal}: {decision.reason}")

    def test_a_goal_never_trains_somebody_elses_camp(self):
        decision = _brain("LANCER_CAMP_TRAINING").decide(self.marksman, v2_registry())
        self.assertEqual(decision.skill, "SELECT_TRAINING_CAMP")
        self.assertIn("LANCER_CAMP", decision.reason)

    def test_the_aggregate_goal_owns_the_page_too(self):
        """``KEEP_TRAINING_PRODUCTIVE``'s route is TRAIN, so it may train what is idle there."""
        decision = _brain("KEEP_TRAINING_PRODUCTIVE").decide(self.marksman, v2_registry())
        self.assertEqual(decision.skill, "TRAIN_TROOPS", decision.reason)

    def test_a_goal_from_another_route_still_leaves_the_page(self):
        """The guard this replaced must keep working: a mail goal has no business on this page."""
        decision = _brain("MAIL_ROUTINE").decide(self.marksman, v2_registry())
        self.assertEqual(decision.skill, "BACK")


if __name__ == "__main__":
    unittest.main()
