"""Automatic UI collection: candidates, statuses, and what may become a template.

Operator directive 2026-09-22 ("自动 UI 元素采集、验证与模板入库").  These tests pin the parts
that decide whether the collector is honest:

* a crop is not an element (a record is ``DISCOVERED``/``CANDIDATE`` until a real step proves it);
* a page that changed is not a task that succeeded -- promotion and ingestion both require the
  step's **own verifier** to have passed;
* the same icon on two pages stays two records, because the page is in the key;
* a countdown inside the crop disqualifies a template (it would match today and rot tomorrow);
* a protected record for the same semantic is never overwritten; the candidate keeps its
  evidence and reports the conflict;
* the development store cannot roll back what the AUTO learned: ``prune`` never drops a
  ``VERIFIED`` record.

The end-to-end case runs the real hook on a real captured frame, so what is tested is the wire
in ``runtime._collect_ui_evidence`` and not a helper in isolation.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ui_collection  # noqa: E402
from winter_agent_v2.models import Decision, ExecutionResult, Page, VerificationResult, WorldState  # noqa: E402
from winter_agent_v2.models import Action  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

#: A real live frame, already used elsewhere in the suite: 720x1280, with the training page's
#: three camp tabs and the running queue on it.
FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_123407_610951/"
    "20260922_123407_610951_step_011_after_refresh_2_20260922T043904261212.png"
)


def _store(root: Path, manifest: Path) -> ui_collection.UiCandidateStore:
    return ui_collection.UiCandidateStore(root=root, manifest=manifest)


class BoxAndTextTests(unittest.TestCase):
    def test_the_element_box_is_padded_and_clipped_to_the_frame(self):
        box = ui_collection.element_box(
            {"x_norm": 0.02, "y_norm": 0.5, "w_norm": 0.05, "h_norm": 0.02}, frame=(720, 1280)
        )
        self.assertEqual(box["x_norm"], 0.0)                 # clipped at the left edge
        self.assertGreater(box["w_norm"], 0.05)              # padded
        self.assertLessEqual(box["x_norm"] + box["w_norm"], 1.0)

    def test_a_strip_too_small_to_be_a_control_is_refused(self):
        self.assertIsNone(
            ui_collection.element_box(
                {"x_norm": 0.5, "y_norm": 0.5, "w_norm": 0.0, "h_norm": 0.0},
                pad=(0.0005, 0.0005),
                frame=(720, 1280),
            )
        )

    def test_a_countdown_in_the_text_disqualifies_a_template(self):
        self.assertTrue(ui_collection.carries_dynamic_text(["原始时间：03:28:53"]))
        self.assertTrue(ui_collection.carries_dynamic_text(["2,786/9,306"]))
        self.assertFalse(ui_collection.carries_dynamic_text(["领取", "前往"]))


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manifest = base / "template_manifest.json"
        self.manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        self.store = _store(base / "candidates", self.manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, page="TRAINING", semantic="TRAINING_CAMP_NEXT", x=0.5, y=0.9):
        return self.store.stage(
            frame_path=FRAME,
            page=page,
            semantic=semantic,
            box_norm={"x_norm": x, "y_norm": y, "w_norm": 0.05, "h_norm": 0.02},
            ocr_text="矛兵营",
            recognition_method=ui_collection.METHOD_OCR_WORD,
        )

    def test_both_crops_and_metadata_are_written(self):
        record = self.stage()
        self.assertIsNotNone(record)
        directory = Path(self.store.root) / record.candidate_id
        self.assertTrue((directory / "element.png").exists())
        self.assertTrue((directory / "context.png").exists())
        self.assertTrue((directory / "metadata.yaml").exists())
        text = (directory / "metadata.yaml").read_text(encoding="utf-8")
        for field in ("candidate_id", "semantic_id", "page", "bbox", "recognition_method",
                      "verification_status", "created_at"):
            self.assertIn(field, text)
        self.assertEqual(record.verification_status, ui_collection.STATUS_CANDIDATE)

    def test_the_context_crop_is_larger_than_the_element(self):
        record = self.stage()
        from PIL import Image

        with Image.open(record.image_path) as element, Image.open(record.context_image_path) as context:
            self.assertGreater(context.size[0], element.size[0])
            self.assertGreater(context.size[1], element.size[1])

    def test_the_same_element_twice_is_one_candidate(self):
        first = self.stage()
        second = self.stage()
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(len(self.store.all()), 1)

    def test_the_same_icon_on_another_page_is_another_candidate(self):
        self.stage(page="TRAINING")
        self.stage(page="HOME")
        self.assertEqual(len(self.store.all()), 2)

    def test_an_unlocatable_named_control_is_recorded_without_a_crop(self):
        record = self.store.stage_unlocated(
            page="POPUP", semantic="POPUP_GENERIC_REWARD_HEADER", episode="run1"
        )
        self.assertEqual(record.verification_status, ui_collection.STATUS_DISCOVERED)
        self.assertEqual(record.failure_count, 1)
        self.assertEqual(record.image_path, "")
        self.assertIn("no crop", record.notes)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manifest = base / "template_manifest.json"
        self.manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        self.store = _store(base / "candidates", self.manifest)
        self.record = self.store.stage(
            frame_path=FRAME,
            page="TRAINING",
            semantic="TRAINING_CAMP_NEXT",
            box_norm={"x_norm": 0.5, "y_norm": 0.9, "w_norm": 0.05, "h_norm": 0.02},
            ocr_text="矛兵营",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_failed_attempt_is_counted_and_named_failed_not_forever(self):
        self.store.record_attempt(page="TRAINING", semantic="TRAINING_CAMP_NEXT", verified=False)
        self.assertEqual(self.record.verification_status, ui_collection.STATUS_FAILED)
        self.assertEqual(self.record.failure_count, 1)
        # And one later success still promotes it: a single unresponsive tap is not a disproof.
        self.store.record_attempt(page="TRAINING", semantic="TRAINING_CAMP_NEXT", verified=True)
        self.assertEqual(self.record.verification_status, ui_collection.STATUS_VERIFIED)
        self.assertEqual(self.record.success_count, 1)

    def test_only_a_passed_verifier_promotes(self):
        touched = self.store.record_attempt(
            page="TRAINING", semantic="TRAINING_CAMP_NEXT", verified=False,
            observed_effect="PAGE_CHANGED",
        )
        self.assertEqual(len(touched), 1)
        self.assertNotEqual(self.record.verification_status, ui_collection.STATUS_VERIFIED)

    def test_a_candidate_for_another_page_is_untouched(self):
        self.store.record_attempt(page="HOME", semantic="TRAINING_CAMP_NEXT", verified=True)
        self.assertEqual(self.record.attempt_count, 0)


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manifest = base / "template_manifest.json"
        self.manifest.write_text(json.dumps({"records": [], "count": 0}), encoding="utf-8")
        self.store = _store(base / "candidates", self.manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def candidate(self, *, semantic="BTN_TEST_CONTROL", ocr_text="领取", page="EVENT"):
        record = self.store.stage(
            frame_path=FRAME,
            page=page,
            semantic=semantic,
            box_norm={"x_norm": 0.5, "y_norm": 0.5, "w_norm": 0.06, "h_norm": 0.03},
            ocr_text=ocr_text,
        )
        return record

    def test_an_unverified_candidate_is_not_written_to_the_manifest(self):
        record = self.candidate()
        ok, reason = self.store.ingest(record)
        self.assertFalse(ok)
        self.assertEqual(reason, "NOT_VERIFIED")
        self.assertEqual(json.loads(self.manifest.read_text(encoding="utf-8"))["records"], [])

    def test_a_verified_candidate_lands_in_the_manifest_with_its_region(self):
        record = self.candidate()
        self.store.record_attempt(page="EVENT", semantic="BTN_TEST_CONTROL", verified=True)
        ok, reason = self.store.ingest(record)
        self.assertTrue(ok, reason)
        rows = json.loads(self.manifest.read_text(encoding="utf-8"))["records"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["semantic"], "BTN_TEST_CONTROL")
        self.assertEqual(row["roi_norm"], record.bbox)
        self.assertEqual(row["status"], "VERIFIED")
        self.assertTrue(Path(row["template_path"]).exists())
        self.assertEqual(row["source"], record.source_frame)

    def test_a_countdown_inside_the_crop_blocks_ingestion(self):
        record = self.candidate(ocr_text="03:28:53")
        self.store.record_attempt(page="EVENT", semantic="BTN_TEST_CONTROL", verified=True)
        ok, reason = self.store.ingest(record, ocr_text="03:28:53")
        self.assertFalse(ok)
        self.assertEqual(reason, "DYNAMIC_REGION")

    def test_a_protected_record_for_the_same_semantic_is_never_overwritten(self):
        protected = {
            "semantic": "BTN_TEST_CONTROL",
            "template_path": "dataset/candidate/templates/reviewed.png",
            "roi_norm": {"x_norm": 0.1, "y_norm": 0.1, "w_norm": 0.1, "h_norm": 0.05},
            "status": "VERIFIED",
            "template_id": "reviewed_one",
        }
        self.manifest.write_text(json.dumps({"records": [protected], "count": 1}), encoding="utf-8")
        record = self.candidate()
        self.store.record_attempt(page="EVENT", semantic="BTN_TEST_CONTROL", verified=True)
        ok, reason = self.store.ingest(record)
        self.assertFalse(ok)
        self.assertEqual(reason, "CONFLICT_WITH_VERIFIED")
        rows = json.loads(self.manifest.read_text(encoding="utf-8"))["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["template_id"], "reviewed_one")

    def test_ingestion_is_idempotent(self):
        record = self.candidate()
        self.store.record_attempt(page="EVENT", semantic="BTN_TEST_CONTROL", verified=True)
        self.assertTrue(self.store.ingest(record)[0])
        ok, reason = self.store.ingest(record)
        self.assertFalse(ok)
        self.assertEqual(reason, "ALREADY_REGISTERED")


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manifest = base / "template_manifest.json"
        self.manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        self.store = _store(base / "candidates", self.manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def test_prune_drops_the_unproven_and_keeps_the_verified(self):
        verified = self.store.stage(
            frame_path=FRAME, page="TRAINING", semantic="KEEP_ME",
            box_norm={"x_norm": 0.5, "y_norm": 0.9, "w_norm": 0.05, "h_norm": 0.02},
        )
        self.store.record_attempt(page="TRAINING", semantic="KEEP_ME", verified=True)
        for index in range(6):
            self.store.stage(
                frame_path=FRAME, page="EVENT", semantic=f"THROW_AWAY_{index}",
                box_norm={"x_norm": 0.1 + index * 0.02, "y_norm": 0.4, "w_norm": 0.05, "h_norm": 0.02},
            )
        dropped = self.store.prune(limit=3)
        self.assertTrue(dropped)
        self.assertIn(verified.candidate_id, [record.candidate_id for record in self.store.all()])
        self.assertEqual(self.store.counts()[ui_collection.STATUS_VERIFIED], 1)


class RuntimeHookTests(unittest.TestCase):
    """The wire, run against a real frame: what the runtime hands the collector."""

    def setUp(self):
        if not FRAME.exists():
            self.skipTest("the live capture was pruned by the retention policy")
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manifest = base / "template_manifest.json"
        self.manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        self.store = _store(base / "candidates", self.manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def _runtime(self):
        runtime = object.__new__(LiveRuntime)
        runtime._ui_candidates = self.store
        runtime._printed_boxes = {}
        runtime.vision = object()
        runtime.semantic_vision = object()
        return runtime

    def collect(self, runtime, *, executed=True, error=None, verified=True, change="PAGE_CHANGED",
                printed_box=None, semantic="BTN_DISMISS_INTEL_REWARD", page=Page.POPUP):
        action = Action("TAP_SEMANTIC", semantic)
        execution = ExecutionResult(
            executed=executed, dry_run=False, action=action, error=error,
            backend="ADB" if executed else "",
        )
        if printed_box is not None:
            runtime._printed_boxes[f"{page.value}|{semantic}"] = {
                "box_norm": printed_box, "word": "点击任意位置继续", "confidence": 0.985,
            }
        runtime._collect_ui_evidence(
            decision=Decision("DISMISS_SHARED_REWARD", "test", 0.99, "popup_closed"),
            before=WorldState(page=page),
            after=WorldState(page=page),
            execution=execution,
            verification=VerificationResult(verified, "" if verified else "POPUP_CLOSE_NOT_PROVEN", {}),
            observed_change=change,
            before_screenshot=FRAME,
            after_screenshot=FRAME,
            episode_id="test_run",
            goal_id="KEEP_TRAINING_PRODUCTIVE",
        )

    def test_an_unlocatable_named_control_becomes_a_discovered_record(self):
        self.collect(self._runtime(), executed=False, error="SEMANTIC_TARGET_NOT_VERIFIED")
        records = self.store.all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].verification_status, ui_collection.STATUS_DISCOVERED)
        self.assertEqual(records[0].semantic_id, "BTN_DISMISS_INTEL_REWARD")
        self.assertEqual(records[0].page, "POPUP")

    def test_a_printed_locator_that_worked_is_cropped_named_and_verified(self):
        runtime = self._runtime()
        self.collect(runtime, printed_box={"x_norm": 0.31, "y_norm": 0.95, "w_norm": 0.37, "h_norm": 0.018})
        records = self.store.all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].verification_status, ui_collection.STATUS_VERIFIED)
        self.assertEqual(records[0].recognition_method, ui_collection.METHOD_OCR_WORD)
        self.assertEqual(records[0].ocr_text, "点击任意位置继续")
        self.assertTrue(Path(records[0].image_path).exists())
        # ...and a template, because its own verifier passed
        self.assertEqual(records[0].template_version.startswith("auto__"), True)
        rows = json.loads(self.manifest.read_text(encoding="utf-8"))["records"]
        self.assertEqual(rows[0]["template_id"], records[0].template_version)

    def test_a_page_change_without_a_passed_verifier_is_not_a_success(self):
        runtime = self._runtime()
        self.collect(
            runtime, verified=False, change="PAGE_CHANGED",
            printed_box={"x_norm": 0.31, "y_norm": 0.95, "w_norm": 0.37, "h_norm": 0.018},
        )
        record = self.store.all()[0]
        self.assertEqual(record.verification_status, ui_collection.STATUS_FAILED)
        self.assertEqual(record.template_version, "")
        self.assertEqual(json.loads(self.manifest.read_text(encoding="utf-8"))["records"], [])

    def test_the_same_step_repeated_does_not_multiply_records(self):
        runtime = self._runtime()
        box = {"x_norm": 0.31, "y_norm": 0.95, "w_norm": 0.37, "h_norm": 0.018}
        self.collect(runtime, printed_box=box)
        self.collect(runtime, printed_box=box)
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(self.store.all()[0].attempt_count, 2)


class PlainControlScanTests(unittest.TestCase):
    """The collector's positive source: ordinary action words nobody has written down.

    Operator §二.3/§十.  Uses a stub OCR so the assertion is about the *rule* (exact match, a
    confidence floor, and never re-collecting a word the dictionary already declares) rather than
    about whichever words happen to be on one capture.
    """

    class _OCR:
        def __init__(self, *tokens):
            self._tokens = tokens

        def recognize(self, image_path, roi=None):
            from winter_agent_v2.ocr import OCRResult, OCRToken

            return OCRResult(
                tuple(
                    OCRToken(text=text, confidence=conf, box=box) for text, conf, box in self._tokens
                ),
                "stub",
            )

    BOX = ((100.0, 1000.0), (160.0, 1000.0), (160.0, 1024.0), (100.0, 1024.0))

    def test_a_new_action_word_becomes_a_candidate_row(self):
        ocr = self._OCR(("领取", 0.99, self.BOX))
        found = ui_collection.find_plain_controls(FRAME, ocr)
        self.assertEqual([row["word"] for row in found], ["领取"])
        self.assertGreater(found[0]["box_norm"]["w_norm"], 0.0)

    def test_a_word_the_dictionary_already_declares_is_not_re_collected(self):
        ocr = self._OCR(("领取", 0.99, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr, skip_words=["领取"]), [])

    def test_a_low_confidence_reading_is_not_staged(self):
        ocr = self._OCR(("领取", 0.62, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr), [])

    def test_a_substring_is_not_an_exact_control_word(self):
        """``我的城镇`` must not be harvested as ``城镇`` -- the same rule the tap path uses."""
        ocr = self._OCR(("我的城镇", 0.99, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr), [])

    def test_a_non_action_word_is_ignored(self):
        ocr = self._OCR(("等级", 0.99, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr), [])


class RuntimeHookScanTests(unittest.TestCase):
    """The scan as the runtime drives it: bounded per run, and staged with its uncertainty kept."""

    def setUp(self):
        if not FRAME.exists():
            self.skipTest("the live capture was pruned by the retention policy")
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.manifest = base / "template_manifest.json"
        self.manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        self.store = _store(base / "candidates", self.manifest)

    def tearDown(self):
        self.tmp.cleanup()

    def _runtime(self, words=("领取",)):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        class OCR:
            def recognize(self, image_path, roi=None):
                return OCRResult(
                    tuple(
                        OCRToken(
                            text=word, confidence=0.99,
                            box=((100.0, 1000.0), (160.0, 1000.0), (160.0, 1024.0), (100.0, 1024.0)),
                        )
                        for word in words
                    ),
                    "stub",
                )

        runtime = object.__new__(LiveRuntime)
        runtime.vision = type("V", (), {"ocr": OCR()})()
        runtime.semantic_vision = None
        runtime._ui_candidates = self.store
        runtime._printed_boxes = {}
        runtime._ui_scans = 0
        return runtime

    def test_a_scanned_word_is_staged_as_an_unconfirmed_candidate(self):
        runtime = self._runtime()
        # Stand on a sampled step: the hook counts steps and scans every UI_SCAN_STRIDE-th one.
        runtime._ui_steps_seen = ui_collection.UI_SCAN_STRIDE - 1
        runtime._collect_printed_controls(
            store=self.store, frame=FRAME, page="EVENT", goal="DAILY_ACTIVITY_TARGET",
            episode_id="run1", skip_words=(),
        )
        records = self.store.all()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.verification_status, ui_collection.STATUS_DISCOVERED)
        self.assertEqual(record.semantic_id, "")
        self.assertEqual(record.semantic_candidates, ("OCR:EVENT:领取",))
        self.assertEqual(record.ocr_text, "领取")
        self.assertTrue(Path(record.image_path).exists())

    def test_the_scan_is_bounded_per_run(self):
        runtime = self._runtime()
        for step in range(1, 60):
            runtime._ui_steps_seen = step - 1
            runtime._collect_printed_controls(
                store=self.store, frame=FRAME, page="EVENT", goal="G", episode_id="r", skip_words=(),
            )
        # One candidate per (page, word, picture) however many times the scan is offered, and the
        # budget caps the OCR passes -- both matter, and the first is what the directory proves.
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(runtime._ui_scans, ui_collection.MAX_SCANS_PER_RUN)

    def test_the_budget_is_spread_across_the_run_not_spent_on_its_first_steps(self):
        """Measured 2026-09-22: the informative frames sat at steps 22-24, so a budget spent up
        front collected nothing.  The stride is what makes the samples land there."""
        runtime = self._runtime()
        scanned_at = []
        original = runtime._collect_printed_controls

        real_store = self.store

        class Recording(ui_collection.UiCandidateStore):
            def stage(self, **kwargs):  # type: ignore[override]
                scanned_at.append(runtime._ui_steps_seen)
                return None

        runtime._ui_candidates = Recording(root=real_store.root, manifest=real_store.manifest)
        for step in range(1, 30):
            runtime._ui_steps_seen = step - 1
            original(
                store=runtime._ui_candidates, frame=FRAME, page="EVENT", goal="G",
                episode_id="r", skip_words=(),
            )
        self.assertEqual(scanned_at[:ui_collection.MAX_SCANS_PER_RUN],
                         [ui_collection.UI_SCAN_STRIDE * (index + 1)
                          for index in range(ui_collection.MAX_SCANS_PER_RUN)])
        # The last sample must still be inside a normal run's length, or the budget would be
        # spent before the frame that matters: measured 2026-09-22, the new control sat at step 24.
        self.assertLessEqual(ui_collection.UI_SCAN_STRIDE * ui_collection.MAX_SCANS_PER_RUN, 24)

    def test_a_declared_word_is_never_staged_again(self):
        runtime = self._runtime()
        runtime._ui_steps_seen = ui_collection.UI_SCAN_STRIDE - 1
        runtime._collect_printed_controls(
            store=self.store, frame=FRAME, page="EVENT", goal="G", episode_id="r",
            skip_words=["领取"],
        )
        self.assertEqual(self.store.all(), [])


if __name__ == "__main__":
    unittest.main()
