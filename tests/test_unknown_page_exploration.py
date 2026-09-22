"""Unknown pages: understood as far as the frame allows, kept, and acted on when it is safe.

Operator directive 2026-09-22 ("未知页面自主探索与页面知识自动入库").  These tests pin the seven
acceptance points, and every one of them runs against a **real captured frame** rather than a
hand-made situation:

* ``Page.UNKNOWN`` no longer refuses every ordinary control -- the brain keeps the goal and asks
  for one bounded attempt, and the resolver answers from the frame;
* the unnamed screen is kept: its frame, its candidate title, its controls with boxes, what it
  was entered from, and the candidate semantics;
* a second visit folds into the same record instead of starting over (§六);
* two unnamed screens with different titles stay two records (§九's rule, applied to pages);
* a control working on a screen does not verify the *screen's* semantics (§四);
* a learned transition (`before page -> control -> action -> after page`) is read back by the
  resolver, which prefers the control that really worked and skips one that did nothing (§五/§七);
* when the frame names nothing, the answer is still ``SAFE_STOP unknown_page`` -- the bounded Back
  recovery's own entry -- so an unknown screen can never become an infinite wait (§六/§七).

The screen used here is the one the live AUTO actually got stuck on: tapping the exploration
panel's idle button opened 挂机收益 on 2026-09-22T04:53Z, the page model could not name it, and 31
recorded steps failed with ``EXPLORATION_IDLE_DIALOG_NOT_PROVEN`` while the reward sat on screen.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import page_knowledge  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import (  # noqa: E402
    Action,
    Decision,
    ExecutionResult,
    Page,
    VerificationResult,
    WorldState,
)
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The real unnamed screen: 720x1280, 挂机收益 with 领取, ✕ and the client's own footer line.
#: Captured live on 2026-09-22, run 20260922_125214_770769, and referenced by an episode (so the
#: retention pass keeps it).
UNKNOWN_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_125214_770769/"
    "20260922_125214_770769_step_001_after_refresh_2_20260922T045309420387.png"
)

#: A second unnamed screen, captured the same day: the battle overlay (对战), reached from a march.
#: Different title, different screen -- which is what keeps the two apart in every key.
SECOND_UNKNOWN_FRAME = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260922_114218_071725/"
    "20260922_114218_071725_step_004_after_20260922T034320650029.png"
)

#: Where the client drew 领取 on UNKNOWN_FRAME, measured with the production OCR.  The resolver's
#: answer is asserted against it at ~1% of the frame: the point has to be read off the live frame,
#: not remembered.
CLAIM_POINT = (0.5014, 0.723)


def _ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(
        ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    )


class _StubOCR:
    """A canned token list, at module level so ``check_wiring`` sees no dangling self-call."""

    def __init__(self, *tokens):
        self._tokens = tokens

    def recognize(self, image_path, roi=None):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=conf, box=box) for text, conf, box in self._tokens),
            "stub",
        )


BOX = ((100.0, 1000.0), (160.0, 1000.0), (160.0, 1024.0), (100.0, 1024.0))
#: A stub title box in the band the title reader accepts (cy 0.172, height 40 px on 720x1280),
#: so a stubbed screen can be keyed by its title exactly as the real one is.
TITLE_BOX = ((400.0, 200.0), (520.0, 200.0), (520.0, 240.0), (400.0, 240.0))


def _runtime(*, ocr=None, pages=None, transitions=None, brain=None) -> LiveRuntime:
    """A runtime with the pieces these tests exercise, and **no production store**.

    The two collection stores are created under a throw-away directory when the caller does not
    pass one, and that is deliberate rather than tidy: ``LiveRuntime._page_store`` creates the
    real ``knowledge/perception/pages`` on demand, so a test that drives the hook without saying
    where to write would file its own frame as knowledge the AUTO had learned.  Measured -- the
    first version of this file did exactly that.
    """
    root = Path(tempfile.mkdtemp(prefix="unknown_page_test_"))
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = {}
    runtime._remembered_reuse = []
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._last_known_label = ""
    runtime.brain = brain or RuleBrain(current_goal="CLAIM_EXPLORATION_IDLE")
    runtime._ui_pages = (
        pages if pages is not None else page_knowledge.PageCandidateStore(root=root / "pages")
    )
    runtime._transitions = (
        transitions if transitions is not None else page_knowledge.TransitionLedger(path=root / "t.json")
    )
    return runtime


# ---------------------------------------------------------------------------
# §一/§三: an unnamed page does not refuse every ordinary operation
# ---------------------------------------------------------------------------


class UnnamedPageKeepsTheGoalTests(unittest.TestCase):
    def test_an_unnamed_page_with_a_named_goal_asks_for_one_ordinary_attempt(self):
        brain = RuleBrain(current_goal="CLAIM_EXPLORATION_IDLE")
        decision = brain.decide(WorldState(page=Page.UNKNOWN), v2_registry())
        self.assertEqual(decision.skill, "TRY_ORDINARY_CONTROL")
        self.assertIn("unnamed_page", decision.reason)
        self.assertEqual(decision.expected_result, "ordinary_control_observed")

    def test_without_a_goal_the_old_honest_answer_stands(self):
        """No goal means nothing to advance, so there is nothing a tap could be for."""
        brain = RuleBrain(current_goal=None)
        decision = brain.decide(WorldState(page=Page.UNKNOWN), v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "unknown_page")

    def test_the_attempt_budget_is_shared_between_named_and_unnamed_pages(self):
        """A bound that doubled on unknown pages would just be an exploration loop with a budget."""
        brain = RuleBrain(current_goal="CLAIM_EXPLORATION_IDLE")
        decisions = [
            brain.decide(WorldState(page=Page.UNKNOWN), v2_registry()).skill
            for _ in range(brain.MAX_ORDINARY_ATTEMPTS + 3)
        ]
        self.assertEqual(decisions.count("TRY_ORDINARY_CONTROL"), brain.MAX_ORDINARY_ATTEMPTS)
        # And then the screen is handed to the runtime's bounded recovery, not tapped again.
        self.assertEqual(decisions[-1], "SAFE_STOP")

    def test_a_frame_that_names_nothing_stops_the_asking_for_this_run(self):
        brain = RuleBrain(current_goal="CLAIM_EXPLORATION_IDLE")
        brain.ordinary_scan_exhausted = True
        decision = brain.decide(WorldState(page=Page.UNKNOWN), v2_registry())
        self.assertEqual((decision.skill, decision.reason), ("SAFE_STOP", "unknown_page"))

    def test_the_real_unnamed_dialog_names_its_own_claim_button(self):
        """The measured case: UNKNOWN, and 领取 read straight off the client's own frame."""
        runtime = _runtime(ocr=_ocr())
        point = runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), UNKNOWN_FRAME)
        self.assertIsNotNone(point, "an unnamed screen must not refuse a control the client drew")
        self.assertAlmostEqual(point[0], CLAIM_POINT[0], delta=0.01)
        self.assertAlmostEqual(point[1], CLAIM_POINT[1], delta=0.01)
        self.assertEqual(runtime._ordinary_last["word"], "领取")
        # The read is visible in the run's own record, keyed by the screen and not just "UNKNOWN".
        self.assertTrue(runtime._printed_reads)
        self.assertIn("UNKNOWN::挂机收益", runtime._printed_reads[0])

    def test_a_screen_that_cannot_be_tapped_still_refuses(self):
        runtime = _runtime(ocr=_ocr())
        for page in (Page.MAINTENANCE, Page.LOADING):
            self.assertIsNone(
                runtime._ordinary_control_candidate(WorldState(page=page), UNKNOWN_FRAME),
                f"{page} must not be tapped however ordinary the word on it looks",
            )

    def test_the_spend_blacklist_still_vetoes_an_unnamed_page(self):
        """§一's boundary: an unnamed screen is not a licence to walk into a purchase dialog."""
        ocr = _StubOCR(("领取", 0.99, BOX), ("特惠", 0.98, BOX))
        runtime = _runtime(ocr=ocr)
        self.assertIsNone(
            runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), UNKNOWN_FRAME)
        )


