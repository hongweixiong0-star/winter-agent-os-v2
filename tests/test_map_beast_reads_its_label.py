"""The map's beast may also be found by the name the client prints beside it.

`world.beast` could only ever be filled by two sprite templates, and those match nothing on 23 live
frames because they search a patch of bare snow (issue ledger #41).  The fallback reads the name the
client draws next to the animal -- 猛犸象 at 0.88, 霜鳞避役 at 0.89 -- which is species-agnostic and
does not care where on the map the animal stands.

It lives in `HybridVision` (ocr.py), not in the template matcher (vision.py), because the matcher
has no OCR service at all: the class that holds `self.ocr` and augments the world state is the one
that already reads the HUD stamina number, and wiring text recognition into the class that cannot
read text was my mistake -- it raised AttributeError out of `observe`.

The narrowness is the design, and these tests pin every part of it:

* the templates keep precedence and their values, asserted structurally against the call site;
* a name is published only when the beast table permits dispatching that target, so an unmeasured
  species or a level that disagrees with the badge yields ``{}`` exactly as before;
* and the reader is *reached* -- asserted with a stubbed recogniser, because a wiring that quietly
  returns ``{}`` forever looks identical to a conservative pass.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import beast_from_its_label  # noqa: E402


class _Token:
    def __init__(self, text: str):
        self.text = text
        self.confidence = 0.95
        self.box = ((0, 0), (10, 0), (10, 10), (0, 10))


class _StubOCR:
    """A recogniser that returns exactly the words the test asks for."""

    def __init__(self, texts):
        self._texts = texts
        self.calls = 0

    def recognize(self, _path, _roi):
        self.calls += 1
        texts = self._texts

        class _Result:
            tokens = tuple(_Token(text) for text in texts)

        return _Result()


class TheMapBeastIsAlsoReadByItsLabelTests(unittest.TestCase):
    def test_the_reader_is_actually_reached(self):
        """The mistake worth naming: a dead wiring answers {} forever and looks conservative."""
        ocr = _StubOCR(["麝牛", "9"])
        found = beast_from_its_label("unused.png", ocr)
        self.assertEqual(ocr.calls, 1, "the recogniser must have been asked")
        self.assertEqual(found["visible_target"], "MUSK_OX")
        self.assertEqual(found["level"], 9)
        self.assertEqual(found["source"], "BEAST_LABEL", "the evidence says where it came from")

    def test_a_dispatchable_target_is_returned(self):
        for tokens, species, level in (
            (["麝牛", "9"], "MUSK_OX", 9),
            (["猛犸象", "5"], "MAMMOTH", 5),
            (["麝牛"], "MUSK_OX", 9),          # no badge: the row's own level is used
        ):
            with self.subTest(tokens=tokens):
                found = beast_from_its_label("unused.png", _StubOCR(tokens))
                self.assertEqual((found.get("visible_target"), found.get("level")), (species, level))

    def test_a_level_that_disagrees_with_the_badge_is_refused(self):
        """麝牛 is dispatchable at 9 and only at 9; a map showing another level is not that target."""
        self.assertEqual(beast_from_its_label("unused.png", _StubOCR(["麝牛", "3"])), {})

    def test_an_unmeasured_species_is_refused_even_though_it_reads(self):
        """霜鳞避役 reads at 0.89 and is registered, but its row says dispatchable false."""
        self.assertEqual(beast_from_its_label("unused.png", _StubOCR(["霜鳞避役", "20"])), {})

    def test_a_verified_row_without_a_victory_assessment_is_still_refused(self):
        """大角鹿 is VERIFIED and would be a fine target; the table has not cleared it to dispatch."""
        self.assertEqual(beast_from_its_label("unused.png", _StubOCR(["大角鹿", "22"])), {})

    def test_noise_and_empty_reads_stay_empty(self):
        for tokens in (["什么都不是"], ["联盟畜牧场"], []):
            with self.subTest(tokens=tokens):
                self.assertEqual(beast_from_its_label("unused.png", _StubOCR(tokens)), {})

    def test_a_broken_recogniser_cannot_take_the_frame_with_it(self):
        """One failing read must not lose the whole observation."""

        class _Broken:
            def recognize(self, _path, _roi):
                raise RuntimeError("engine down")

        self.assertEqual(beast_from_its_label("unused.png", _Broken()), {})

    def test_the_templates_still_win_when_they_hit(self):
        """The call site must prefer whatever the template path already produced.

        Asserted against the source because the precedence *is* the call-site expression, and this
        is the property that keeps the LIVE_VERIFIED musk ox route untouched.
        """
        source = (ROOT / "winter_agent_v2/ocr.py").read_text(encoding="utf-8")
        pattern = r"beast=dict\(primary\.beast\) or beast_from_its_label\(image_path, self\.ocr\)"
        self.assertRegex(source, pattern,
                         "the fallback must be reached only when primary.beast is empty")
        self.assertEqual(len(re.findall(pattern, source)), 1)


if __name__ == "__main__":
    unittest.main()
