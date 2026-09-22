"""The screen the training route kept dying on, read from the client's own words.

What was wrong, 2026-09-21/22
----------------------------
``NAVIGATE_INFANTRY_CAMP`` -- the hop that brings the client to the barracks -- was
recorded 35 times: 13 passed, and then **every attempt from 16:24 to 23:47 failed**, all
twelve with ``INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN``.  Reading the frames says the route
had already arrived.  The older render is a gold ring around the barracks and nothing
else, which is what ``camp_ring.py`` was built from.  The current one is the client's
ordinary selected-building treatment: the scene dimmed, ``盾兵营`` named above the
building, and its own ``详情 / 升级 / 训练`` bar drawn along the bottom -- and

    ``ocr.SemanticWorldVision._building_is_selected`` gates on three templates
    (``BTN_UPGRADE`` / ``BTN_TRAINING_MENU_LABEL`` / ``BTN_OPEN_TRAINING_FROM_CAMP``)

**all three of which miss this render**, so ``training`` came back empty and the
verifier answered "not proven".  Measured on the ten failing frames (720x1280):

    盾兵营   (376-378, 545-548)   conf 0.958 - 0.995     which camp is selected
    详情     (236, 914-915)       conf 0.994 - 0.998
    升级     (360, 943-944)       conf 1.000
    训练     (483-487, 912-916)   conf 0.986 - 0.997     and where to tap

Four pixels of spread across seven hours, because the bar is a screen-space overlay.  The
two renders are genuinely different and not two readings of one: the 训练 label does not
appear at all on the gold-ring frames.

So the reading is text, which is the same conclusion ``read_resource_tab_labels`` reached
for the search strip and ``BTN_BEAST_CARD_ATTACK`` for the beast card.  These tests pin
the four things that decide whether it is safe rather than merely working: what the bar
says, which building it names, what it refuses, and where the tap lands.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import OCRToken, read_building_action_tokens  # noqa: E402
from winter_agent_v2.verifier import (  # noqa: E402
    verify_infantry_camp_highlighted,
    verify_training_page_open,
)

FRAME = (720, 1280)

#: Kept outside ``dataset/raw``: the retention policy prunes captured frames, and a test
#: that points at a prunable file is a test that will one day fail for the wrong reason.
EVIDENCE = ROOT / "dataset/truth_audit/camp_action_bar_20260922"
ACTION_BAR_FRAME = EVIDENCE / "camp_selected_action_bar__shield_camp__live_20260922T0747.png"
GOLD_RING_FRAME = EVIDENCE / "camp_gold_ring_render__shield_camp__live_20260921T1307.png"
TRAINING_PAGE_FRAME = EVIDENCE / "training_page__three_camp_tabs_and_queue__live_20260921T0953.png"
OTHER_BUILDING_FRAME = EVIDENCE / "gate_also_matches__research_lab_selected__live_20260919T1012.png"


def token(text: str, box: tuple[float, float, float, float], confidence: float = 0.99) -> OCRToken:
    x0, y0, x1, y1 = box
    return OCRToken(text=text, confidence=confidence,
                    box=((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def action_bar_tokens(confidence: float = 0.99) -> list[OCRToken]:
    """The ten failing frames' readings, with the boxes and confidences OCR reported."""
    return [
        token("盾兵营", (352, 532, 402, 560), confidence),
        token("详情", (211, 900, 261, 929), confidence),
        token("升级", (335, 929, 385, 958), confidence),
        token("训练", (458, 897, 512, 930), confidence),
        token("16:14", (40, 20, 110, 48)),          # HUD clock -- neither action nor name
        token("通关探险第80关（0/1）", (120, 1030, 420, 1060)),
    ]


# ------------------------------------------------------------------ what the bar says


class ActionBarReadingTests(unittest.TestCase):
    def test_the_three_controls_are_read_where_the_client_drew_them(self):
        reading = read_building_action_tokens(action_bar_tokens(), FRAME)
        self.assertEqual(set(reading["actions"]), {"详情", "升级", "训练"})
        x_norm, y_norm = reading["actions"]["训练"]
        self.assertAlmostEqual(x_norm, 485 / 720, places=3)
        self.assertAlmostEqual(y_norm, 913.5 / 1280, places=3)

    def test_the_selected_building_is_named_and_resolved_to_a_camp(self):
        reading = read_building_action_tokens(action_bar_tokens(), FRAME)
        self.assertEqual(reading["name"], "盾兵营")
        self.assertEqual(reading["camp"], "SHIELD_CAMP")

    def test_a_hud_token_is_neither_an_action_nor_a_name(self):
        """The bands are what keep 通关探险第80关 and the clock out of the reading."""
        reading = read_building_action_tokens(action_bar_tokens(), FRAME)
        self.assertNotIn("通关探险第80关（0/1）", reading["actions"])

    def test_an_unreadable_level_badge_is_not_invented(self):
        """Nothing here reads a level, so a frame that draws one gains nothing.

        Stated as a test because the temptation is real: ``16`` is on the frame, and the
        bar is gated on the *camp name*, not on the badge.
        """
        tokens = action_bar_tokens() + [token("16", (205, 452, 245, 484))]
        reading = read_building_action_tokens(tokens, FRAME)
        self.assertEqual(set(reading), {"actions", "name", "camp", "name_norm"})


