# -*- coding: utf-8 -*-
"""One malformed worker event must not end the drain -- and must not be silent.

Measured 2026-10-11 08:00, unattended: the panel sat ten minutes with ``workers: 0``,
``panel.log`` frozen at the last 「自动运行已启动」, and three ledgers stopped in adjacent minutes,
while the process stayed ``alive=True``.  The drain loop drained inside one ``try`` whose only
handler was ``queue.Empty``, and the re-arm sat after it -- so an exception from handling any single
event ended the drain, and ``pythonw`` swallowed the traceback.

These tests bind the real method to a stub, so no Tk root is needed.  The second test reproduces the
OLD body verbatim and asserts it fails the same judgement, which is what shows the first test bites.
"""
from __future__ import annotations

import queue
import unittest
from types import SimpleNamespace

from tools.control_panel import ControlPanel


def _stub(events: "queue.Queue") -> SimpleNamespace:
    stub = SimpleNamespace()
    stub.events = events
    stub.lines: list[str] = []
    stub.rearmed: list[tuple[int, object]] = []
    stub.root = SimpleNamespace(
        after=lambda ms, fn: stub.rearmed.append((ms, fn))
    )
    stub._append = lambda message: stub.lines.append(str(message))
    stub._apply_world = lambda *a: None
    stub._apply_complete = lambda *a: (_ for _ in ()).throw(RuntimeError("payload exploded"))
    stub._handle_worker_failure = lambda data: stub.lines.append("worker_failure handled")
    stub._handle_runtime_error = lambda text: stub.lines.append(f"runtime_error {text}")
    # The re-arm hands ``self._drain_events`` back to ``after``, so a stub without that attribute
    # cannot even express the thing under test -- which is exactly how the first run failed.
    stub._drain_events = ControlPanel._drain_events
    return stub


def _old_drain(self) -> None:
    """The body as it was before the fix, kept here so the difference is testable."""
    try:
        while True:
            kind, data = self.events.get_nowait()
            if kind == "refresh":
                self._apply_world(*data)
            elif kind == "complete":
                self._apply_complete(*data)
            elif kind == "note":
                self._append(str(data))
            elif kind == "worker_failure":
                self._handle_worker_failure(data)
            else:
                self._handle_runtime_error(str(data))
    except queue.Empty:
        pass
    self.root.after(100, self._drain_events)


class TheDrainSurvivesABadEventTests(unittest.TestCase):
    def test_a_raising_handler_is_named_and_the_drain_is_rearmed(self):
        events: queue.Queue = queue.Queue()
        events.put(("complete", (0, {}, "")))          # this one raises
        events.put(("note", "after the bad one"))      # this one must still be handled
        stub = _stub(events)

        ControlPanel._drain_events(stub)

        self.assertTrue(
            any("payload exploded" in line for line in stub.lines),
            f"the failure was not recorded; lines={stub.lines!r}",
        )
        self.assertEqual(
            [(100, ControlPanel._drain_events)],
            [(ms, fn) for ms, fn in stub.rearmed],
            "the drain was not re-armed",
        )
        self.assertTrue(
            any("after the bad one" in line for line in stub.lines),
            "the event AFTER the bad one was dropped, so one bad event cost later ones",
        )

    def test_the_old_body_fails_the_same_judgement(self):
        """Positive control: with the old body the re-arm and the later event are both lost."""
        events: queue.Queue = queue.Queue()
        events.put(("complete", (0, {}, "")))
        events.put(("note", "after the bad one"))
        stub = _stub(events)

        with self.assertRaises(RuntimeError):
            _old_drain(stub)

        self.assertEqual(stub.rearmed, [], "the old body re-armed despite the exception")
        self.assertFalse(
            any("after the bad one" in line for line in stub.lines),
            "the old body still handled the later event, which contradicts the diagnosis",
        )


if __name__ == "__main__":
    unittest.main()
