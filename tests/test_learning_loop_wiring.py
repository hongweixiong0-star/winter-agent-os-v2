"""The learning loop end to end: the first encounter asks, the second does not.

Directive 2026-10-01 sections 15 and 42.  Section 42 states the acceptance in three words:

    FIRST_ENCOUNTER_MODEL_USED  = TRUE
    SECOND_ENCOUNTER_MODEL_USED = FALSE
    SECOND_ENCOUNTER_VERIFIER_PASS = TRUE

A device would prove that; without one, this file proves the *mechanism* by driving the real
``LiveRuntime`` against the real relocation path with a counting advisor in place.  What it
therefore establishes and what it does not is worth saying plainly:

* it **does** establish that a verified step is filed, that the second encounter re-locates the
  element on the current frame, and that the advisor is not consulted on that second encounter --
  the three facts section 42 is about, at the code path that decides them;
* it does **not** establish that the real client behaves this way, because no step here touched the
  device.  ``SECOND_ENCOUNTER_VERIFIER_PASS`` in a live run still needs a live run.

The screenshot is synthesised for the same reason the OCR is stubbed: neither the pixels nor the
reader are what is under test.  ``_learned_reuse_point`` obtains its point by running the project's
own ``find_printed_words`` against the frame in front of it, so the assertion below is about that
path -- that a learned semantic is re-measured, not replayed -- and the picture is only what gives
the measurement a coordinate system.
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

from winter_agent_v2 import page_knowledge, skill_repair, unknown_learning  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402

#: The frame the client would have produced.  Synthesised rather than loaded from the machine so the
#: suite is hermetic: the pixels are never read here (the OCR is stubbed and ``find_printed_words``
#: only asks the frame for its size), so a stored screenshot would add a dependency on untracked
#: machine state -- ``dataset/raw`` is not in git, and a ``git clean`` would have turned this test
#: into a silent pass on the weaker path.  What is asserted is the *relocation*, which runs through
#: the real code, not the picture.
FRAME_SIZE = (720, 1280)


def _frame(directory: Path) -> Path:
    """Write a 720x1280 PNG for the unnamed screen and return its path."""
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "unnamed_screen.png"
    if not path.exists():
        Image.new("RGB", FRAME_SIZE, (12, 14, 20)).save(path)
    return path


BOX = ((360.0, 920.0), (420.0, 920.0), (420.0, 950.0), (360.0, 950.0))
CENTER = (390.0 / 720.0, 935.0 / 1280.0)


class _StubOCR:
    """A canned token list.  Module level, so ``check_wiring`` sees no dangling self-call."""

    def __init__(self, *tokens):
        self._tokens = tokens

    def recognize(self, image_path, roi=None):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=conf, box=box) for text, conf, box in self._tokens),
            "stub",
        )


class _CountingAdvisor:
    """An advisor that answers nothing and counts how often it was asked.

    Counting is the whole point: section 15's claim is about whether the model was *consulted*, not
    about what it said, so a stub that always refused to answer would still prove the property.
    """

    def __init__(self) -> None:
        self.asked = 0

    def take_request(self, request, registry=None):
        self.asked += 1
        return None

    def take(self, key, registry=None):
        self.asked += 1
        return None

    def ask(self, request, force=False):
        return False

    def read_request(self, key):
        return None

    def note_step(self, **kwargs):
        return None

    def note_outcome(self, *args, **kwargs):
        return None


def _runtime(*, ocr, learned: unknown_learning.VerifiedStepLedger) -> LiveRuntime:
    """A runtime with only what this path touches, and no production store.

    Built through ``object.__new__`` like the neighbouring suites, so the test can never write to
    ``knowledge/perception`` or to the real learned ledger.
    """
    runtime = object.__new__(LiveRuntime)
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = {}
    runtime._printed_remembered = set()
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime.MAX_ORDINARY_ATTEMPTS = 4
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._last_known_label = ""
    runtime.brain = RuleBrain(current_goal="CLAIM_EXPLORATION_IDLE")
    runtime.learned_ledger = learned
    runtime._learned_cache = None
    runtime._learned_reuse_hits = 0
    runtime._learned_model_calls_on_known = 0
    root = Path(tempfile.mkdtemp(prefix="learning_loop_"))
    runtime._ui_pages = page_knowledge.PageCandidateStore(root=root / "pages")
    runtime._transitions = page_knowledge.TransitionLedger(path=root / "t.json")
    return runtime


def _learned_ledger(tmp: Path, *, word: str = "领取") -> unknown_learning.VerifiedStepLedger:
    """A ledger holding one verified step for the unnamed screen, naming ``word``."""
    ledger = unknown_learning.VerifiedStepLedger(tmp / "steps.jsonl")
    key = page_knowledge.page_key("UNKNOWN", "")
    ledger.append(unknown_learning.LearnedStepCandidate(
        recorded_at="2026-10-01T00:00:00+00:00",
        request_id="req-1",
        session_id="session-1",
        episode_id="session-1",
        step_index=1,
        goal_id="CLAIM_EXPLORATION_IDLE",
        role_id="ROLE_A",
        page_before=key,
        page_after="UNKNOWN::挂机收益",
        semantic_target=f"ORDINARY_CONTROL[{word}]",
        action_type="CLICK_ELEMENT",
        basis="ORDINARY_CONTROL",
        grounding_basis="PRINTED_WORD",
        verifier_ok=True,
        expected_result="奖励已领取",
        risk_route=unknown_learning.ROUTE_FAST,
        source_frames=("frame.png",),
    ))
    return ledger


class SecondEncounterTests(unittest.TestCase):
    def test_the_second_encounter_does_not_ask_the_model(self):
        """§15/§42's SECOND_ENCOUNTER_MODEL_USED = FALSE, at the decision site."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(
                ocr=_StubOCR(("领取", 0.99, BOX)),
                learned=_learned_ledger(Path(tmp)),
            )
            advisor = _CountingAdvisor()
            runtime._advisor = advisor
            point = runtime._advised_control(
                "UNKNOWN", "", _frame(Path(tmp)), WorldState(page=Page.UNKNOWN),
                unnamed=True, confidence=0.4,
            )
        self.assertIsNotNone(point, "the learned action must be taken, not deferred")
        assert point is not None
        self.assertAlmostEqual(point[0], CENTER[0], delta=0.02)
        self.assertAlmostEqual(point[1], CENTER[1], delta=0.02)
        self.assertEqual(advisor.asked, 0, "the model must not be consulted on a solved screen")
        self.assertEqual(runtime.learning_run_counters()["learned_reuse_hits"], 1)

    def test_the_first_encounter_does_ask_the_model(self):
        """§42's FIRST_ENCOUNTER_MODEL_USED = TRUE: with nothing learned, the question is asked."""
        with tempfile.TemporaryDirectory() as tmp:
            empty = unknown_learning.VerifiedStepLedger(Path(tmp) / "steps.jsonl")
            runtime = _runtime(ocr=_StubOCR(("领取", 0.99, BOX)), learned=empty)
            advisor = _CountingAdvisor()
            runtime._advisor = advisor
            point = runtime._advised_control(
                "UNKNOWN", "", _frame(Path(tmp)), WorldState(page=Page.UNKNOWN),
                unnamed=True, confidence=0.4,
            )
        self.assertIsNone(point, "a counting advisor answers nothing")
        self.assertEqual(advisor.asked, 1)
        self.assertEqual(runtime.learning_run_counters()["learned_reuse_hits"], 0)

    def test_a_learned_control_that_is_no_longer_drawn_goes_back_to_the_model(self):
        """The fallthrough that keeps a stale record from becoming a dead end."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(
                ocr=_StubOCR(("其他", 0.99, BOX)),
                learned=_learned_ledger(Path(tmp), word="领取"),
            )
            advisor = _CountingAdvisor()
            runtime._advisor = advisor
            point = runtime._advised_control(
                "UNKNOWN", "", _frame(Path(tmp)), WorldState(page=Page.UNKNOWN),
                unnamed=True, confidence=0.4,
            )
        self.assertIsNone(point)
        self.assertEqual(advisor.asked, 1, "an unlocatable learned record must be a re-ask")
        self.assertEqual(runtime.learning_run_counters()["learned_reuse_hits"], 0)

    def test_a_learned_action_for_another_goal_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = _learned_ledger(Path(tmp))
            runtime = _runtime(ocr=_StubOCR(("领取", 0.99, BOX)), learned=ledger)
            runtime.brain = RuleBrain(current_goal="KEEP_TRAINING_PRODUCTIVE")
            advisor = _CountingAdvisor()
            runtime._advisor = advisor
            runtime._advised_control(
                "UNKNOWN", "", _frame(Path(tmp)), WorldState(page=Page.UNKNOWN),
                unnamed=True, confidence=0.4,
            )
        self.assertEqual(advisor.asked, 1)


class FailureIsolationTests(unittest.TestCase):
    def test_a_broken_learning_lookup_still_lets_the_ordinary_path_run(self):
        """§28: the learning layer must not be able to take a live step down with it.

        The guard is worth testing rather than trusting because the failure mode it prevents is
        silent: an exception here would land on every unnamed screen, and the screen that used to
        work through the ordinary path would stop working because of a layer that was only supposed
        to make things cheaper.
        """
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(
                ocr=_StubOCR(("领取", 0.99, BOX)),
                learned=_learned_ledger(Path(tmp)),
            )
            advisor = _CountingAdvisor()
            runtime._advisor = advisor

            def _explode(*args, **kwargs):
                raise RuntimeError("learning layer is broken")

            runtime._learned_reuse_point = _explode
            point = runtime._advised_control(
                "UNKNOWN", "", _frame(Path(tmp)), WorldState(page=Page.UNKNOWN),
                unnamed=True, confidence=0.4,
            )
        self.assertIsNone(point, "a counting advisor answers nothing")
        self.assertEqual(advisor.asked, 1, "the model must still be consulted when learning breaks")


class FilingTests(unittest.TestCase):
    def _context(self, frame: Path) -> dict:
        return {
            "page_key": "UNKNOWN",
            "goal": "CLAIM_EXPLORATION_IDLE",
            "semantic": "ORDINARY_CONTROL[领取]",
            "basis": "ORDINARY_CONTROL",
            "grounding_basis": "PRINTED_WORD",
            "expected_result": "奖励已领取",
            "frame": str(frame),
            "attempts": 2,
            "visual_evidence": {"reader": "AI_ADVICE/PRINTED_WORD", "ocr_anchor": "领取"},
        }

    def test_a_verified_advised_step_is_filed(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(ocr=_StubOCR(), learned=unknown_learning.VerifiedStepLedger(
                Path(tmp) / "steps.jsonl"))
            runtime.learned_ledger = unknown_learning.VerifiedStepLedger(Path(tmp) / "steps.jsonl")
            runtime.capture_dir = Path(tmp) / "run1"
            runtime.role_id = "ROLE_A"
            runtime._last_advice = {"request_id": "req-1"}
            runtime._advised_learn_context = self._context(_frame(Path(tmp)))
            runtime._note_learned_step(
                decision=SimpleNamespace(skill="TRY_ORDINARY_CONTROL"),
                verification=SimpleNamespace(ok=True, reason="", evidence={}),
                result="SUCCESS",
                observed_change="PAGE_CHANGED",
                after=WorldState(page=Page.UNKNOWN),
                step_id=3,
            )
            rows = runtime.learned_ledger.verified()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["semantic_target"], "ORDINARY_CONTROL[领取]")
        self.assertEqual(rows[0]["step_index"], 3)
        self.assertEqual(rows[0]["attempts_before_success"], 2)
        # §10: no coordinate field anywhere in the record.
        self.assertNotIn("x_norm", rows[0])
        self.assertNotIn("bbox", rows[0])

    def test_a_failed_advised_step_files_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = unknown_learning.VerifiedStepLedger(Path(tmp) / "steps.jsonl")
            runtime = _runtime(ocr=_StubOCR(), learned=ledger)
            runtime.capture_dir = Path(tmp) / "run1"
            runtime.role_id = "ROLE_A"
            runtime._last_advice = {"request_id": "req-1"}
            runtime._advised_learn_context = self._context(_frame(Path(tmp)))
            runtime._note_learned_step(
                decision=SimpleNamespace(skill="TRY_ORDINARY_CONTROL"),
                verification=SimpleNamespace(ok=False, reason="not_verified", evidence={}),
                result="FAILURE", observed_change="NONE",
                after=WorldState(page=Page.UNKNOWN), step_id=3,
            )
            rows = ledger.verified()
        self.assertEqual(rows, [])

    def test_the_context_is_consumed_even_when_nothing_is_filed(self):
        """A context that outlived its step would attach a later verdict to an earlier answer."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(ocr=_StubOCR(),
                               learned=unknown_learning.VerifiedStepLedger(Path(tmp) / "s.jsonl"))
            runtime._advised_learn_context = self._context(_frame(Path(tmp)))
            runtime._note_learned_step(
                decision=SimpleNamespace(skill="X"),
                verification=SimpleNamespace(ok=False, reason="r", evidence={}),
                result="FAILURE", observed_change="NONE", after=None, step_id=1,
            )
        self.assertEqual(runtime._advised_learn_context, {})


