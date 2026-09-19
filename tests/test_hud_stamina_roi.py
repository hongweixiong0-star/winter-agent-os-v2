"""The HUD stamina number must be read whole, not as its first two digits.

Measured 2026-09-19 on a live run.  The frame said **527** and ``world.stamina.current`` said
**52**: the recogniser's detector under-segments the small HUD number and can stop after the
second digit.  The glyphs are not clipped -- the ``7`` ends at frame x 63 and the old ROI's
right edge was x 70 -- so this was a detector failure, and the parser's fragment stitching could
not repair it because there was only one fragment to stitch.

It matters more than a wrong cell on a board.  ``AVOID_STAMINA_WASTE`` reads this number to
decide whether there is anything left to spend, so a dropped digit reads as "nearly empty"
while stamina is plentiful -- and the goal stops spending, which is the opposite of what it
exists for.  The same class produced the ``0/200`` reading that could not be corroborated
earlier the same day.

The frames are kept under ``dataset/truth_audit/stamina_hud_roi_20260919`` precisely because
the runtime screenshots they came from are prunable: a test may not rest on a file retention
is allowed to delete.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    HUD_STAMINA_ROI,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    parse_stamina_number,
)

FRAMES = ROOT / "dataset/truth_audit/stamina_hud_roi_20260919"

#: ``frame -> what the HUD actually shows``.  Read off the pictures by eye, which is the only
#: ground truth available for a screenshot.
TRUE_VALUE = {
    "hud_527_read_as_52.png": 527,
    "hud_527_read_as_52_second_frame.png": 527,
    "hud_382_read_correctly.png": 382,
}

#: Still misread after the widening.  Kept as its own assertion rather than folded into the
#: dict above, so it cannot be mistaken for a passing case: the fix narrowed the failure, it
#: did not eliminate it, and saying so here is cheaper than rediscovering it in a live run.
KNOWN_RESIDUAL = {"hud_still_read_as_502.png": 502}


def _service() -> OCRService:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


class HudStaminaIsReadWholeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = _service()

    def _read(self, name: str) -> int | None:
        result = self.service.recognize(FRAMES / name, HUD_STAMINA_ROI)
        return parse_stamina_number(result.tokens)

    def test_the_frames_the_measurement_rests_on_are_kept(self):
        """A missing frame must fail loudly rather than make the suite vacuous."""
        for name in (*TRUE_VALUE, *KNOWN_RESIDUAL):
            self.assertTrue((FRAMES / name).is_file(), f"evidence frame missing: {name}")

    def test_a_three_digit_value_is_read_whole(self):
        """The regression: these two frames returned 52 for 527 before the ROI was widened."""
        for name, expected in TRUE_VALUE.items():
            with self.subTest(frame=name):
                self.assertEqual(
                    self._read(name), expected,
                    f"{name}: the HUD shows {expected}; a dropped digit is what stops the "
                    f"stamina goal from spending",
                )

    def test_the_widening_did_not_break_a_value_that_was_already_right(self):
        self.assertEqual(self._read("hud_382_read_correctly.png"), 382)

    def test_the_residual_misread_is_named_not_hidden(self):
        """One frame still loses its last digit; if that changes, this test says so.

        Asserting the wrong value on purpose is the point: the alternative is a suite that
        reports all-green over a frame everybody knows is misread, and then nobody looks again.
        """
        for name, current in KNOWN_RESIDUAL.items():
            with self.subTest(frame=name):
                self.assertEqual(
                    self._read(name), current,
                    f"{name} now reads differently -- if it reads 527, the residual is fixed "
                    f"and this entry should be deleted",
                )

    def test_the_roi_is_still_wide_enough_for_the_measured_case(self):
        """Cheap guard against the width being trimmed back without re-measuring."""
        self.assertGreaterEqual(
            HUD_STAMINA_ROI["w_norm"], 0.075,
            "the HUD ROI was measured at 0.075 on real frames; narrowing it re-breaks 527 -> 52",
        )


if __name__ == "__main__":
    unittest.main()
