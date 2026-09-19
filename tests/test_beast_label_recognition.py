"""The beast's name is read off the map, and only a *registered* name counts.

Tonight's measurement: the beast templates matched nothing on 23 live frames, while the client
prints the animal's name right beside it -- 猛犸象 at 0.88 and 霜鳞避役 at 0.89, each with a level
badge at full confidence nearby.  So the recognition target is the client's own word.

The whitelist is what makes this safe rather than dangerous, in two directions:

* the same band carries alliance flags, 未驻防 markers and building names (联盟畜牧场, 联盟木材场,
  铁厂, 开), so an unfiltered read would call a sawmill a beast;
* a species the table has never heard of is refused even though it reads perfectly.  霜鳞避役 is
  exactly that case tonight, and it is asserted rather than worked around: the read is correct and
  the answer is still None, because nothing here is invented and the answer decides whether a march
  is dispatched.
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
    BEAST_LABEL_BAND,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    level_beside_label,
    named_beast_label,
)

FRAMES = ROOT / "dataset/raw/live_runtime"

#: frame -> the name the client printed on it (read by eye); the table knows this one.
REGISTERED = {
    "stamina_verify2/stamina_verify2_step_003_after_20260919T144435621168.png": "猛犸象",
}

#: Readable on the frame, absent from ``beasts.json`` -- so the read must still answer None.
#: Registering it is a separate job: the row's level and cost have to be measured first.
READABLE_BUT_UNREGISTERED = {
    "stamina_verify2/stamina_verify2_step_001_before_20260919T144336706139.png": "霜鳞避役",
}

#: Frames whose band holds no beast name at all; the read must stay silent.
NEGATIVES = (
    "stamina_verify2/stamina_verify2_step_002_after_20260919T144413221517.png",
    "stamina_verify/stamina_verify_step_005_after_20260919T143517420153.png",
)


def _known_names() -> set[str]:
    table = json.loads((ROOT / "knowledge/game/beasts.json").read_text(encoding="utf-8"))
    names: set[str] = set()
    for row in table.get("records", []):
        if row.get("name"):
            names.add(str(row["name"]))
        for alias in row.get("aliases", []) or []:
            names.add(str(alias))
    return names


class BeastLabelRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        cls.service = OCRService(
            ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
        )
        cls.names = _known_names()

    def _tokens(self, relative: str):
        self.assertTrue((FRAMES / relative).is_file(), f"evidence frame missing: {relative}")
        return self.service.recognize(FRAMES / relative, BEAST_LABEL_BAND).tokens

    def test_a_registered_species_is_read_off_the_map(self):
        for relative, expected in REGISTERED.items():
            with self.subTest(frame=relative):
                self.assertEqual(
                    named_beast_label(self._tokens(relative), self.names), expected,
                    f"{relative}: the client prints {expected}",
                )

    def test_the_name_reads_even_when_the_table_does_not_know_it(self):
        """Two different failures, and both matter.

        If this starts returning the name, the whitelist has been weakened.  If the name stops
        being readable at all, the read has regressed.  Meanwhile the species stays undispatched
        until it is registered, and this test is what stops that gap from looking like a detection.
        """
        for relative, printed in READABLE_BUT_UNREGISTERED.items():
            with self.subTest(frame=relative):
                tokens = self._tokens(relative)
                self.assertIsNone(
                    named_beast_label(tokens, self.names),
                    f"{relative}: {printed} is not in beasts.json, so it may not be returned",
                )
                self.assertTrue(
                    any(printed in str(t.text or "") for t in tokens),
                    f"{relative}: the name {printed} was expected to be readable on this frame",
                )

    def test_a_level_badge_is_read_or_refused(self):
        """Either a number, or None when the band holds several -- never a guess."""
        for relative in (*REGISTERED, *READABLE_BUT_UNREGISTERED):
            with self.subTest(frame=relative):
                level = level_beside_label(self._tokens(relative))
                self.assertTrue(level is None or isinstance(level, int))

    def test_an_unknown_name_is_never_returned(self):
        """The whitelist is the safety property, not a nicety."""
        tokens = self._tokens(next(iter(REGISTERED)))
        self.assertIsNone(named_beast_label(tokens, {"不存在的野兽"}))

    def test_frames_without_a_beast_stay_silent(self):
        for relative in NEGATIVES:
            with self.subTest(frame=relative):
                self.assertIsNone(
                    named_beast_label(self._tokens(relative), self.names),
                    f"{relative}: no beast is drawn here, so nothing may be named",
                )


if __name__ == "__main__":
    unittest.main()