class RepairChannelTests(unittest.TestCase):
    def test_a_repeated_perception_failure_files_one_question_and_no_model_call(self):
        """§16: the trigger files a question; it never asks one synchronously."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(ocr=_StubOCR(),
                               learned=unknown_learning.VerifiedStepLedger(Path(tmp) / "s.jsonl"))
            runtime._repair_root = Path(tmp) / "repairs"
            runtime.registry = SimpleNamespace(get=lambda skill_id: None)
            frame = _frame(Path(tmp))
            decision = SimpleNamespace(skill="CLAIM_LOGIN_GIFT", reason="SEMANTIC_TARGET_NOT_FOUND")
            for _ in range(skill_repair.REPAIR_TRIGGER_FAILURES):
                runtime._maybe_request_repair(
                    decision=decision,
                    verification=SimpleNamespace(
                        ok=False, reason="SEMANTIC_TARGET_NOT_FOUND", evidence={}),
                    result="FAILURE",
                    before=WorldState(page=Page.UNKNOWN),
                    frame=frame,
                )
            files = list((Path(tmp) / "repairs").glob("*.json"))
            payload = json.loads(files[0].read_text(encoding="utf-8")) if files else {}
        self.assertEqual(len(files), 1, "one broken skill must file one question, not one per step")
        # The request file is the *question*: it names the skill and counts the run that broke.
        # ``status = CANDIDATE_PATCH`` is a property of the answer's patch, not of this -- asserting
        # it here would be asserting the wrong object, so the request's own fields are checked.
        self.assertEqual(payload["skill_id"], "CLAIM_LOGIN_GIFT")
        self.assertEqual(payload["consecutive_failures"], skill_repair.REPAIR_TRIGGER_FAILURES)
        self.assertIn("SEMANTIC_TARGET_NOT_FOUND", payload["failure_kinds"])
        self.assertNotIn("status", payload, "a question is not a patch")

    def test_a_success_clears_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _runtime(ocr=_StubOCR(),
                               learned=unknown_learning.VerifiedStepLedger(Path(tmp) / "s.jsonl"))
            runtime._repair_root = Path(tmp) / "repairs"
            runtime.registry = SimpleNamespace(get=lambda skill_id: None)
            frame = _frame(Path(tmp))
            decision = SimpleNamespace(skill="X", reason="SEMANTIC_TARGET_NOT_FOUND")
            for _ in range(skill_repair.REPAIR_TRIGGER_FAILURES - 1):
                runtime._maybe_request_repair(
                    decision=decision,
                    verification=SimpleNamespace(ok=False, reason="SEMANTIC_TARGET_NOT_FOUND",
                                                 evidence={}),
                    result="FAILURE", before=WorldState(page=Page.UNKNOWN), frame=frame,
                )
            runtime._maybe_request_repair(
                decision=decision, verification=SimpleNamespace(ok=True, reason="", evidence={}),
                result="SUCCESS", before=WorldState(page=Page.UNKNOWN), frame=frame,
            )
            runtime._maybe_request_repair(
                decision=decision,
                verification=SimpleNamespace(ok=False, reason="SEMANTIC_TARGET_NOT_FOUND",
                                             evidence={}),
                result="FAILURE", before=WorldState(page=Page.UNKNOWN), frame=frame,
            )
            files = list((Path(tmp) / "repairs").glob("*.json"))
        self.assertEqual(files, [], "a run broken by a success is not a run of failures")


class CompilationEndToEndTests(unittest.TestCase):
    def test_two_verified_steps_in_one_session_compile_into_a_candidate_skill(self):
        """§13: the chain the directive describes, produced from filed steps rather than fixtures."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = unknown_learning.VerifiedStepLedger(Path(tmp) / "steps.jsonl")
            for index, (before, after, semantic) in enumerate((
                ("HOME", "UNKNOWN::活动中心", "ORDINARY_CONTROL[活动]"),
                ("UNKNOWN::活动中心", "UNKNOWN::登录好礼", "ORDINARY_CONTROL[登录好礼]"),
            ), 1):
                ledger.append(unknown_learning.LearnedStepCandidate(
                    recorded_at=f"2026-10-01T00:00:0{index}+00:00",
                    session_id="run-1", episode_id="run-1", step_index=index,
                    goal_id="DAILY_ROUTINE", role_id="ROLE_A",
                    page_before=before, page_after=after, semantic_target=semantic,
                    action_type="CLICK_ELEMENT", verifier_ok=True,
                    grounding_basis="PRINTED_WORD",
                    risk_route=unknown_learning.ROUTE_FAST,
                ))
            compiled = unknown_learning.compile_candidate_skills(
                ledger.verified(), out_dir=Path(tmp) / "skills"
            )
            written = json.loads(
                (Path(tmp) / "skills" / f"{compiled[0].skill_id}.json").read_text(encoding="utf-8")
            )
        self.assertEqual(len(compiled), 1)
        self.assertEqual(compiled[0].entry_page, "HOME")
        self.assertEqual(compiled[0].exit_page, "UNKNOWN::登录好礼")
        self.assertEqual(len(compiled[0].steps), 2)
        self.assertEqual(written["lifecycle"], unknown_learning.STATUS_CANDIDATE)
        self.assertIn("not registered", written["not_yet"])


if __name__ == "__main__":
    unittest.main()