# ---------------------------------------------------------------------------
# §四: the unnamed screen is kept
# ---------------------------------------------------------------------------


class TheScreenItselfIsKeptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = page_knowledge.PageCandidateStore(root=Path(self.tmp.name) / "pages")
        self.runtime = _runtime(ocr=_ocr(), pages=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self, frame=UNKNOWN_FRAME, *, verified=True, goal="CLAIM_EXPLORATION_IDLE"):
        self.runtime._collect_page_evidence(
            decision=Decision("EXPLORATION_IDLE_CLAIM", "test", 0.99, "idle_income_claimed"),
            before=WorldState(page=Page.EXPLORATION, confidence=0.97),
            after=WorldState(page=Page.UNKNOWN),
            execution=ExecutionResult(
                executed=True, dry_run=False, action=Action("TAP_SEMANTIC", "BTN_EXPLORATION_IDLE_CLAIM"),
                backend="ADB",
            ),
            verification=VerificationResult(verified, "" if verified else "NOT_PROVEN", {}),
            observed_change="PAGE_CHANGED",
            before_screenshot=frame,
            after_screenshot=frame,
            episode_id="run1",
            goal_id=goal,
        )

    def test_the_real_unnamed_screen_is_kept_with_its_reading(self):
        self.collect()
        pages = self.store.all()
        self.assertEqual(len(pages), 1)
        page = pages[0]
        self.assertEqual(page.page_key, "UNKNOWN::挂机收益")
        self.assertEqual(page.title, "挂机收益")
        self.assertGreater(page.title_confidence, 0.95)
        self.assertEqual(page.entry_page, "EXPLORATION")
        self.assertIn("EXPLORATION_IDLE_CLAIM", page.entry_trigger)
        self.assertIn("REWARD_PANEL", page.candidate_page_semantics)
        # The client's own controls, with their boxes -- not a guess about them.
        by_text = {item["text"]: item for item in page.controls}
        self.assertEqual(by_text["领取"]["kind"], "ACTION")
        self.assertEqual(by_text["X"]["kind"], "CLOSE_GLYPH")
        self.assertIn("box_norm", by_text["领取"])
        # And the frame itself, copied out of the prunable tree.
        picture = Path(page.page_image_path)
        self.assertTrue(picture.exists())
        self.assertEqual(picture.name, "page.png")

    def test_the_second_visit_folds_into_the_same_record(self):
        """§六: the same screen again must not start from zero -- or copy its picture again."""
        self.collect()
        first = self.store.all()[0]
        self.collect(verified=False)
        pages = self.store.all()
        self.assertEqual(len(pages), 1)
        same = pages[0]
        self.assertEqual(same.page_candidate_id, first.page_candidate_id)
        self.assertEqual(same.attempt_count, 2)
        self.assertEqual(same.failure_count, 1)
        self.assertEqual(same.success_count, 1)

    def test_an_action_result_moves_the_status_but_not_the_semantics(self):
        """§四: "页面与元素分别管理验证状态" -- a control working does not name the screen."""
        self.collect()
        self.collect()
        page = self.store.all()[0]
        self.assertEqual(page.verification_status, page_knowledge.STATUS_VERIFIED)
        self.assertEqual(page.recognition_method, page_knowledge.PAGE_METHOD_ACTION)
        self.assertEqual(page.candidate_page_semantics, ("DICTIONARY_PAGE:EXPLORATION", "REWARD_PANEL"))

    def test_two_unnamed_screens_with_different_titles_stay_two_records(self):
        """§九's rule ("不同页面下的同形图标必须保留独立语义记录") applied to the pages themselves."""
        self.collect()
        self.collect(frame=SECOND_UNKNOWN_FRAME)
        keys = {page.page_key for page in self.store.all()}
        self.assertEqual(len(keys), 2, keys)
        self.assertIn("UNKNOWN::挂机收益", keys)

    def test_a_named_page_is_not_staged(self):
        """A screen the model can name already has a better identifier than a picture."""
        self.runtime._collect_page_evidence(
            decision=Decision("OPEN_MAP", "test", 0.99, "map_open"),
            before=WorldState(page=Page.HOME, confidence=0.98),
            after=WorldState(page=Page.MAP, confidence=0.97),
            execution=ExecutionResult(
                executed=True, dry_run=False, action=Action("TAP_SEMANTIC", "BTN_OPEN_MAP"), backend="ADB"
            ),
            verification=VerificationResult(True, "", {}),
            observed_change="PAGE_CHANGED",
            before_screenshot=UNKNOWN_FRAME,
            after_screenshot=UNKNOWN_FRAME,
            episode_id="run2",
            goal_id="OPEN_MAP",
        )
        self.assertEqual(self.store.all(), [])


