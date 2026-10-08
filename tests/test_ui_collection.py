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
from unittest import mock

from PIL import Image  # noqa: E402

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


class _StubOCR:
    """One canned token list in the shape the OCR readers consume.

    Module level rather than a nested class: ``tools/check_wiring.py`` reads ``self.<Name>(...)``
    as a call to a method of the enclosing class and reports a dangling self-call, which is the
    right hunt for production code and a false positive on a test helper.
    """

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

    def test_the_manifest_record_carries_the_printed_label_it_was_filed_under(self):
        """The identity the registry is keyed by must not be dropped on the way in.

        Measured 2026-10-02: 31 verified, auto-collected manifest records with 31 distinct
        semantics, against 3 labels in ``knowledge/ui/icon_label_controls.json`` -- the file
        ``composite_controls`` reads to decide whether a printed word names a control.  The
        registry is keyed by the client's printed word and the manifest is keyed by semantic, and
        the label was the only thing that could join them; ``ingest`` received it (it needs it for
        the dynamic-text check) and then did not write it down.  The consequence is measured on
        real frames: the TAP_SEMANTIC resolver locates ``REGULAR_EVENT_ENTRY`` while the planner's
        element table on that same frame offers the model no executable element at all.

        Its own frame rather than ``FRAME``: the retention sweep empties old ``runtime_auto`` run
        directories, and that fixture has already been collected (all six tests in
        ``IngestionTests`` fail on it with ``'NoneType' object has no attribute
        'verification_status'``).  A fixture that the product deletes cannot be a fixture.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            frame = base / "frame.png"
            Image.new("RGB", (720, 1280), (20, 30, 40)).save(frame)
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"records": [], "count": 0}), encoding="utf-8")
            store = _store(base / "candidates", manifest)
            record = store.stage(
                frame_path=frame, page="HOME", semantic="REGULAR_EVENT_ENTRY",
                box_norm={"x_norm": 0.5, "y_norm": 0.5, "w_norm": 0.06, "h_norm": 0.03},
                ocr_text="常规活动",
            )
            self.assertIsNotNone(record, "the synthetic frame could not support a candidate")
            store.record_attempt(page="HOME", semantic="REGULAR_EVENT_ENTRY", verified=True)
            ok, reason = store.ingest(record, ocr_text="常规活动")
            self.assertTrue(ok, reason)
            row = json.loads(manifest.read_text(encoding="utf-8"))["records"][0]
            self.assertEqual(row.get("ocr_text"), "常规活动")


class UnnamedPageOfferTests(unittest.TestCase):
    """An unnamed page must not be used to exclude every registered control.

    Measured 2026-10-08 on one real frame (720x1280), changing nothing but the ``page`` argument
    to ``build_element_table``:

        page='UNKNOWN' -> executable_count 0
        page=''        -> executable_count 2
        page='HOME'    -> executable_count 2

    Every record in ``icon_label_controls.json`` carries a ``pages`` list, so on a screen the
    reader could not name, the list excluded all of them and the element table offered the
    planner no pressable element at all -- which is why ``EXECUTE`` had not been produced since
    2026-09-30, and why no unknown screen could ever be advanced.  The same frame with the
    filter relaxed produced ``EXECUTE`` + ``CLICK_ELEMENT`` from the local model on the first
    call.

    What must NOT change: a page with a name keeps the filter exactly as it was.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frame = Path(self.tmp.name) / "frame.png"
        Image.new("RGB", (720, 1280), (20, 30, 40)).save(self.frame)
        self.label_box = {"x_norm": 0.05, "y_norm": 0.96, "w_norm": 0.07, "h_norm": 0.03}
        self.measured = {
            "box_norm": dict(self.label_box),
            "icon_box_norm": None,
            "label_box_norm": dict(self.label_box),
            "basis": "TEMPLATE_LABEL_ON_CONTROL",
            "confidence": 0.99,
            "detail": {},
        }
        self.registry = {
            "探险": {
                "label": "探险", "semantic": "NAV[探险]", "pages": ["MAP"],
                "relation": "label_is_the_control",
                "template_path": "knowledge/ui/icon_templates/登录好礼.png",
                "source": "TEST",
            },
        }

    def _controls(self, page: str):
        region = {"text": "探险", "box_norm": dict(self.label_box),
                  "basis": "OCR_BOX", "score": 0.99, "detail": {}}
        with mock.patch.object(ui_collection, "grounding_regions", lambda *_a, **_k: [region]), \
             mock.patch.object(ui_collection, "registered_control_region",
                               lambda *_a, **_k: dict(self.measured)):
            return ui_collection.composite_controls(
                self.frame, ocr=None, page=page, registry=self.registry,
            )

    def test_an_unnamed_page_still_offers_the_registered_control(self):
        for page in ("UNKNOWN", "UNKNOWN::使用", "UNKNOWN::对战"):
            found = self._controls(page)
            self.assertEqual([c["text"] for c in found], ["探险"],
                             f"{page!r} offered no control; this is the unknown-screen blackhole")
            self.assertEqual(found[0]["kind"], ui_collection.ELEMENT_INTERACTIVE_CONTROL)

    def test_a_named_page_keeps_the_filter_it_had(self):
        self.assertEqual(self._controls("EVENT"), [],
                         "a record that belongs to MAP must still be excluded on EVENT")
        self.assertEqual([c["text"] for c in self._controls("MAP")], ["探险"])

    def test_page_is_unnamed_reads_the_reader_admitting_it(self):
        for page in ("UNKNOWN", "unknown", " UNKNOWN::使用 "):
            self.assertTrue(ui_collection.page_is_unnamed(page))
        for page in ("HOME", "MAP", "EVENT", ""):
            self.assertFalse(ui_collection.page_is_unnamed(page))


