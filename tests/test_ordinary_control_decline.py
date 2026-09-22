"""A refusal is recorded as the refusal it was, not as "the frame names no target".

Measured 2026-09-23 over the 69 live attempts of ``TRY_ORDINARY_CONTROL``
(``tools/probe_ordinary_control_resolution.py``): 18 of them were a *repeat within their own run*, and
17 of those failed as ``SEMANTIC_TARGET_NOT_VERIFIED`` -- while the frame they stood on demonstrably
draws the collapsed 快捷面板 handle (the same replay returns the point the moment the run's used-set is
empty, and loses it the moment ``(HOME, QUICK_PANEL_HANDLE)`` is in it).

So the runtime declined a control it could see, and the record said the control was not there.  Three
consequences, each fixed and each asserted here:

* the episode's ``failure_type`` is the runtime's own name (operator §6: different root causes must not
  share a reason string);
* the name does not end in ``escalation_queue``'s UI-unread suffixes, so the signature stops being
  reported as ``UNKNOWN_UI`` -- "the client showed something V2 could not read" -- which is a diagnosis
  nothing can act on, because nothing is unreadable;
* the element collector no longer files it as *unlocated*, which would put a false candidate in a store
  whose whole purpose is to describe what the client draws.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import is_ui_unread  # noqa: E402
from winter_agent_v2.models import (  # noqa: E402
    Action,
    ExecutionResult,
    Page,
    VerificationResult,
    WorldState,
)
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.runtime_snapshot import is_fatal_stop  # noqa: E402

HANDLE = "QUICK_PANEL_HANDLE"
FRAME = Path("dataset/raw/control_panel/runtime_auto/run_stub/frame.png")
ALREADY_USED = LiveRuntime.ORDINARY_CONTROL_DECLINES["already_used"]


def _frame(state: str = "COLLAPSED", page: Page = Page.HOME) -> WorldState:
    """The reading the vision layer produces for a city frame with the panel closed."""
    return WorldState(
        page=page,
        quick_panel={
            "open": state == "EXPANDED",
            "state": state,
            "handle": {
                "state": state,
                "point_norm": [0.0181, 0.4301],
                "box_norm": {"x_norm": 0.0083, "y_norm": 0.4203, "w_norm": 0.0208, "h_norm": 0.0203},
                "basis": "HANDLE_TRIANGLE_SCAN",
            },
        },
        confidence=0.99,
    )


class _StubOCR:
    """An OCR service that reads whatever it is told to, in the shape the readers consume.

    Empty here on purpose: these frames draw the panel's own textless tab, and a whitelist word that
    does not exist keeps the printed-word tier out of the way so the declared tier is what answers.
    """

    def __init__(self, tokens=()):
        self._tokens = tuple(tokens)

    def recognize(self, image_path, roi=None):
        from winter_agent_v2.ocr import OCRResult, OCRToken

        return OCRResult(
            tuple(OCRToken(text=text, confidence=0.99, box=box) for text, box in self._tokens),
            "stub",
        )


def _runtime(*, goal: str = "TRAIN", goal_id: str = "KEEP_TRAINING_PRODUCTIVE") -> LiveRuntime:
    """A runtime with only what the ordinary-control path touches (no device, no cycle)."""
    runtime = object.__new__(LiveRuntime)
    ocr = _StubOCR()
    runtime.vision = SimpleNamespace(ocr=ocr)
    runtime.semantic_vision = SimpleNamespace(ocr=None)
    runtime._control_ledger = {}
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}
    runtime.MAX_ORDINARY_ATTEMPTS = 2
    runtime._ordinary_attempts = 0
    runtime._ordinary_tried = set()
    runtime._ordinary_last = None
    runtime._ordinary_declined = None
    runtime._l1_context = None
    runtime._l1_frame_hint = ""
    runtime._transitions = None
    runtime._ui_candidates = None
    runtime.brain = SimpleNamespace(current_goal=goal, goal_id=goal_id, ordinary_scan_exhausted=False)
    runtime.capture_dir = FRAME.parent
    return runtime


def _not_executed() -> ExecutionResult:
    return ExecutionResult(
        executed=False,
        dry_run=False,
        action=Action("TAP_SEMANTIC", "ORDINARY_CONTROL"),
        backend="ADB",
        error="SEMANTIC_TARGET_NOT_VERIFIED",
    )


class TheDeclineIsNamedTest(unittest.TestCase):
    def test_the_first_use_is_resolved_and_names_no_refusal(self):
        runtime = _runtime()
        self.assertEqual(
            runtime._ordinary_control_candidate(_frame(), FRAME), (0.0181, 0.4301)
        )
        self.assertIsNone(runtime._ordinary_declined)

    def test_the_second_use_is_declined_by_name(self):
        """The frame still draws it; the run has used it; and that is what gets recorded."""
        runtime = _runtime()
        runtime._ordinary_tried = {(Page.HOME.value, HANDLE)}
        self.assertIsNone(runtime._ordinary_control_candidate(_frame(), FRAME))
        declined = runtime._ordinary_declined or {}
        self.assertEqual(declined.get("reason"), ALREADY_USED)
        self.assertEqual(declined.get("semantic"), HANDLE)

    def test_a_later_resolution_does_not_inherit_the_refusal(self):
        """Same discipline as ``_ordinary_last``: a step that resolved nothing must not wear the
        previous step's reason."""
        runtime = _runtime()
        runtime._ordinary_declined = {"reason": ALREADY_USED}
        self.assertEqual(
            runtime._ordinary_control_candidate(_frame(), FRAME), (0.0181, 0.4301)
        )
        self.assertIsNone(runtime._ordinary_declined)

    def test_an_expanded_panel_names_its_own_gate(self):
        """The already-open case has its own gate, and it says so.

        ``EXPANDED`` satisfies the state the record exists for, so toggling it would undo what the
        goal wants -- a different refusal from "this run used it", and it must not borrow that name.
        """
        runtime = _runtime()
        self.assertIsNone(runtime._ordinary_control_candidate(_frame(state="EXPANDED"), FRAME))
        self.assertEqual(
            (runtime._ordinary_declined or {}).get("reason"),
            LiveRuntime.ORDINARY_CONTROL_DECLINES["already_open"],
        )


