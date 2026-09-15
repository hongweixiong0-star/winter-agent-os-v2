"""One rule for `unexpected_worker_exits`, and both writers must ask it.

Origin: RR-001 / WB-R19-RUNTIME-EXIT-SEMANTICS (2026-09-16).  The counter had two
writers in `tools/control_panel.py` with different rules.  The classified path
counted only a genuine `WORKER_CRASH`; the unclassified fallback counted every
non-fatal error.  So an emulator dropout or an operator stop incremented a
counter that the 72-hour gate requires to be zero -- which made that gate
unreachable by fixing crashes, the only way it was ever going to be reached.

Two things are pinned here:

1. the table of verdicts for the four event classes, and
2. that BOTH handlers call the shared rule, checked statically.

(2) matters as much as (1).  The original defect was not a wrong verdict inside
one function; it was two functions disagreeing.  A test that only exercises the
predicate would still pass if a future edit re-inlined the old arithmetic into
one of the handlers.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from winter_agent_v2.runtime_snapshot import (
    NON_FATAL_STOPS,
    UNCLASSIFIED_EVENT,
    counts_as_unexpected_worker_exit,
)

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "tools/control_panel.py"

# The real markers, so the test is tied to the strings that actually appear.
ENVIRONMENT_MESSAGE = "DEVICE_NOT_CONNECTED: adb reports no online device"
OPERATOR_STOP_MESSAGE = "用户已停止"
CRASH_MESSAGE = "KeyError: 'march_max'"
FATAL_MESSAGE = "FATAL_INVARIANTS_BROKEN"


class TheVerdictTableTests(unittest.TestCase):
    """ENVIRONMENT / operator stop / WORKER_CRASH / fatal."""

    def test_the_table(self):
        table = [
            # (label, classification, message, stop_requested, expected)
            ("environment failure is not a worker exit", "ENVIRONMENT", ENVIRONMENT_MESSAGE, False, False),
            ("operator stop is not a worker exit", "ENVIRONMENT", OPERATOR_STOP_MESSAGE, False, False),
            ("operator stop flag alone is enough", "WORKER_CRASH", CRASH_MESSAGE, True, False),
            ("a worker crash is a worker exit", "WORKER_CRASH", CRASH_MESSAGE, False, True),
            ("a fatal stop is not counted twice", "WORKER_CRASH", FATAL_MESSAGE, False, False),
            ("a fatal stop is not counted even if classified environmental", "ENVIRONMENT", FATAL_MESSAGE, False, False),
            ("an unclassified event is not a worker exit", UNCLASSIFIED_EVENT, CRASH_MESSAGE, False, False),
            ("a missing classification is not a worker exit", None, CRASH_MESSAGE, False, False),
            ("an empty classification is not a worker exit", "", CRASH_MESSAGE, False, False),
            ("an unknown classification string is not a worker exit", "SOMETHING_ELSE", CRASH_MESSAGE, False, False),
        ]
        for label, classification, message, stop_requested, expected in table:
            with self.subTest(label=label):
                self.assertIs(
                    counts_as_unexpected_worker_exit(
                        classification=classification, message=message, stop_requested=stop_requested
                    ),
                    expected,
                )

    def test_the_old_fallback_behaviour_is_now_refused(self):
        # The regression, stated as a test: the fallback used to increment for
        # EVERY non-fatal message, including this one.
        self.assertFalse(
            counts_as_unexpected_worker_exit(
                classification=UNCLASSIFIED_EVENT, message=ENVIRONMENT_MESSAGE, stop_requested=False
            )
        )

    def test_fatal_and_non_fatal_reasons_are_contrasted_through_the_shared_table(self):
        """Only a FATAL/CONFIRM reason suppresses counting; a benign one does not.

        The direction matters: NON_FATAL_STOPS lists reasons that are *not*
        fatal, so a genuine crash that ended with one of them still counts.  The
        fatal branch exists only to avoid reporting one event twice (as both a
        `last_fatal_error` and a counter increment).
        """
        self.assertIn("intel_no_untried_pins", NON_FATAL_STOPS)
        self.assertTrue(
            counts_as_unexpected_worker_exit(
                classification="WORKER_CRASH", message="intel_no_untried_pins", stop_requested=False
            ),
            "a crash with a NON-fatal stop reason must still be counted",
        )
        self.assertFalse(
            counts_as_unexpected_worker_exit(
                classification="WORKER_CRASH", message="FATAL_INVARIANTS_BROKEN", stop_requested=False
            ),
            "a fatal stop is already recorded, so it must not also be counted",
        )


class BothWritersAskTheSameQuestionTests(unittest.TestCase):
    """Static: the two handlers must call the shared rule, not re-implement it."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(PANEL.read_text(encoding="utf-8"))

    def _handler(self, name: str) -> ast.FunctionDef:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        self.fail("handler not found: %s" % name)

    def _calls(self, fn: ast.FunctionDef) -> set[str]:
        return {
            node.func.id
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

    def test_worker_failure_handler_uses_the_shared_rule(self):
        self.assertIn("counts_as_unexpected_worker_exit", self._calls(self._handler("_handle_worker_failure")))

    def test_runtime_error_handler_uses_the_shared_rule(self):
        # This is the one that used to bypass classification entirely.
        self.assertIn("counts_as_unexpected_worker_exit", self._calls(self._handler("_handle_runtime_error")))

    def test_no_handler_does_its_own_counter_arithmetic(self):
        """The counter may only move through `counts_as_exit`."""
        for name in ("_handle_worker_failure", "_handle_runtime_error"):
            fn = self._handler(name)
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Name) or func.id != "update":
                    continue
                for kw in node.keywords:
                    if kw.arg != "unexpected_worker_exits":
                        continue
                    with self.subTest(handler=name):
                        # Expected shape: previous.X + (1 if counts_as_exit else 0)
                        self.assertIsInstance(kw.value, ast.BinOp)
                        right = kw.value.right
                        self.assertIsInstance(right, ast.IfExp)
                        self.assertIsInstance(right.test, ast.Name)
                        self.assertEqual(right.test.id, "counts_as_exit")


