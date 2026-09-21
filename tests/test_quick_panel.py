"""The 快捷面板: one frame that reports all three barracks, and the misread it caused.

The left-edge triangle opens a panel over whichever page is underneath.  It repeats
three queues -- 建筑队列 / 部队训练 / 科技研究 -- and it is the only surface that shows
all three barracks at once, which matters because the training page draws one camp per
visit (issue #86).

Measured 2026-09-21.  Driving the operator's own panel frame through production vision
returned every field wrong, and the two errors compounded into "why is nothing
training":

    page     = Page.RESEARCH   conf 0.9998
    training = {}
    research = {"timer": "06:39:17", "status": "IN_PROGRESS", "queue_available": false}

* the panel's 科技研究 header named a page the player was not on, overriding the
  template layer's correct ``Page.UNKNOWN`` (``test_the_panel_does_not_name_a_page``);
* the frame's first ``HH:MM:SS`` was 使馆升级中's countdown -- the *building* queue --
  and it was taken as research's, so ``queue_available`` went false and the brain
  answered ``SAFE_STOP training_queue_busy`` without opening a barracks at all
  (``test_a_building_countdown_is_not_the_research_timer``).

The frames are archived under ``dataset/truth_audit/quick_panel_20260921``; the reader is
pinned against them rather than against a description of them.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.live_stack import production_vision

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import (
    QUICK_PANEL_PLATE_ROI,
    QUICK_PANEL_ROI,
    OCRPageClassifier,
    OCRResult,
    OCRToken,
    read_quick_panel,
)
from winter_agent_v2.skills import v2_registry

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "dataset" / "truth_audit" / "quick_panel_20260921"
PANEL_OPEN = ARCHIVE / "01_panel_open_all_camps_idle.png"
CITY_CLOSED = ARCHIVE / "02_city_panel_closed.png"
INTEL_CLOSED = ARCHIVE / "03_intel_panel_closed.png"
CITY_CLOSED_2 = ARCHIVE / "04_city_panel_closed_second.png"


def _token(text: str, x: float, y: float, *, conf: float = 0.99, width: float = 120.0):
    """A token whose centre lands on ``(x, y)`` in a 720x1280 frame."""
    return OCRToken(
        text=text,
        confidence=conf,
        box=((x - width / 2, y - 15), (x + width / 2, y - 15), (x + width / 2, y + 15), (x - width / 2, y + 15)),
    )


#: The panel's own rows, transcribed from the live frame's OCR pass.  Reproduced as
#: tokens so the reader can be driven without opening the image, and *verified* against
#: the image by ``LiveQuickPanelTests`` below.
PANEL_TOKENS = (
    _token("建筑队列", 81.5, 321.0),
    _token("使馆升级中", 225.0, 360.5),
    _token("06:14:58", 224.5, 390.0),
    _token("队列2", 224.0, 433.5),
    _token("购买队列", 223.5, 464.0),
    _token("部队训练", 99.5, 507.5),
    _token("盾兵", 225.0, 546.0),
    _token("已完成", 224.5, 576.5),
    _token("矛兵", 224.5, 619.0),
    _token("已完成", 225.0, 649.5),
    _token("射手", 224.5, 692.5),
    _token("已完成", 225.0, 723.0),
    # The recogniser folds a stroke of the header's icon into the word at 0.90.
    _token("X科技研究", 80.5, 765.5, conf=0.90),
    _token("科技研究", 224.0, 805.5),
    _token("空闲中", 224.0, 835.0),
)


class _NullOCR:
    """Serves a fixed token set, so the reader is driven without an image."""

    def __init__(self, tokens):
        self._result = OCRResult(tokens, "fixed")

    def recognize(self, image_path, roi=None):  # noqa: ANN001 - test double
        return self._result


class QuickPanelReaderTests(unittest.TestCase):
    """What the panel says, read from its tokens."""

    def setUp(self) -> None:
        self.panel = read_quick_panel(None, _NullOCR(PANEL_TOKENS))

    def test_the_panel_is_read_as_its_own_surface(self) -> None:
        self.assertTrue(self.panel["open"])

    def test_all_three_barracks_are_reported_idle(self) -> None:
        """The reading the operator had to supply by hand, from one frame."""
        camps = self.panel["camps"]
        self.assertEqual(set(camps), {"SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP"})
        for camp, reading in camps.items():
            self.assertEqual(reading["status"], "IDLE", camp)
            self.assertIs(reading["queue_available"], True, camp)
            self.assertEqual(reading["source_word"], "已完成", camp)
        self.assertEqual(camps["SHIELD_CAMP"]["troop_type"], "INFANTRY")
        self.assertEqual(camps["LANCER_CAMP"]["troop_type"], "LANCER")
        self.assertEqual(camps["MARKSMAN_CAMP"]["troop_type"], "MARKSMAN")

    def test_the_camps_use_the_same_keys_as_the_training_page(self) -> None:
        """One per-camp model, so a consumer need not know which surface it came from."""
        from winter_agent_v2.camp_training import CAMP_ORDER

        self.assertEqual(set(self.panel["camps"]), set(CAMP_ORDER))

    def test_the_building_row_is_busy_with_its_own_countdown(self) -> None:
        building = self.panel["building"]
        self.assertEqual(building["status"], "IN_PROGRESS")
        self.assertIs(building["queue_available"], False)
        self.assertEqual(building["timer"], "06:14:58")

    def test_research_is_idle(self) -> None:
        research = self.panel["research"]
        self.assertEqual(research["status"], "IDLE")
        self.assertIs(research["queue_available"], True)
        self.assertEqual(research["source_word"], "空闲中")

    def test_a_second_building_queue_is_not_a_second_reading(self) -> None:
        """队列2 sits inside 建筑队列's section, so it must not overwrite the first row."""
        self.assertEqual(self.panel["building"]["name"], "使馆升级中")

    def test_no_section_is_invented_when_it_was_not_read(self) -> None:
        """A section that could not be read is absent, not reported idle."""
        only_headers = read_quick_panel(
            None,
            _NullOCR(tuple(_token(header, 100, y) for header, y in
                           (("建筑队列", 321), ("部队训练", 507), ("科技研究", 765)))),
        )
        self.assertNotIn("camps", only_headers)
        self.assertNotIn("building", only_headers)
        self.assertNotIn("research", only_headers)