# ------------------------------------------------------------------ what it refuses


class RefusalTests(unittest.TestCase):
    def test_a_bar_without_the_training_control_is_not_this_state(self):
        """A selected 仓库 draws 升级 and 详情 and no 训练 -- and must not read as a camp."""
        tokens = [
            token("仓库", (351, 534, 401, 559)),
            token("详情", (276, 926, 324, 956)),
            token("升级", (335, 929, 385, 958)),
        ]
        reading = read_building_action_tokens(tokens, FRAME)
        self.assertNotIn("训练", reading["actions"])
        self.assertEqual(reading["camp"], "")

    def test_a_label_below_the_confidence_floor_is_not_read(self):
        reading = read_building_action_tokens(action_bar_tokens(0.41), FRAME)
        self.assertEqual(reading["actions"], {})
        self.assertEqual(reading["camp"], "")

    def test_a_token_without_a_box_is_not_read(self):
        tokens = [OCRToken(text="训练", confidence=0.99, box=())]
        self.assertEqual(read_building_action_tokens(tokens, FRAME)["actions"], {})

    def test_no_frame_size_means_no_reading(self):
        """Boxes are pixels; without the frame's size there is no normalised point."""
        for size in (None, (0, 1280), (720, 0)):
            reading = read_building_action_tokens(action_bar_tokens(), size)
            self.assertEqual(reading["actions"], {})
            self.assertIsNone(reading["name_norm"])


# ------------------------------------------------------- what the reading is used for


def _selected_camp_state() -> WorldState:
    reading = read_building_action_tokens(action_bar_tokens(), FRAME)
    return WorldState(
        page=Page.HOME,
        confidence=0.99,
        training={
            "menu_open": True,
            "camp": reading["camp"],
            "camp_label": reading["name"],
            "train_tap_norm": reading["actions"]["训练"],
            "source": "ACTION_BAR",
        },
    )


class WiringTests(unittest.TestCase):
    def test_the_hop_that_failed_twelve_times_now_verifies(self):
        before = WorldState(page=Page.POPUP, popup="POWER_DETAILS", confidence=0.99)
        result = verify_infantry_camp_highlighted(before, _selected_camp_state())
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(result.evidence["menu_open_after"])

    def test_the_next_hop_is_authorised_by_the_same_reading(self):
        """``verify_training_page_open`` requires the menu to have been open before."""
        after = WorldState(page=Page.TRAINING, confidence=0.99)
        self.assertTrue(verify_training_page_open(_selected_camp_state(), after).ok)

    def test_the_reading_does_not_claim_the_gold_ring(self):
        """``navigation`` means the ring was seen.  This render has none, so it stays unset."""
        self.assertIsNone(_selected_camp_state().training.get("navigation"))

    def test_the_reading_does_not_claim_the_queue_is_free(self):
        """This screen does not say, and the route's guard reads ``is False``.

        Absent keeps the route on its normal path; ``True`` would authorise a spend the
        frame never justified, and ``False`` would stop a goal that may well be startable.
        """
        self.assertNotIn("queue_available", _selected_camp_state().training)


class ResolverTests(unittest.TestCase):
    """The tap must land where this frame's label was, not on a remembered point."""

    def _runtime(self):
        from winter_agent_v2.runtime import LiveRuntime

        return object.__new__(LiveRuntime)

    def test_the_training_control_resolves_to_the_label_the_frame_carries(self):
        runtime = self._runtime()
        state = _selected_camp_state()
        point = runtime._resolve_semantic_target("BTN_OPEN_TRAINING_FROM_CAMP", state)
        expected = read_building_action_tokens(action_bar_tokens(), FRAME)["actions"]["训练"]
        self.assertEqual(point, expected)

    def test_a_frame_without_the_reading_resolves_to_nothing(self):
        runtime = self._runtime()
        empty = WorldState(page=Page.HOME, confidence=0.99)
        self.assertIsNone(runtime._resolve_semantic_target("BTN_OPEN_TRAINING_FROM_CAMP", empty))

    def test_the_point_is_not_reused_off_the_page_it_was_read_from(self):
        runtime = self._runtime()
        state = _selected_camp_state()
        for page in (Page.MAP, Page.TRAINING, Page.POPUP):
            self.assertIsNone(
                runtime._resolve_semantic_target(
                    "BTN_OPEN_TRAINING_FROM_CAMP",
                    WorldState(page=page, confidence=0.99, training=dict(state.training)),
                ),
                f"a {page} frame must not be tapped with a point read off a HOME frame",
            )

    def test_an_out_of_frame_point_is_refused(self):
        runtime = self._runtime()
        for point in ((1.4, 0.5), (-0.1, 0.5), (0.5,), "nope", None):
            state = WorldState(page=Page.HOME, confidence=0.99,
                               training={"menu_open": True, "train_tap_norm": point})
            self.assertIsNone(
                runtime._resolve_semantic_target("BTN_OPEN_TRAINING_FROM_CAMP", state), point
            )


