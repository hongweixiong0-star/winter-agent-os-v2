# -*- coding: utf-8 -*-
"""Offline proof of VisualServoSession (PHASE 5, 6, 7).

The loop is exercised against a synthetic "game": the fake device renders a white
column at ``target_x`` and can drift it, so the detector→controller→touch_move
cycle really closes.  Nothing here touches the device.

Proven:
  1  closed loop converges onto a static target
  2  it TRACKS a moving target instead of replaying a trajectory
  3  dead zone: no twitch inside the dead band
  4  max_move_per_tick is never exceeded, however large the error
  5  low-pass smooths intent (a step target is not jumped to in one tick)
  6  a blink (< max_lost_frames) does not produce a correction: it holds
  7  hold_while_lost=False releases the finger when the target stays lost
  8  max_session_duration stops a runaway loop
  9  a frozen client raises CLIENT_FROZEN instead of steering blind
 10  completion_detector ends the session as COMPLETED
 11  an exception in the detector ends as ERROR and still lifts the finger
 12  per-frame timings (capture/vision/decision/input/loop) are all recorded
 13  the loop calls nothing but capture + touch_move/down/up (scope discipline)
 14  target_hz pacing is honoured
 15  TOUCH is never left down on any outcome

usage: python tools/test_visual_servo.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.continuous_touch import release_all  # noqa: E402
from winter_agent_v2.visual_servo import (  # noqa: E402
    ServoCommand, ServoConfig, VisualServoSession)

RESULTS: list[bool] = []


def check(title: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'} | {title}{('  <- ' + detail) if detail and not ok else ''}")


H, W = 60, 720


class FakeScreen:
    """Renders a white column at ``x``; records every device call."""

    def __init__(self, x: int = 300, drift: float = 0.0, freeze_after: int | None = None):
        self.x = float(x)
        self.drift = drift
        self.freeze_after = freeze_after
        self.calls: list[str] = []
        self.captures = 0
        self.finger: int | None = None       # None while not pressed
        self.last_x: int | None = None       # last commanded x (survives touch_up)
        self.frozen_frame: np.ndarray | None = None

    def capture(self) -> np.ndarray:
        self.captures += 1
        if self.freeze_after is not None and self.captures > self.freeze_after:
            if self.frozen_frame is None:
                self.frozen_frame = self._render()
            return self.frozen_frame
        self.x += self.drift
        # bounce inside the screen so a "moving target" stays measurable
        if self.x > 640:
            self.x, self.drift = 640.0, -abs(self.drift)
        elif self.x < 80:
            self.x, self.drift = 80.0, abs(self.drift)
        return self._render()

    def _render(self) -> np.ndarray:
        f = np.zeros((H, W, 3), dtype=np.uint8)
        xi = int(max(0, min(W - 1, self.x)))
        f[:, max(0, xi - 4):xi + 4] = 255
        return f

    # --- device surface used by the servo ---
    def touch_down(self, x, y, contact=0, pressure=1):
        self.calls.append("touch_down")
        self.finger = self.last_x = int(x)
        return True, ""

    def touch_move(self, x, y, contact=0, pressure=1):
        self.calls.append("touch_move")
        self.finger = self.last_x = int(x)
        return True, ""

    def touch_up(self, contact=0):
        self.calls.append("touch_up")
        self.finger = None
        return True, ""

    # --- things the servo must NEVER call ---
    def ocr(self, *a, **k):       # pragma: no cover
        self.calls.append("ocr")
        raise AssertionError("visual servo must not call OCR")

    def observe_world(self, *a, **k):   # pragma: no cover
        self.calls.append("observe_world")
        raise AssertionError("visual servo must not build a world state")


def column_detector(roi: np.ndarray) -> dict:
    cols = roi.mean(axis=(0, 2)) if roi.ndim == 3 else roi.mean(axis=0)
    bright = np.nonzero(cols > 128)[0]
    if bright.size == 0:
        return {"found": False, "lost": True}
    return {"found": True, "lost": False, "target_x": int(bright.mean())}


def steer_onto_target(state) -> ServoCommand:
    if not state.get("found"):
        return ServoCommand(desired_x=None)
    return ServoCommand(desired_x=state["target_x"])


def run(screen: FakeScreen, **cfg_kw):
    cfg = ServoConfig(anchor_y=10, **cfg_kw)
    sess = VisualServoSession(screen, config=cfg)
    rep = sess.run(column_detector, steer_onto_target, None)
    return sess, rep


def case_converge() -> None:
    # drive until the finger sits on the column, then let completion stop the loop
    screen = FakeScreen(x=600)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                         max_move_per_tick_px=80,
                                                         low_pass_alpha=1.0,
                                                         max_session_duration_s=5.0))

    def completion(_frame, _state):
        return screen.finger is not None and abs(screen.last_x - int(screen.x)) <= 6

    rep = sess.run(column_detector, steer_onto_target, completion)
    check("1 closed loop converged onto the target",
          rep.outcome == "COMPLETED" and abs(screen.last_x - int(screen.x)) <= 8,
          f"{rep.outcome} finger={screen.finger} target={int(screen.x)}")


def case_track_moving() -> None:
    screen = FakeScreen(x=300, drift=6.0)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                         max_move_per_tick_px=40,
                                                         low_pass_alpha=1.0,
                                                         dead_zone_px=6))
    rep = sess.run(column_detector, steer_onto_target, None)
    # after the loop, the finger should be near the (still drifting) target
    near = abs(screen.last_x - int(screen.x)) <= 45
    check("2 tracked a moving target (no replayed trajectory)", near,
          f"finger={screen.last_x} target={int(screen.x)} moves={rep.moves_sent}")
    check("2 many distinct commands were issued", rep.moves_sent >= 3, str(rep.moves_sent))


def case_dead_zone() -> None:
    screen = FakeScreen(x=300)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                         low_pass_alpha=1.0, dead_zone_px=6))
    # press lands at the ROI centre (360); target 300 -> will be driven close then stop
    rep = sess.run(column_detector, steer_onto_target, None)
    check("3 dead zone suppressed pointless moves",
          rep.moves_skipped_dead_zone > 0, str(rep.moves_skipped_dead_zone))
    check("3 final error inside the dead zone",
          abs(screen.last_x - 300) <= 8, f"finger={screen.last_x}")


def case_clamp() -> None:
    screen = FakeScreen(x=700)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                         max_move_per_tick_px=25,
                                                         low_pass_alpha=1.0))
    deltas: list[int] = []
    orig_move = screen.touch_move

    def spy(x, y, contact=0, pressure=1):
        if screen.finger is not None:
            deltas.append(abs(int(x) - screen.finger))
        return orig_move(x, y, contact, pressure)

    screen.touch_move = spy  # type: ignore[assignment]
    rep = sess.run(column_detector, steer_onto_target, None)
    check("4 no tick ever exceeded max_move_per_tick", deltas and max(deltas) <= 25,
          f"max delta={max(deltas) if deltas else None}")


def case_low_pass() -> None:
    screen = FakeScreen(x=700)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                         max_move_per_tick_px=1000,
                                                         low_pass_alpha=0.25))
    sess.run(column_detector, steer_onto_target, None)
    cmds = [r["commanded_x"] for r in sess.report.timeline if r["commanded_x"] is not None]
    # alpha=0.25 from the press point: the command must ramp toward 700, not jump
    ramp = cmds[:3]
    check("5 low-pass smoothed the intent (command ramps, does not jump)",
          len(ramp) >= 3 and ramp[0] < 620 and ramp[0] < ramp[1] < ramp[2],
          str(ramp))


def case_blink_holds() -> None:
    class BlinkingScreen(FakeScreen):
        def capture(self):
            f = super().capture()
            if self.captures in (3, 4):        # two frames with no target
                return np.zeros((H, W, 3), dtype=np.uint8)
            return f

    screen = BlinkingScreen(x=300)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                        max_lost_frames=4,
                                                        hold_while_lost=True))
    rep = sess.run(column_detector, steer_onto_target, None)
    check("6 a brief loss is counted but does not abort", rep.lost_events >= 1, str(rep.lost_events))
    check("6 finger was still held through the blink", rep.presses == 1, str(rep.presses))
    check("6 no session was left stuck", all(not s["stuck"] for s in rep.touch_sessions))


def case_lost_release() -> None:
    screen = FakeScreen(x=300)
    screen.x = -9999.0     # never visible again
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                        max_lost_frames=3,
                                                        hold_while_lost=False))
    rep = sess.run(column_detector, steer_onto_target, None)
    check("7 released the finger when the target stayed lost",
          any(s["state"] == "RELEASED" for s in rep.touch_sessions), str(rep.touch_sessions))
    check("7 nothing stuck", all(not s["stuck"] for s in rep.touch_sessions))


def case_max_duration() -> None:
    screen = FakeScreen(x=300, drift=1.0)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=20,
                                                        max_session_duration_s=0.4))
    rep = sess.run(column_detector, steer_onto_target, None)
    check("8 max_session_duration stopped the loop", rep.outcome == "TIMEOUT", rep.outcome)
    check("8 finger lifted on timeout", all(not s["stuck"] for s in rep.touch_sessions))


def case_frozen_client() -> None:
    screen = FakeScreen(x=300, freeze_after=2)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0,
                                                         stale_frame_limit=5,
                                                         max_session_duration_s=10.0))
    rep = sess.run(column_detector, steer_onto_target, None)
    check("9 frozen client detected", rep.outcome == "CLIENT_FROZEN", rep.outcome)
    check("9 stopped early instead of steering blind", rep.frames < 40, str(rep.frames))
    check("9 finger lifted", all(not s["stuck"] for s in rep.touch_sessions))


def case_completion() -> None:
    screen = FakeScreen(x=300)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0))
    calls = {"n": 0}

    def completion(frame, _state):
        calls["n"] += 1
        return calls["n"] >= 4

    rep = sess.run(column_detector, steer_onto_target, completion)
    check("10 completion_detector ended the session", rep.outcome == "COMPLETED", rep.outcome)
    check("10 completion was checked on every frame", calls["n"] == rep.frames,
          f"{calls['n']} vs {rep.frames}")


def case_detector_exception() -> None:
    screen = FakeScreen(x=300)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0))

    def boom(_roi):
        raise ValueError("detector blew up")

    rep = sess.run(boom, steer_onto_target, None)
    check("11 detector exception -> ERROR", rep.outcome == "ERROR", rep.outcome)
    check("11 finger still lifted after the crash",
          all(not s["stuck"] for s in rep.touch_sessions), str(rep.touch_sessions))


def case_timings() -> None:
    screen = FakeScreen(x=300, drift=2.0)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0))
    rep = sess.run(column_detector, steer_onto_target, None)
    t = rep.timings()
    check("12 capture timing recorded", t["capture_ms"]["p50"] is not None)
    check("12 vision timing recorded", t["vision_ms"]["p50"] is not None)
    check("12 decision timing recorded", t["decision_ms"]["p50"] is not None)
    check("12 loop timing + hz recorded",
          t["loop_ms"]["p50"] is not None and t["loop_hz_median"] is not None,
          str(t["loop_hz_median"]))
    check("12 input timing recorded for sent moves", t["input_ms"]["p50"] is not None)


def case_scope() -> None:
    screen = FakeScreen(x=300)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0))
    sess.run(column_detector, steer_onto_target, None)
    forbidden = {"ocr", "observe_world"}
    check("13 the loop called only capture/touch verbs",
          not (set(screen.calls) & forbidden), str(set(screen.calls) & forbidden))
    src = (ROOT / "winter_agent_v2" / "visual_servo.py").read_text(encoding="utf-8")
    check("13 module does not import world state / scheduler / qwen / ocr",
          not any(k in src for k in ("from .brain", "from .scheduler", "import qwen",
                                     "from .ocr")), "forbidden import found")


def case_pacing() -> None:
    screen = FakeScreen(x=300)
    sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=10,
                                                        max_session_duration_s=0.75))
    rep = sess.run(column_detector, steer_onto_target, None)
    hz = rep.timings()["loop_hz_median"]
    check("14 target_hz pacing honoured (~10Hz)", hz is not None and 6.0 <= hz <= 14.0, str(hz))


def case_never_stuck() -> None:
    ok = True
    for kw in ({}, {"hold_while_lost": False}, {"max_session_duration_s": 0.2}):
        screen = FakeScreen(x=300)
        sess = VisualServoSession(screen, config=ServoConfig(anchor_y=10, target_hz=0, **kw))
        rep = sess.run(column_detector, steer_onto_target, None)
        ok = ok and all(not s["stuck"] for s in rep.touch_sessions)
        ok = ok and screen.finger is None   # lifted
    check("15 TOUCH was never left down on any outcome", ok)
    check("15 no session still holds a finger", not release_all("TEST_CLEANUP"))


def main() -> int:
    case_converge()
    case_track_moving()
    case_dead_zone()
    case_clamp()
    case_low_pass()
    case_blink_holds()
    case_lost_release()
    case_max_duration()
    case_frozen_client()
    case_completion()
    case_detector_exception()
    case_timings()
    case_scope()
    case_pacing()
    case_never_stuck()
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
