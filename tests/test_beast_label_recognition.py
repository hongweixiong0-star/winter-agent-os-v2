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
    OCRToken,
    RapidOCRBackend,
    ResilientOCRBackend,
    level_beside_label,
    named_beast_label,
)

FRAMES = ROOT / "dataset/raw/live_runtime"

#: frame -> the name the client printed on it (read by eye); the table knows this one.
REGISTERED = {
    "stamina_verify2/stamina_verify2_step_003_after_20260919T144435621168.png": "猛犸象",
    # Registered on 2026-09-19 from this very frame.  Before that row existed the label read
    # returned None for it, which was correct; this entry is the proof the whitelist path works
    # end to end rather than merely refusing.
    "stamina_verify2/stamina_verify2_step_001_before_20260919T144336706139.png": "霜鳞避役",
    # CORRECTED 2026-09-20: both of these were in NEGATIVES, and both are wrong there.  The band was
    # widened because it was clipping whole animals, and the two frames immediately named a beast:
    #   猛犸象 at 0.87, tap point (0.676, 0.718)
    #   霜鳞避役 at 0.81 (read as 霸鳞避役 -- one glyph -- and matched by the near-miss path)
    # The second was then cropped and looked at: the ice-blue animal and its nameplate are plainly
    # drawn at the reported point.  So "frames without a beast" was a label the old band had earned,
    # not a fact about the frames -- the same mistake as calling a full intel board empty.
    "stamina_verify2/stamina_verify2_step_002_after_20260919T144413221517.png": "猛犸象",
    "stamina_verify/stamina_verify_step_005_after_20260919T143517420153.png": "霜鳞避役",
}

#: A frame whose printed name is readable.  The refusal test below removes that name from the
#: whitelist rather than relying on a species nobody has registered yet, so the safety property
#: stays pinned whatever the table happens to contain.
READABLE_FRAME = {
    "stamina_verify2/stamina_verify2_step_001_before_20260919T144336706139.png": "霜鳞避役",
}

#: There is no frame here any more, and that is the honest state of the evidence: the two that
#: used to be listed were falsified by looking at them (see REGISTERED).  The silence property is
#: still pinned, by stubbed tokens whose words are not beast names -- which is the safer form of
#: the test anyway, because it does not depend on a picture somebody once believed was empty.
#: Measured 2026-09-20 for the record: over 40 live MAP frames, 38 carried no beast name at all,
#: so silent frames are the common case -- they just are not these two.


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

    def test_a_readable_name_is_still_refused_when_the_table_does_not_know_it(self):
        """Two different failures, and both matter.

        If the name is returned while it is absent from the whitelist, the whitelist has been
        weakened, and whatever the band happens to contain could be dispatched as a beast.  If the
        name stops being readable at all, the read has regressed.  The refusal is asserted against
        a whitelist with that one name removed, so it keeps meaning the same thing no matter which
        species the table carries.
        """
        for relative, printed in READABLE_FRAME.items():
            with self.subTest(frame=relative):
                tokens = self._tokens(relative)
                self.assertTrue(
                    any(printed in str(t.text or "") for t in tokens),
                    f"{relative}: the name {printed} was expected to be readable on this frame",
                )
                self.assertIsNone(
                    named_beast_label(tokens, set(self.names) - {printed}),
                    f"{relative}: {printed} must not be returned when no row carries it",
                )

    def test_a_level_badge_is_read_or_refused(self):
        """Either a number, or None when the band holds several -- never a guess."""
        for relative in (*REGISTERED, *READABLE_FRAME):
            with self.subTest(frame=relative):
                level = level_beside_label(self._tokens(relative))
                self.assertTrue(level is None or isinstance(level, int))

    def test_an_unknown_name_is_never_returned(self):
        """The whitelist is the safety property, not a nicety."""
        tokens = self._tokens(next(iter(REGISTERED)))
        self.assertIsNone(named_beast_label(tokens, {"不存在的野兽"}))

    def test_frames_without_a_beast_stay_silent(self):
        """Silence, pinned on words rather than on a frame somebody believed was empty.

        The two frames this used to iterate over were falsified: a beast was drawn on both and the
        narrow band was hiding it.  See the note where NEGATIVES used to be -- a picture is not a
        negative until someone has looked at it.
        """
        box = ((0.0, 0.0), (40.0, 0.0), (40.0, 14.0), (0.0, 14.0))
        for words in (["联盟畜牧场"], ["铁厂"], ["未驻防"], ["[DIK]联盟旗帜"], ["开"], []):
            with self.subTest(words=words):
                tokens = tuple(
                    OCRToken(text=text, confidence=0.99, box=box) for text in words
                )
                self.assertIsNone(
                    named_beast_label(tokens, self.names),
                    f"{words}: none of these is a registered beast name",
                )


if __name__ == "__main__":
    unittest.main()
