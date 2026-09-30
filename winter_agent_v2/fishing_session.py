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
import numpy as np
import cv2

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

    def __init__(self, *, mode: str = "AUTO", line_gain: float = 0.6,
                 calibrate_ticks: int = 0, max_tick_s: float | None = None,
                 smoothing: float = .25, hysteresis: float = .1,
                 prediction_horizon: float = .6, line_step_px: int = LINE_STEP_PX) -> None:
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
        self.smoothing, self.hysteresis = smoothing, hysteresis
        self.prediction_horizon, self.line_step_px = prediction_horizon, line_step_px
        self.effective_gain = .5  # measured prior; updated from real actuator/line deltas
        self._previous_pair = None
        self._smoothed_target = None
        self._last_delta = 0
        self.direction_reversals = self.large_steering_changes = self.phase_switch_count = 0
        self._ascent_votes = 0
        self._ascent_since = None

    # ------------------------------------------------------------------ helpers
    def _enter(self, phase: Phase) -> None:
        if phase is not self.phase:
            self.phase = phase
            self.phase_entered_at_tick = self.tick
            self.phase_switch_count += 1

    def _line_target(self, state: FishingFrame) -> int | None:
        """Descent policy: the clearest corridor below the hook."""
        if state.line_x is None or state.hook_y is None:
            return None
        # free_corridor needs the full frame; the controller only has the state, so
        # the caller supplies the last frame it captured (see set_frame()).
        frame = getattr(self, "_last_frame", None)
        if frame is None:
            return state.line_x
        height,width = frame.shape[:2]
        candidates = sorted({int(np.clip(state.line_x+d, width*.12, width*.88))
                             for d in (-140,-100,-60,0,60,100,140)})
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        water = ((hsv[:,:,0]>=85)&(hsv[:,:,0]<=115)&(hsv[:,:,1]>=150))
        top, bottom = min(height-1,state.hook_y+25), min(height,state.hook_y+260)
        scores = []
        for x in candidates:
            stripe = water[top:bottom,max(0,x-22):min(width,x+23)]
            free = float(np.mean(stripe)) if stripe.size else 1.0
            risk = 1-free
            for obstacle in state.obstacles:
                oy = obstacle['y']-state.hook_y
                if -20 <= oy <= 300:
                    clearance = abs(x-obstacle['x'])-obstacle['w']/2-28
                    risk += max(0, 1-clearance/100)*(1-oy/400)
            cost = risk + .12*abs(x-state.line_x)/140
            cost += .12*max(0, 70-min(x,width-x))/70
            if self._smoothed_target is not None:
                cost += .08*abs(x-self._smoothed_target)/140
            scores.append((cost,x))
        best = min(scores)
        current = min(scores,key=lambda p:abs(p[1]-state.line_x))
        want = best[1] if current[0]-best[0] > self.hysteresis else state.line_x
        self._route_risk = best[0]
        return want

    def _fish_target(self, state: FishingFrame) -> int | None:
        """Ascent policy: the nearest reachable fish head."""
        if not state.fish:
            return None
        hook_y = state.hook_y if state.hook_y is not None else 0
        reachable = [f for f in state.fish if (f.get("h") or 0) >= 8 and f.get('confidence',.75)>=.65]
        if not reachable:
            return None
        targets = []
        for fish in reachable:
            horizon = min(self.prediction_horizon,abs(fish['y']-hook_y)/200)
            x = fish['x']+fish.get('vx',0)*horizon
            if abs(x-(state.line_x or 360)) > 180 or abs(fish.get('vx',0))>400:
                continue
            if any(abs(x-o['x'])<o['w']/2+25 and abs(o['y']-hook_y)<180 for o in state.obstacles):
                continue
            targets.append((abs(fish['y']-hook_y)+.4*abs(x-(state.line_x or 360)),x))
        return int(min(targets)[1]) if targets else None

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
        self._state = state
        pair = (state.finger_x, state.line_x)
        if self._previous_pair is not None and all(v is not None for v in pair):
            pf,pl = self._previous_pair
            df,dl = pair[0]-pf,pair[1]-pl
            if 4 <= abs(df) <= 60 and 1 <= abs(dl) <= 70 and .1 <= dl/df <= 1.5:
                self.effective_gain = float(np.clip(.9*self.effective_gain+.1*dl/df,.2,1.2))
        if all(v is not None for v in pair):
            self._previous_pair = pair

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
            # In the recorded client the camera pins the descending hook near the TOP;
            # after the depth peak the hook travels DOWN the screen during retrieval.
            # Raw hook_y was previously interpreted with the opposite sign. Do not let
            # noisy scene correlation override this observed, sustained turnaround.
            ascent = rising > 25 and recent[-1]-min(self._depth_hist) >= 120
            self._ascent_votes = self._ascent_votes+1 if ascent else max(0,self._ascent_votes-1)
            at = state.meta.get('timestamp')
            if ascent and self._ascent_since is None:
                self._ascent_since = at
            if self._ascent_votes == 0:
                self._ascent_since = None
            confirmed = (self._ascent_votes>=PHASE_CONFIRM_TICKS or
                         self._ascent_votes>=2 and at is not None and self._ascent_since is not None
                         and at-self._ascent_since>=.25)
            if confirmed and self.phase is Phase.DESCENDING:
                self._enter(Phase.ASCENDING)  # one-way: camera scrolling cannot flip it back

        if self.phase is Phase.DESCENDING:
            want = self._line_target(state)
            return self._decide(want, "OBSTACLE_AVOIDANCE",
                                {"descent_risk_score":getattr(self,'_route_risk',None)})
        want = self._fish_target(state)
        if want is None:
            return self._decide(state.line_x, "FISH_TRACK_NO_TARGET", {"fish_seen": len(state.fish)})
        return self._decide(want, "INTERCEPT_TARGET", {"fish_seen": len(state.fish)})

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
        if self._smoothed_target is None:
            self._smoothed_target = float(want_line_x)
        self._smoothed_target += self.smoothing*(want_line_x-self._smoothed_target)
        want_line_x = round(self._smoothed_target)
        finger = getattr(self, "_finger_now", None)
        # fall back to proportional control in line space when the servo has not
        # published an actuator position yet (first tick)
        observed = getattr(self, "_observed_line_x", None)
        if finger is None or observed is None:
            return ServoCommand(desired_x=int(want_line_x), idle=False, note=reason)
        err = want_line_x - observed
        step = int(np.clip(round(err*self.line_gain/self.effective_gain),-self.line_step_px,self.line_step_px))
        step = int(np.clip(step,self._last_delta-8,self._last_delta+8))
        # Target smoothing must not carry the hook into an already visible hazard.
        # Compare the next observed-line displacement, never a cached touch point.
        state = getattr(self, "_state", None)
        if state is not None and state.hook_y is not None:
            def risk(x):
                return sum(max(0, 1-(abs(x-o['x'])-o['w']/2-28)/100)
                           * max(0, 1-(o['y']-state.hook_y)/350)
                           for o in state.obstacles if -20 <= o['y']-state.hook_y <= 280)
            if risk(observed+step*self.effective_gain) > risk(observed):
                step = 0
                extra['hazard_brake'] = True
        if self._last_delta*step < 0:
            self.direction_reversals += 1
        if abs(step-self._last_delta)>18:
            self.large_steering_changes += 1
        self._last_delta = step
        cmd = ServoCommand(desired_x=int(finger + step), idle=False, note=reason)
        extra["line_err"] = int(err)
        extra["finger_step"] = int(step)
        return cmd

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "ticks": self.tick, "phase": self.phase.value,
            "max_depth_px": self._max_depth, "lost_at_end": self._lost_streak,
            "calibration_samples": len(self.calibration),
            "effective_gain":self.effective_gain,
            "direction_reversals":self.direction_reversals,
            "large_steering_changes":self.large_steering_changes,
            "phase_switch_count":self.phase_switch_count,
            "decision_trace": self.trace[-40:],
        }