class QuickPanelIsNotAPageTests(unittest.TestCase):
    """The panel is an overlay, so it must not decide the page under it."""

    def test_the_panel_does_not_name_a_page(self) -> None:
        """科技研究 in the panel's band cannot identify the research page.

        Measured 2026-09-21: this frame was read as ``Page.RESEARCH`` at 0.9998 while the
        template layer had it right at ``Page.UNKNOWN``.  The page's own header sits at
        y_norm ~0.035; the panel draws its headers in the middle of the frame.
        """
        result = OCRResult(PANEL_TOKENS, "fake")
        state = OCRPageClassifier().classify(result, frame_size=(720, 1280))
        self.assertIsNot(state.page, Page.RESEARCH)
        self.assertIs(state.page, Page.UNKNOWN)

    def test_a_real_research_header_still_names_the_page(self) -> None:
        """The exclusion is positional, so nothing real lost its recognition."""
        result = OCRResult((_token("科技研究", 100.0, 45.0),), "fake")
        state = OCRPageClassifier().classify(result, frame_size=(720, 1280))
        self.assertIs(state.page, Page.RESEARCH)

    def test_a_building_countdown_is_not_the_research_timer(self) -> None:
        """06:14:58 belongs to 建筑队列, which 使馆升级中 sits directly above.

        Reading it as research's timer set ``queue_available=False``, which brain.py turns
        into ``SAFE_STOP training_queue_busy`` -- the whole reason the three idle camps
        were never trained.
        """
        result = OCRResult(PANEL_TOKENS, "fake")
        state = OCRPageClassifier().classify(result, frame_size=(720, 1280))
        self.assertNotEqual(state.research.get("status"), "IN_PROGRESS")
        self.assertIsNot(state.research.get("queue_available"), False)


