"""The semantic dictionary's incremental upgrade, and the code that has to read it.

Operator directive 2026-09-22 ("语义词典增量升级与未知控件自动学习").  Item 一 is the rule these tests
exist for: a field added to the JSON must have a reader in production code, or it is decoration.

What is pinned here:

* every existing record keeps its mandatory keys, and the optional fields stay optional -- a record
  without them must load and behave exactly as before;
* dynamic OCR has left the fixed identity of a control (no countdown, no troop count), while the
  stable word that really identifies the button is still there to be matched;
* the quick panel handle is registered as a *hypothesis*: both of its states are marked unverified,
  because the only capture this project owns does not confirm the triangle;
* the four consumers work on the real capture of the expanded panel: ``position_hint`` locates a
  row's own arrow, ``states`` refuses the handle while the panel already satisfies its target,
  ``related_goals`` widens the interactivity judgement, and ``expected_transition`` is what an L1
  step records as its expectation;
* a row's navigation arrow is identified by the row it is on -- never by matching one blue arrow
  against another -- and an arrow's presence is never read as "idle".
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ui_collection  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
    find_printed_words,
    read_quick_panel,
)
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

DICTIONARY = ROOT / "knowledge/ui/semantic_dictionary.json"

#: The one real capture of the expanded 快捷面板 this project owns.
PANEL_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260921_213506_694242/"
    "20260921_213506_694242_step_001_before_20260921T133510479855.png"
)
#: A real frame where the client draws the training button's own label, used to prove the button is
#: still identifiable after the countdown was taken out of its identity.
TRAIN_BUTTON_FRAME = ROOT / "dataset/raw/live_train_selection_available.png"

MANDATORY = ("id", "type", "cn", "ocr", "pages", "target_state", "actions")
OPTIONAL = (
    "visual_features",
    "position_hint",
    "preconditions",
    "states",
    "expected_transition",
    "verification",
    "related_goals",
)
DYNAMIC = re.compile(r"^\d[\d:.,%]*$|^\d{1,2}:\d{2}:\d{2}$|^\d{1,4}天?$")


def _dictionary() -> dict:
    return json.loads(DICTIONARY.read_text(encoding="utf-8"))


def _ocr():
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _runtime(*, ocr=None, goal="KEEP_TRAINING_PRODUCTIVE"):
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._l1_context = None
    runtime._ui_candidates = None
    runtime._transitions = None
    runtime.brain = SimpleNamespace(current_goal=goal)
    runtime.capture_dir = PANEL_FRAME.parent
    return runtime


class DictionaryStructureTests(unittest.TestCase):
    """Item 二: additive, optional, and nothing existing lost."""

    def setUp(self):
        self.payload = _dictionary()
        self.records = self.payload["records"]

    def test_every_record_keeps_its_mandatory_keys_and_the_ids_are_unique(self):
        ids = [record["id"] for record in self.records]
        self.assertEqual(len(ids), len(set(ids)), "an id may appear once")
        for record in self.records:
            for key in MANDATORY:
                self.assertIn(key, record, f"{record.get('id')} lost {key}")

    def test_the_optional_fields_really_are_optional(self):
        """Most records carry none of them, and that has to stay a valid record."""
        without = [r for r in self.records if not any(k in r for k in OPTIONAL)]
        self.assertTrue(without, "the file is not supposed to be all-new-fields")
        self.assertTrue(all(r.get("id") for r in without))

    def test_no_control_identity_carries_a_dynamic_value(self):
        """Item 三, applied to the whole file rather than to the two records that were reported."""
        offenders = []
        for record in self.records:
            for word in record.get("ocr") or ():
                text = str(word or "").strip()
                if text and DYNAMIC.match(text):
                    offenders.append((record["id"], text))
        self.assertEqual(offenders, [], "a countdown or a value cannot be part of a control")

    def test_the_reported_records_were_cleaned_and_kept_identifiable(self):
        by_id = {record["id"]: record for record in self.records}
        self.assertEqual(by_id["BTN_START_TRAINING"]["ocr"], ["训练"])
        self.assertEqual(by_id["STATUS_TRAINING_IN_PROGRESS"]["ocr"], ["训练中"])
        # The button must still be findable by the word that stays.
        self.assertIn("训练", by_id["BTN_START_TRAINING"]["ocr"])

    def test_the_training_button_is_still_located_on_a_real_frame(self):
        """Item 三's caution: cleaning the field must not lose the control.

        Measured on ``dataset/raw/live_train_selection_available.png``, where the client draws the
        training button's own label: the removed countdown never took part in finding it, which is
        the whole point of separating the two.
        """
        hit = find_printed_words(TRAIN_BUTTON_FRAME, ("训练",), _ocr())
        self.assertIsNotNone(hit, "训练 has to remain matchable where the client prints it")
        self.assertGreaterEqual(float(hit["confidence"]), 0.9)
        # And the values that were taken out of the identity are still recorded, just not as identity.
        by_id = {record["id"]: record for record in _dictionary()["records"]}
        self.assertIn("10:03:12", by_id["BTN_START_TRAINING"].get("ocr_dynamic") or [])
        self.assertNotIn("10:03:12", by_id["BTN_START_TRAINING"]["ocr"])

    def test_the_handle_is_measured_but_its_action_is_not(self):
        """Both appearances are measured now; the *tap* is still unproven, and the record says so.

        This test replaces one that asserted the opposite, and the correction is the point of it:
        the operator's message of 2026-09-22 ("我用红色圈起来的地方就是快捷面板把手") supplied the
        collapsed appearance the project had never captured, so ``UNVERIFIED``/``NEVER_SEEN`` stopped
        being the truth.  What must NOT drift is the other half: the appearance being measured says
        nothing about whether pressing it opens the panel, so the status stays CANDIDATE and
        ``tap_to_open`` has to admit it.
        """
        record = {r["id"]: r for r in self.records}["QUICK_PANEL_HANDLE"]
        self.assertEqual(record["status"], "CANDIDATE", "the appearance is measured; the action is not")
        self.assertEqual(set(record["states"]), {"EXPANDED", "COLLAPSED"})
        self.assertEqual(record["position_hint"]["basis"], "SCREEN_EDGE_RELATIVE")
        self.assertIn("EDGE", record["position_hint"]["anchor"].upper())
        for state in ("EXPANDED", "COLLAPSED"):
            self.assertTrue(
                record["visual_features"][state]["confirmed_by_measurement"],
                f"{state} was measured on a real frame",
            )
            self.assertIn("MEASURED", str(record["verification"][state]).upper())
        self.assertIn("NOT YET VERIFIED", str(record["verification"]["tap_to_open"]).upper())
        # And every measurement names the frame it came from, because that is what makes it checkable.
        for state in ("EXPANDED", "COLLAPSED"):
            self.assertTrue(record["visual_features"][state]["measured_on"])
        self.assertTrue(
            record["visual_features"]["COLLAPSED"]["cross_checked_on"].endswith(
                "dataset/raw/reference/quick_panel_handle_collapsed_20260922.jpg"
            ),
            "the operator's own frame is the cross-check, and it is kept in the repository",
        )
        self.assertEqual(record["locator"]["reader"], "ocr.find_quick_panel_handle")
        self.assertEqual(str(record["risk"]).upper(), "LOW")


class PanelReadingTests(unittest.TestCase):
    """Item 四/五 on the real capture: the rows, and the arrows that belong to them."""

    @classmethod
    def setUpClass(cls):
        cls.ocr_service = _ocr()
        cls.panel = read_quick_panel(PANEL_FRAME, cls.ocr_service)

    def test_the_panel_reports_its_state_its_rows_and_its_handle(self):
        self.assertTrue(self.panel.get("open"))
        self.assertEqual(self.panel["handle"]["state"], "EXPANDED")
        # The handle's point is measured, not estimated: the estimate put it at (0.3708, 0.2779),
        # the middle of the panel, while the tab with its left-pointing triangle is at
        # (0.6431, 0.4301).  A tap from the estimate would have hit the panel's own content.
        self.assertEqual(self.panel["handle"]["basis"], "HANDLE_TRIANGLE_SCAN")
        self.assertAlmostEqual(self.panel["handle"]["point_norm"][0], 0.6431, places=3)
        keys = [row["key"] for row in self.panel["rows"]]
        self.assertEqual(keys, ["SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP", "RESEARCH"])
        # The three bottom-navigation words must not have become research rows (measured failure).
        self.assertNotIn("野外", [row["label"] for row in self.panel["rows"]])
        self.assertNotIn("英雄", [row["label"] for row in self.panel["rows"]])

    def test_each_row_carries_its_own_y_and_the_arrow_that_belongs_to_it(self):
        rows = {row["key"]: row for row in self.panel["rows"]}
        self.assertAlmostEqual(rows["SHIELD_CAMP"]["y_norm"], 0.427, delta=0.02)
        self.assertAlmostEqual(rows["LANCER_CAMP"]["y_norm"], 0.484, delta=0.02)
        self.assertAlmostEqual(rows["MARKSMAN_CAMP"]["y_norm"], 0.541, delta=0.02)
        # On this capture the three barracks are 已完成, so the client draws its green tick where the
        # enter-arrow otherwise is -- and the button is located by the white chevron it draws inside
        # (see ocr._panel_button_chevron).  No chevron therefore means no point to hand an executor,
        # which is the right answer for a finished row and is asserted below rather than assumed.
        self.assertEqual({rows[k]["control"] for k in
                          ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP")}, {"DONE"})
        for key in ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP"):
            with self.subTest(row=key):
                self.assertIsNone(rows[key].get("arrow_box_norm"),
                                  f"{key}: a 已完成 row draws no enter-arrow")
                self.assertEqual(rows[key]["arrow_basis"], "PANEL_RELATIVE_ESTIMATE", key)
        # 科技研究 is 空闲中 and does draw one.  Measured 2026-09-23 against this capture: the point
        # 0.5618 is the button's own centre (its cyan spans x 384-425) and the box it reports is the
        # button's own extent, 0.0569 of the frame wide -- 41 px.  Before the chevron locator the same
        # reader reported 0.539-0.749 for it, a box two to seven times too wide and centre 0.644, both
        # of which were the search band reaching 155 px of blue city past the panel's edge.
        research = rows["RESEARCH"]
        self.assertEqual(research["control"], "ARROW")
        self.assertEqual(research["arrow_basis"], "ROW_BUTTON_SCAN")
        box = research["arrow_box_norm"]
        self.assertIsNotNone(box, "RESEARCH: a located button must report its own box")
        self.assertLessEqual(box["w_norm"], 0.07, "one widget, one width")
        self.assertGreaterEqual(research["arrow_norm"][0], box["x_norm"], "RESEARCH")
        self.assertLessEqual(research["arrow_norm"][0], box["x_norm"] + box["w_norm"], "RESEARCH")
        for key, row in rows.items():
            self.assertEqual(row["arrow_norm"][1], row["y_norm"], key)

    def test_a_row_is_never_called_idle_because_it_has_an_arrow(self):
        """Item 五's prohibition, stated as a property of the reading itself.

        The row's status comes from the word under it and from nothing else; the arrow is only
        located.  On this capture all three barracks are 已完成 while a research arrow would still
        be drawn, so a reader that used arrow presence would call them busy.
        """
        for row in self.panel["rows"]:
            self.assertIn(row["status"], ("IDLE", "IN_PROGRESS"))
            self.assertEqual(
                row["status"],
                "IDLE" if row["source_word"] in ("已完成", "空闲中") else "IN_PROGRESS",
            )
        self.assertEqual({row["key"]: row["status"] for row in self.panel["rows"]}[
            "LANCER_CAMP"], "IDLE")


class DictionaryConsumerTests(unittest.TestCase):
    """Item 一/六: the four fields, each with the production reader that uses it."""

    @classmethod
    def setUpClass(cls):
        cls.ocr_service = _ocr()
        cls.panel = read_quick_panel(PANEL_FRAME, cls.ocr_service)
        cls.world = WorldState(page=Page.MAP, quick_panel=cls.panel)

    def test_the_records_are_readable_and_the_expectation_is_consumed(self):
        runtime = _runtime(ocr=self.ocr_service)
        self.assertEqual(len(runtime._semantic_records()), len(_dictionary()["records"]))
        self.assertEqual(runtime._declared_expectation("BTN_START_TRAINING"), "TRAINING_STARTED")
        self.assertEqual(runtime._declared_expectation("NOT_A_RECORD_AT_ALL"), "")

    def test_related_goals_add_goal_vocabulary(self):
        runtime = _runtime(ocr=self.ocr_service)
        words = runtime._declared_goal_words("KEEP_TRAINING_PRODUCTIVE")
        self.assertIn("训练", words)
        self.assertIn("矛兵", words)
        self.assertEqual(runtime._declared_goal_words(""), ())

    def test_related_goals_widen_the_interactivity_judgement(self):
        """A word the dictionary ties to the goal is relevant even without a table entry."""
        from winter_agent_v2.ocr import OCRResult, OCRToken

        class _StubOCR:
            def recognize(self, image_path, roi=None):
                return OCRResult(
                    (
                        OCRToken(
                            text="矛兵磨练",
                            confidence=0.99,
                            box=((300.0, 900.0), (420.0, 900.0), (420.0, 940.0), (300.0, 940.0)),
                        ),
                    ),
                    "stub",
                )

        stub = _StubOCR()
        without = ui_collection.interactive_controls(
            PANEL_FRAME, stub, skip_words=(), goal="KEEP_MARCHES_PRODUCTIVE"
        )
        self.assertFalse([row for row in without if row["goal_relevant"]])
        with_hints = ui_collection.interactive_controls(
            PANEL_FRAME,
            stub,
            skip_words=(),
            goal="KEEP_MARCHES_PRODUCTIVE",
            hints=("矛兵",),
        )
        self.assertTrue([row for row in with_hints if row["goal_relevant"]])

    def test_position_hint_locates_the_row_asked_for_and_no_other(self):
        runtime = _runtime(ocr=self.ocr_service)
        spearman = runtime._dictionary_hint("QUICK_PANEL_ROW_LANCER_CAMP", self.world, PANEL_FRAME)
        archer = runtime._dictionary_hint("QUICK_PANEL_ROW_MARKSMAN_CAMP", self.world, PANEL_FRAME)
        self.assertIsNotNone(spearman)
        self.assertIsNotNone(archer)
        self.assertAlmostEqual(spearman[1], 0.4836, delta=0.02)
        self.assertAlmostEqual(archer[1], 0.541, delta=0.02)
        self.assertNotAlmostEqual(spearman[1], archer[1], places=2)
        # Each row's arrow is located from that row's own button, so the two need not share an exact x.
        # What they must share is the panel's button column: measured on the device the button spans
        # x 0.539-0.749 on every row, and the located centres differ by <=0.03.
        self.assertLess(abs(spearman[0] - archer[0]), 0.06, "both arrows live in the panel's own column")
        self.assertTrue(
            [line for line in runtime._printed_reads if "ROW_RELATIVE" in line],
            "the basis has to be visible in the run, like every other read",
        )

    def test_a_range_hint_resolves_to_its_centre(self):
        runtime = _runtime(ocr=self.ocr_service)
        point = runtime._dictionary_hint("QUICK_PANEL_TAB_CITY", self.world, PANEL_FRAME)
        self.assertIsNotNone(point)
        self.assertAlmostEqual(point[0], (0.125 + 0.196) / 2, delta=0.005)
        self.assertAlmostEqual(point[1], 0.212, delta=0.005)

    def test_the_handle_is_refused_while_the_panel_already_satisfies_its_target(self):
        """Item 四's guard, consuming ``states``: expanded means read, not toggle."""
        runtime = _runtime(ocr=self.ocr_service)
        self.assertIsNone(runtime._dictionary_hint("QUICK_PANEL_HANDLE", self.world, PANEL_FRAME))
        # And the same record with the other state declared is *not* refused -- the refusal is the
        # state's, not the control's.
        collapsed = WorldState(
            page=Page.MAP,
            quick_panel={"handle": {"state": "COLLAPSED", "point_norm": [0.03, 0.5], "basis": "x"}},
        )
        self.assertEqual(
            runtime._dictionary_hint("QUICK_PANEL_HANDLE", collapsed, PANEL_FRAME), (0.03, 0.5)
        )

    def test_a_hint_is_never_used_for_a_page_the_record_excludes(self):
        runtime = _runtime(ocr=self.ocr_service)
        elsewhere = WorldState(page=Page.TRAINING, quick_panel=self.panel)
        self.assertIsNone(runtime._dictionary_hint("QUICK_PANEL_ROW_LANCER_CAMP", elsewhere, PANEL_FRAME))


if __name__ == "__main__":
    unittest.main()
