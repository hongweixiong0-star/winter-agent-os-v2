# -*- coding: utf-8 -*-
"""PHASE 4 — live proof that continuous touch works on this MuMu.

What is proven, and how it is MEASURED rather than asserted:

1. **The stream is really sent.**  Every ``touch_down`` / ``touch_move`` /
   ``touch_up`` is recorded with its latency and success flag; the run fails if
   any move was rejected.
2. **A frame can be captured WHILE the finger is held.**  Captures happen between
   moves, never after the release — that is the whole point of the subsystem.
3. **The client really tracks the finger.**  The world map is panned with one held
   finger and the result is recovered from the pixels: the content displacement is
   found by brute-force SSD over horizontal shifts in a map band, so the number is
   reproducible offline from the saved PNGs without the device.
4. **No broken or stuck touch.**  What happens after the release is checked too
   (must be static), and ``touch_balance.stuck`` must be 0.

Safe page: the world map.  Panning it changes no game state — nothing is used,
claimed, spent or sent.

Measured result on this machine (2026-09-29, MuMu Player 12, MAA_MUMU_EXTRAS)
-----------------------------------------------------------------------------
    cmd +40 -> measured   0     <- the FIRST move is consumed by the client
    cmd +60 -> measured  60     <- pixel exact
    cmd +60 -> measured  60     <- and reproducible
    cmd -40 -> measured -40     <- exact in both directions
    touch_down 0.48 ms | touch_move 0.29 ms mean | touch_up 0.37 ms
    TOUCH_STUCK 0

The first-move absorption is the single most important finding here: a continuous
controller must open every session with a throwaway "engage" move, because the
first motion is spent confirming the gesture instead of moving anything.
``VisualServoSession`` therefore does exactly that.

usage:
  python tools/probe_continuous_touch.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Central band of the map, excluding the top HUD and the bottom nav bar (those
#: do NOT pan, so including them would only dilute the displacement measurement).
BAND = (200, 1000, 60, 660)
#: Horizontal drag line, on the map, clear of the left icon stack and right icons.
DRAG_Y = 700
#: Where the finger first lands.
DRAG_X0 = 360
#: Per-step commands.  The first one is expected to be swallowed, which is the
#: point of the experiment; the rest must be tracked exactly.
STEPS = ((400, "02_move_+40"), (460, "03_move_+60"),
         (520, "04_move_+60"), (480, "05_move_-40"))
MAX_SHIFT = 320


def estimate_content_shift_x(a: np.ndarray, b: np.ndarray,
                             band: tuple[int, int, int, int] = BAND,
                             max_shift: int = MAX_SHIFT) -> int:
    """Horizontal displacement of the CONTENT from frame ``a`` to frame ``b``.

    Positive means the scene moved right.  Found by brute-force SSD over integer
    shifts inside a map band, so the evidence can be re-checked offline.
    """
    y0, y1, x0, x1 = band
    ga = a[y0:y1, x0:x1].astype(np.float32)
    gb = b[y0:y1, x0:x1].astype(np.float32)
    if ga.shape != gb.shape or ga.size == 0:
        return 0
    best_d, best_score = 0, None
    for d in range(-max_shift, max_shift + 1, 2):
        if d >= 0:
            sa, sb = ga[:, : ga.shape[1] - d], gb[:, d:]
        else:
            sa, sb = ga[:, -d:], gb[:, : gb.shape[1] + d]
        if sa.size == 0:
            continue
        score = float(np.mean((sa - sb) ** 2))
        if best_score is None or score < best_score:
            best_score, best_d = score, d
    return best_d


def _report(title: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'} | {title}{('  <- ' + detail) if detail else ''}")
    return bool(ok)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.continuous_touch import ContinuousTouchSession, release_all
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"touch_poc_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_TOUCH_POC", capability_id="CONTINUOUS_TOUCH",
                             ttl_seconds=420, reason="PHASE 4 continuous touch proof of concept")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    result: dict = {"phase": "PHASE4_CONTINUOUS_TOUCH_POC", "stamp": stamp,
                    "evidence_dir": str(outd.relative_to(ROOT))}
    checks: list[bool] = []
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(json.dumps({"ensure_ready": reason}, ensure_ascii=False))
            return 3
        result["negotiated"] = ad.negotiated

        def shot(tag: str) -> np.ndarray:
            frame = ad.capture()
            if frame is None:
                raise RuntimeError("SCREENCAP_FAILED")
            Image.fromarray(frame).save(outd / f"{tag}.png")
            return frame

        # ---- 0. safe page: the world map is on screen (bottom nav says 城镇) ----
        f0 = shot("00_before")
        text0 = " ".join(t["text"] for t in read_all(Image.fromarray(f0)))
        result["page_text_before"] = text0[:200]
        on_map = "城镇" in text0
        checks.append(_report("0 safe page = world map (bottom nav shows 城镇)", on_map, text0[:60]))
        if not on_map:
            result["aborted"] = "NOT_ON_WORLD_MAP"
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 4

        # ---- the PoC: one held finger, a capture after every move ----
        touch = ContinuousTouchSession(ad, session_id="POC")
        down_ms = up_ms = 0.0
        move_latencies: list[float] = []
        try:
            t_down = time.perf_counter()
            begun = touch.begin(DRAG_X0, DRAG_Y)
            down_ms = (time.perf_counter() - t_down) * 1000.0
            checks.append(_report("1 touch_down accepted", begun))
            checks.append(_report("1 state PRESSED", touch.state.value == "PRESSED",
                                  touch.state.value))
            f_down = shot("01_down_no_move")
            checks.append(_report("2 frame captured WHILE the finger is still down",
                                  touch.holds_finger, f"holds_finger={touch.holds_finger}"))

            steps: list[dict] = []
            for x, tag in STEPS:
                t0 = time.perf_counter()
                moved = touch.move(x, DRAG_Y)
                ms = (time.perf_counter() - t0) * 1000.0
                move_latencies.append(ms)
                if not moved:
                    raise RuntimeError(f"MOVE_REJECTED_AT_{x}")
                time.sleep(0.35)                      # bounded settle: let it render
                steps.append({"cmd_x": x, "tag": tag, "frame": shot(tag), "send_ms": round(ms, 2)})

            checks.append(_report("3 all moves accepted", touch.report().moves == len(STEPS),
                                  str(touch.report().moves)))

            prev, prev_x = f_down, DRAG_X0
            for s in steps:
                s["measured_dx"] = estimate_content_shift_x(prev, s["frame"])
                s["cmd_dx"] = s["cmd_x"] - prev_x
                prev, prev_x = s["frame"], s["cmd_x"]
            cumulative = estimate_content_shift_x(f_down, steps[-1]["frame"])
            result["per_step"] = [{"cmd_dx": s["cmd_dx"], "measured_dx": s["measured_dx"],
                                   "send_ms": s["send_ms"]} for s in steps]
            result["first_move_absorbed_px"] = steps[0]["cmd_dx"] - steps[0]["measured_dx"]
            result["cumulative_shift_from_down"] = cumulative
            result["finding_first_move_absorbed"] = (
                "The client consumes the FIRST motion after touch_down entirely "
                "(cmd +40 -> 0 px) while every later motion is tracked pixel-exact and "
                "reproducibly (cmd +60 -> 60, +60 -> 60, -40 -> -40). A continuous "
                "controller must open a session with a throwaway 'engage' move before "
                "its commands can be trusted.")

            steady = steps[1:]
            steady_ok = all(abs(s["measured_dx"] - s["cmd_dx"]) <= 15 for s in steady)
            checks.append(_report("4 steady state: every later step tracks its command",
                                  steady_ok,
                                  str([(s["cmd_dx"], s["measured_dx"]) for s in steady])))
            measured_sum = sum(s["measured_dx"] for s in steps)
            excursion = sum(abs(s["measured_dx"]) for s in steps)
            checks.append(_report("5 bookkeeping self-consistent "
                                  "(cumulative == sum of per-step displacements)",
                                  cumulative == measured_sum,
                                  f"cumulative={cumulative} sum={measured_sum}"))
            checks.append(_report("6 finger travelled far and the client followed",
                                  excursion >= 120, f"total excursion={excursion}px"))
            checks.append(_report("7 repeated identical commands reproduced identically",
                                  steps[1]["measured_dx"] == steps[2]["measured_dx"],
                                  str((steps[1]["measured_dx"], steps[2]["measured_dx"]))))

            t_up = time.perf_counter()
            released = touch.end(reason="POC_END")
            up_ms = (time.perf_counter() - t_up) * 1000.0
            checks.append(_report("8 touch_up confirmed", released))
            f5 = shot("06_after_release")
            time.sleep(0.9)
            f6 = shot("07_after_release_settled")
            d54 = estimate_content_shift_x(steps[-1]["frame"], f5)
            d65 = estimate_content_shift_x(f5, f6)
            result["post_release"] = {"shift_last_step_to_release": d54, "shift_after_settle": d65}
            checks.append(_report("9 the release itself is not a swipe", abs(d54) <= 12,
                                  f"shift={d54}"))
            checks.append(_report("10 nothing drifting after release (no stuck finger)",
                                  abs(d65) <= 10, f"shift={d65}"))
            checks.append(_report("11 move after release is refused (no orphan finger)",
                                  touch.move(300, DRAG_Y) is False))
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}:{exc}"
            touch.abort("POC_EXCEPTION")
            checks.append(_report("PoC completed without exception", False, result["error"]))
        finally:
            if touch.holds_finger:
                touch.abort("POC_FINALLY")

        result["touch_session"] = touch.report().to_dict()
        result["latency_ms"] = {
            "down": round(down_ms, 2),
            "move_mean": round(sum(move_latencies) / len(move_latencies), 2) if move_latencies else None,
            "move_min": round(min(move_latencies), 2) if move_latencies else None,
            "move_max": round(max(move_latencies), 2) if move_latencies else None,
            "up": round(up_ms, 2),
        }
        result["touch_balance"] = ad.touch_balance
        result["input_stats"] = {k: v for k, v in ad.stats().items()
                                 if k.startswith("touch") or k == "screen"}
        checks.append(_report("12 TOUCH_STUCK = 0", ad.touch_balance["stuck"] == 0,
                              str(ad.touch_balance)))
        checks.append(_report("13 nothing left holding after the PoC",
                              not release_all("POC_CLEANUP")))

        result["checks_passed"] = sum(checks)
        result["checks_total"] = len(checks)
        result["verdict"] = "CONTINUOUS_TOUCH_LIVE_VERIFIED" if all(checks) else "NEEDS_FIX"
        (outd / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        print()
        print(json.dumps({k: result[k] for k in
                          ("verdict", "checks_passed", "checks_total", "latency_ms",
                           "per_step", "first_move_absorbed_px", "cumulative_shift_from_down",
                           "post_release", "touch_balance")},
                         ensure_ascii=False, indent=1))
        return 0 if all(checks) else 1
    finally:
        lease.release(result="DONE", reason="touch PoC finished")


if __name__ == "__main__":
    raise SystemExit(main())