# ---------------------------------------------------------------------------
# §五/§六/§七: transitions are learned and reused
# ---------------------------------------------------------------------------


def _ledger(tmp: Path) -> page_knowledge.TransitionLedger:
    return page_knowledge.TransitionLedger(path=tmp / "page_transitions.json")


class TransitionLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = _ledger(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_hook_records_the_transition_it_measured(self):
        """The whole production sequence for this screen: resolve on the unnamed page, then record."""
        runtime = _runtime(ocr=_ocr(), transitions=self.ledger)
        point = runtime._ordinary_control_candidate(WorldState(page=Page.UNKNOWN), UNKNOWN_FRAME)
        self.assertIsNotNone(point, "the frame names 领取, so the step has something to do")
        runtime._collect_page_evidence(
            decision=Decision("TRY_ORDINARY_CONTROL", "ordinary", 0.99, "ordinary_control_observed"),
            before=WorldState(page=Page.UNKNOWN),
            after=WorldState(page=Page.EXPLORATION, confidence=0.97),
            execution=ExecutionResult(
                executed=True, dry_run=False, action=Action("TAP_SEMANTIC", "ORDINARY_CONTROL"), backend="ADB"
            ),
            verification=VerificationResult(True, "", {}),
            observed_change="PAGE_CHANGED",
            before_screenshot=UNKNOWN_FRAME,
            after_screenshot=UNKNOWN_FRAME,
            episode_id="run3",
            goal_id="CLAIM_EXPLORATION_IDLE",
        )
        rows = self.ledger.rows_for("UNKNOWN", "挂机收益")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.control, "ORDINARY_CONTROL[领取]")
        self.assertEqual(row.after_page, "EXPLORATION")
        self.assertTrue(row.verified)
        self.assertEqual(row.observed_change, "PAGE_CHANGED")

    def test_a_verified_transition_out_of_named_pages_is_reachable_by_page(self):
        self.ledger.record(
            before_page="EXPLORATION", control="BTN_EXPLORATION_IDLE_CLAIM",
            after_page="UNKNOWN", verified=True, skill="EXPLORATION_IDLE_CLAIM",
        )
        self.assertEqual(
            self.ledger.preferred_controls("EXPLORATION"), ["BTN_EXPLORATION_IDLE_CLAIM"]
        )
        # A named page is keyed by its label alone: the title is what separates unnamed screens,
        # and a page the model can name does not need it.
        self.assertEqual(
            self.ledger.rows_for("EXPLORATION", "挂机收益"),
            self.ledger.rows_for("EXPLORATION"),
        )

    def test_the_resolver_prefers_what_worked_and_skips_what_did_nothing(self):
        """§五/§六/§七.3, in one read: proven first, discredited dropped, all measured on the frame."""
        self.ledger.record(
            before_page=page_knowledge.UNKNOWN_LABEL, before_title="挂机收益",
            control="ORDINARY_CONTROL[签到]", after_page="EXPLORATION", verified=True,
            skill="TRY_ORDINARY_CONTROL",
        )
        self.ledger.record(
            before_page=page_knowledge.UNKNOWN_LABEL, before_title="挂机收益",
            control="ORDINARY_CONTROL[领取]", after_page="", verified=False,
            skill="TRY_ORDINARY_CONTROL",
        )
        # A frame carrying the screen's own title plus both words: 签到 is what the ledger says
        # worked here, 领取 is what it says did nothing.  The order is the first half of the read
        # and the resolution below is the second -- the dropped word is really skipped, and the
        # point that comes back is the word the record prefers.
        runtime = _runtime(
            ocr=_StubOCR(("挂机收益", 0.99, TITLE_BOX), ("签到", 0.99, BOX), ("领取", 0.99, BOX)),
            transitions=self.ledger,
        )
        order = runtime._ordinary_word_order(
            page_knowledge.UNKNOWN_LABEL, "挂机收益", unnamed=True
        )
        self.assertEqual(order[0], "签到")
        self.assertNotIn("领取", order)
        point = runtime._ordinary_control_candidate(
            WorldState(page=Page.UNKNOWN), UNKNOWN_FRAME
        )
        self.assertIsNotNone(point)
        self.assertEqual(runtime._ordinary_last["word"], "签到")

    def test_an_unnamed_screen_only_offers_its_exit_words_after_the_goal_words(self):
        runtime = _runtime(ocr=_ocr(), transitions=self.ledger)
        unnamed = runtime._ordinary_word_order(
            page_knowledge.UNKNOWN_LABEL, "挂机收益", unnamed=True
        )
        named = runtime._ordinary_word_order("EXPLORATION", "", unnamed=False)
        self.assertEqual(unnamed[0], "领取")
        self.assertIn("返回", unnamed)
        self.assertNotIn("返回", named)

    def test_the_ledger_is_bounded_and_keeps_what_was_verified(self):
        for index in range(page_knowledge.MAX_TRANSITIONS + 20):
            self.ledger.record(
                before_page="EXPLORATION", control=f"CTRL_{index}",
                after_page="HOME", verified=index == 0,
            )
        self.ledger.save()
        reloaded = _ledger(Path(self.tmp.name))
        self.assertLessEqual(len(reloaded.rows_for("EXPLORATION")), page_knowledge.MAX_TRANSITIONS)
        self.assertIn(
            "CTRL_0",
            [row.control for row in reloaded.rows_for("EXPLORATION")],
            "a verified transition is what reuse depends on, so it is the last to be pruned",
        )


class ReadingHelpersTests(unittest.TestCase):
    def test_the_title_is_the_largest_word_in_the_title_band(self):
        """Measured: the frame's *largest* text is the 领取 button at cy 0.72, not the title."""
        title = page_knowledge.read_title_candidate(UNKNOWN_FRAME, _ocr())
        self.assertEqual(title["text"], "挂机收益")
        self.assertLess(title["center_norm"][1], page_knowledge.TITLE_BAND_CY)

    def test_the_client_word_pages_of_the_dictionary_confirm_the_screen(self):
        """The one cross-check available without a new table: the project's own dictionary."""
        self.assertEqual(page_knowledge.dictionary_word_pages().get("挂机收益"), ("EXPLORATION",))

    def test_page_keys_keep_unnamed_screens_apart_and_named_ones_plain(self):
        self.assertEqual(page_knowledge.page_key("UNKNOWN", "挂机收益"), "UNKNOWN::挂机收益")
        self.assertEqual(page_knowledge.page_key("EXPLORATION", "挂机收益"), "EXPLORATION")
        self.assertEqual(page_knowledge.page_key("UNKNOWN", ""), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
