"""The map's beast may also be found by the name the client prints beside it.

`world.beast` could only ever be filled by two sprite templates, and those match nothing on 23 live
frames because they search a patch of bare snow (issue ledger #41).  The fallback reads the name the
client draws next to the animal -- 猛犸象 at 0.88, 霜鳞避役 at 0.89 -- which is species-agnostic and
does not care where on the map the animal stands.

It lives in `HybridVision` (ocr.py), not in the template matcher (vision.py), because the matcher
has no OCR service at all: the class that holds `self.ocr` and augments the world state is the one
that already reads the HUD stamina number, and wiring text recognition into the class that cannot
read text was my mistake -- it raised AttributeError out of `observe`.

REVISED 2026-09-20.  This used to publish only when the beast table said the target could be
*dispatched*, which is a per-species pre-approval, and the measured cost was that a live frame whose
霜鳞避役/20 read perfectly produced `{}` -- so the route recorded nothing and went back to panning
the map, while the operator could see the animal on screen.  It now publishes whenever the identity
could be *read*, and carries the tap point measured from the label's own box.  The spend is not
authorised here and never was: it is the client's own printed assessment, read later on the card.

So the tests pin the new contract, in the order the design depends on it:

* identity alone is enough to publish, so an unmeasured species is *considered* (may_evaluate);
* the spend still needs either a pre-cleared row or the client's green string (is_dispatchable);
* a target the client has already refused is not published at all, so the level-29 leopard is not
  re-tapped on every pass;
* the tap point is measured from the label box, and is *absent* rather than invented when there is
  no frame size to map it with;
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

from winter_agent_v2.beast_targets import (  # noqa: E402
    GREEN_ASSESSMENT,
    is_dispatchable,
    may_evaluate,
    refused_by_evidence,
)
from winter_agent_v2.ocr import beast_from_its_label  # noqa: E402

# A 720x1280 frame, the client's own size.  Real boxes measured on
# dataset/raw/live_runtime/stamina_verify2/stamina_verify2_step_001_before_20260919T144336706139.png:
# the label 霜鳞避役 sits at x 157-204, y 831-846 within a band whose origin is (36, 576), which
# maps to (0.2687, 0.6551) in frame coordinates.
FRAME_SIZE = (720, 1280)


class _Token:
    def __init__(self, text: str, box=None):
        self.text = text
        self.confidence = 0.95
        self.box = box if box is not None else ((0, 0), (10, 0), (10, 10), (0, 10))


class _StubOCR:
    """A recogniser that returns exactly the words the test asks for."""

    def __init__(self, texts):
        self._texts = texts
        self.calls = 0

    def recognize(self, _path, _roi):
        self.calls += 1
        texts = self._texts

        class _Result:
            tokens = tuple(
                token if isinstance(token, _Token) else _Token(token) for token in texts
            )

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

    def test_an_unmeasured_species_is_now_considered(self):
        """The 2026-09-20 change, and the frame that produced it.

        霜鳞避役 reads at 0.89 and is registered, but its row is UNVERIFIED -- so the old code
        answered ``{}`` and the route fell back to panning.  Identity is now enough to publish,
        because what may be *done* with it is a separate question: ``may_evaluate`` says yes,
        ``is_dispatchable`` still says no until the client prints its verdict.
        """
        found = beast_from_its_label("unused.png", _StubOCR(["霜鳞避役", "20"]))
        self.assertEqual((found.get("visible_target"), found.get("level")), ("FROST_SCALED_RUNNER", 20))
        self.assertTrue(may_evaluate(found), "an unmeasured species must be tappable, or it is invisible")
        self.assertFalse(is_dispatchable(found), "no verdict on this frame means no spend")
        self.assertFalse(refused_by_evidence(found), "unmeasured is not the same as refused")

    def test_a_verified_row_without_a_victory_assessment_is_now_considered(self):
        """大角鹿 is VERIFIED but has never had an assessment read; same shape as the row above."""
        found = beast_from_its_label("unused.png", _StubOCR(["大角鹿", "22"]))
        self.assertEqual(found.get("visible_target"), "GREAT_HORNED_DEER")
        self.assertTrue(may_evaluate(found))
        self.assertFalse(is_dispatchable(found))

    def test_the_client_green_light_is_what_authorises_the_spend(self):
        """The generalisation, stated as one assertion: the frame's words decide, not a row."""
        for species, level in (("FROST_SCALED_RUNNER", 20), ("GREAT_HORNED_DEER", 22)):
            with self.subTest(species=species):
                fragment = {"visible_target": species, "level": level,
                            "victory_assessment": GREEN_ASSESSMENT}
                self.assertTrue(is_dispatchable(fragment))

    def test_a_target_the_client_already_refused_is_not_even_tapped(self):
        """雪豹/29 printed 本次出征胜算较低 and recorded BLOCKED_BEFORE_DISPATCH."""
        fragment = {"visible_target": "SNOW_LEOPARD", "level": 29, "available": True}
        self.assertTrue(refused_by_evidence(fragment))
        self.assertFalse(may_evaluate(fragment))
        self.assertFalse(is_dispatchable(fragment))
        # ...and a frame that happens to carry the green string does not overturn a measurement.
        self.assertFalse(is_dispatchable({**fragment, "victory_assessment": GREEN_ASSESSMENT}))

    def test_the_tap_point_comes_from_the_label_box_and_is_not_invented(self):
        """Measured, not guessed: the nameplate sits on the animal, so its centre is the tap."""
        label = _Token("霜鳞避役", ((157, 255), (204, 255), (204, 270), (157, 270)))
        found = beast_from_its_label("unused.png", _StubOCR([label, _Token("20")]), frame_size=FRAME_SIZE)
        self.assertIn("tap_norm", found)
        x_norm, y_norm = found["tap_norm"]
        self.assertAlmostEqual(x_norm, (36 + 180.5) / 720, places=3)
        self.assertAlmostEqual(y_norm, (576 + 262.5) / 1280, places=3)

    def test_without_a_frame_size_there_is_no_tap_point_rather_than_a_guess(self):
        """An ROI-scoped box cannot be mapped without the frame size; absent beats invented."""
        found = beast_from_its_label("unused.png", _StubOCR(["霜鳞避役", "20"]))
        self.assertNotIn("tap_norm", found)
        self.assertEqual(found.get("visible_target"), "FROST_SCALED_RUNNER",
                         "the identity is still published -- only the coordinate is withheld")

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
        pattern = (
            r"beast=dict\(primary\.beast\)\s*\n\s*or beast_from_its_label\("
            r"image_path, self\.ocr, frame_size=\(frame_width, frame_height\)\)"
        )
        self.assertRegex(source, pattern,
                         "the fallback must be reached only when primary.beast is empty")
        self.assertEqual(len(re.findall(pattern, source)), 1)


if __name__ == "__main__":
    unittest.main()