class TheRealHandlersMoveTheCounterCorrectlyTests(unittest.TestCase):
    """Drive the actual handlers, against a real RuntimeSnapshotStore on disk.

    Stronger than testing the predicate alone: this is the code that runs, with
    the real store, asserting the arithmetic that lands in
    `learning/runtime_snapshot.json`.

    Deliberately no GUI.  `tools/control_panel.py` creates its Tk root only in
    `main()`, so the handlers can be driven directly -- and a rule that can only
    be exercised by opening a window is a rule that does not get exercised, which
    is how the two writers drifted apart in the first place.  No crash is
    manufactured here, as the work order requires.
    """

    @classmethod
    def setUpClass(cls):
        import sys

        sys.path.insert(0, str(ROOT / "tools"))
        import control_panel  # noqa: PLC0415

        cls.panel = control_panel

    def _harness(self, starting: int):
        import tempfile

        from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = RuntimeSnapshotStore(Path(tmp.name) / "runtime_snapshot.json")
        store.update(unexpected_worker_exits=starting, watchdog_restart_count=13)

        class _Var:
            def __init__(self, value=False):
                self._v = value

            def get(self):
                return self._v

            def set(self, _value):
                pass

        class _Self:
            pass

        fake = _Self()
        fake.runtime_store = store
        fake.values = {"vision": _Var(), "result": _Var()}
        fake.continuous = _Var(False)  # no watchdog restart, no tk after()
        fake.stop_requested = False
        fake.paused = False
        fake.appended = []
        fake._append = lambda text: fake.appended.append(text)
        fake._idle_buttons = lambda: None
        fake._clear_running_task_labels = lambda: None
        return fake, store

    def _counter(self, store) -> int:
        return store.read().unexpected_worker_exits

    def test_an_environment_failure_through_the_fallback_does_not_count(self):
        # The exact regression: this path used to add 1 for any non-fatal text.
        fake, store = self._harness(15)
        self.panel.ControlPanel._handle_runtime_error(
            fake, "DEVICE_NOT_CONNECTED: adb reports no online device"
        )
        self.assertEqual(self._counter(store), 15)

    def test_an_operator_stop_through_the_fallback_does_not_count(self):
        fake, store = self._harness(15)
        fake.stop_requested = True
        self.panel.ControlPanel._handle_runtime_error(fake, "用户已停止")
        self.assertEqual(self._counter(store), 15)

    def test_an_unrecognised_message_through_the_fallback_does_not_count(self):
        # No classification can be established here, so the safe answer is "not
        # a worker exit" -- and the reason is still recorded.
        fake, store = self._harness(15)
        self.panel.ControlPanel._handle_runtime_error(fake, "KeyError: 'march_max'")
        self.assertEqual(self._counter(store), 15)
        self.assertEqual(store.read().stop_reason, "KeyError: 'march_max'")

    def test_a_classified_worker_crash_still_counts_once(self):
        fake, store = self._harness(15)
        self.panel.ControlPanel._handle_worker_failure(
            fake,
            {
                "message": "KeyError: 'march_max'",
                "classification": "WORKER_CRASH",
                "crash_report": "/somewhere/crashes/20260916_report.json",
            },
        )
        self.assertEqual(self._counter(store), 16)
        self.assertTrue(any("根因证据" in line for line in fake.appended))

    def test_an_environment_failure_through_the_classified_path_does_not_count(self):
        # Unchanged behaviour on the path that was already correct: this is the
        # control that shows the fix added a rule rather than a blanket refusal.
        fake, store = self._harness(15)
        self.panel.ControlPanel._handle_worker_failure(
            fake,
            {
                "message": "DEVICE_NOT_CONNECTED: adb reports no online device",
                "classification": "ENVIRONMENT",
            },
        )
        self.assertEqual(self._counter(store), 15)

    def test_a_fatal_stop_is_not_counted_on_either_path(self):
        for handler, payload in (
            (self.panel.ControlPanel._handle_worker_failure,
             {"message": "FATAL_INVARIANTS_BROKEN", "classification": "WORKER_CRASH"}),
            (self.panel.ControlPanel._handle_runtime_error, "FATAL_INVARIANTS_BROKEN"),
        ):
            with self.subTest(handler=handler.__name__):
                fake, store = self._harness(15)
                handler(fake, payload)
                self.assertEqual(self._counter(store), 15)
                self.assertEqual(store.read().last_fatal_error, "FATAL_INVARIANTS_BROKEN")


if __name__ == "__main__":
    unittest.main()