class UnnamedPageTemplateSourcesTests(unittest.TestCase):
    """The same rule at the two places that decide which *templates* are searched.

    ``composite_controls`` was one member of a family.  These two gate the evidence the grounding
    pool is built from -- collected candidate crops and L1 experience crops -- and they used the
    identical test: ``record_page != wanted``.  On a screen named UNKNOWN that excluded every
    record, so the pool had no template regions at all and a textless control could never be
    grounded, however well the model named it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.frame = base / "source_frame.png"
        Image.new("RGB", (720, 1280), (40, 50, 60)).save(self.frame)
        self.box = {"x_norm": 0.10, "y_norm": 0.20, "w_norm": 0.08, "h_norm": 0.05}

    def _candidate(self, page: str):
        from types import SimpleNamespace

        return SimpleNamespace(page=page, image_path=self.frame, bbox=dict(self.box),
                               semantic_id="BTN_TEST")

    def _experience(self, page: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            page=page, control="BTN_TEST",
            visual_features={"box_norm": dict(self.box), "read_from_frame": str(self.frame)},
        )

    def test_an_unnamed_page_still_offers_collected_and_measured_templates(self):
        candidates = ui_collection.template_entries_from_candidates(
            [self._candidate("HOME")], page="UNKNOWN")
        self.assertEqual(len(candidates), 1,
                         "a crop collected on HOME was excluded by a page name that is not a page")
        experiences = ui_collection.template_entries_from_experience(
            [self._experience("HOME")], page="UNKNOWN",
            cache_dir=Path(self.tmp.name) / "crops",
        )
        self.assertEqual(len(experiences), 1,
                         "an L1 crop measured on HOME was excluded by an unnamed page")

    def test_the_whole_library_is_offered_not_its_first_four(self):
        """The cap used to be 4, which is a fixed prefix of a library that now holds 199 records.

        Measured 2026-10-08 on one real frame: the first four eligible records were one ALLIANCE
        crop, then two with no image at all, then one HOME crop -- so the pool was built from two
        crops belonging to other screens, and ``template_regions`` measured **0** regions on that
        frame. Lifting the cap measured 6 regions, at 439 ms against a model call of 44-69 s.

        The bound belongs to ``template_regions`` (which stops at 6 and breaks out), not to a
        fixed prefix here, which is why the default is now "every eligible record" and the
        parameter survives only for a caller that deliberately wants a cap.
        """
        records = [self._candidate("HOME") for _ in range(9)]
        self.assertEqual(
            len(ui_collection.template_entries_from_candidates(records, page="UNKNOWN")), 9,
            "every eligible record must be offered; a fixed prefix silently ignores the library")
        self.assertEqual(
            len(ui_collection.template_entries_from_candidates(
                records, page="UNKNOWN", limit=4)), 4,
            "an explicit cap must still be honoured")

    def test_a_named_page_still_excludes_another_named_page(self):
        self.assertEqual(
            ui_collection.template_entries_from_candidates(
                [self._candidate("HOME")], page="EVENT"),
            [], "a crop collected on HOME must still not be evidence about EVENT")
        self.assertEqual(
            ui_collection.template_entries_from_experience(
                [self._experience("HOME")], page="EVENT",
                cache_dir=Path(self.tmp.name) / "crops2"),
            [])


class RegisteredTextButtonTests(unittest.TestCase):
    """A registered ``label_is_the_control`` word is a control with no crop at all.

    The measured need, from learning/local_planner_steps.jsonl: on page ``UNKNOWN::城墙`` the
    local model answered ``{"decision":"EXECUTE","action":{"type":"CLICK_ELEMENT",
    "target_element_id":"E16"},"reason":"…点击升级按钮即可推进。"}`` -- correct -- and was refused
    with ``PLAN_TARGET_IS_NOT_A_CONTROL: E16 is TEXT_LABEL``.  That refusal accounts for 50 of the
    58 in the ledger: the table could not type a printed button as a control.

    The crop route was measured and rejected before this: the manifest's verified
    ``BTN_BUILD_UPGRADE`` crop contains the button's own countdown (which this project disqualifies
    a template for) and scores at most 0.2864 over 75 real frames against a 0.7 threshold -- it
    matches nothing, not even the button.  ``label_is_the_control`` needs no crop: the region is
    the box this frame's OCR measured for the word, so nothing stored is a coordinate.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frame = Path(self.tmp.name) / "frame.png"
        Image.new("RGB", (720, 1280), (20, 30, 40)).save(self.frame)
        self.label_box = {"x_norm": 0.42, "y_norm": 0.68, "w_norm": 0.10, "h_norm": 0.03}

    def _region(self, text: str) -> dict:
        return {"text": text, "box_norm": dict(self.label_box),
                "basis": "OCR_BOX", "score": 0.99, "detail": {}}

    def _controls(self, record: dict, text: str):
        with mock.patch.object(ui_collection, "grounding_regions",
                               lambda *_a, **_k: [self._region(text)]):
            return ui_collection.composite_controls(
                self.frame, ocr=None, page="UNKNOWN", registry={text: record})

    def test_a_self_relation_needs_no_crop(self):
        found = self._controls({
            "label": "升级", "semantic": "BTN_BUILD_UPGRADE",
            "relation": ui_collection.RELATION_SELF, "source": "TEST",
        }, "升级")
        self.assertEqual([c["text"] for c in found], ["升级"])
        self.assertEqual(found[0]["box_norm"], self.label_box,
                         "the control region must be this frame's own label box")
        self.assertEqual(found[0]["kind"], ui_collection.ELEMENT_INTERACTIVE_CONTROL)
        self.assertEqual(found[0]["detail"]["source"], "LABEL_BOX_IS_THE_CONTROL")

    def test_an_above_relation_still_needs_its_crop(self):
        """The relaxation is scoped to the relation that claims it, and to nothing else."""
        found = self._controls({
            "label": "登录好礼", "semantic": "CONTROL[登录好礼]",
            "relation": ui_collection.RELATION_ABOVE, "source": "TEST",
        }, "登录好礼")
        self.assertEqual(found, [],
                         "a control_directly_above_label record with no crop must stay unlocated")