class TheStructuralGatesAreNamedTest(unittest.TestCase):
    """Every gate that refuses a control the frame draws names itself.

    Measured 2026-09-23: of the 31 failed live attempts, 15 stood on a frame that draws the collapsed
    handle -- 7 refused by "already used this run" and 8 by one of these gates.  All 31 were recorded
    as "the frame names no control".
    """

    def test_a_goal_the_record_does_not_serve_is_named(self):
        runtime = _runtime(goal="INTEL", goal_id="CLEAR_INTEL")
        self.assertIsNone(runtime._ordinary_control_candidate(_frame(), FRAME))
        self.assertEqual(
            (runtime._ordinary_declined or {}).get("reason"),
            LiveRuntime.ORDINARY_CONTROL_DECLINES["not_for_goal"],
        )

    def test_a_page_the_record_does_not_name_is_named(self):
        runtime = _runtime()
        self.assertIsNone(
            runtime._ordinary_control_candidate(_frame(page=Page.ALLIANCE), FRAME)
        )
        self.assertEqual(
            (runtime._ordinary_declined or {}).get("reason"),
            LiveRuntime.ORDINARY_CONTROL_DECLINES["not_on_page"],
        )

    def test_the_first_gate_to_refuse_is_the_name_reported(self):
        """The reason must be the gate that decided, not a later one describing a control already
        ruled out.  ALLIANCE is both unlisted and unserved; the record's own page list comes first."""
        runtime = _runtime(goal="INTEL", goal_id="CLEAR_INTEL")
        self.assertIsNone(
            runtime._ordinary_control_candidate(_frame(page=Page.ALLIANCE), FRAME)
        )
        self.assertEqual(
            (runtime._ordinary_declined or {}).get("reason"),
            LiveRuntime.ORDINARY_CONTROL_DECLINES["not_on_page"],
        )

    def test_every_decline_name_classifies_as_what_it_is(self):
        names = LiveRuntime.ORDINARY_CONTROL_DECLINES
        self.assertGreaterEqual(len(names), 5)
        for gate, name in names.items():
            with self.subTest(gate=gate):
                self.assertTrue(name.startswith("ORDINARY_CONTROL_"), name)
                self.assertFalse(is_ui_unread(name), f"{gate}: not an unreadable UI")
                self.assertFalse(is_fatal_stop(name), f"{gate}: must hand the cycle over")


