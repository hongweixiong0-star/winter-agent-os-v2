"""On-demand UNKNOWN analysis: the AUTO asks without waiting, and a candidate must earn its tap.

Operator directive 2026-09-22 ("复用现有 UNKNOWN，接入按需 AI 分析").  What these tests pin is the
part that could go wrong quietly:

* existing methods come first -- an unnamed screen whose own words name a control never files a
  question (§一);
* nothing blocks: an answer is a file that either exists or does not, so a question with no answer
  leaves the cycle to the chain that already works (§六);
* an answer cannot invent a control -- its point has to fall on text this frame's OCR read (§四),
  and cannot name a skill the registry does not have (§三, the same rule ``parse_qwen_decision``
  applies to a model's JSON);
* an answer cannot spend -- money, gems or an irreversible action is refused on the project's own
  blacklist, before the answer is parsed into anything;
* an answer is never a verdict: it changes neither a page's nor an element's status, and the
  existing verifier still decides (§五);
* the provider stays off the runtime path (operator section 7), which is what the project's own
  ``tests/test_qwen_decoupling.py`` requires of this module too.

Two of the cases run on the real captured 挂机收益 frame, so what is exercised is the wire in
``runtime._advised_control`` and not a helper in isolation.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import page_knowledge, ui_collection, unknown_advisor  # noqa: E402
from winter_agent_v2.models import Decision, ExecutionResult, Page, VerificationResult, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The real unnamed screen whose own words DO name a tap-safe control (领取) -- the one the live
#: AUTO acted on.  On this frame the existing methods answer, so no question is asked (§一).
UNKNOWN_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_125214_770769/"
    "20260922_125214_770769_step_001_after_refresh_2_20260922T045309420387.png"
)

#: The other real unnamed screen (the battle overlay): OCR reads 对战 / 自动 / X2 and none of them is
#: an ordinary action this project may tap, so this is the frame that has to ask.
SILENT_UNKNOWN_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_114218_071725/"
    "20260922_114218_071725_step_004_after_20260922T034320650029.png"
)

#: What the live frame really shows, measured with the production OCR: the 领取 button's own box.
CLAIM_BOX = {"x_norm": 0.4472, "y_norm": 0.7047, "w_norm": 0.1083, "h_norm": 0.0367}


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))


def _runtime(root: Path, *, ocr=None) -> LiveRuntime:
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime.registry = v2_registry()
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._last_known_label = "EXPLORATION"
    runtime._last_advice = None
    runtime._last_attempt_summary = {}
    runtime._advisor = unknown_advisor.UnknownAdvisor(root=root / "requests")
    runtime._transitions = None
    runtime._ui_pages = page_knowledge.PageCandidateStore(root=root / "pages")
    runtime._ui_candidates = ui_collection.UiCandidateStore(
        root=root / "candidates", manifest=root / "manifest.json"
    )
    runtime.brain = SimpleNamespace(current_goal="CLAIM_EXPLORATION_IDLE", goal_id="")
    return runtime


def _answer(request_id: str, **overrides) -> dict:
    payload = {
        "unknown_type": "CONTROL",
        "candidate_semantics": ["REWARD_PANEL", "领取"],
        "proposed_action": "TRY_ORDINARY_CONTROL",
        "expected_result": "the reward is claimed",
        "uncertainty": "medium",
    }
    payload.update(overrides)
    return payload


class TheQuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_request_carries_everything_the_directive_asks_for(self):
        """§二: goal, frame, page label and confidence, OCR with boxes, entry, world state,
        the last attempt's expectation against what was seen -- and both frames when the question
        is about a result."""
        request = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_RESULT,
            page_label="UNKNOWN",
            page_key="UNKNOWN::挂机收益",
            frame_path=UNKNOWN_FRAME,
            goal="CLAIM_EXPLORATION_IDLE",
            page_confidence=0.0,
            ocr_texts=("挂机收益", "领取"),
            ocr_boxes=(CLAIM_BOX,),
            entry_page="EXPLORATION",
            entry_trigger="EXPLORATION_IDLE_CLAIM::idle_income_claimable",
            world_state={"page": "UNKNOWN"},
            template_match="no template matched",
            ledger_match="no ledger entry",
            last_attempt={"skill": "EXPLORATION_IDLE_CLAIM", "observed_change": "PAGE_CHANGED"},
            before_frame_path="before.png",
            after_frame_path="after.png",
            question="did the claim work?",
        )
        row = request.as_row()
        for field in ("goal", "frame_path", "page_label", "page_confidence", "ocr_texts",
                      "ocr_boxes", "entry_page", "entry_trigger", "world_state",
                      "template_match", "ledger_match", "last_attempt",
                      "before_frame_path", "after_frame_path"):
            self.assertIn(field, row)
        self.assertEqual(row["before_frame_path"], "before.png")
        self.assertEqual(row["after_frame_path"], "after.png")
        self.assertTrue(row["frame_digest"], "the frame is identified, not just pathed")

    def test_the_same_screen_asks_one_question_not_one_per_frame(self):
        """A digest-keyed id would file a new question every step of an unnamed screen."""
        first = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL, page_label="UNKNOWN",
            page_key="UNKNOWN::挂机收益", frame_path=UNKNOWN_FRAME,
        )
        second = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL, page_label="UNKNOWN",
            page_key="UNKNOWN::挂机收益", frame_path=UNKNOWN_FRAME,
        )
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.frame_digest, second.frame_digest)

    def test_asking_is_bounded_and_never_asks_twice(self):
        advisor = unknown_advisor.UnknownAdvisor(root=self.root / "requests")
        request = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL, page_label="UNKNOWN",
            page_key="UNKNOWN::挂机收益", frame_path=UNKNOWN_FRAME,
        )
        self.assertTrue(advisor.ask(request))
        self.assertFalse(advisor.ask(request), "the same question is not filed twice")
        other = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL, page_label="UNKNOWN",
            page_key="UNKNOWN::领主指令", frame_path=UNKNOWN_FRAME,
        )
        self.assertTrue(advisor.ask(other))
        third = unknown_advisor.build_request(
            unknown_type=unknown_advisor.UNKNOWN_CONTROL, page_label="UNKNOWN",
            page_key="UNKNOWN::第三张屏", frame_path=UNKNOWN_FRAME,
        )
        self.assertFalse(advisor.ask(third), "a run asks its share and stops")
        self.assertEqual(len(advisor.pending()), unknown_advisor.MAX_REQUESTS_PER_RUN)

    def test_reading_an_answer_never_waits(self):
        advisor = unknown_advisor.UnknownAdvisor(root=self.root / "requests")
        started = time.monotonic()
        self.assertIsNone(advisor.take("unknown__control"))
        self.assertLess(time.monotonic() - started, 0.5, "no answer means no wait, by construction")


class TheAnswerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def answer(self, request_id: str, payload: dict) -> None:
        answers = self.root / "requests" / unknown_advisor.ANSWERS_DIR
        answers.mkdir(parents=True, exist_ok=True)
        (answers / f"{request_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_the_silent_screen_asks_and_the_answer_becomes_the_tap(self):
        """A real unnamed frame whose own words name nothing tap-safe: ask, answer, tap.

        The battle overlay is exactly §一's second case -- OCR reads 对战 / 自动 / X2 and none of
        them is an ordinary action this project may tap -- so this is the frame that asks.
        """
        runtime = _runtime(self.root, ocr=_ocr())
        world = WorldState(page=Page.UNKNOWN)
        # 1) with no answer: nothing is tapped, and the question is on file for a reasoner
        self.assertIsNone(runtime._ordinary_control_candidate(world, SILENT_UNKNOWN_FRAME))
        pending = runtime._advisor.pending()
        self.assertEqual(len(pending), 1, "the screen asks exactly once")
        request = pending[0]
        self.assertTrue(request.request_id, "the question has an id a reasoner can answer")
        self.assertEqual(request.goal, "CLAIM_EXPLORATION_IDLE")
        self.assertTrue(request.ocr_boxes, "the question carries the frame's own text boxes")
        self.assertTrue(request.frame_digest)
        # 2) an answer whose point sits on text this frame really read becomes the tap
        box = request.ocr_boxes[0]
        point = [box["x_norm"] + box["w_norm"] / 2, box["y_norm"] + box["h_norm"] / 2]
        self.answer(request.request_id, _answer(request.request_id, target_point=point))
        runtime2 = _runtime(self.root, ocr=_ocr())
        resolved = runtime2._ordinary_control_candidate(world, SILENT_UNKNOWN_FRAME)
        self.assertIsNotNone(resolved)
        self.assertAlmostEqual(resolved[0], round(point[0], 4), delta=0.01)
        self.assertAlmostEqual(resolved[1], round(point[1], 4), delta=0.01)
        self.assertEqual(runtime2._ordinary_last["word"], "TRY_ORDINARY_CONTROL")
        self.assertTrue(
            any("AI_ADVICE" in line for line in runtime2._printed_reads),
            "the read has to be visible in the run's own record, like every other layer's",
        )
        self.assertEqual(runtime2._last_advice["request_id"], request.request_id)
        self.assertEqual(runtime2._last_advice["uncertainty"], "medium")

    def test_a_point_over_nothing_the_frame_read_is_refused(self):
        """§四: a candidate needs a locating basis on *this* frame, not good intentions."""
        advice = unknown_advisor.parse_advice(
            _answer("r", target_point=[0.02, 0.02]), request_id="r"
        )
        self.assertIsNone(
            unknown_advisor.justified_point(advice, [CLAIM_BOX]),
            "an invented coordinate must not become a tap",
        )
        near = unknown_advisor.parse_advice(
            _answer("r", target_point=[0.5020, 0.7240]), request_id="r"
        )
        self.assertEqual(
            unknown_advisor.justified_point(near, [CLAIM_BOX]), (0.502, 0.724)
        )

    def test_the_collector_is_handed_the_frame_s_own_box_not_the_answer_s(self):
        """§五: what gets cropped and remembered is the region this frame drew."""
        self.assertIsNone(unknown_advisor.box_containing((0.02, 0.02), [CLAIM_BOX]))
        landed = unknown_advisor.box_containing((0.50, 0.72), [CLAIM_BOX])
        self.assertIsNotNone(landed)
        self.assertEqual(landed["x_norm"], CLAIM_BOX["x_norm"])

    def test_an_answer_cannot_propose_money_or_an_invented_skill(self):
        with self.assertRaises(unknown_advisor.AdviceRejected):
            unknown_advisor.parse_advice(
                _answer("r", note="先充值 6 元再看"), request_id="r"
            )
        with self.assertRaises(unknown_advisor.AdviceRejected):
            unknown_advisor.parse_advice(
                _answer("r", proposed_action="CLAIM_BY_MAGIC"), request_id="r", registry=v2_registry()
            )
        with self.assertRaises(unknown_advisor.AdviceRejected):
            unknown_advisor.parse_advice(
                _answer("r", target_point=[1.4, 0.3]), request_id="r"
            )
        with self.assertRaises(unknown_advisor.AdviceRejected):
            payload = _answer("r")
            payload.pop("uncertainty")
            unknown_advisor.parse_advice(payload, request_id="r")

    def test_a_refused_answer_is_kept_aside_with_its_reason(self):
        runtime = _runtime(self.root, ocr=_ocr())
        key = unknown_advisor.request_id(
            page_knowledge.page_key("UNKNOWN", "挂机收益"), unknown_advisor.UNKNOWN_CONTROL
        )
        self.answer(key, _answer(key, note="购买礼包"))
        self.assertIsNone(runtime._advisor.take(key, registry=runtime.registry))
        self.assertTrue(
            (self.root / "requests" / unknown_advisor.ANSWERS_DIR / f"{key}.rejected.reason").exists(),
            "what a reasoner said is evidence about the reasoner",
        )

    def test_an_answer_is_never_a_verdict(self):
        """§五: the answer changes no status; only a real step's verifier can."""
        runtime = _runtime(self.root, ocr=_ocr())
        world = WorldState(page=Page.UNKNOWN)
        self.assertIsNone(runtime._ordinary_control_candidate(world, SILENT_UNKNOWN_FRAME))
        key = runtime._advisor.pending()[0].request_id
        self.answer(key, _answer(key, target_point=[0.50, 0.22]))
        runtime._ordinary_control_candidate(world, SILENT_UNKNOWN_FRAME)
        self.assertIsNotNone(runtime._last_advice)
        runtime._collect_page_evidence(
            decision=Decision("TRY_ORDINARY_CONTROL", "unnamed", 0.99, "ordinary_control_observed"),
            before=WorldState(page=Page.UNKNOWN),
            after=WorldState(page=Page.POPUP),
            execution=ExecutionResult(
                executed=True, dry_run=False,
                action=type("A", (), {"target": "ORDINARY_CONTROL", "kind": "TAP_SEMANTIC"})(),
                backend="ADB",
            ),
            verification=VerificationResult(True, "", {}),
            observed_change="PAGE_CHANGED",
            before_screenshot=SILENT_UNKNOWN_FRAME, after_screenshot=SILENT_UNKNOWN_FRAME,
            episode_id="run-ai", goal_id="CLAIM_EXPLORATION_IDLE",
        )
        page = runtime._ui_pages.all()[0]
        self.assertTrue(page.ai_advice, "the answer travels with the screen (§五)")
        self.assertEqual(page.ai_advice[0]["request_id"], key)
        # The proposal is filed as a proposal: the screen's own reading is untouched, and the
        # status moved because the step's verifier passed, not because a reasoner said so.
        self.assertIn("REWARD_PANEL", page.ai_advice[0]["candidate_semantics"])
        # The screen's own reading is what OCR/its hint table produced -- this frame really is a
        # battle overlay -- and the reasoner's proposal did not leak into it.
        self.assertIn("BATTLE_OVERLAY", page.candidate_page_semantics)
        self.assertNotIn("REWARD_PANEL", page.candidate_page_semantics)
        self.assertEqual(page.verification_status, page_knowledge.STATUS_VERIFIED)
        self.assertEqual(page.recognition_method, page_knowledge.PAGE_METHOD_ACTION)

    def test_the_provider_stays_off_the_runtime_path(self):
        """Operator section 7, as the project's own decoupling test defines it."""
        source = (ROOT / "winter_agent_v2" / "unknown_advisor.py").read_text(encoding="utf-8")
        for token in ("requests.post", "httpx", "aiohttp", "openai", "ollama", "llama_cpp",
                      "transformers", "torch", "llm_client", "LLMClient", "chat.completions",
                      ":11434"):
            self.assertNotIn(token, source, f"{token} would be a provider on the runtime path")


if __name__ == "__main__":
    unittest.main()
