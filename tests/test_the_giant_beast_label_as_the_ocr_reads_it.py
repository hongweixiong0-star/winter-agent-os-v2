"""The search strip's 冰原巨兽 label, as the client and this OCR actually render it.

Measured 2026-10-05, from the ledger and from the frames:

* ``SELECT_GIANT_BEAST_TAB`` ended ``GIANT_BEAST_TAB_NOT_PROVEN`` 48 times, the last 20 of them
  once every few minutes; the verifier's only criterion is
  ``after.resource_selected_tab == "GIANT_BEAST"``;
* on those frames the strip really is ``野兽 / 冰原巨兽 / 大型养殖场 / 生肉``, the mammoth cell
  carries the selection highlight, and the level slider reads ``5级`` -- i.e. the tap worked;
* but the OCR read the label as ``冰原巨善`` (``兽`` -> ``善``) at confidence 0.91-0.94, and
  ``RESOURCE_TAB_LABEL_TO_KIND`` matches exactly, so ``GIANT_BEAST`` dropped out of the strip;
* with it missing, ``selected_tab_from_live_labels`` cannot bind the bracket to a label and
  answers ``None``, and the bracket fallback then reads ``BEAST``;
* both halves were checked on a real frame: the same call returns ``None`` with the old
  labels and ``GIANT_BEAST`` once the label is back.

The variant table is a census, not a patch: over 17 live frames the only band token one
character from a key was this one, 14 times; everything else that missed (``大型养殖场``,
player names) has no key within one character.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from winter_agent_v2.ocr import (
    RESOURCE_TAB_LABEL_TO_KIND,
    RESOURCE_TAB_LABEL_VARIANTS,
    read_resource_tab_labels,
)


class _Token:
    def __init__(self, text, confidence, box):
        self.text = text
        self.confidence = confidence
        self.box = box


class _Result:
    def __init__(self, tokens):
        self.tokens = tokens


class _FakeOCR:
    """The only surface `read_resource_tab_labels` uses: `recognize(path, roi).tokens`."""

    def __init__(self, tokens):
        self._tokens = tokens

    def recognize(self, image_path, roi=None):
        return _Result(list(self._tokens))


def _frame(folder, width=720, height=1280):
    path = Path(folder) / "frame.png"
    Image.new("RGB", (width, height), "black").save(path)
    return path


def _tab(text, centre_x, image_height=1280, confidence=0.94):
    """A token box centred on `centre_x`, inside the reader's default band."""
    y = 0.739 * image_height
    half = 20
    return _Token(text, confidence, [(centre_x - half, y - half), (centre_x + half, y - half),
                                     (centre_x + half, y + half), (centre_x - half, y + half)])


class TheGiantBeastLabelAsTheOCRActuallyReadsIt(unittest.TestCase):
    def test_the_observed_substitution_names_the_tab(self):
        """The measured reading, verbatim: 冰原巨善 -> GIANT_BEAST."""
        with TemporaryDirectory() as folder:
            path = _frame(folder)
            ocr = _FakeOCR([_tab("野兽", 87), _tab("冰原巨善", 244), _tab("生肉", 561)])
            found = read_resource_tab_labels(path, ocr)
        self.assertIn("GIANT_BEAST", found, f"the tab dropped out again: {sorted(found)}")
        self.assertIn("BEAST", found)
        self.assertIn("MEAT", found)

    def test_the_canonical_label_still_works(self):
        with TemporaryDirectory() as folder:
            path = _frame(folder)
            ocr = _FakeOCR([_tab("冰原巨兽", 244)])
            found = read_resource_tab_labels(path, ocr)
        self.assertIn("GIANT_BEAST", found)

    def test_an_unrelated_neighbour_is_still_not_named(self):
        """`大型养殖场` is a real cell with no kind -- the census says it has no near key."""
        with TemporaryDirectory() as folder:
            path = _frame(folder)
            ocr = _FakeOCR([_tab("大型养殖场", 424)])
            found = read_resource_tab_labels(path, ocr)
        self.assertEqual(found, {})

    def test_the_variant_table_only_holds_labels_the_map_knows(self):
        """A variant must point at a real label; a typo here would name a kind that no key has."""
        for variant, label in RESOURCE_TAB_LABEL_VARIANTS.items():
            self.assertIn(label, RESOURCE_TAB_LABEL_TO_KIND, variant)
            self.assertNotIn(variant, RESOURCE_TAB_LABEL_TO_KIND,
                             f"{variant} is a key in its own right now; the variant entry is stale")

    def test_a_low_confidence_reading_is_still_refused(self):
        """The floor is unchanged: this is a substitution fix, not an 'accept anything' fix."""
        with TemporaryDirectory() as folder:
            path = _frame(folder)
            ocr = _FakeOCR([_tab("冰原巨善", 244, confidence=0.55)])
            found = read_resource_tab_labels(path, ocr)
        self.assertNotIn("GIANT_BEAST", found)


if __name__ == "__main__":
    unittest.main()