class TheSpeedupPanelTests(unittest.TestCase):
    """The model was right about the screen, and the record was missing.

    Measured from ``learning/local_planner_steps.jsonl`` (2026-10-08T03:31:49Z), the live reply on
    the 士兵训练加速 panel was::

        {"decision": "EXECUTE", "action": {"type": "CLICK_ELEMENT", "target_element_id": "E16"},
         "expected": {"result": "training_completed"},
         "reason": "Goal is to keep building productive; '一键使用' (Use All) is the only executable
                    control to apply boosts and finish training"}

    -- it named the control in English *and* Chinese -- and the contract answered
    ``PLAN_TARGET_IS_NOT_A_CONTROL: E16 is TEXT_LABEL``.  Rebuilding the table on that exact frame
    (located by image digest) with the registry as it then stood reproduces the ledger's own
    ``element_count 16 / executable_count 0``, and E16 on it really is ``一键使用``.

    So ``一键使用`` and ``使用`` are registered as ``label_is_the_control``.  ``立即完成`` is on the
    same panel and is **refused on purpose**: it prints a gem cost (8,292 there, 15,699 on 城墙) and
    ``OPERATIONAL.md`` puts 大额宝石 in the Strict tier.  Both halves are asserted here, because a
    test that only pins the additions would let the next pass add the gem button as a "sibling".
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.frame = Path(self.tmp.name) / "frame.png"
        Image.new("RGB", (720, 1280), (20, 30, 40)).save(self.frame)
        self.label_box = {"x_norm": 0.42, "y_norm": 0.68, "w_norm": 0.10, "h_norm": 0.03}

    def _table(self, text: str) -> list[dict]:
        """The production table for a frame whose only printed word is ``text``."""
        region = {"text": text, "box_norm": dict(self.label_box),
                  "basis": "OCR_BOX", "score": 0.99, "detail": {}}
        with mock.patch.object(ui_collection, "grounding_regions", lambda *_a, **_k: [region]):
            return ui_collection.build_element_table(
                self.frame, ocr=None, page="UNKNOWN::使用")

    def test_the_word_the_refusal_named_is_now_a_control(self):
        row = next(r for r in self._table("一键使用") if r["text"] == "一键使用")
        self.assertEqual(row["kind"], ui_collection.ELEMENT_INTERACTIVE_CONTROL)
        self.assertTrue(row["executable"])
        self.assertEqual(row["semantic"], "BTN_USE_ALL_ITEMS")
        self.assertEqual(row["box_norm"], self.label_box,
                         "the region must be this frame's own label box, never a stored position")

    def test_its_sibling_on_the_same_panel_is_a_control_too(self):
        row = next(r for r in self._table("使用") if r["text"] == "使用")
        self.assertEqual(row["kind"], ui_collection.ELEMENT_INTERACTIVE_CONTROL)
        self.assertTrue(row["executable"])

    def test_the_two_are_separate_keys_so_neither_stands_in_for_the_other(self):
        """The match is an equality on the printed word, so ``使用`` must not match ``一键使用``."""
        payload = json.loads(
            (ui_collection.PROJECT_ROOT / ui_collection.ICON_CONTROL_REGISTRY).read_text(
                encoding="utf-8"))
        controls = payload["controls"]
        self.assertIn("使用", controls)
        self.assertIn("一键使用", controls)
        self.assertNotEqual(controls["使用"]["semantic"], controls["一键使用"]["semantic"])

        rows = self._table("一键使用")
        offered = [r["text"] for r in rows
                   if r["kind"] == ui_collection.ELEMENT_INTERACTIVE_CONTROL]
        self.assertEqual(offered, ["一键使用"],
                         "a frame printing only 一键使用 must offer exactly that one control")

        # Two rows for the one word, and that is the table's design rather than a duplicate: the
        # resolved control comes first so a label-grounded answer lands on the control's region, and
        # the raw text row stays behind it, marked executable *because* this frame measured a control
        # for it (``build_element_table``'s own ``control_labels``). Asserted so the shape is not
        # mistaken for a bug by the next reader -- and so it cannot silently become three rows.
        same_word = [r for r in rows if r["text"] == "一键使用"]
        self.assertEqual([r["kind"] for r in same_word],
                         [ui_collection.ELEMENT_INTERACTIVE_CONTROL, ui_collection.ELEMENT_TEXT_LABEL])
        self.assertTrue(all(r["executable"] for r in same_word))

    def test_the_gem_button_is_not_registered_and_the_reason_is_on_file(self):
        row = next(r for r in self._table("立即完成") if r["text"] == "立即完成")
        self.assertEqual(row["kind"], ui_collection.ELEMENT_TEXT_LABEL)
        self.assertFalse(row["executable"], "a large gem spend must stay unpressable")

        payload = json.loads(
            (ui_collection.PROJECT_ROOT / ui_collection.ICON_CONTROL_REGISTRY).read_text(
                encoding="utf-8"))
        self.assertNotIn("立即完成", payload["controls"])
        refused = {item["label"]: item for item in payload.get("refused_on_purpose") or []}
        self.assertIn("立即完成", refused,
                      "an absent record must say why it is absent, or the next pass re-adds it")
        self.assertIn("宝石", refused["立即完成"]["reason"])


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

    BOX = ((100.0, 1000.0), (160.0, 1000.0), (160.0, 1024.0), (100.0, 1024.0))

    def test_a_new_action_word_becomes_a_candidate_row(self):
        ocr = _StubOCR(("领取", 0.99, self.BOX))
        found = ui_collection.find_plain_controls(FRAME, ocr)
        self.assertEqual([row["word"] for row in found], ["领取"])
        self.assertGreater(found[0]["box_norm"]["w_norm"], 0.0)

    def test_a_word_the_dictionary_already_declares_is_not_re_collected(self):
        ocr = _StubOCR(("领取", 0.99, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr, skip_words=["领取"]), [])

    def test_a_low_confidence_reading_is_not_staged(self):
        ocr = _StubOCR(("领取", 0.62, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr), [])

    def test_a_substring_is_not_an_exact_control_word(self):
        """``我的城镇`` must not be harvested as ``城镇`` -- the same rule the tap path uses."""
        ocr = _StubOCR(("我的城镇", 0.99, self.BOX))
        self.assertEqual(ui_collection.find_plain_controls(FRAME, ocr), [])

    def test_a_non_action_word_is_ignored(self):
        ocr = _StubOCR(("等级", 0.99, self.BOX))
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

    def test_every_step_is_scanned_and_the_cap_is_only_a_safety_valve(self):
        """Measured: a cold pass is 0.31 s against steps 20-40 s apart, so coverage is every step.

        The ration was tried twice and missed both times -- two frames per run, then every fourth
        step -- so what this pins is that the policy is now coverage, with the cap far above any
        real run's step count.
        """
        self.assertEqual(ui_collection.UI_SCAN_EVERY_STEP, 1)
        self.assertGreaterEqual(ui_collection.MAX_SCANS_PER_RUN, 24)
        runtime = self._runtime()
        for _ in range(30):
            runtime._collect_printed_controls(
                store=self.store, frame=FRAME, page="EVENT", goal="G", episode_id="r", skip_words=(),
            )
        # One candidate per (page, word, picture) however many times the scan is offered...
        self.assertEqual(len(self.store.all()), 1)
        # ...and the counter stops climbing at the cap, so the valve still works.
        self.assertEqual(runtime._ui_scans, min(30, ui_collection.MAX_SCANS_PER_RUN))

    def test_a_declared_word_is_never_staged_again(self):
        runtime = self._runtime()
        runtime._collect_printed_controls(
            store=self.store, frame=FRAME, page="EVENT", goal="G", episode_id="r",
            skip_words=["领取"],
        )
        self.assertEqual(self.store.all(), [])


if __name__ == "__main__":
    unittest.main()
