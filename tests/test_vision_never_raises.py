"""The vision layer reports; it never raises.

``SemanticROIVision.find`` builds ``matches`` by appending one entry per
candidate record, but its ``ccoeff`` branch appends nothing when
``match_ccoeff`` returns ``None``.  A semantic whose records are *all*
``ccoeff`` therefore leaves the list empty, and ``min(matches, ...)`` raised

    ValueError: min() iterable argument is empty

Measured 2026-09-15: a corpus sweep over ``dataset/raw`` died on the first frame
whose resolution differs from the registered one, inside
``match("POPUP_HERO_BATTLE_VICTORY")``.  Four semantics are single-record and
ccoeff-only -- ``BTN_HERO_CAMP_FIGHT``, ``BTN_HERO_FIGHT``,
``BTN_INTEL_VIEW_TARGET``, ``POPUP_HERO_BATTLE_VICTORY`` -- and they are reached
from ordinary page branches, so any frame whose size is not 720x1280 could take
the whole observation down instead of reporting UNKNOWN.

``match_ccoeff`` returns ``None`` when every scale is skipped, and a scale is
skipped when the template is not strictly smaller than the search window
(ROI + 40 px on each side).  On a 302x79 crop every ROI lies outside the frame,
so the window is empty and no scale can run.

The fix is the guard in ``find``: a template that cannot be evaluated is not a
match.  ``observe`` is called on every captured frame -- including partial
screenshots and frames from a device whose resolution changed -- so it has to be
total.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
# A 302x79 crop: every ROI in the manifest falls outside it.  It is kept out of
# dataset/raw precisely because it is not a client frame.
SMALL_CROP = ROOT / "dataset" / "probe_output" / "formation_title"
CLIENT_FRAME = ROOT / "dataset" / "raw" / "live_exploration_after_claim.png"


def _ccoeff_only_semantics() -> list[str]:
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]
    totals: dict[str, int] = {}
    ccoeff: dict[str, int] = {}
    for row in records:
        totals[row["semantic"]] = totals.get(row["semantic"], 0) + 1
        if row.get("matcher") == "ccoeff":
            ccoeff[row["semantic"]] = ccoeff.get(row["semantic"], 0) + 1
    return sorted(name for name, count in ccoeff.items() if count == totals[name])


class FindNeverRaisesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = SemanticWorldVision(MANIFEST)
        cls.crops = sorted(SMALL_CROP.glob("*.png")) if SMALL_CROP.is_dir() else []
        if not cls.crops:
            raise unittest.SkipTest(f"no probe crops under {SMALL_CROP}")

    def test_the_fixture_is_a_frame_the_matcher_cannot_evaluate(self) -> None:
        """Guard the fixture, so this test cannot quietly stop testing."""
        from PIL import Image

        with Image.open(self.crops[0]) as crop:
            self.assertEqual(crop.size, (302, 79))
        with Image.open(CLIENT_FRAME) as frame:
            self.assertEqual(frame.size, (720, 1280))

    def test_a_ccoeff_only_semantic_exists_and_is_the_hazard(self) -> None:
        names = _ccoeff_only_semantics()
        self.assertIn("POPUP_HERO_BATTLE_VICTORY", names)
        self.assertIn("BTN_HERO_CAMP_FIGHT", names)

    def test_every_ccoeff_only_semantic_returns_none_on_an_unusable_frame(self) -> None:
        crop = self.crops[0]
        for semantic in _ccoeff_only_semantics():
            with self.subTest(semantic=semantic):
                self.assertIsNone(self.vision.semantic.find(crop, semantic))

    def test_the_observation_reports_unknown_instead_of_raising(self) -> None:
        for crop in self.crops[:5]:
            with self.subTest(crop=crop.name):
                state = self.vision.observe(crop)
                self.assertFalse(state.known)
                self.assertEqual(state.page.value, "UNKNOWN")

    def test_a_real_client_frame_still_classifies(self) -> None:
        """The guard must not have turned every lookup into None."""
        state = self.vision.observe(CLIENT_FRAME)
        self.assertTrue(state.known)
        self.assertEqual(state.page.value, "EXPLORATION")


class TheCorpusHoldsOnlyClientFramesTests(unittest.TestCase):
    """Why the guard matters even though it is cheap.

    ``dataset/raw`` is the frame corpus the gates are measured over, and the
    invariant "every PNG in it is a full client frame" is what makes a corpus
    sweep meaningful.  Crops belong in ``dataset/probe_output``.
    """

    def test_no_probe_crops_are_written_into_the_corpus(self) -> None:
        stray = sorted((ROOT / "dataset" / "raw").rglob("*formation_title*"))
        self.assertEqual(stray, [], f"probe crops must not live in dataset/raw: {stray}")

    def test_the_probe_writes_its_crops_outside_the_corpus(self) -> None:
        source = (ROOT / "tools" / "probe_formation_title.py").read_text(encoding="utf-8")
        self.assertIn('"probe_output"', source)
        self.assertNotIn(
            'ROOT / "dataset" / "raw" / "control_panel" / "probe" / "formation_title"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
