"""Goal-driven visual attention: what the observation reads, and what it is spared from reading.

Operator directive 2026-09-22 ("Goal 驱动的视觉注意力优化").  The measuring was done before the code,
so these tests pin the numbers rather than the intentions:

Baseline, production ``SemanticWorldVision.observe`` on real 720x1280 frames -- **106 semantic
lookups and 8.2-9.7 s per frame, whatever the goal was**, with one map sweep
(``TARGET_INTEL_BEAST_MISSION``) costing 3.6-3.8 s of it on frames that cannot contain it:

    训练页        65 lookups   2.80 s
    快捷面板展开  106 lookups   9.55 s
    燃霜矿区      106 lookups   9.67 s

What these tests require of the result:

* the frame is decoded once per observation, not once per lookup, and a template is hashed once per
  file rather than once per frame -- item 六's 不要求每一步重新识别整张截图中的全部控件;
* a second look at the **same** frame is answered from what the first look found, while a different
  frame is never answered from it;
* the map sweeps are skipped only when the caller's own context says the frame is not the map field
  *and* the goal is not about the map -- and never on an unnamed page, which may well be a map;
* when a skipped sweep left the frame unnamed, the observation **widens by itself** and really
  performs the sweeps it declined (the first version of this silently returned a cached "not found"
  and widened nothing, at a cost of 0.00 s -- the tell);
* the page classification is identical with and without the attention, on every real frame.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2 import vision as vision_module  # noqa: E402
from winter_agent_v2.models import Page  # noqa: E402
from winter_agent_v2.vision import MAP_FIELD_PAGES, SemanticROIVision, SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

#: Real frames: a named training page, the quick panel open over HOME, and two unnamed screens.
FRAMES = {
    "training": ROOT / "dataset/raw/live_train_selection_available.png",
    "quick_panel": ROOT / (
        "dataset/raw/control_panel/runtime_auto/20260921_213506_694242/"
        "20260921_213506_694242_step_001_before_20260921T133510479855.png"
    ),
    "frostfire": ROOT / (
        "dataset/raw/control_panel/runtime_auto/20260922_163010_905874/"
        "20260922_163010_905874_step_002_before_20260922T083049654040.png"
    ),
}

#: The sweep the measurement blames for most of the cost.
EXPENSIVE_SWEEP = "TARGET_INTEL_BEAST_MISSION"


def _vision() -> SemanticWorldVision:
    """A cold vision, which is what production has for every step: each frame is a new file."""
    return SemanticWorldVision(MANIFEST)


class ReadingOnceTests(unittest.TestCase):
    """The same picture is decoded once, and the same question is answered once."""

    def test_the_frame_is_decoded_once_per_observation_not_once_per_lookup(self):
        opens: list[str] = []
        original = Image.open

        def counting_open(fp, *args, **kwargs):
            opens.append(str(fp))
            return original(fp, *args, **kwargs)

        lookups: list[str] = []
        original_find = SemanticROIVision.find

        def counting_find(self, image_path, semantic):
            lookups.append(semantic)
            return original_find(self, image_path, semantic)

        vision = _vision()
        with mock.patch.object(vision_module.Image, "open", counting_open), mock.patch.object(
            SemanticROIVision, "find", counting_find
        ):
            vision.observe(FRAMES["training"])
        same_frame = [path for path in opens if FRAMES["training"].name in path]
        # Not "exactly one": the observation layer itself reads the frame directly for its own pixel
        # measurements (the overlay strip, the map band), which is its business.  What must not
        # happen is a decode per lookup, and the chain asks about ~100 semantics.
        self.assertGreater(len(lookups), 20, "this frame really does run a long chain")
        self.assertLess(
            len(same_frame), 10,
            f"{len(same_frame)} decodes for {len(lookups)} lookups: the frame is being re-read",
        )

    def test_a_template_is_hashed_once_not_once_per_frame(self):
        vision = _vision()
        first = vision.semantic._template_digest(
            Path(vision.semantic.records[0]["template_path"]), size=8, kind="phash"
        )
        self.assertTrue(first)
        cached = dict(vision.semantic._template_digests)
        self.assertTrue(cached, "the digest has to be remembered")
        with mock.patch.object(vision_module, "phash", side_effect=AssertionError("re-hashed")):
            again = vision.semantic._template_digest(
                Path(vision.semantic.records[0]["template_path"]), size=8, kind="phash"
            )
        self.assertEqual(first, again)

    def test_a_second_look_at_the_same_frame_reuses_what_the_first_found(self):
        """``find`` is still called -- the chain asks the same questions -- but no lookup is *done*."""
        vision = _vision()
        vision.observe(FRAMES["training"])
        asked: list[str] = []
        original = SemanticROIVision._find_in_roi

        def counting(self, image_path, candidates, semantic):
            asked.append(semantic)
            return original(self, image_path, candidates, semantic)

        with mock.patch.object(SemanticROIVision, "_find_in_roi", counting):
            vision.observe(FRAMES["training"])
        self.assertEqual(asked, [], "the same frame must not be looked up again")

    def test_a_different_frame_is_never_answered_from_the_old_one(self):
        """The whole point of caching: it must not become a stale answer."""
        vision = _vision()
        vision.observe(FRAMES["training"])
        asked: list[str] = []
        original = SemanticROIVision._find_in_roi

        def counting(self, image_path, candidates, semantic):
            asked.append(semantic)
            return original(self, image_path, candidates, semantic)

        with mock.patch.object(SemanticROIVision, "_find_in_roi", counting):
            vision.observe(FRAMES["quick_panel"])
        self.assertTrue(asked, "a new picture has to be looked at")


class AttentionGateTests(unittest.TestCase):
    """Which lookups the goal and the page excuse us from."""

    def test_a_non_map_goal_on_a_named_non_map_page_skips_the_map_sweeps(self):
        vision = _vision()
        vision.focus(goal="TRAIN", page_hint="TRAINING")
        state = vision.observe(FRAMES["quick_panel"])
        self.assertEqual(state.page, Page.HOME, "the page must be read the same either way")
        skipped = vision.sweeps_skipped()
        self.assertIn(EXPENSIVE_SWEEP, skipped, "the expensive sweep must be among the excused")
        self.assertIn("TRAINING", skipped[EXPENSIVE_SWEEP])

    def test_the_page_is_identical_with_and_without_the_attention(self):
        """The one thing the attention may not change: what the frame is."""
        for name, frame in FRAMES.items():
            with self.subTest(frame=name):
                plain = _vision()
                plain.focus(goal="", page_hint="")
                before = plain.observe(frame).page
                focused = _vision()
                focused.focus(goal="TRAIN", page_hint="TRAINING")
                after = focused.observe(frame).page
                self.assertEqual(before, after)

    def test_an_unnamed_page_keeps_its_sweeps(self):
        """§五: an unnamed screen may well *be* a map this build cannot name."""
        vision = _vision()
        vision.focus(goal="TRAIN", page_hint="UNKNOWN")
        vision.observe(FRAMES["frostfire"])
        self.assertEqual(vision.sweeps_skipped(), {})

    def test_a_map_goal_keeps_its_sweeps_even_on_a_non_map_page(self):
        vision = _vision()
        vision.focus(goal="CLEAR_INTEL", page_hint="TRAINING")
        vision.observe(FRAMES["frostfire"])
        self.assertEqual(vision.sweeps_skipped(), {})

    def test_a_caller_with_no_goal_gets_the_old_behaviour(self):
        vision = _vision()
        state = vision.observe(FRAMES["quick_panel"])
        self.assertEqual(vision.sweeps_skipped(), {})
        self.assertEqual(state.page, Page.HOME)

    def test_the_map_pages_are_the_project_s_own_page_names(self):
        self.assertIn("MAP", MAP_FIELD_PAGES)
        for page in MAP_FIELD_PAGES:
            self.assertIn(page, {member.value for member in Page})


class WideningTests(unittest.TestCase):
    """§五: a focus that found nothing must widen, and the widening must really look."""

    def test_a_skipped_sweep_is_not_cached_as_an_answer(self):
        """The bug the first version had, measured: the second look cost 0.00 s and widened nothing."""
        vision = _vision()
        vision.focus(goal="TRAIN", page_hint="TRAINING")
        vision.observe(FRAMES["frostfire"])
        self.assertTrue(vision.sweeps_skipped())
        self.assertNotIn(
            (str(FRAMES["frostfire"]), EXPENSIVE_SWEEP),
            vision.semantic._answers,
            "a lookup this observation declined to do is not an answer",
        )

    def test_widening_really_performs_the_sweeps_it_declined(self):
        vision = _vision()
        vision.focus(goal="TRAIN", page_hint="TRAINING")
        first = vision.observe(FRAMES["frostfire"])
        self.assertEqual(first.page, Page.UNKNOWN)
        vision.focus(goal="TRAIN", page_hint="TRAINING", widen=True)
        started = time.perf_counter()
        vision.observe(FRAMES["frostfire"])
        widened = time.perf_counter() - started
        # The sweeps were declined, so the widening pass has to pay for them; without the fix this
        # was 0.00 s because the cached None answered for a lookup that never happened.
        self.assertGreater(widened, 0.5, "the widening pass must actually do the sweeps")
        self.assertEqual(vision.sweeps_skipped(), {}, "and it must no longer be declining anything")


class RuntimeWiringTests(unittest.TestCase):
    """Item 七: it has to participate in the live observation, not just exist."""

    def test_every_observation_goes_through_the_attention_helper(self):
        source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "self.vision.observe(",
            source,
            "a direct observe would bypass the goal and the widening path",
        )
        self.assertIn("self._observe(", source)

    def test_the_helper_widens_only_after_an_unnamed_frame(self):
        from winter_agent_v2.models import WorldState

        from winter_agent_v2.runtime import LiveRuntime

        calls: list[dict] = []

        class _Vision:
            def focus(self, **kwargs):
                calls.append(dict(kwargs))

            def observe(self, path):
                return WorldState(page=Page.UNKNOWN, confidence=0.0)

            def sweeps_skipped(self):
                return {EXPENSIVE_SWEEP: "skipped for the test"}

        runtime = object.__new__(LiveRuntime)
        runtime.vision = _Vision()
        from types import SimpleNamespace

        runtime.brain = SimpleNamespace(current_goal="TRAIN")
        runtime._last_known_label = "TRAINING"
        runtime._observe(Path("frame.png"))
        self.assertEqual(len(calls), 2, "an unnamed frame after a skipped sweep widens once")
        self.assertFalse(calls[0]["widen"])
        self.assertTrue(calls[1]["widen"])
        self.assertEqual(calls[0]["goal"], "TRAIN")
        self.assertEqual(calls[0]["page_hint"], "TRAINING")

    def test_a_named_frame_does_not_widen(self):
        from types import SimpleNamespace

        from winter_agent_v2.models import WorldState

        from winter_agent_v2.runtime import LiveRuntime

        calls: list[dict] = []

        class _Vision:
            def focus(self, **kwargs):
                calls.append(dict(kwargs))

            def observe(self, path):
                return WorldState(page=Page.HOME, confidence=0.98)

            def sweeps_skipped(self):
                return {EXPENSIVE_SWEEP: "skipped for the test"}

        runtime = object.__new__(LiveRuntime)
        runtime.vision = _Vision()
        runtime.brain = SimpleNamespace(current_goal="TRAIN")
        runtime._last_known_label = "HOME"
        runtime._observe(Path("frame.png"))
        self.assertEqual(len(calls), 1, "a frame it could name needs no second look")


if __name__ == "__main__":
    unittest.main()
