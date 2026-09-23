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
        """A closed panel yields no *panel reading* -- no sections, no rows, nothing to act on.

        What it may now carry is the handle, and that is not the panel: the handle is drawn *by* the
        closed state, at the frame's own left edge, and the route needs it precisely to open what is
        not open (operator 2026-09-22, the screenshot with the handle circled).  So the assertion is
        about what must stay empty -- the three sections and the task rows -- while a handle, if the
        frame draws one, has to describe itself as COLLAPSED and say what located it.
        """
        for frame in (CITY_CLOSED, INTEL_CLOSED, CITY_CLOSED_2):
            with self.subTest(frame=frame.name):
                world = self.vision.observe(frame)
                panel = world.quick_panel or {}
                self.assertFalse(panel.get("open"), frame.name)
                for section in ("building", "camps", "research", "rows"):
                    self.assertNotIn(section, panel, f"{frame.name}: a closed panel has no {section}")
                handle = panel.get("handle")
                if handle is not None:
                    self.assertEqual(handle["state"], "COLLAPSED", frame.name)
                    self.assertEqual(handle["basis"], "HANDLE_TRIANGLE_SCAN", frame.name)
                    self.assertLess(handle["point_norm"][0], 0.1, f"{frame.name}: the handle is at the left edge")

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
        """Every camp busy is an *answer*, not a reason to go and look again.

        The assertion changed 2026-09-23 and the rule behind it is the operator's §二/§三/§五: the
        panel reports 进行中 per barracks, and 兵营和科研已在进行中 means 记录预计结束时间，在需要重新
        确认状态时再观察 -- 周期到达只表示相关状态可能需要刷新，不代表必须进入具体功能页面.

        Before this the goal walked ``OPEN_POWER_OVERVIEW`` -> ``OPEN_POWER_DETAILS`` to ask the same
        question: 20 such steps in the corpus, **every one of them a FAILURE**
        (``POWER_DETAILS_NOT_PROVEN``).  So the earlier form of this test -- that the panel must not
        appear in the reason at all -- was pinning the detour.  What it should pin is that a busy panel
        does not send the run anywhere: the goal steps aside, non-fatally, and the cycle goes to
        another selectable task (§六).
        """
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
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertIn("quick_panel", decision.reason, "the reason names the reading that decided it")
        from winter_agent_v2.runtime_snapshot import is_fatal_stop

        self.assertFalse(is_fatal_stop(decision.reason), "this must hand the cycle over, not end it")


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


ROWS_ARCHIVE = ROOT / "dataset" / "truth_audit" / "quick_panel_row_20260923"
#: 2026-09-22 19:31:04.  The four rows all draw an arrow, and two of them carry the client's dot.
ROWS_WITH_BADGES = ROWS_ARCHIVE / "panel_rows_arrows_and_badges__live_20260922T1931.png"
#: 2026-09-22 19:44:14.  Its 矛兵 row is 已完成, so the client draws its green tick there instead of a
#: chevron -- the frame that pins "no chevron" as the client's own statement rather than a scan failure.
ROWS_ONE_DONE = ROWS_ARCHIVE / "panel_rows_one_done__live_20260922T1944.png"
#: The panel scrolled one screen down, so its lower sections are in view -- and so is the city's event
#: rail to its right, which is what made this frame evidence (issue #99).
ROWS_SCROLLED = ROWS_ARCHIVE / "panel_scrolled_sections_with_the_city_event_rail__live_20260922T2202.png"


