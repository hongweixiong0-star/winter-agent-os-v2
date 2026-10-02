"""The material tabs' tap point was known, read, and thrown away.

Measured 2026-10-02 on the deployed revision: four `SELECT_RESOURCE` steps failed in 0.11-0.14 s
with no after-frame at all, and their own before-states say something no other cluster does:

    resource_search_open  = True
    resource_target       = MEAT
    resource_tab_kinds    = ('BEAST', 'GIANT_BEAST', 'MEAT', 'WOOD')   <- the wanted tab is drawn
    resource_tab_offset   = None
    anchored_tab_kind     = None
    resource_selected_tab = None

The identity layer knows the tab is on screen and the geometry layer resolves nothing, so the
resolver's one line -- `resource_cell_center_norm(resource)` -- answers nothing and the step is
refused.  On the archived frame the 生肉 tab is plainly there in the strip, with its label read at
OCR confidence 0.95-1.00.

`ocr.read_resource_tab_labels` returns exactly what is missing: `kind -> that tab's centre`.  Two of
the five tabs already use it as their tap point, and have since 2026-09-21 --
`BEAST_SEARCH_TAB` returns `frame.resource_beast_tab_norm` and `GIANT_BEAST_SEARCH_TAB` returns
`resource_giant_beast_tab_norm`, both read off the frame's own OCR.  The observation keeps those two
centres and **discards the gatherable ones**, keeping only their names in `resource_tab_kinds`:

    resource_beast_tab_norm        = tab_labels.get("BEAST")
    resource_giant_beast_tab_norm  = tab_labels.get("GIANT_BEAST")
    resource_tab_kinds             = tuple(sorted(tab_labels))     <- centres gone

So the fix is not a new mechanism: it is the pattern this project already chose for the tab it
needed first, applied to the tabs it needs next.  These tests pin the three layers -- the
observation keeps what it read, the resolver prefers geometry and falls back to the label, and the
fallback refuses what it cannot see.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.live_stack import production_vision  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

EPISODE = "20261002_182040_468682"
RUN = ROOT / "dataset/raw/control_panel/runtime_auto" / EPISODE
# The four frames the refused steps were decided on; the first is the one quoted above.
FRAMES = (
    RUN / f"{EPISODE}_step_003_before_20261002T102114362188.png",
    RUN / f"{EPISODE}_step_004_before_20261002T102121466286.png",
)
#: What the client drew on those frames, in the order the strip prints it.
DRAWN_TABS = ("BEAST", "GIANT_BEAST", "MEAT", "WOOD")
#: The strip sits near the bottom of the panel; a centre outside this is not a tab read.
STRIP_BAND = (0.60, 0.85)


class _DeadGeometry:
    """The measured state of the geometry layer on these frames: it answers nothing."""

    resource_tab_offset = None
    anchored_tab_kind = None
    selected_resource = property(lambda self: None)

    def resource_cell_center_norm(self, _resource):
        return None

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _LiveGeometry(_DeadGeometry):
    """A frame whose strip *was* located -- the geometry must win over the label."""

    resource_tab_offset = 210.0

    def resource_cell_center_norm(self, resource):
        return {"MEAT": (0.10, 0.70)}.get(resource)


def _runtime(semantic):
    """A runtime carrying only what the resolver branch touches.

    ``_semantic`` is a read-only property that resolves ``semantic_vision`` (or its
    ``.semantic``), so the stub is injected there rather than on the property.
    """
    runtime = object.__new__(LiveRuntime)
    runtime.semantic_vision = semantic
    return runtime


def _frame(**overrides):
    fields = {
        "page": Page.MAP,
        "resource_search_open": True,
        "resource_target": "MEAT",
        "resource_tab_kinds": DRAWN_TABS,
        "resource_tab_label_norm": {"BEAST": (0.0576, 0.7398), "MEAT": (0.6462, 0.7008),
                                    "WOOD": (0.7747, 0.7016)},
    }
    fields.update(overrides)
    return WorldState(**fields)


class TheObservationKeepsWhatItReadTest(unittest.TestCase):
    def test_the_read_tab_centres_survive_into_the_state(self):
        """Every tab the client drew, not just the two the beast route happened to need."""
        vision = production_vision()
        if vision is None or not FRAMES[0].is_file():
            self.skipTest("production OCR stack or the archived frame is unavailable here")
        observed = vision.observe(FRAMES[0])
        centres = getattr(observed, "resource_tab_label_norm", None)
        self.assertIsInstance(centres, dict, "the state must carry the centres it read")
        self.assertEqual(set(centres), set(observed.resource_tab_kinds),
                         "the centres and the kinds must come from the same reading")
        for kind in DRAWN_TABS:
            self.assertIn(kind, centres, kind)
            x_norm, y_norm = centres[kind]
            self.assertTrue(0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0, kind)
            self.assertTrue(STRIP_BAND[0] <= y_norm <= STRIP_BAND[1],
                            f"{kind} centre {y_norm} is not in the strip band")
        # The two the beast route already used keep their own fields, unchanged.
        self.assertEqual(tuple(centres["BEAST"]), tuple(observed.resource_beast_tab_norm))


class TheResolverTapsWhereTheLabelWasReadTest(unittest.TestCase):
    def test_the_wanted_material_tab_resolves_from_its_label(self):
        """The measured failure, resolved: geometry dead, target drawn, point available."""
        runtime = _runtime(_DeadGeometry())
        point = runtime._resolve_semantic_target("RESOURCE_DYNAMIC", _frame(), resource="MEAT")
        self.assertEqual(point, (0.6462, 0.7008))

    def test_geometry_still_wins_when_the_strip_was_located(self):
        """The label is a fallback, not a replacement -- the order the beast tab documents."""
        runtime = _runtime(_LiveGeometry())
        point = runtime._resolve_semantic_target("RESOURCE_DYNAMIC", _frame(), resource="MEAT")
        self.assertEqual(point, (0.10, 0.70))

    def test_a_resource_the_frame_never_read_is_not_invented(self):
        runtime = _runtime(_DeadGeometry())
        for resource in ("COAL", "IRON", "GEMS", "", None):
            with self.subTest(resource=resource):
                self.assertIsNone(
                    runtime._resolve_semantic_target("RESOURCE_DYNAMIC", _frame(), resource=resource)
                )

    def test_the_fallback_refuses_off_the_map_or_with_the_panel_closed(self):
        """A label point belongs to the frame it was read from, and only the panel draws it."""
        runtime = _runtime(_DeadGeometry())
        for page in (Page.HOME, Page.MARCH, Page.RESOURCE_DETAIL):
            with self.subTest(page=page):
                self.assertIsNone(runtime._resolve_semantic_target(
                    "RESOURCE_DYNAMIC", _frame(page=page), resource="MEAT"))
        self.assertIsNone(runtime._resolve_semantic_target(
            "RESOURCE_DYNAMIC", _frame(resource_search_open=False), resource="MEAT"))

    def test_a_centre_outside_the_frame_is_refused(self):
        runtime = _runtime(_DeadGeometry())
        for bad in ((1.4, 0.70), (0.6, -0.2), ("x", 0.7), (0.6,), None):
            with self.subTest(point=bad):
                labels = {"MEAT": bad}
                self.assertIsNone(runtime._resolve_semantic_target(
                    "RESOURCE_DYNAMIC", _frame(resource_tab_label_norm=labels), resource="MEAT"))

    def test_the_two_beast_tabs_still_resolve_from_their_own_fields(self):
        """The refactor must not disturb the behaviour they already had."""
        runtime = _runtime(_DeadGeometry())
        frame = WorldState(page=Page.MAP, resource_search_open=True,
                           resource_beast_tab_norm=(0.0576, 0.7398),
                           resource_giant_beast_tab_norm=(0.2197, 0.7394),
                           confidence=0.99)
        self.assertEqual(runtime._resolve_semantic_target("BEAST_SEARCH_TAB", frame),
                         (0.0576, 0.7398))
        self.assertEqual(runtime._resolve_semantic_target("GIANT_BEAST_SEARCH_TAB", frame),
                         (0.2197, 0.7394))


class TheRecordedFrameYieldsAPointTest(unittest.TestCase):
    """End to end on the frame the refusal was decided on: observe, then resolve."""

    def test_every_archived_refusal_frame_now_resolves_the_tab_it_wanted(self):
        vision = production_vision()
        if vision is None:
            self.skipTest("production OCR stack is unavailable here")
        checked = 0
        for frame_path in FRAMES:
            if not frame_path.is_file():
                continue
            checked += 1
            observed = vision.observe(frame_path)
            self.assertTrue(observed.resource_search_open, frame_path.name)
            self.assertIn("MEAT", observed.resource_tab_kinds, frame_path.name)
            runtime = _runtime(_DeadGeometry())
            point = runtime._resolve_semantic_target("RESOURCE_DYNAMIC", observed, resource="MEAT")
            self.assertIsNotNone(point, f"{frame_path.name}: the tab is drawn and has no point")
            self.assertTrue(0.0 <= point[0] <= 1.0 and 0.0 <= point[1] <= 1.0, point)
        if checked == 0:
            self.skipTest("none of the archived frames are present")


if __name__ == "__main__":
    unittest.main()
