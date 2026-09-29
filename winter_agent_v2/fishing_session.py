"""FishingSessionController — the ice-fishing state machine and its two policies.

This is a Skill-internal controller, not a scheduler (PHASE 8 explicit rule).  It
receives one ``FishingFrame`` per tick and returns one ``ServoCommand``.  It owns
no device, opens no lease, and never decides whether to play.

Two nested loops
----------------
The servo closes an INNER loop on the finger position.  The line, however, is what
has to reach a target.  So this controller closes an OUTER loop: it asks the servo
where the finger is, compares the OBSERVED line position with the wanted one, and
returns a finger delta.  That makes the finger→line mapping self-calibrating —
it is never assumed, it is measured by the loop itself.

Phases (PHASE 7 spec)
---------------------
    FISHING_READY → CAST_START → DESCENDING → ASCENDING → RESULT → COMPLETE
    plus PAUSED / FAILED / UNKNOWN

v1 policies, deliberately simple (PHASE 12: do not over-engineer the first one)

* DESCENDING — **OBSTACLE_AVOIDANCE**: keep the hook in the clearest water.  The
  corridor probe scores left/centre/right below the hook; the controller nudges
  the line toward the best one but only when the difference is real, so it does
  not oscillate between near-equal options.
* ASCENDING — **FISH_HEAD_TRACKING**: drive the line onto the nearest reachable
  coloured blob (a fish), preferring the one closest to the hook vertically.
* Target briefly lost → hold, never lunge (the servo already protects the input;
  this protects the *decision*).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .fishing_vision import FishingFrame, free_corridor
from .visual_servo import ServoCommand

#: The line may only be asked to move this far per tick.  Matches the servo's own
#: clamp so the two loops cannot disagree about what is reachable.
LINE_STEP_PX = 26
#: A corridor must beat the runner-up by this many free pixels before the descent
#: policy will move at all.
CORRIDOR_MARGIN = 900
#: Phase decision: this many consecutive ticks of rising hook_y mean "descending".
PHASE_CONFIRM_TICKS = 6


class Phase(str, Enum):
    READY = "FISHING_READY"
    CAST_START = "CAST_START"
    DESCENDING = "DESCENDING"
    ASCENDING = "ASCENDING"
    RESULT = "RESULT"
    COMPLETE = "COMPLETE"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class FishingDecision:
    phase: str
    desired_line_x: int | None
    reason: str
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "desired_line_x": self.desired_line_x,
                "reason": self.reason, **self.extras}


class FishingSessionController:
    """Turn a per-frame FishingFrame into a per-frame steering decision."""

    def __init__(self, *, mode: str = "AUTO", line_gain: float = 0.85,
                 calibrate_ticks: int = 0, max_tick_s: float | None = None) -> None:
        self.mode = mode
        self.line_gain = line_gain
        #: Run the calibration legs for this many ticks before handing over to the
        #: real policy.  This is how closed-loop AUTHORITY over the line is proven
        #: rather than assumed: two known targets, and the pixels are compared
        #: against them.  Measured on the real level the actionable window is only
        #: a few seconds, so this must be short.
        self.calibrate_ticks = calibrate_ticks
        self.phase = Phase.READY
        self.phase_entered_at_tick = 0
        self.tick = 0
        #: calibration bookkeeping (mode="CALIBRATE")
        self.calibration: list[dict[str, Any]] = []
        self.cal_targets: tuple[int, int] | None = None
        self.cal_hold_ticks = 13
        self.last: FishingDecision | None = None
        self.trace: list[dict[str, Any]] = []
        self._depth_hist: list[int] = []
        self._lost_streak = 0
        self._max_depth = 0
        self._best_line_x: int | None = None

    # ------------------------------------------------------------------ helpers
    def _enter(self, phase: Phase) -> None:
        if phase is not self.phase:
            self.phase = phase
            self.phase_entered_at_tick = self.tick

    def _line_target(self, state: FishingFrame) -> int | None:
        """Descent policy: the clearest corridor below the hook."""
        if state.line_x is None or state.hook_y is None:
            return None
        # free_corridor needs the full frame; the controller only has the state, so
        # the caller supplies the last frame it captured (see set_frame()).
        frame = getattr(self, "_last_frame", None)
        if frame is None:
            return state.line_x
        try:
            corr = free_corridor(frame, state.line_x, state.hook_y)
        except Exception:  # noqa: BLE001
            return state.line_x
        order = sorted(("left", "centre", "right"), key=lambda k: -corr[k])
        best, second = order[0], order[1]
        if corr[best] - corr[second] < CORRIDOR_MARGIN:
            return state.line_x                    # near-tie: do not twitch
        dx = {"left": -70, "centre": 0, "right": 70}[best]
        return int(state.line_x + dx)

    def _fish_target(self, state: FishingFrame) -> int | None:
        """Ascent policy: the nearest reachable fish head."""
        if not state.fish:
            return None
        hook_y = state.hook_y if state.hook_y is not None else 0
        reachable = [f for f in state.fish if (f.get("h") or 0) >= 18]
        if not reachable:
            return None
        pick = min(reachable, key=lambda f: abs(f["y"] - hook_y) + abs(f["x"] - (state.line_x or 360)) * 0.35)
        return int(pick["x"])

    def set_frame(self, frame) -> None:
        """The caller hands over the frame it just fed the detector.

        Kept as a setter so the controller's ``__call__`` signature stays exactly
        ``controller(state)`` as specified.
        """
        self._last_frame = frame

    # -------------------------------------------------------------------- call
    def __call__(self, state: FishingFrame) -> ServoCommand:
        self.tick += 1
        # The servo published the actuator position into the state; the detector
        # published where the line actually is.  Both are needed to turn a line
        # goal into a finger delta.
        self._finger_now = state.finger_x
        self._observed_line_x = state.line_x

        # ---- lost handling (decision-level protection) ----
        if getattr(state, "lost", True) or state.line_x is None:
            self._lost_streak += 1
            if self._lost_streak >= 25:
                self._enter(Phase.UNKNOWN)
            return self._decide(None, "LOST_HOLD", {"lost_streak": self._lost_streak})
        self._lost_streak = 0
        if self._best_line_x is None:
            self._best_line_x = state.line_x

        # ---- phase from observed depth trend ----
        if state.hook_y is not None:
            self._depth_hist.append(int(state.hook_y))
            if len(self._depth_hist) > 120:
                del self._depth_hist[:40]
            self._max_depth = max(self._max_depth, int(state.hook_y))

        if self.mode == "CALIBRATE" or (self.calibrate_ticks and self.tick <= self.calibrate_ticks):
            return self._calibrate(state)

        if self.phase in (Phase.READY, Phase.CAST_START):
            self._enter(Phase.DESCENDING)
        elif self.phase in (Phase.DESCENDING, Phase.ASCENDING) and len(self._depth_hist) > PHASE_CONFIRM_TICKS:
            recent = self._depth_hist[-PHASE_CONFIRM_TICKS:]
            rising = recent[-1] - recent[0]
            if rising > 18 and self.phase is Phase.ASCENDING:
                self._enter(Phase.DESCENDING)
            elif rising < -18 and self.phase is Phase.DESCENDING:
                self._enter(Phase.ASCENDING)

        if self.phase is Phase.DESCENDING:
            want = self._line_target(state)
            return self._decide(want, "OBSTACLE_AVOIDANCE",
                                {"corridor": self.last.extras.get("corridor") if self.last else None})
        want = self._fish_target(state)
        if want is None:
            return self._decide(state.line_x, "FISH_TRACK_NO_TARGET", {"fish_seen": len(state.fish)})
        return self._decide(want, "FISH_HEAD_TRACKING", {"fish_seen": len(state.fish)})

    def _calibrate(self, state: FishingFrame) -> ServoCommand:
        """Drive the line to two known targets and record what the pixels did.

        This is the experiment that proves closed-loop authority over the line, and
        it measures the finger→line gain instead of assuming it.  The targets are
        anchored on the FIRST observed line position, because the line starts
        wherever the game put it rather than at a known x.
        """
        if self.cal_targets is None:
            base = state.line_x or 360
            self.cal_targets = (max(140, base - 95), min(580, base + 95))
        leg = (self.tick // self.cal_hold_ticks) % 2
        want = self.cal_targets[leg]
        self.calibration.append({
            "tick": self.tick, "target_line_x": want, "observed_line_x": state.line_x,
            "finger_x": state.finger_x, "hook_y": state.hook_y,
        })
        return self._decide(want, "CALIBRATE", {"leg": leg})

    def _decide(self, want_line_x: int | None, reason: str,
                extras: dict[str, Any]) -> ServoCommand:
        """Convert 'the LINE must be at X' into 'move the FINGER by dx'."""
        extra = dict(extras)
        self.last = FishingDecision(phase=self.phase.value, desired_line_x=want_line_x,
                                    reason=reason, extras=extra)
        if want_line_x is None:
            return ServoCommand(desired_x=None, idle=True, note=reason)
        finger = getattr(self, "_finger_now", None)
        # fall back to proportional control in line space when the servo has not
        # published an actuator position yet (first tick)
        observed = getattr(self, "_observed_line_x", None)
        if finger is None or observed is None:
            return ServoCommand(desired_x=int(want_line_x), idle=False, note=reason)
        err = want_line_x - observed
        step = max(-LINE_STEP_PX, min(LINE_STEP_PX, int(round(err * self.line_gain))))
        cmd = ServoCommand(desired_x=int(finger + step), idle=False, note=reason)
        extra["line_err"] = int(err)
        extra["finger_step"] = int(step)
        return cmd

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "ticks": self.tick, "phase": self.phase.value,
            "max_depth_px": self._max_depth, "lost_at_end": self._lost_streak,
            "calibration_samples": len(self.calibration),
            "decision_trace": self.trace[-40:],
        }