class TheEpisodeCarriesItTest(unittest.TestCase):
    def test_the_executors_generic_verdict_becomes_the_runtime_s_own_name(self):
        runtime = _runtime()
        runtime._ordinary_declined = {
            "reason": ALREADY_USED,
            "semantic": HANDLE,
        }
        self.assertEqual(
            runtime._failure_type_from(_not_executed()),
            ALREADY_USED,
        )

    def test_without_a_refusal_the_executors_verdict_is_kept_verbatim(self):
        """The negative control: a frame that really does not show the control keeps saying so."""
        runtime = _runtime()
        self.assertEqual(runtime._failure_type_from(_not_executed()), "SEMANTIC_TARGET_NOT_VERIFIED")

    def test_a_named_refusal_is_not_relabelled_when_nothing_declined_it(self):
        """The substitution is keyed on the executor's own string, so it cannot swallow another
        failure that happens to arrive on the same step."""
        runtime = _runtime()
        runtime._ordinary_declined = {"reason": ALREADY_USED}
        other = ExecutionResult(
            executed=False, dry_run=False,
            action=Action("TAP_SEMANTIC", "BTN_OPEN_HOME"), backend="ADB",
            error="BTN_OPEN_HOME_NOT_PROVEN",
        )
        self.assertEqual(runtime._failure_type_from(other), "BTN_OPEN_HOME_NOT_PROVEN")

    def test_no_execution_keeps_its_own_name(self):
        runtime = _runtime()
        self.assertEqual(runtime._failure_type_from(None), "NO_EXECUTION")

    def test_a_step_that_resolved_something_after_a_refusal_keeps_the_verdict(self):
        """The guard that keeps the claim honest: a control *was* aimed at, so "the frame does not
        show it" is the true sentence and the refusal is not allowed to overwrite it."""
        runtime = _runtime()
        runtime._ordinary_declined = {"reason": ALREADY_USED, "semantic": HANDLE}
        runtime._ordinary_last = {"semantic": "ORDINARY_CONTROL[领取]", "word": "领取"}
        self.assertEqual(runtime._failure_type_from(_not_executed()), "SEMANTIC_TARGET_NOT_VERIFIED")


class TheNameClassifiesAsWhatItIsTest(unittest.TestCase):
    def test_it_is_no_longer_reported_as_an_unreadable_ui(self):
        named = ALREADY_USED
        self.assertFalse(is_ui_unread(named))
        self.assertTrue(
            is_ui_unread("SEMANTIC_TARGET_NOT_VERIFIED"),
            "the string this replaces is classified as UNKNOWN_UI, which is the wrong diagnosis",
        )

    def test_it_hands_the_cycle_over_instead_of_ending_the_run(self):
        """Operator §7: a policy refusal is not a reason to stop the whole agent."""
        self.assertFalse(is_fatal_stop(ALREADY_USED))


class _RecorderStore:
    """Only the calls the collector makes, recorded rather than written."""

    def __init__(self):
        self.unlocated = []
        self.saved = 0

    def stage_unlocated(self, **kwargs):
        self.unlocated.append(kwargs)
        return None

    def save(self):
        self.saved += 1


class TheCollectorDoesNotCallItUnlocatableTest(unittest.TestCase):
    def _collect(self, *, declined):
        runtime = _runtime()
        store = _RecorderStore()
        runtime._ui_candidates = store
        runtime._ordinary_declined = declined
        with patch.object(runtime, "_collect_printed_controls", lambda **kwargs: None):
            runtime._collect_ui_evidence(
                decision=SimpleNamespace(expected_result="ordinary_control_observed"),
                before=_frame(),
                after=_frame(),
                execution=_not_executed(),
                verification=VerificationResult(False, "SEMANTIC_TARGET_NOT_VERIFIED", {}),
                observed_change="UNKNOWN",
                before_screenshot=FRAME,
                after_screenshot=FRAME,
                episode_id="run_stub",
                goal_id="KEEP_TRAINING_PRODUCTIVE",
            )
        return store

    def test_a_frame_that_shows_nothing_is_still_filed_as_unlocated(self):
        store = self._collect(declined=None)
        self.assertEqual(len(store.unlocated), 1, "this is the case the branch exists for")

    def test_a_named_refusal_is_not_filed_as_unlocated(self):
        store = self._collect(declined={"reason": ALREADY_USED})
        self.assertEqual(store.unlocated, [], "the element was located; the runtime declined to use it")


if __name__ == "__main__":
    unittest.main()