# --------------------------------------------------------------- against real frames


class LiveFrameTests(unittest.TestCase):
    """The reading is only worth anything if it holds on the frames that failed."""

    def setUp(self):
        from live_stack import production_vision  # noqa: E402 - tests/ is on sys.path

        vision = production_vision()
        if vision is None:
            self.skipTest("OCR runtime unavailable in this environment")
        self.vision = vision

    def test_the_frame_all_twelve_failures_ended_on_now_reads_as_the_camp_action_bar(self):
        if not ACTION_BAR_FRAME.exists():
            self.skipTest(f"evidence frame missing: {ACTION_BAR_FRAME}")
        state = self.vision.observe(ACTION_BAR_FRAME)
        self.assertIs(state.page, Page.HOME)
        self.assertTrue(state.training.get("menu_open"), state.training)
        self.assertEqual(state.training.get("camp"), "SHIELD_CAMP")
        self.assertEqual(state.training.get("source"), "ACTION_BAR")
        point = state.training.get("train_tap_norm")
        self.assertTrue(0.0 < point[0] < 1.0 and 0.0 < point[1] < 1.0, point)

    def test_the_older_gold_ring_frame_keeps_its_own_reading(self):
        """Two renders, two readings -- and the action bar must not be claimed on this one."""
        if not GOLD_RING_FRAME.exists():
            self.skipTest(f"evidence frame missing: {GOLD_RING_FRAME}")
        state = self.vision.observe(GOLD_RING_FRAME)
        self.assertNotEqual(state.training.get("source"), "ACTION_BAR")
        self.assertIsNone(state.training.get("menu_open"))
        self.assertIsNone(state.training.get("train_tap_norm"))

    def test_the_three_camp_tabs_are_read_on_the_training_page(self):
        """The step after this one: all three labels are drawn at once, so all three read."""
        from winter_agent_v2.ocr import read_training_camp_tabs

        if not TRAINING_PAGE_FRAME.exists():
            self.skipTest(f"evidence frame missing: {TRAINING_PAGE_FRAME}")
        tabs = read_training_camp_tabs(TRAINING_PAGE_FRAME, self.vision.ocr)
        self.assertEqual(set(tabs), {"盾兵营", "矛兵营", "射手营"})
        self.assertLess(tabs["盾兵营"][0], tabs["矛兵营"][0])
        self.assertLess(tabs["矛兵营"][0], tabs["射手营"][0])
        for label, (x_norm, y_norm) in tabs.items():
            self.assertTrue(0.0 < x_norm < 1.0 and 0.9 < y_norm <= 1.0, (label, x_norm, y_norm))


class GateTests(unittest.TestCase):
    """The gate is a template, because reading every city frame is not affordable.

    ``test_ocr.py::test_hybrid_is_template_first`` pins that contract, and it caught the
    first version of this work.  These two tests are the other half: the gate does match
    the render it was cut from, and it matching is not the same as the reading being right.
    """

    def setUp(self):
        from live_stack import production_vision  # noqa: E402 - tests/ is on sys.path

        vision = production_vision()
        if vision is None:
            self.skipTest("OCR runtime unavailable in this environment")
        self.vision = vision

    def test_the_gate_matches_the_render_it_was_cut_from(self):
        from winter_agent_v2.ocr import CAMP_ACTION_BAR_GATE

        if not ACTION_BAR_FRAME.exists():
            self.skipTest(f"evidence frame missing: {ACTION_BAR_FRAME}")
        match = self.vision.template_vision.semantic.find(ACTION_BAR_FRAME, CAMP_ACTION_BAR_GATE)
        self.assertIsNotNone(match, "the action-bar gate must find the bar it was cut from")
        self.assertEqual(match.distance, 0, "the icon is identical on all twelve frames")

    def test_the_gate_matching_is_not_the_reading(self):
        """The same bar is drawn for the 研究实验室, and that frame must read as nothing.

        Measured: gate distance 0 on that frame too.  What stops it from becoming a
        training reading is the reader itself -- no 训练 control, no barracks named --
        which is why the gate is allowed to be loose.
        """
        from winter_agent_v2.ocr import CAMP_ACTION_BAR_GATE

        if not OTHER_BUILDING_FRAME.exists():
            self.skipTest(f"evidence frame missing: {OTHER_BUILDING_FRAME}")
        self.assertIsNotNone(
            self.vision.template_vision.semantic.find(OTHER_BUILDING_FRAME, CAMP_ACTION_BAR_GATE)
        )
        state = self.vision.observe(OTHER_BUILDING_FRAME)
        self.assertEqual(state.training, {}, "a selected research lab is not a training camp")


if __name__ == "__main__":
    unittest.main()
