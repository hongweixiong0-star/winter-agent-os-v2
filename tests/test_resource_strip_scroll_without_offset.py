"""Which way to scroll the search strip when its offset cannot be resolved.

Measured 2026-10-02: 20 of the day's 92 failures were `SELECT_RESOURCE`, and on their own frames
`resource_tab_offset` was `None` -- the white bracket's offset could not be resolved at all:

    semantic.selected_resource -> None
    semantic.resource_tab_offset -> None
    semantic.anchored_tab_kind -> None

The resolver for `RESOURCE_DYNAMIC` is one line, `resource_cell_center_norm(resource)`, which
needs that offset; and the runtime's only recovery for "the cell is off-screen" was gated on
`resource_tab_offset is not None` too. So with the offset missing the loop could neither tap nor
scroll: nothing was attempted, the step was refused in ~0.12 s, and it happened twice in a row
with no after-frame at all. That is the one failure shape with no recovery.

Direction does not need the offset. The client's order is fixed and the frame's own label reading
says which tabs are on screen, so a target outside that range lies to one side of it. These tests
pin the direction, the sign convention, and the refusals.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

#: The strip, as this frame actually read it (episode 20261002_155419_821689 step 22's own
#: before-frame): the beast tabs are on screen and every gatherable is to their right.
MEASURED_VISIBLE = ("SNOW_MONSTER", "BEAST", "GIANT_BEAST")


def _semantic():
    return SemanticWorldVision(MANIFEST).semantic


class ResourceTabSwipeWithoutOffsetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic = _semantic()
        self.pitch_px = self.semantic.resource_tab_pitch * 720.0

    def test_it_will_only_answer_for_the_resources_that_carry_reviewed_templates(self):
        """A monster tab must not become a resource decision by appearing in a new table."""
        self.assertIn("MEAT", self.semantic.resource_tab_cell_templates)
        for kind in ("SNOW_MONSTER", "BEAST", "GIANT_BEAST", "NOT_A_TAB", ""):
            self.assertIsNone(
                self.semantic.resource_tab_swipe_without_offset(kind, MEASURED_VISIBLE), kind)

    def test_a_target_to_the_right_of_the_visible_range_scrolls_negative(self):
        """The measured case: the strip shows the beast tabs, so the gatherable it wants is to
        their right, and a negative drag delta is what reveals a right-clipped tab."""
        delta = self.semantic.resource_tab_swipe_without_offset("WOOD", MEASURED_VISIBLE)
        self.assertIsNotNone(delta)
        self.assertAlmostEqual(delta, -self.pitch_px, places=6)

    def test_a_target_to_the_left_of_the_visible_range_scrolls_positive(self):
        delta = self.semantic.resource_tab_swipe_without_offset("MEAT", ("WOOD", "COAL", "IRON"))
        self.assertIsNotNone(delta)
        self.assertAlmostEqual(delta, self.pitch_px, places=6)

    def test_a_target_already_inside_the_visible_range_is_not_a_scroll_problem(self):
        for kind in ("MEAT", "WOOD"):
            self.assertIsNone(
                self.semantic.resource_tab_swipe_without_offset(kind, ("MEAT", "WOOD", "COAL")))

    def test_no_visible_tab_means_no_direction_to_guess_from(self):
        """Only a frame that names no strip tab at all leaves the direction unknowable.  A frame
        that names one tab *is* enough: the order is fixed, so the target's side is decided.  The
        first version of this test listed ``("BEAST",)`` here and was wrong -- with 野兽 on screen,
        木材 is to its right and the swipe has a defensible direction."""
        for visible in ((), None, ("NOT_A_TAB",), ("",)):
            self.assertIsNone(
                self.semantic.resource_tab_swipe_without_offset("WOOD", visible), visible)

    def test_one_named_tab_is_enough_to_decide_the_side(self):
        delta = self.semantic.resource_tab_swipe_without_offset("WOOD", ("BEAST",))
        self.assertAlmostEqual(delta, -self.pitch_px, places=6)
        delta = self.semantic.resource_tab_swipe_without_offset("MEAT", ("IRON",))
        self.assertAlmostEqual(delta, self.pitch_px, places=6)

    def test_the_direction_agrees_with_the_geometry_path_it_stands_in_for(self):
        """The strongest check available without a device: for an offset that puts the same target
        off the right edge, `resource_tab_swipe_for` -- the measured-in-production function this
        one substitutes for -- must return the same sign.  A sign disagreement between the two
        would mean the fallback scrolls away from the tab it is trying to reach."""
        saved = self.semantic.resource_tab_offset
        try:
            for target in ("MEAT", "WOOD", "COAL", "IRON"):
                if target not in self.semantic.resource_tab_cell_templates:
                    continue
                index = self.semantic.resource_tab_order.index(target)
                # An offset that pushes this cell past the right edge of a 720 px frame.
                offset = 716 - (self.semantic.resource_tab_first_left * 720.0
                                + index * self.pitch_px) + 40
                self.semantic.resource_tab_offset = offset
                geometry = self.semantic.resource_tab_swipe_for(target)
                fallback = self.semantic.resource_tab_swipe_without_offset(target, MEASURED_VISIBLE)
                self.assertIsNotNone(geometry, target)
                self.assertIsNotNone(fallback, target)
                self.assertLess(geometry, 0, target)
                self.assertLess(fallback, 0, target)
        finally:
            self.semantic.resource_tab_offset = saved

    def test_one_pitch_is_bounded_by_the_pitch_itself(self):
        """The amount may not become a guess either: it is one tab's spacing, and the caller keeps
        its own max_scroll_attempts bound on top of it."""
        for target in ("MEAT", "WOOD", "COAL", "IRON"):
            delta = self.semantic.resource_tab_swipe_without_offset(target, MEASURED_VISIBLE)
            if delta is None:
                continue
            self.assertLessEqual(abs(delta), self.pitch_px + 1e-9)


if __name__ == "__main__":
    unittest.main()
