"""The training page is recognised by OCR, and its numbers are readings.

Measured 2026-09-21.  `KEEP_TRAINING_PRODUCTIVE` could never act, and the reason was upstream of
the goal: its own page has no working template.  On the frame production itself recorded as
`page=TRAINING`, the current template layer answers UNKNOWN, because

    PAGE_TRAINING_INFANTRY / _LANCER / _MARKSMAN   no match
    TRAINING_QUEUE_TIMER                           no match
    TAB_TRAINING_LANCER and TAB_TRAINING_MARKSMAN  both d=2 -- identical art, and both cut from
                                                   the *unselected* tab, so they cannot tell the
                                                   three barracks apart even when they do match

They are CANDIDATE records cut from old screenshots (`REPLAY_HUMAN_REVIEWED_SCREENSHOT`), never
measured on the client.  So `world.training` was empty on every frame, `TRAIN_TROOPS` (which
requires ``Page.TRAINING``) could never run, and the branch that was supposed to fill it carried
``tier: 10`` / ``batch_count: 806`` -- constants off one old screenshot written as if they had been
read off the frame being classified.  Those are gone.

The same frames answer the OCR classifier exactly: 训练中 + 盾兵营 + 正在训练250位英勇盾兵 +
01:00:08.  Over all eight live training frames in the corpus it returns
TRAINING/INFANTRY/IN_PROGRESS with countdowns 01:09:31, 01:00:00, 01:00:08, 00:59:58, 02:59:45,
02:59:33, 00:25:15, 00:25:05 and batch counts 216/250.  ``HybridVision`` now consults it when the
template layer has nothing.

Both halves matter and both are here: the page must be recognised, and nothing else may become it.
Measured over fourteen non-training live frames the classifier answers ALLIANCE (where production
says ALLIANCE) or UNKNOWN, and never TRAINING; through the production entry point, 0 of 14 changed
page.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    HybridVision,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

KEYS = ROOT / "dataset" / "truth_audit" / "training_three_barracks_20260921" / "key"

#: frame -> the countdown and batch count the client printed on it, read by eye.
#: Three separate sessions, which is why the countdowns differ: a constant could not produce this.
TRAINING_FRAMES = {
    "01_training_page_infantry_100008_250_20260920T013348.png": ("01:00:08", 250),
    "02_training_page_infantry_025945_250_20260920T231851.png": ("02:59:45", 250),
    "03_training_page_infantry_002515_250_20260921T015321.png": ("00:25:15", 250),
}

#: Frames that are plainly not the training page, from other published evidence sets.
OTHER_PAGES = (
    ROOT / "dataset" / "truth_audit" / "march_reservation_20260921" / "key"
    / "01_the_frame_the_reservation_ended_the_round_20260921T031751.png",
    ROOT / "dataset" / "truth_audit" / "reward_popup_exit_20260920" / "key"
    / "01_shared_reward_popup_step_001_before_20260920T124146.png",
)

COUNTDOWN = re.compile(r"^\d{2}:\d{2}:\d{2}$")


class TrainingPageIsReadByOcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        cls.service = OCRService(
            ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
        )
        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        cls.template_only = SemanticWorldVision(manifest)
        cls.hybrid = HybridVision(cls.template_only, cls.service)

    def _frame(self, name: str) -> Path:
        path = KEYS / name
        self.assertTrue(path.is_file(), f"evidence frame missing: {path}")
        return path

    def test_the_template_layer_alone_cannot_name_the_page(self):
        """The reason the fallback exists, pinned rather than described."""
        for name in TRAINING_FRAMES:
            with self.subTest(frame=name):
                state = self.template_only.observe(self._frame(name))
                self.assertIs(state.page, Page.UNKNOWN,
                              "if a training template starts matching, revisit the OCR fallback")

    def test_the_page_and_its_numbers_are_read_off_the_frame(self):
        for name, (countdown, batch) in TRAINING_FRAMES.items():
            with self.subTest(frame=name):
                state = self.hybrid.observe(self._frame(name))
                self.assertIs(state.page, Page.TRAINING)
                self.assertEqual(state.training.get("troop_type"), "INFANTRY",
                                 "盾兵营 is the barrack this page is showing")
                self.assertEqual(state.training.get("status"), "IN_PROGRESS")
                self.assertEqual(state.training.get("queue_available"), False)
                self.assertEqual(state.training.get("timer"), countdown)
                self.assertEqual(state.training.get("batch_count"), batch)

    def test_the_countdown_is_a_reading_and_not_a_shape(self):
        """A constant cannot produce three different countdowns from three sessions."""
        seen = set()
        for name in TRAINING_FRAMES:
            state = self.hybrid.observe(self._frame(name))
            self.assertRegex(str(state.training.get("timer")), COUNTDOWN)
            seen.add(state.training.get("timer"))
        self.assertEqual(len(seen), len(TRAINING_FRAMES))

    def test_no_other_page_becomes_the_training_page(self):
        """The false-positive half: an UNKNOWN frame may only become TRAINING if it IS one."""
        for path in OTHER_PAGES:
            if not path.is_file():
                continue
            with self.subTest(frame=path.name[:48]):
                self.assertIsNot(self.hybrid.observe(path).page, Page.TRAINING)

    def test_the_fabricated_constants_are_gone(self):
        """``tier: 10`` / ``batch_count: 806`` were one screenshot's numbers served as readings."""
        source = (ROOT / "winter_agent_v2" / "vision.py").read_text(encoding="utf-8")
        body = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn('"batch_count": 806', body)
        self.assertNotIn('"tier": 10', body)

    def test_the_fallback_is_gated_on_the_template_layer_having_nothing(self):
        """It may fill a blank, not overrule an answer -- the same rule the other enrichers use."""
        source = (ROOT / "winter_agent_v2" / "ocr.py").read_text(encoding="utf-8")
        self.assertIn("if primary.page is Page.UNKNOWN and not primary.training:", source)
        self.assertIn("if secondary.page is Page.TRAINING and secondary.training:", source)


if __name__ == "__main__":
    unittest.main()
