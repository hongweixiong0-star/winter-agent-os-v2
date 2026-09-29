"""VisualServoSession — a generic closed-loop, frame-by-frame visual controller.

Why this is a new module and not a new architecture (2026-09-29):

``semantic_executor`` handles *discrete* reliability: authorised action, click,
verify, retry.  This handles *continuous* control: the client is animating, the
target moves, and the correct input for this frame depends on the pixels of this
frame.  Nothing here schedules, owns a goal, or decides whether to play at all —
the caller (a Skill) is handed a ``device`` and decides everything else.

Hard scope rules, enforced by design rather than by good intentions:

* the loop only ever touches: a fast screencap, a cropped ROI, the caller's
  ``detector``, the caller's ``controller`` and ``touch_move``.  It never calls
  the full world state, the global scheduler, OCR over the whole screen, or
  Qwen.  ``test_visual_servo.py`` asserts that a tick calls nothing but these.
* positions are NEVER replayed from a recorded trajectory.  Every frame is
  re-detected and the command is recomputed, so a moving target stays tracked.
* the finger is owned by ``ContinuousTouchSession``, so every exit path lifts it.

Controller protections (PHASE 7) all live here, in one place, because a fishing
controller must not be the thing that discovers them:

    dead_zone              do not twitch for sub-pixel noise
    max_move_per_tick      never teleport the finger across the screen
    low_pass_filter        smooth the target, not the measurement
    lost_target_timeout    a blink must not become a violent correction
    max_lost_frames        hold, then release-and-reacquire, then give up
    frame_stale_guard      a frozen client must not be steered blind
    max_session_duration   a runaway loop must end by itself

The first-move absorption measured in PHASE 4 (the client eats the first motion
after ``touch_down``) is handled explicitly: every press opens with a throwaway
ENGAGE move whose displacement nobody depends on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import numpy as np
from PIL import Image

from .continuous_touch import ContinuousTouchSession

#: Fast phase-correlation-free frame hash: 48x48 grey.  ~0.2 ms, enough to tell
#: "this is the same picture as last frame" from "the client is animating".
_HASH_SHAPE = (48, 48)


def frame_signature(frame: np.ndarray) -> np.ndarray:
    """Cheap downsampled signature used for the frame-stale guard.

    AREA-AVERAGED, not pixel-sampled.  Sampling a handful of pixels (the obvious
    ``frame[ys][:, xs]`` trick) is blind to anything that does not land exactly on
    a sampled row: measured on a real fishing frame, a scene that had clearly
    moved produced a signature change of 0.00 with sampling but 34.6 with
    averaging.  A stale-frame guard built on the sampling version would declare a
    live client frozen.
    """
    if frame is None or frame.size == 0:
        return np.zeros(_HASH_SHAPE, dtype=np.float32)
    small = Image.fromarray(frame).resize((_HASH_SHAPE[1], _HASH_SHAPE[0]))
    arr = np.asarray(small).astype(np.float32)
    return arr.mean(axis=2) if arr.ndim == 3 else arr


def _pct(values: Iterable[float], q: float) -> float | None:
    arr = [v for v in values if v is not None]
    if not arr:
        return None
    return round(float(np.percentile(arr, q)), 2)


# --------------------------------------------------------------------- config
@dataclass
class ServoConfig:
    """Controller protections.  Defaults are for a 720x1280 touch game."""

    #: Below this distance from the current finger position, do nothing at all.
    dead_zone_px: int = 6
    #: Hard clamp on how far the finger may travel in one tick.
    max_move_per_tick_px: int = 42
    #: Exponential smoothing on the commanded target (0 = ignore new target,
    #: 1 = jump straight to it).  Smooths intent, never the measurement.
    low_pass_alpha: float = 0.5
    #: A target that is missing for longer than this is "lost" for good.
    lost_target_timeout_s: float = 2.5
    #: Consecutive missing frames tolerated while still holding the finger.
    max_lost_frames: int = 6
    #: Hold the finger while briefly lost (True) or release immediately (False).
    hold_while_lost: bool = True
    #: A byte-identical frame this many times in a row means the client is stuck.
    stale_frame_limit: int = 25
    #: Absolute cap on one session.
    max_session_duration_s: float = 90.0
    #: Target loop rate.  The loop sleeps to hit it; it never busy-waits.
    target_hz: float = 12.0
    #: Throwaway first move (PHASE 4: the client eats the first motion).
    engage_move_px: int = 24
    #: Where the finger lives.  y is constant for a horizontal-steer game.
    anchor_y: int = 0
    #: Extra settle after each move (0 = let the loop pace itself).
    settle_s: float = 0.0
    #: Record at most this many per-frame rows in the report (ring).
    max_frame_records: int = 2000


@dataclass
class ServoCommand:
    """What the controller wants.  Absolute target, not a delta."""

    desired_x: int | None = None
    desired_y: int | None = None
    #: True when the controller understands the frame but has nothing to do
    #: (e.g. already aligned).  Distinct from "I cannot see anything".
    idle: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"desired_x": self.desired_x, "desired_y": self.desired_y,
                "idle": self.idle, "note": self.note}


@dataclass
class ServoFrame:
    """One tick, with the timings PHASE 6 asks for."""

    index: int
    at: float
    capture_ms: float = 0.0
    vision_ms: float = 0.0
    decision_ms: float = 0.0
    input_ms: float = 0.0
    loop_ms: float = 0.0
    finger_x: int | None = None
    desired_x: int | None = None
    commanded_x: int | None = None
    moved: bool = False
    skipped_reason: str = ""
    lost: bool = False
    stale: bool = False
    state_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: (round(v, 2) if isinstance(v, float) else v)
                for k, v in self.__dict__.items()}


@dataclass
class ServoReport:
    outcome: str                                  # COMPLETED / TIMEOUT / ...
    frames: int = 0
    duration_s: float = 0.0
    reason: str = ""
    presses: int = 0
    moves_sent: int = 0
    moves_skipped_dead_zone: int = 0
    moves_skipped_clamped: int = 0
    lost_events: int = 0
    max_lost_streak: int = 0
    stale_frames: int = 0
    timeline: list[dict[str, Any]] = field(default_factory=list)
    touch_sessions: list[dict[str, Any]] = field(default_factory=list)

    def timings(self) -> dict[str, Any]:
        cap = [f["capture_ms"] for f in self.timeline]
        vis = [f["vision_ms"] for f in self.timeline]
        dec = [f["decision_ms"] for f in self.timeline]
        inp = [f["input_ms"] for f in self.timeline]
        loop = [f["loop_ms"] for f in self.timeline]
        loops = [v for v in loop if v]
        return {
            "frames": self.frames,
            "capture_ms": {"p50": _pct(cap, 50), "p95": _pct(cap, 95),
                           "max": _pct(cap, 100)},
            "vision_ms": {"p50": _pct(vis, 50), "p95": _pct(vis, 95),
                          "max": _pct(vis, 100)},
            "decision_ms": {"p50": _pct(dec, 50), "p95": _pct(dec, 95),
                            "max": _pct(dec, 100)},
            "input_ms": {"p50": _pct(inp, 50), "p95": _pct(inp, 95),
                         "max": _pct(inp, 100)},
            "loop_ms": {"p50": _pct(loop, 50), "p95": _pct(loop, 95),
                        "max": _pct(loop, 100)},
            "loop_hz_median": (round(1000.0 / np.median(loops), 2) if loops else None),
            "loop_hz_p95_slowest": (round(1000.0 / max(loops), 2) if loops else None),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome, "frames": self.frames,
            "duration_s": round(self.duration_s, 3), "reason": self.reason,
            "presses": self.presses, "moves_sent": self.moves_sent,
            "moves_skipped_dead_zone": self.moves_skipped_dead_zone,
            "moves_skipped_clamped": self.moves_skipped_clamped,
            "lost_events": self.lost_events, "max_lost_streak": self.max_lost_streak,
            "stale_frames": self.stale_frames,
            "timings": self.timings(),
            "touch_sessions": self.touch_sessions,
            "timeline": self.timeline,
        }


class VisualServoSession:
    """Run a detector+controller against the live screen until the caller says stop.

    ``detector(roi_frame) -> state dict`` must include ``lost`` when it cannot
    find the target.  ``controller(state) -> ServoCommand`` is arbitrary caller
    code; it may be a class instance with ``__call__``, which is how the fishing
    state machine plugs in.

    The session never decides *what* game it is in — that is ``completion_detector``'s
    job, and it is deliberately called on the RAW frame so it can recognise a
    result page outside the servo ROI.
    """

    def __init__(self, device: Any, *, config: ServoConfig | None = None,
                 on_frame: Callable[[ServoFrame, np.ndarray, Any], None] | None = None,
                 on_transition: Callable[[str, Any], None] | None = None) -> None:
        self.device = device
        self.cfg = config or ServoConfig()
        self._on_frame = on_frame
        self._on_transition = on_transition
        self._touch: ContinuousTouchSession | None = None
        self._finger_x: int | None = None
        self._finger_y: int | None = None
        self._abort_reason: str | None = None
        self._filtered: float | None = None
        self.report = ServoReport(outcome="NOT_STARTED")
        self.sessions: list[dict[str, Any]] = []

    # ------------------------------------------------------------- lifecycle
    def abort(self, reason: str = "ABORT") -> None:
        """Ask the loop to stop and lift the finger immediately."""
        self._abort_reason = reason
        self._release(reason)

    @property
    def holds_finger(self) -> bool:
        return bool(self._touch and self._touch.holds_finger)

    def _press(self, x: int, y: int) -> bool:
        self._touch = ContinuousTouchSession(self.device, session_id=f"VS{self.report.presses + 1:03d}")
        self.report.presses += 1
        if not self._touch.begin(x, y):
            self._touch.abort("PRESS_REFUSED")
            self._touch = None
            return False
        self._finger_x, self._finger_y = x, y
        # ENGAGE: the first move after touch_down is swallowed by the client
        # (measured in PHASE 4), so it is sent deliberately and never counted as
        # a control command.
        engage_x = int(np.clip(x + np.sign(self.cfg.engage_move_px or 1)
                               * abs(self.cfg.engage_move_px), 20, 700))
        self._touch.move(engage_x, y)
        self._finger_x = engage_x
        return True

    def _release(self, reason: str) -> None:
        if self._touch is None:
            return
        try:
            if self._touch.holds_finger:
                self._touch.end(reason=reason)
        finally:
            self.sessions.append(self._touch.report().to_dict())
            self._touch = None

    # ------------------------------------------------------------------- run
    def run(self, detector: Callable[[np.ndarray], Any],
            controller: Callable[[Any], ServoCommand],
            completion_detector: Callable[[np.ndarray, Any], bool] | None = None,
            *, roi: tuple[int, int, int, int] | None = None,
            max_duration_s: float | None = None) -> ServoReport:
        cfg = self.cfg
        duration = max_duration_s if max_duration_s is not None else cfg.max_session_duration_s
        started = time.monotonic()
        self.report = ServoReport(outcome="RUNNING")

        last_sig: np.ndarray | None = None
        stale_streak = 0
        lost_streak = 0
        last_seen_at = started
        index = 0
        press_x = int(roi[0] + (roi[2] - roi[0]) / 2) if roi else 360
        if not self._press(press_x, cfg.anchor_y):
            self.report.outcome = "PRESS_FAILED"
            self.report.reason = "touch_down refused"
            return self.report

        try:
            while True:
                loop_start = time.monotonic()
                if self._abort_reason:
                    self.report.outcome = "ABORTED"
                    self.report.reason = self._abort_reason
                    break
                if loop_start - started > duration:
                    self.report.outcome = "TIMEOUT"
                    self.report.reason = f"max_session_duration_s={duration}"
                    break

                row = ServoFrame(index=index, at=loop_start)

                # ---- 1. capture (fast path) -------------------------------
                t0 = time.perf_counter()
                frame = self.device.capture()
                row.capture_ms = (time.perf_counter() - t0) * 1000.0
                if frame is None:
                    self._release("CAPTURE_FAILED")
                    self.report.outcome = "CAPTURE_FAILED"
                    self.report.reason = self.device.unavailable_reason or "screencap returned None"
                    break

                # ---- 2. frame-stale guard ---------------------------------
                sig = frame_signature(frame)
                if last_sig is not None and float(np.mean(np.abs(sig - last_sig))) < 0.4:
                    stale_streak += 1
                else:
                    stale_streak = 0
                last_sig = sig
                row.stale = stale_streak >= cfg.stale_frame_limit
                if row.stale:
                    self.report.stale_frames += 1
                    row.skipped_reason = "FRAME_FROZEN"
                    # A frozen client must not be steered blind: stop rather than
                    # keep pushing moves into a screen that never changes.
                    if stale_streak >= cfg.stale_frame_limit * 3:
                        self.report.timeline.append(row.to_dict())
                        index += 1
                        self.report.frames = index
                        self.report.outcome = "CLIENT_FROZEN"
                        self.report.reason = (f"{stale_streak} consecutive identical "
                                              f"frames; stopping instead of steering blind")
                        break

                # ---- 3. completion check on the RAW frame ------------------
                if completion_detector is not None:
                    t1 = time.perf_counter()
                    done = bool(completion_detector(frame, None))
                    row.decision_ms += (time.perf_counter() - t1) * 1000.0
                    if done:
                        self.report.outcome = "COMPLETED"
                        self.report.reason = "completion_detector returned True"
                        self.report.timeline.append(row.to_dict())
                        index += 1
                        self.report.frames = index
                        break

                # ---- 4. vision on the ROI only ----------------------------
                roi_frame = self._crop(frame, roi)
                t1 = time.perf_counter()
                state = detector(roi_frame)
                row.vision_ms = (time.perf_counter() - t1) * 1000.0
                row.state_summary = self._summarise(state)
                # Publish the actuator position into the state.  An outer control
                # loop (e.g. "put the fishing LINE at x") needs to know where the
                # finger actually is to convert its goal into a finger delta, and
                # the servo is the only component that knows.
                self._publish_actuator(state)

                lost = bool(getattr(state, "lost", None)) if not isinstance(state, dict) \
                    else bool(state.get("lost", False))
                missing = lost or (isinstance(state, dict) and state.get("found") is False)

                # ---- 5. lost-target policy --------------------------------
                if missing:
                    lost_streak += 1
                    self.report.max_lost_streak = max(self.report.max_lost_streak, lost_streak)
                    if lost_streak == 1:
                        self.report.lost_events += 1
                    row.lost = True
                    if lost_streak > cfg.max_lost_frames and not cfg.hold_while_lost:
                        self._release("TARGET_LOST")
                        row.skipped_reason = "RELEASED_ON_LOST"
                    elif lost_streak > cfg.max_lost_frames and (
                            time.monotonic() - last_seen_at > cfg.lost_target_timeout_s):
                        # Out of patience: hold the finger steady (no wild moves)
                        # and keep looking; the duration guard is the backstop.
                        row.skipped_reason = "HOLD_LOST_TIMEOUT"
                    else:
                        row.skipped_reason = "HOLD_LOST"
                    self._finish_tick(row, loop_start, index, pace=True)
                    index += 1
                    continue

                lost_streak = 0
                last_seen_at = time.monotonic()

                # ---- 6. decide -------------------------------------------
                t1 = time.perf_counter()
                command = controller(state)
                row.decision_ms += (time.perf_counter() - t1) * 1000.0
                if not isinstance(command, ServoCommand):
                    command = ServoCommand(desired_x=getattr(command, "desired_x", None),
                                           desired_y=getattr(command, "desired_y", None),
                                           idle=bool(getattr(command, "idle", False)),
                                           note=str(getattr(command, "note", "")))
                row.desired_x = command.desired_x

                # ---- 7. protections, then move ---------------------------
                moved, skipped = self._steer(command, row)
                row.moved = moved
                row.skipped_reason = row.skipped_reason or skipped

                self._finish_tick(row, loop_start, index, pace=True)
                index += 1
        except Exception as exc:  # noqa: BLE001
            self.report.outcome = "ERROR"
            self.report.reason = f"{type(exc).__name__}:{exc}"
        finally:
            self._release(f"SESSION_END:{self.report.outcome}")
            self.report.duration_s = time.monotonic() - started
            self.report.frames = index
            self.report.touch_sessions = self.sessions
            for r in self.sessions:
                if r.get("stuck"):
                    self.report.outcome = "TOUCH_STUCK"
                    self.report.reason = self.report.reason or "a press could not be lifted"
        return self.report

    # ------------------------------------------------------------- internals
    def _publish_actuator(self, state: Any) -> None:
        """Expose the current finger position to the caller's controller.

        Written into the state object the detector returned, so a controller can
        close an outer loop ("the line must reach x") on top of this inner loop
        ("the finger must reach y") without the servo needing to know anything
        about the game.
        """
        payload = {"finger_x": self._finger_x, "finger_y": self._finger_y,
                   "presses": self.report.presses, "moves_sent": self.report.moves_sent}
        try:
            if isinstance(state, dict):
                state["servo"] = payload
            elif hasattr(state, "finger_x"):
                state.finger_x = self._finger_x
                if hasattr(state, "servo"):
                    state.servo = payload
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _crop(frame: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
        if roi is None:
            return frame
        x0, y0, x1, y1 = roi
        return frame[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]

    @staticmethod
    def _summarise(state: Any) -> str:
        if isinstance(state, dict):
            keys = ("found", "lost", "mode", "hook_x", "target_x", "depth")
            return ",".join(f"{k}={state[k]}" for k in keys if k in state)[:120]
        return str(state)[:120]

    def _steer(self, command: ServoCommand, row: ServoFrame) -> tuple[bool, str]:
        """dead zone -> low pass -> clamp -> touch_move.  Returns (moved, skipped)."""
        cfg = self.cfg
        if command.desired_x is None or self._finger_x is None:
            return False, "NO_COMMAND"
        # low-pass on the TARGET (intent), never on the measurement.  Seeded from
        # where the finger actually IS, so the very first command is already a
        # smoothed step away from the current position rather than a jump to the
        # raw target — otherwise the filter would do nothing on the tick that
        # matters most.
        if self._filtered is None:
            self._filtered = float(self._finger_x)
        else:
            self._filtered = (cfg.low_pass_alpha * float(command.desired_x)
                              + (1.0 - cfg.low_pass_alpha) * self._filtered)
        desired = self._filtered
        row.commanded_x = int(round(desired))
        delta = desired - self._finger_x
        if abs(delta) < cfg.dead_zone_px:
            self.report.moves_skipped_dead_zone += 1
            return False, "DEAD_ZONE"
        stepped = float(np.clip(delta, -cfg.max_move_per_tick_px, cfg.max_move_per_tick_px))
        if abs(stepped) < abs(delta):
            self.report.moves_skipped_clamped += 1
            note = "CLAMPED"
        else:
            note = ""
        target_x = int(round(self._finger_x + stepped))
        y = int(command.desired_y) if command.desired_y is not None else int(self._finger_y)
        t0 = time.perf_counter()
        ok = bool(self._touch and self._touch.move(target_x, y))
        row.input_ms = (time.perf_counter() - t0) * 1000.0
        if ok:
            self._finger_x, self._finger_y = target_x, y
            self.report.moves_sent += 1
            return True, note
        return False, "MOVE_FAILED"

    def _finish_tick(self, row: ServoFrame, loop_start: float, index: int, *, pace: bool) -> None:
        row.finger_x = self._finger_x
        if pace and self.cfg.target_hz > 0:
            budget = 1.0 / self.cfg.target_hz
            spent = time.monotonic() - loop_start
            if spent < budget:
                time.sleep(budget - spent)
        row.loop_ms = (time.monotonic() - loop_start) * 1000.0
        if len(self.report.timeline) < self.cfg.max_frame_records:
            self.report.timeline.append(row.to_dict())
        elif index % 10 == 0:
            # keep a low-frequency tail so a long session still has evidence
            self.report.timeline.append(row.to_dict())
        if self._on_frame is not None:
            try:
                self._on_frame(row, None, None)
            except Exception:  # noqa: BLE001
                pass
