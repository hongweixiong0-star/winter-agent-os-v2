"""The closure card is published off the UI thread, and a *failed* card is retried sooner.

Two separate contracts live here, and both were paid for by a measured freeze.

**The window must not compute the card.**  ``closure_card_now`` reads
``learning/workbuddy_escalations.jsonl`` (7.5 MB), a 32 MB tail of ``learning/episodes.jsonl``
and runs ``git log``.  Measured 2026-10-04, cold on the thread that draws the window: 3104 ms
once a minute, which the operator reported as lag.  ``ClosureCardProbe`` now computes it on a
daemon thread named ``closure-card-probe`` and the window only ever *reads* the published
snapshot.  The regression is the point of ``test_the_window_never_computes_the_card``: it fails
if a repaint can reach the computation again.

**A failure must not look like an answer.**  ``closure_card_now`` never raises -- it returns the
failure as ``ok: False`` -- so the publisher decides its next delay from the returned card
rather than from an exception.  Two different ``ok: False`` cards mean two different things:

* an *empty ledger* ("no upgrade carries a job id yet") is a real answer and keeps the full
  interval; reading it six times as often buys no new information;
* a *caught exception* is a failure to answer -- the ledger rewritten under the reader, or
  ``git`` briefly unavailable -- and waits :data:`control_panel.CLOSURE_RETRY_SECONDS` instead,
  because a stale card plus up to a minute of silence is exactly the lag the probe exists to
  remove.

The distinction is carried by one key, ``transient``, which is why the last test pins that the
exception path sets it: without it the retry rule silently degrades to "never retry soon".
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import control_panel  # noqa: E402
import unattended_closure  # noqa: E402


class _StopAfter:
    """A stand-in for ``threading.Event`` that records the delays it was asked to wait.

    ``wait`` returning ``True`` is the loop's own exit condition, so a count of ``n`` ends the
    loop after ``n`` published cards instead of leaving the test inside an infinite ``while``.
    """

    def __init__(self, n: int) -> None:
        self.n = n
        self.delays: list[float] = []

    def set(self) -> None:
        self.n = 0

    def wait(self, delay: float) -> bool:
        self.delays.append(delay)
        return len(self.delays) >= self.n


class ThePublisherPacesItselfByTheAnswer(unittest.TestCase):
    def _delays_for(self, card: dict) -> list[float]:
        probe = control_panel.ClosureCardProbe(".", interval=60.0)
        stop = _StopAfter(3)
        probe._stop = stop
        with mock.patch.object(probe, "refresh_once", return_value=card):
            probe._loop()
        return stop.delays

    def test_a_published_card_keeps_the_full_interval(self):
        self.assertEqual(self._delays_for({"ok": True}), [60.0, 60.0, 60.0])

    def test_an_empty_ledger_is_an_answer_not_a_failure(self):
        """``ok: False`` without ``transient`` is "nothing has happened yet" -- not an error."""
        card = {"ok": False, "reason": "台账中没有带 Job 的升级记录，闭环尚未开始"}
        self.assertEqual(self._delays_for(card), [60.0, 60.0, 60.0])

    def test_a_failed_card_is_retried_at_the_short_cadence(self):
        card = {"ok": False, "transient": True, "reason": "OSError: [Errno 22]"}
        expected = control_panel.CLOSURE_RETRY_SECONDS
        self.assertEqual(self._delays_for(card), [expected, expected, expected])

    def test_the_short_cadence_really_is_shorter(self):
        """A guard on the guard: if the constant were ever raised to the interval the retry
        would become a no-op and the test above would still pass."""
        self.assertLess(control_panel.CLOSURE_RETRY_SECONDS, control_panel.CLOSURE_INTERVAL)


class TheWindowNeverComputesTheCard(unittest.TestCase):
    def test_the_window_never_computes_the_card(self):
        published = {"ok": True, "trace_id": "T", "steps": []}

        class _StubProbe:
            started = False

            def start(self) -> None:
                self.started = True

            def latest(self):
                return published

        stub = _StubProbe()
        with mock.patch.object(control_panel, "closure_probe", return_value=stub), \
                mock.patch.object(control_panel, "closure_card_now",
                                  side_effect=AssertionError("the UI thread computed the card")):
            card = control_panel.closure_card()

        self.assertTrue(stub.started, "the publisher was never started")
        self.assertEqual(card, published, "the window did not read the published card")

    def test_before_the_first_card_the_window_says_it_is_counting(self):
        """The warming card must be distinguishable from "the loop has not started": the former
        is a fact about the renderer, the latter a claim about the system."""
        class _StubProbe:
            def start(self) -> None:
                pass

            def latest(self):
                return None

        with mock.patch.object(control_panel, "closure_probe", return_value=_StubProbe()), \
                mock.patch.object(control_panel, "closure_card_now",
                                  side_effect=AssertionError("computed too early")):
            card = control_panel.closure_card()

        self.assertIs(card.get("pending"), True, card)
        self.assertIs(card.get("ok"), False, card)
        # It is *not* a failure: a transient mark here would make the publisher retry a card that
        # has simply not been computed yet.
        self.assertNotIn("transient", card)

    def test_the_pending_card_renders_as_counting_not_as_never_started(self):
        line = control_panel.render_loop_card(dict(control_panel.CLOSURE_WARMING))
        self.assertIn("计算中", line)
        self.assertNotIn("尚未开始", line)


class AFailureCardSaysSo(unittest.TestCase):
    def test_a_caught_exception_is_marked_transient(self):
        with mock.patch.object(unattended_closure, "rows",
                               side_effect=RuntimeError("ledger rewritten mid-read")):
            card = control_panel.closure_card_now()

        self.assertIs(card.get("ok"), False, card)
        self.assertIs(card.get("transient"), True, card)
        self.assertIn("RuntimeError", str(card.get("reason")))


if __name__ == "__main__":
    unittest.main()
