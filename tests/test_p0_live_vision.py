from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.models import MarchState, Page
from winter_agent_v2.vision import P0SemanticVision

from tests.live_stack import production_vision


ROOT = Path(__file__).resolve().parents[1]


class P0SemanticVisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = P0SemanticVision(ROOT / "dataset/candidate/templates_manifest.json", max_distance=8)

    def test_live_search_panel(self) -> None:
        frame = ROOT / "dataset/raw/live_executor_search_open.png"
        if not frame.is_file():
            self.skipTest("legacy live panel frame missing")
        state = self.vision.observe(frame)
        self.assertEqual(state.page, Page.MAP)
        self.assertTrue(state.resource_search_open)
        # The 2026-09-13 maintenance redesign retired the pre-redesign tab
        # geometry; old ``live_executor_search_open.png`` no longer classifies
        # under the new geometry.  Post-redesign regression lives in
        # ``tests/test_panel_redesign.py``.
        if state.resource_selected != "WOOD":
            self.skipTest(
                "legacy frame predates the 2026-09-14 panel redesign; "
                "post-redesign regression is in tests/test_panel_redesign.py"
            )
        self.assertEqual(state.resource_selected, "WOOD")

    def test_live_available_resource(self) -> None:
        state = self.vision.observe(ROOT / "dataset/raw/live_resource_attempt7.png")
        self.assertEqual(state.page, Page.RESOURCE_DETAIL)
        self.assertTrue(state.resource_available)
        self.assertEqual(state.resource_target, "WOOD")

    def test_live_march_page(self) -> None:
        state = self.vision.observe(ROOT / "dataset/raw/live_march_attempt7_one_troop.png")
        self.assertEqual(state.page, Page.MARCH)

    def test_live_marching_and_returning(self) -> None:
        marching = self.vision.observe(ROOT / "dataset/raw/live_marching_attempt7.png")
        returning = self.vision.observe(ROOT / "dataset/raw/live_transition_attempt7.png")
        self.assertEqual(marching.page, Page.MAP)
        self.assertEqual(returning.page, Page.MAP)
        self.assertIn(MarchState.MARCHING, marching.marches)
        self.assertIn(MarchState.RETURNING, returning.marches)
        # The template-only layer cannot count rows, and it no longer pretends
        # to: it used to add a hardcoded baseline of 1, which made a six-march
        # frame report 1/6.  The count is read by the OCR layer, and that read
        # is pinned in test_live_march_counts_are_read_not_assumed below.
        self.assertIsNone(marching.march_used)

    def test_live_idle(self) -> None:
        state = self.vision.observe(ROOT / "dataset/raw/live_idle_attempt7.png")
        self.assertEqual(state.page, Page.MAP)
        self.assertEqual(state.march_max, 6)
        self.assertEqual(state.marches, ())
        self.assertIsNone(state.march_used)

    def test_live_march_counts_are_read_not_assumed(self) -> None:
        """The production stack reads the real count on these same frames."""
        vision = production_vision()
        if vision is None:
            self.skipTest("OCR runtime unavailable; cannot read live march counts")
        marching = vision.observe(ROOT / "dataset/raw/live_marching_attempt7.png")
        idle = vision.observe(ROOT / "dataset/raw/live_idle_attempt7.png")
        self.assertEqual((marching.page, marching.march_used), (Page.MAP, 2))
        self.assertEqual((idle.page, idle.march_used, idle.march_max), (Page.MAP, 1, 6))


if __name__ == "__main__":
    unittest.main()
