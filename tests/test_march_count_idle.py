"""A march counter that is not drawn means idle, not unreadable.

Why (2026-09-15, continuation of the gather blocker recorded as 0bc)
--------------------------------------------------------------------
The gather workflow never started: on genuine world-map frames ``march_used`` was
``None`` while ``march_max`` read 6, so the brain chose CHECK_MARCH and the run
ended at step 1 with MARCH_COUNT_NOT_READ (live 2026-09-15T12:59:36Z).

Two live MAP frames showed the difference.  One OCRs the counter ROI as ``6/6``;
the other returns *no tokens at all* and has no march states either.  So on the
second frame the client is simply not drawing a counter -- because nothing is
marching -- and reading that as "unreadable" is what stops everything.

The rule is deliberately the CONJUNCTION, and the corpus is what forced it:
(march_used is None, no march states) occurs 98 times, but (march_used is None,
march states present) occurs 35 times.  The second is a count we genuinely cannot
read, so it stays unknown.  Guessing there would be inventing a queue length we
have no evidence for.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.ocr import HybridVision

ROOT = Path(__file__).resolve().parents[1]

# Real live frames.  A missing frame skips rather than fails: dataset/raw is
# machine-local evidence that is deliberately not in git.
IDLE_FRAME = ROOT / "dataset/evidence/maa_live/state_maa_20260915T124440.png"
BUSY_FRAME = ROOT / "dataset/raw/control_panel/probe/live_page_20260915_133152.png"


class _Token:
    def __init__(self, text: str, confidence: float = 0.99):
        self.text = text
        self.confidence = confidence
        self.box = ((0, 0), (1, 0), (1, 1), (0, 1))


class _Result:
    def __init__(self, tokens):
        self.tokens = tokens
        self.text = " ".join(t.text for t in tokens)


class _FakeOCR:
    """Returns nothing anywhere: the counter is not drawn on this frame."""

    def recognize(self, _path, _roi=None):
        return _Result([])


class _FakeTemplate:
    """The reviewed layer's verdict, which is what the guard is measured against."""

    def __init__(self, primary: WorldState):
        self._primary = primary

    def observe(self, _path):
        return self._primary


def _blank_png(tmp: Path) -> Path:
    from PIL import Image

    path = tmp / "frame.png"
    Image.new("RGB", (720, 1280), (0, 0, 0)).save(path)
    return path


def _map_state(marches) -> WorldState:
    return WorldState(
        page=Page.MAP, march_used=None, march_max=6, marches=marches, confidence=0.99
    )


class TheCounterIsNotDrawnWhenNothingIsOutTests(unittest.TestCase):
    def _observe(self, tmp: Path, marches) -> WorldState:
        frame = _blank_png(tmp)
        return HybridVision(_FakeTemplate(_map_state(marches)), _FakeOCR()).observe(frame)

    def test_no_counter_and_no_marches_reads_as_idle(self):
        # The whole point: an empty queue must not look like an unreadable one.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state = self._observe(Path(tmp), [])
        self.assertEqual(state.march_used, 0)
        self.assertEqual(state.march_max, 6)

    def test_no_counter_but_a_march_is_present_stays_unknown(self):
        # Negative control for the guard: evidence of a march from the reviewed
        # layer forbids inventing a zero.  This is the 35-observation case.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state = self._observe(Path(tmp), [MarchState.MARCHING])
        self.assertIsNone(state.march_used)


class RealFramesStillReadTheSameWayTests(unittest.TestCase):
    def _vision(self):
        import json
        import sys

        sys.path.insert(0, str(ROOT))
        from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision

        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        ocr = OCRService(
            ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
        )
        return HybridVision(template, ocr)

    @unittest.skipUnless(IDLE_FRAME.is_file(), "idle MAP frame not on this machine")
    def test_the_live_frame_that_blocked_gather_now_reads_idle(self):
        state = self._vision().observe(IDLE_FRAME)
        self.assertEqual(state.page.value, "MAP")
        self.assertEqual(state.march_used, 0)

    @unittest.skipUnless(BUSY_FRAME.is_file(), "busy MAP frame not on this machine")
    def test_a_frame_with_a_real_counter_is_unchanged(self):
        state = self._vision().observe(BUSY_FRAME)
        self.assertEqual(state.march_used, 6)
        self.assertEqual(state.march_max, 6)


if __name__ == "__main__":
    unittest.main()
