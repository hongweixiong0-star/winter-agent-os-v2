# -*- coding: utf-8 -*-
"""Offline proof of the ContinuousTouchSession invariant (PHASE 3).

The one thing this subsystem must never do is leave a finger pressed.  Every
case below is a different way a naive down/move/up triple leaks one:

  1  happy path                    -> RELEASED, balanced
  2  exception inside the block    -> ABORTED,  balanced
  3  explicit abort()              -> ABORTED,  balanced
  4  move before begin             -> refused, no device call
  5  begin refused by the device   -> IDLE,     balanced
  6  touch_up keeps failing        -> reports stuck=True HONESTLY (never silent)
  7  watchdog release_all()        -> every live session lifted
  8  report is complete evidence   -> geometry + latency present

usage: python tools/test_continuous_touch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.continuous_touch import (  # noqa: E402
    ContinuousTouchSession, TouchState, active_sessions, release_all)

RESULTS: list[bool] = []


def check(title: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} | {title}{('  <- ' + detail) if detail and not ok else ''}")


class FakeDevice:
    """Records the stream; can be told to fail specific verbs."""

    def __init__(self, fail_begin: bool = False, fail_up: bool = False,
                 fail_move_on: int | None = None) -> None:
        self.stream: list[tuple] = []
        self.fail_begin = fail_begin
        self.fail_up = fail_up
        self.fail_move_on = fail_move_on
        self.moves = 0

    def touch_down(self, x, y, contact=0, pressure=1):
        if self.fail_begin:
            return False, "MAA_TOUCH_DOWN_FAILED"
        self.stream.append(("down", x, y, contact))
        return True, ""

    def touch_move(self, x, y, contact=0, pressure=1):
        self.moves += 1
        if self.fail_move_on is not None and self.moves >= self.fail_move_on:
            return False, "MAA_TOUCH_MOVE_FAILED"
        self.stream.append(("move", x, y, contact))
        return True, ""

    def touch_up(self, contact=0):
        if self.fail_up:
            return False, "MAA_TOUCH_UP_FAILED"
        self.stream.append(("up", contact))
        return True, ""

    @property
    def joined(self) -> list[str]:
        return [s[0] for s in self.stream]


def case_happy() -> None:
    dev = FakeDevice()
    with ContinuousTouchSession(dev, session_id="T-HAPPY") as t:
        assert t.begin(360, 900), "begin should succeed"
        check("1 begin -> PRESSED", t.state is TouchState.PRESSED, t.state.value)
        t.move(340, 900)
        t.move(320, 900)
        check("1 move -> MOVING", t.state is TouchState.MOVING, t.state.value)
    rep = t.report()
    check("1 exit -> RELEASED", rep.state == "RELEASED", rep.state)
    check("1 no stuck finger", rep.stuck is False)
    check("1 balanced stream", dev.joined.count("down") == dev.joined.count("up") == 1,
          str(dev.joined))
    check("1 distance accumulates", rep.distance_px == 40.0, str(rep.distance_px))
    check("1 moves counted", rep.moves == 2, str(rep.moves))


def case_exception() -> None:
    dev = FakeDevice()
    t = ContinuousTouchSession(dev, session_id="T-EXC")
    try:
        with t:
            t.begin(360, 900)
            t.move(360, 880)
            raise ValueError("simulated vision blow-up")
    except ValueError:
        pass
    rep = t.report()
    check("2 exception -> ABORTED", rep.state == "ABORTED", rep.state)
    check("2 exception still lifted", rep.stuck is False and dev.joined[-1] == "up",
          str(dev.joined))
    check("2 abort reason recorded", "EXCEPTION_ValueError" in rep.reason, rep.reason)


def case_explicit_abort() -> None:
    dev = FakeDevice()
    t = ContinuousTouchSession(dev, session_id="T-ABORT")
    t.begin(100, 200)
    ok = t.abort("TARGET_LOST")
    check("3 abort lifts", ok and t.state is TouchState.ABORTED, t.state.value)
    check("3 abort balanced", t.report()["stuck"] is False if isinstance(t.report(), dict)
          else t.report().stuck is False)


def case_move_before_begin() -> None:
    dev = FakeDevice()
    t = ContinuousTouchSession(dev, session_id="T-NOBEGIN")
    ok = t.move(10, 10)
    check("4 move before begin refused", ok is False and dev.joined == [], str(dev.joined))
    check("4 state still IDLE", t.state is TouchState.IDLE, t.state.value)


def case_begin_refused() -> None:
    dev = FakeDevice(fail_begin=True)
    t = ContinuousTouchSession(dev, session_id="T-NODOWN")
    ok = t.begin(360, 900)
    check("5 refused begin -> False", ok is False)
    check("5 state stays IDLE (nothing to lift)",
          t.state is TouchState.IDLE and t.report().stuck is False, t.state.value)


def case_unliftable() -> None:
    """An unliftable finger must be REPORTED, never silently swallowed."""
    dev = FakeDevice(fail_up=True)
    t = ContinuousTouchSession(dev, session_id="T-UNLIFT")
    t.begin(360, 900)
    t.abort("DEVICE_GONE")
    rep = t.report()
    check("6 unliftable is reported stuck", rep.stuck is True)
    check("6 lift was retried", rep.lift_attempts == 3, str(rep.lift_attempts))
    check("6 failure traced", any(e["ok"] is False and "LIFT_FAILED" in (e["reason"] or "")
                                  for e in rep.events), "no LIFT_FAILED event")


def case_watchdog_release_all() -> None:
    dev = FakeDevice()
    a = ContinuousTouchSession(dev, session_id="T-A")
    b = ContinuousTouchSession(dev, session_id="T-B")
    a.begin(1, 1)
    b.begin(2, 2)
    check("7 both sessions hold a finger", len(active_sessions()) >= 2)
    out = release_all("TEST_WATCHDOG")
    check("7 release_all lifted both", all(o["lifted"] for o in out), str(out))
    check("7 nothing left holding", not [s for s in (a, b) if s.holds_finger])


def case_report_evidence() -> None:
    dev = FakeDevice()
    t = ContinuousTouchSession(dev, session_id="T-REPORT")
    t.begin(360, 900)
    t.move(350, 900)
    t.move(340, 900)
    t.end()
    rep = t.to_dict() if hasattr(t, "to_dict") else t.report().to_dict()
    check("8 report carries geometry", rep["begin_xy"] == [360, 900] and rep["end_xy"] == [340, 900],
          str((rep["begin_xy"], rep["end_xy"])))
    check("8 report carries per-event latency",
          all("ms" in e for e in rep["events"]) and rep["mean_move_ms"] is not None,
          str(rep["mean_move_ms"]))
    check("8 report duration measured", rep["duration_s"] >= 0.0)


def main() -> int:
    case_happy()
    case_exception()
    case_explicit_abort()
    case_move_before_begin()
    case_begin_refused()
    case_unliftable()
    case_watchdog_release_all()
    case_report_evidence()
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
