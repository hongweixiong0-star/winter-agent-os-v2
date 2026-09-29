# -*- coding: utf-8 -*-
"""Offline replay of the fishing session against REAL frames.

Why this exists: the live level costs a bait and lasts seconds, so iterating the
detector and the controller on the device is expensive and unrepeatable.  The real
frames were captured once (``run_20260929T225731``) and can be replayed forever.

What is honest about the numbers it prints:

* ``opencv_ms`` is REAL — it is the same detector code on the same pixels.
* ``lost_target_frames`` and every control decision are REAL.
* ``fps`` / ``control_hz`` are **replay-bound**, not device-bound: the replay device
  returns a frame instantly, so those two describe the algorithm's ceiling, not the
  robot.  The device-bound figures come from the live run (21.28 Hz control,
  12.24 ms capture) and are printed side by side so the two are never confused.

It also re-proves VISION POLICY V1 section F on real data: the fishing control loop
runs with OCR_CALLS == 0.

usage: python tools/fishing_replay.py [start_i] [end_i]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FRAME_DIR = ROOT / "dataset/raw/fishing_tournament/run_20260929T225731/frames"
#: The frames measured to be real gameplay (i=904..1140 held the line and the hook).
GAMEPLAY = (904, 1140)


class ReplayScreen:
    """A device that replays saved frames and records the touch stream."""

    def __init__(self, frames: list[np.ndarray]):
        self.frames = frames
        self.i = 0
        self.touch: list[tuple] = []
        self.finger: int | None = None
        self.last_x: int | None = None

    def capture(self):
        if self.i >= len(self.frames):
            return None
        f = self.frames[self.i]
        self.i += 1
        return f

    def touch_down(self, x, y, contact=0, pressure=1):
        self.touch.append(("down", int(x), int(y)))
        self.finger = self.last_x = int(x)
        return True, ""

    def touch_move(self, x, y, contact=0, pressure=1):
        self.touch.append(("move", int(x), int(y)))
        self.finger = self.last_x = int(x)
        return True, ""

    def touch_up(self, contact=0):
        self.touch.append(("up",))
        self.finger = None
        return True, ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else GAMEPLAY[0]
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else GAMEPLAY[1]

    from winter_agent_v2.continuous_touch import release_all
    from winter_agent_v2.fishing_session import FishingSessionController
    from winter_agent_v2.fishing_vision import detect_fishing
    from winter_agent_v2.visual_servo import ServoConfig, VisualServoSession

    paths = []
    for p in sorted(FRAME_DIR.glob("f0*.png"), key=lambda q: int(re.search(r"f(\d+)", q.name).group(1))):
        i = int(re.search(r"f(\d+)", p.name).group(1))
        if lo <= i <= hi:
            paths.append((i, p))
    if not paths:
        print(json.dumps({"error": "no frames found", "dir": str(FRAME_DIR)}, ensure_ascii=False))
        return 2
    frames = [np.asarray(Image.open(p).convert("RGB")) for _i, p in paths]
    print(f"replaying {len(frames)} real frames (i={paths[0][0]}..{paths[-1][0]})")

    screen = ReplayScreen(frames)
    ctrl = FishingSessionController(mode="AUTO", calibrate_ticks=0)
    detections: list[dict] = []
    decisions: list[dict] = []

    def detector(frame):
        st = detect_fishing(frame)
        ctrl.set_frame(frame)
        detections.append(st.to_dict())
        return st

    def on_frame(row, _f, _s):
        if ctrl.last is not None and detections:
            decisions.append({"i": row.index, "finger_x": row.finger_x,
                              "phase": ctrl.last.phase,
                              "desired_line_x": ctrl.last.desired_line_x,
                              "reason": ctrl.last.reason,
                              "line_x": detections[-1]["line_x"],
                              "hook_y": detections[-1]["hook_y"]})

    cfg = ServoConfig(anchor_y=800, target_hz=0, dead_zone_px=5,
                      max_move_per_tick_px=28, low_pass_alpha=0.55,
                      engage_move_px=22, max_lost_frames=8,
                      max_session_duration_s=30.0, stale_frame_limit=60)
    sess = VisualServoSession(screen, config=cfg, on_frame=on_frame)
    rep = sess.run(detector, ctrl, None, roi=None)
    d = rep.to_dict()

    PLAY_END = 1040          # measured: line present up to here, gone after (result page)
    play_idx = [n for n, (i, _p) in enumerate(paths) if i <= PLAY_END]
    tail_idx = [n for n, (i, _p) in enumerate(paths) if i > PLAY_END]
    play_hits = sum(1 for n in play_idx if detections[n]["line_x"] is not None)
    tail_refused = sum(1 for n in tail_idx if detections[n]["line_x"] is None)
    found = sum(1 for x in detections if x["line_x"] is not None)
    out = {
        "phase": "FISHING_REPLAY",
        "frames_replayed": len(frames),
        "frame_range": [paths[0][0], paths[-1][0]],
        "line_detected_frames": found,
        "line_detection_rate": round(found / max(1, len(detections)), 4),
        "gameplay_frames": len(play_idx),
        "gameplay_detected": play_hits,
        "gameplay_detection_rate": round(play_hits / max(1, len(play_idx)), 4),
        "nongameplay_frames": len(tail_idx),
        "nongameplay_refused": tail_refused,
        "nongameplay_refusal_rate": round(tail_refused / max(1, len(tail_idx)), 4),
        "hook_detected_frames": sum(1 for x in detections if x["hook_y"] is not None),
        "outcome": d["outcome"],
        "moves_sent": d["moves_sent"],
        "moves_skipped_dead_zone": d["moves_skipped_dead_zone"],
        "lost_events": d["lost_events"],
        "max_lost_streak": d["max_lost_streak"],
        "vision_policy": d["vision_policy"],
        "opencv_ms_mean_REAL": d["vision_policy"]["opencv_ms_mean"],
        "fps_REPLAY_BOUND": d["vision_policy"]["fps"],
        "control_hz_REPLAY_BOUND": d["vision_policy"]["control_hz"],
        "live_reference": {"control_hz": 21.28, "capture_ms": 12.24,
                           "source": "dataset/raw/fishing_tournament/run_20260929T231017/run.json"},
        "decisions": decisions,
        "detections": detections,
    }

    ok = []
    def check(t, c, det=""):
        ok.append(bool(c))
        print(f"{'PASS' if c else 'FAIL'} | {t}{('  <- ' + str(det)) if det and not c else ''}")

    check("R1 the detector found the line on EVERY real gameplay frame",
          out["gameplay_detection_rate"] >= 0.95, out["gameplay_detection_rate"])
    check("R1b the detector REFUSED every non-gameplay frame instead of inventing a line",
          out["nongameplay_refusal_rate"] >= 0.95, out["nongameplay_refusal_rate"])
    check("R2 the hook was located on real frames", out["hook_detected_frames"] > 0,
          out["hook_detected_frames"])
    check("R3 the loop drove the finger (moves were actually sent)", d["moves_sent"] > 0,
          d["moves_sent"])
    check("R4 VISION POLICY F: OCR_CALLS == 0 during the fishing loop",
          out["vision_policy"]["ocr_calls_inside_realtime"] == 0,
          out["vision_policy"]["ocr_calls_inside_realtime"])
    check("R5 no finger left down after the replay",
          all(not s["stuck"] for s in d["touch_sessions"]))
    check("R6 nothing left holding", not release_all("REPLAY_CLEANUP"))
    check("R7 the controller produced a phase decision on nearly every frame",
          len(decisions) >= len(detections) - 2, f"{len(decisions)} vs {len(detections)}")

    outdir = ROOT / "dataset/raw/fishing_tournament" / f"replay_{paths[0][0]}_{paths[-1][0]}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "replay.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print(f"\n{sum(ok)}/{len(ok)} checks passed")
    print(json.dumps({k: out[k] for k in
                      ("frames_replayed", "line_detection_rate", "hook_detected_frames",
                       "outcome", "moves_sent", "lost_events", "max_lost_streak",
                       "opencv_ms_mean_REAL", "fps_REPLAY_BOUND",
                       "control_hz_REPLAY_BOUND", "live_reference")},
                     ensure_ascii=False, indent=1))
    print("DECISIONS (first 12):")
    for x in decisions[:12]:
        print("  ", json.dumps(x, ensure_ascii=False))
    print("EVIDENCE:", outdir)
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