class LiveQuickPanelTests(unittest.TestCase):
    """The archived frames, driven through production vision."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()

    def test_the_open_panel_reads_all_three_barracks_idle(self) -> None:
        world = self.vision.observe(PANEL_OPEN)
        camps = world.camps
        self.assertEqual(set(camps), {"SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP"})
        for camp, reading in camps.items():
            self.assertEqual(reading.get("status"), "IDLE", camp)
            self.assertIs(reading.get("queue_available"), True, camp)

    def test_the_open_panel_no_longer_masquerades_as_the_research_page(self) -> None:
        world = self.vision.observe(PANEL_OPEN)
        self.assertIsNot(world.page, Page.RESEARCH)

    def test_the_panel_is_not_read_when_it_is_closed(self) -> None:
        """Four frames without the panel, each read as no panel at all."""
        for frame in (CITY_CLOSED, INTEL_CLOSED, CITY_CLOSED_2):
            with self.subTest(frame=frame.name):
                world = self.vision.observe(frame)
                self.assertFalse(world.quick_panel.get("open"), frame.name)
                self.assertEqual(world.quick_panel, {}, frame.name)

    def test_the_plate_gate_separates_open_from_closed(self) -> None:
        """The pixel gate itself, measured on the archived frames."""
        vision = self.vision
        self.assertTrue(vision._quick_panel_is_drawn(PANEL_OPEN))
        for frame in (CITY_CLOSED, INTEL_CLOSED, CITY_CLOSED_2):
            with self.subTest(frame=frame.name):
                self.assertFalse(vision._quick_panel_is_drawn(frame), frame.name)


class PanelReachesTheTrainingDecisionTests(unittest.TestCase):
    """An idle camp on the panel is a fact the TRAIN goal can act on."""

    def _panel(self, **camps):
        return {
            "open": True,
            "camps": {
                camp: {"status": status, "queue_available": available}
                for camp, (status, available) in camps.items()
            },
        }

    def test_an_idle_camp_is_named_when_the_goal_routes_to_it(self) -> None:
        brain = RuleBrain(current_goal="TRAIN")
        decision = brain.decide(
            WorldState(
                page=Page.HOME,
                quick_panel=self._panel(
                    SHIELD_CAMP=("IDLE", True),
                    LANCER_CAMP=("IDLE", True),
                    MARKSMAN_CAMP=("IDLE", True),
                ),
                confidence=0.98,
            ),
            v2_registry(),
        )
        self.assertEqual(decision.skill, "OPEN_POWER_OVERVIEW")
        self.assertIn("quick_panel", decision.reason)
        self.assertEqual(brain.idle_camp_from_quick_panel, "SHIELD_CAMP")

    def test_a_busy_panel_leaves_the_route_on_its_own_path(self) -> None:
        """Every camp busy means no idle-camp claim, so the existing route stands."""
        decision = RuleBrain(current_goal="TRAIN").decide(
            WorldState(
                page=Page.HOME,
                quick_panel=self._panel(
                    SHIELD_CAMP=("IN_PROGRESS", False),
                    LANCER_CAMP=("IN_PROGRESS", False),
                    MARKSMAN_CAMP=("IN_PROGRESS", False),
                ),
                confidence=0.98,
            ),
            v2_registry(),
        )
        self.assertNotIn("quick_panel", decision.reason)


class QuickPanelGeometryTests(unittest.TestCase):
    """The two ROIs describe the panel, so a change to either is a deliberate one."""

    def test_the_read_roi_covers_the_panel_rows(self) -> None:
        left = QUICK_PANEL_ROI["x_norm"]
        right = left + QUICK_PANEL_ROI["w_norm"]
        # Measured: panel tokens run from x_norm 0.10 (headers) to 0.34 (row words).
        self.assertLessEqual(left, 0.10)
        self.assertGreaterEqual(right, 0.34)

    def test_the_plate_roi_sits_inside_the_read_roi(self) -> None:
        left, top, right, bottom = QUICK_PANEL_PLATE_ROI
        self.assertGreaterEqual(left, QUICK_PANEL_ROI["x_norm"])
        self.assertGreaterEqual(top, QUICK_PANEL_ROI["y_norm"])
        self.assertLessEqual(right, QUICK_PANEL_ROI["x_norm"] + QUICK_PANEL_ROI["w_norm"])
        self.assertLessEqual(bottom, QUICK_PANEL_ROI["y_norm"] + QUICK_PANEL_ROI["h_norm"])


if __name__ == "__main__":
    unittest.main()