class TheButtonIsLocatedByItsChevronTests(unittest.TestCase):
    """A row's arrow point comes from the button, and the blue alone cannot say where the button is.

    What was wrong, measured 2026-09-22/23.  The search band was (0.45, 0.80) -- x 324..576 on a
    720-wide frame -- while the panel's own right edge is around x 476-484, so 155 px of blue city sat
    inside it, and the blue was taken as min..max with the WIDEST scan line preferred, which actively
    picks the contaminated line:

        frame 19:31:04    reader reported 384-477, 384-498, 386-574, 401-494  (centres 0.5979-0.6667)
                          the button's own cyan (76,198,244) spans          x 384-425

    Those points are what the resolver taps, and the ledger shows the cost: 19:32:04 [448,804] left the
    panel open with PANEL_ROW_RESEARCH_BAR_NOT_PROVEN, 17:16:14 [480,804] and 17:54:12 [448,804] failed
    the same way, while 18:55:10 [404,804] -- inside the button -- succeeded.

    The locator is now the white chevron the client draws inside the button: measured over ten live
    panel frames (40 row-readings) it is a near-white run of exactly 20 px at x 396-416 on every hit,
    centre 0.5639 with spread 0.0000, and the three misses are the 已完成 rows, whose button is replaced
    by the green tick.  These tests pin the located point, the badge states that the same change had to
    not disturb, and the done-row case.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()

    def _rows(self, frame: Path):
        world = self.vision.observe(frame)
        rows = (world.quick_panel or {}).get("rows") or []
        return {str(r.get("key")): r for r in rows}

    def test_every_row_arrow_lands_on_the_button(self) -> None:
        if not ROWS_WITH_BADGES.exists():
            self.skipTest(f"evidence frame missing: {ROWS_WITH_BADGES}")
        rows = self._rows(ROWS_WITH_BADGES)
        self.assertEqual(set(rows), {"SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP", "RESEARCH"})
        for key, row in rows.items():
            with self.subTest(row=key):
                self.assertEqual(row["arrow_basis"], "ROW_BUTTON_SCAN", key)
                # The button's own cyan spans x 384-425 on this frame; 0.5618 is its centre.  The old
                # reading gave 0.5979-0.6667 per row, all of them off the button.
                self.assertAlmostEqual(row["arrow_norm"][0], 0.5618, places=4)
                box = row["arrow_box_norm"]
                self.assertLessEqual(box["w_norm"], 0.07, f"{key}: one widget, one width")

    def test_the_badge_states_are_the_measured_ones(self) -> None:
        """The badge window moved to the button's right third; the verdicts must not move with it.

        The dot is drawn at the button's top-right corner (412-420 inside 384-425).  The old window
        looked at the LEFT third and only found it because the contaminated box had made the button
        look about 50 px wider than it is.
        """
        if not ROWS_WITH_BADGES.exists():
            self.skipTest(f"evidence frame missing: {ROWS_WITH_BADGES}")
        rows = self._rows(ROWS_WITH_BADGES)
        self.assertEqual(rows["SHIELD_CAMP"]["badge"], "PRESENT")
        self.assertEqual(rows["RESEARCH"]["badge"], "PRESENT")
        self.assertEqual(rows["LANCER_CAMP"]["badge"], "ABSENT")
        self.assertEqual(rows["MARKSMAN_CAMP"]["badge"], "ABSENT")

    def test_a_done_row_gets_no_arrow_point(self) -> None:
        """No chevron means the client drew no enter-arrow, so there is no point to hand the executor.

        On this frame the 矛兵 row is 已完成: the client draws its green tick where the arrow usually is.
        The row falls back to the labelled text-column estimate, which the enter paths refuse, so the
        row is left alone -- which is what makes "a done row is not an enter target" structural rather
        than a hand-written condition.
        """
        if not ROWS_ONE_DONE.exists():
            self.skipTest(f"evidence frame missing: {ROWS_ONE_DONE}")
        rows = self._rows(ROWS_ONE_DONE)
        done = rows["LANCER_CAMP"]
        self.assertEqual(done["control"], "DONE")
        self.assertEqual(done["arrow_basis"], "PANEL_RELATIVE_ESTIMATE")
        for key in ("SHIELD_CAMP", "MARKSMAN_CAMP", "RESEARCH"):
            with self.subTest(row=key):
                self.assertEqual(rows[key]["control"], "ARROW")
                self.assertEqual(rows[key]["arrow_basis"], "ROW_BUTTON_SCAN")
                self.assertAlmostEqual(rows[key]["arrow_norm"][0], 0.5618, places=4)


class TheRowMustBeThePanelsOwnTests(unittest.TestCase):
    """A row's identity may only come from text the panel itself drew (issue #99).

    What was wrong, measured 2026-09-22 22:02.  The reader takes the tokens that follow a section
    header *in y order* and stops at the next header, with no test on where they sit -- and the panel
    is drawn over a city whose right-hand event rail draws its own text at the same heights:

        the 科技研究 header            y 0.2898   x 0.112
        梦境寻忆, on the event rail    y 0.2977   x 0.769      <- between the two
        the 科技研究 row itself        y 0.3211   x 0.311, with 空闲中 30 px below and a blue arrow

    So the section's "first row" became the rail's token: key RESEARCH (correct, by section), label
    梦境寻忆, status IN_PROGRESS, source_word None, control NONE.  The real row was not reported at all,
    which means a RESEARCH goal saw a busy, arrowless row where the client had drawn an idle one with a
    button -- it would skip a research building that was free.

    The fix is one predicate built on the constant that already answers this question for the geometry
    (``QUICK_PANEL_COLUMN_MAX_X_NORM``, whose note records the panel's measured band 0.10-0.34); the
    three places that take a token as part of a row use it.  After it, this frame reads exactly what
    the live device read on the same slot the next evening: 科技研究 / 空闲中 / control=ARROW /
    badge=PRESENT at y 0.3207.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()

    def test_the_research_row_is_the_panels_own_row(self) -> None:
        if self.vision is None:
            self.skipTest("OCR runtime unavailable")
        if not ROWS_SCROLLED.exists():
            self.skipTest(f"evidence frame missing: {ROWS_SCROLLED}")
        rows = {str(row.get("key")): row
                for row in (self.vision.observe(ROWS_SCROLLED).quick_panel or {}).get("rows") or []}
        self.assertEqual(set(rows), {"RESEARCH", "ALLIANCE_DONATION", "HERO_RECRUIT", "MY_REWARDS"})
        research = rows["RESEARCH"]
        self.assertEqual(research["label"], "科技研究")
        self.assertEqual(research["source_word"], "空闲中")
        self.assertEqual(research["status"], "IDLE")
        self.assertEqual(research["control"], "ARROW")
        # The row's own y is the one under its header, 30 px above its state word -- not the rail
        # token's y, which is 0.023 higher and is what the reader used to report.
        self.assertAlmostEqual(research["y_norm"], 0.6293 - 0.308, delta=0.01)
        self.assertNotEqual(research["y_norm"], 0.2977)
        # ...and no row on this frame is named by the rail.
        self.assertNotIn("梦境寻忆", {row["label"] for row in rows.values()})

    def test_a_token_the_panel_did_not_draw_cannot_name_a_row(self) -> None:
        """The same decoy, injected into the synthetic panel: it must not become the row.

        Driven with the archived frame as the image path (so the width the column test needs is real)
        and a fixed token set, with 梦境寻忆 placed at x 553 -- the rail's own x on a 720-wide frame,
        which is beyond the panel's column -- between the 科技研究 header and its row.
        """
        if not ROWS_SCROLLED.exists():
            self.skipTest(f"frame missing: {ROWS_SCROLLED}")
        tokens = PANEL_TOKENS + (_token("梦境寻忆", 553.0, 785.0),)
        panel = read_quick_panel(ROWS_SCROLLED, _NullOCR(tokens))
        rows = {str(row.get("key")): row for row in panel.get("rows") or []}
        self.assertIn("RESEARCH", rows)
        self.assertEqual(rows["RESEARCH"]["label"], "科技研究")
        self.assertEqual(rows["RESEARCH"]["source_word"], "空闲中")
        self.assertEqual(rows["RESEARCH"]["status"], "IDLE")
        # and the decoy's height is not the row's height
        self.assertNotAlmostEqual(rows["RESEARCH"]["y_norm"], 785.0 / 1280, places=3)


if __name__ == "__main__":
    unittest.main()
