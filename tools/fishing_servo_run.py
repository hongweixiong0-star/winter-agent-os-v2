# -*- coding: utf-8 -*-
"""FIRST LIVE RUN: steer one whole fishing level with the visual servo, and verify it.

What this does, in order (PHASE 8, 9, 10, 11):

  1. lease -> enter 普通关卡 -> tap the tutorial circle (the run is live and waiting)
  2. poll cheaply until the LINE is actually visible (the detector refuses to report
     a line during the cutscene, so nothing is sent to a screen we cannot see)
  3. hand control to VisualServoSession with the FishingSessionController:
     capture -> detect -> decide -> touch_move -> repeat, at whatever rate the
     device sustains
  4. stop when the line has been gone for a while (the level ended), then verify the
     RESULT PAGE and the bait change by OCR — the two things PHASE 10 demands
  5. write the run into dataset/raw/fishing_tournament/<run_id>/

Data is sampled, not exhaustive (PHASE 9): every Nth frame is kept, plus every
frame where the phase changed or the target was lost for a while.  Detections and
control outputs are stored for every tick because they are tiny.

usage: python tools/fishing_servo_run.py [max_control_seconds]
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

NORMAL_STAGE = (500, 1170)
TUTORIAL_TAP = (357, 632)
HUD_HOME = (664, 476)
SAVE_EVERY = 15
LINE_GONE_TICKS_TO_END = 45          # ~1s at 40Hz


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    max_control_s = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.fishing_session import FishingSessionController
    from winter_agent_v2.fishing_vision import detect_fishing
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.visual_servo import ServoConfig, VisualServoSession

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    rid = f"run_{stamp}"
    outd = ROOT / "dataset" / "raw" / "fishing_tournament" / rid
    (outd / "frames").mkdir(parents=True, exist_ok=True)

    rep: dict = {"run_id": rid, "phase": "START", "dir": str(outd.relative_to(ROOT))}
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=f"FISHING_SESSION_{rid}", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=int(max_control_s) + 240,
                             reason="one controlled fishing level (short session lease)")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3

        # VISION POLICY V1 section F: OCR is allowed BEFORE entering the minigame
        # (bait/points/tokens/attempts/timer) and AFTER leaving it (result/points/
        # tokens/bait/rewards) — and is a hard error in between.  Both sides are
        # counted so the run can prove which side each call was on.
        ocr_outside = {"calls": 0}

        def txt(f):
            ocr_outside["calls"] += 1
            return " ".join(t["text"] for t in read_all(Image.fromarray(f)))

        def cap(attempts=3):
            for _ in range(attempts):
                f = ad.capture()
                if f is not None:
                    return f
                time.sleep(0.3)
            return None

        # ---------- 0. reach the fishing home, read the bait ----------
        f = cap()
        t = txt(f)
        Image.fromarray(f).save(outd / "00_start.png")
        # Blocking modals are normal here: a new collection entry pops "恭喜您获得
        # 新图鉴 / 点击任意位置继续", and the level result page pops 本次收获.  Both
        # must be cleared before the home page can be read, or every later step
        # measures the popup instead of the game.
        for _ in range(5):
            if "点击任意位置继续" in t or "恭喜您获得新图鉴" in t:
                ad.click(360, 640)
                time.sleep(1.6)
                f = cap()
                t = txt(f)
                continue
            if "本次收获" in t:
                hit = [x for x in read_all(Image.fromarray(f)) if "退出" in x["text"]]
                if hit:
                    ad.click(*hit[0]["centre"])
                    time.sleep(2.2)
                    f = cap()
                    t = txt(f)
                    continue
            break
        if "普通关卡" not in t:
            hit = [x for x in read_all(Image.fromarray(f)) if "钓鱼锦标赛" in x["text"]]
            if hit:
                ad.click(*hit[0]["centre"])
                time.sleep(2.4)
                f = cap()
                t = txt(f)
        if "普通关卡" not in t:
            rep["aborted"] = "NOT_ON_FISHING_HOME"
            rep["screen_text"] = t[:300]
            (outd / "run.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
            print("NOT ON FISHING HOME:", t[:250])
            return 4
        import re
        m = re.search(r"(\d+)\s*/\s*(\d+)", t)
        rep["bait_before"] = m.group(1) if m else None
        rep["bait_cap"] = m.group(2) if m else None
        rep["home_text"] = t[:400]
        Image.fromarray(f).save(outd / "01_home.png")
        print(f"BAIT BEFORE = {rep['bait_before']}/{rep['bait_cap']}")

        # ---------- 1. start the level ----------
        rep["phase"] = "ENTER_LEVEL"
        ad.click(*NORMAL_STAGE)
        time.sleep(1.8)
        ad.click(*TUTORIAL_TAP)
        # No extra delay and no second tap: the actionable window measured ~4 s, so
        # every tenth of a second spent waiting is control we never get.  If a
        # second tutorial step exists, the poll below simply waits for the line.
        time.sleep(0.15)
        ad.click(*TUTORIAL_TAP)

        # ---------- 2. wait until the LINE is really visible ----------
        rep["phase"] = "WAIT_FOR_LINE"
        t0 = time.monotonic()
        seen = 0
        first_state = None
        while time.monotonic() - t0 < 45:
            fr = cap()
            if fr is None:
                continue
            st = detect_fishing(fr)
            if st.found:
                seen += 1
                if first_state is None:
                    first_state = st.to_dict()
                    Image.fromarray(fr).save(outd / "02_line_first_seen.png")
                    rep["first_line_seen_after_s"] = round(time.monotonic() - t0, 2)
                if seen >= 3:
                    break
            else:
                seen = 0
            time.sleep(0.05)
        rep["first_state"] = first_state
        if not first_state:
            rep["aborted"] = "LINE_NEVER_VISIBLE"
            rep["screen_text"] = txt(cap())[:300]
            (outd / "run.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
            print("LINE NEVER VISIBLE — aborted without steering blind")
            return 5
        print(f"LINE SEEN after {rep['first_line_seen_after_s']}s: {first_state}")

        # ---------- 3. hand over to the visual servo ----------
        rep["phase"] = "CONTROL_SESSION"
        ctrl = FishingSessionController(mode="AUTO", calibrate_ticks=26)
        detectors: list[dict] = []
        decisions: list[dict] = []
        sampled = 0
        lost_run = 0

        cfg_servo = ServoConfig(anchor_y=800, target_hz=20.0, dead_zone_px=5,
                                max_move_per_tick_px=28, low_pass_alpha=0.55,
                                engage_move_px=22, max_lost_frames=8,
                                lost_target_timeout_s=1.5, hold_while_lost=True,
                                max_session_duration_s=max_control_s,
                                stale_frame_limit=90)

        last_frame = {"f": None}

        def det(roi_frame):
            # roi_frame is the full frame (roi=None), so coordinates stay native
            st = detect_fishing(roi_frame)
            last_frame["f"] = roi_frame
            ctrl.set_frame(roi_frame)
            detectors.append(st.to_dict())
            return st

        def on_frame(row, _f, _s):
            nonlocal sampled, lost_run
            if ctrl.last is not None:
                decisions.append({"i": row.index, "finger_x": row.finger_x,
                                  "commanded_x": row.commanded_x,
                                  "phase": ctrl.last.phase,
                                  "desired_line_x": ctrl.last.desired_line_x,
                                  "reason": ctrl.last.reason,
                                  "line_x": detectors[-1]["line_x"] if detectors else None,
                                  "hook_y": detectors[-1]["hook_y"] if detectors else None})
            if row.index % SAVE_EVERY == 0 and last_frame["f"] is not None:
                Image.fromarray(last_frame["f"]).save(outd / "frames" / f"t{row.index:05d}.png")
                sampled += 1

        def completed(frame, _s):
            return False   # end conditions are handled by the lost-streak counter below

        session = VisualServoSession(ad, config=cfg_servo, on_frame=on_frame)
        # end when the line has been gone for a while
        import threading

        def watchdog():
            while True:
                time.sleep(0.5)
                if detectors and detectors[-1].get("line_x") is None:
                    nonlocal_lost[0] += 1
                    # The line vanishing is the level ending, not a failure.  Give
                    # it a generous window before stopping: too early an abort was
                    # exactly what cut the previous run's control short.
                    if nonlocal_lost[0] >= 16:
                        session.abort("LINE_GONE_LEVEL_ENDED")
                        return
                else:
                    nonlocal_lost[0] = 0
                if not session.report.outcome == "RUNNING":
                    return

        nonlocal_lost = [0]
        th = threading.Thread(target=watchdog, daemon=True)
        th.start()
        srep = session.run(det, ctrl, completed)
        rep["control_session"] = srep.to_dict()
        pol = srep.to_dict().get("vision_policy", {})
        rep["vision_policy"] = pol
        rep["ocr_calls_outside_realtime"] = ocr_outside["calls"]
        rep["ocr_zero_inside_realtime"] = (pol.get("ocr_calls_inside_realtime") == 0)
        rep["control_hz"] = pol.get("control_hz")
        rep["vision_hz"] = pol.get("vision_hz")
        rep["lost_target_frames"] = pol.get("lost_target_frames")
        rep["detections"] = detectors
        rep["decisions"] = decisions
        rep["frames_saved"] = sampled
        rep["line_lost_ticks"] = nonlocal_lost[0]

        # ---------- 4. verify the RESULT PAGE and the bait change ----------
        rep["phase"] = "VERIFY"
        f2 = cap()
        rt = txt(f2)
        # The result page lands 2-4 s after the level ends; the previous run read
        # the gameplay HUD and called it a failure.  Poll for it instead.
        v0 = time.monotonic()
        while time.monotonic() - v0 < 14:
            if ("本次收获" in rt) or ("下潜深度" in rt):
                break
            if "点击任意位置继续" in rt or "恭喜" in rt:
                ad.click(360, 640)
            time.sleep(1.4)
            f2 = cap()
            rt = txt(f2)
        Image.fromarray(f2).save(outd / "03_result.png")
        rep["result_text"] = rt[:600]
        rep["minigame_started"] = True
        rep["control_session_ran"] = srep.frames > 0 and srep.moves_sent > 0
        rep["result_page"] = ("本次收获" in rt) or ("下潜深度" in rt)
        depth = re.search(r"下潜深度[:：]\s*(\d+)", rt)
        rep["depth_m"] = depth.group(1) if depth else None
        # popups can sit over the result
        for _ in range(3):
            if rep["result_page"]:
                break
            if "点击任意位置" in rt or "恭喜" in rt:
                ad.click(360, 640)
                time.sleep(1.6)
                f2 = cap()
                Image.fromarray(f2).save(outd / "03b_result_after_tap.png")
                rt = txt(f2)
                rep["result_text"] = rt[:600]
                rep["result_page"] = ("本次收获" in rt) or ("下潜深度" in rt)
                d2 = re.search(r"下潜深度[:：]\s*(\d+)", rt)
                if d2:
                    rep["depth_m"] = d2.group(1)
            else:
                break

        # back to the home page and read the bait again
        hit = [x for x in read_all(Image.fromarray(f2)) if "退出" in x["text"]]
        if hit:
            ad.click(*hit[0]["centre"])
            time.sleep(2.4)
        f3 = cap()
        Image.fromarray(f3).save(outd / "04_home_after.png")
        t3 = txt(f3)
        rep["home_after_text"] = t3[:400]
        m3 = re.search(r"(\d+)\s*/\s*(\d+)", t3)
        rep["bait_after"] = m3.group(1) if m3 else None
        rep["points_after"] = (re.search(r"冰钓积分[:：]\s*(\d+)", t3).group(1)
                               if re.search(r"冰钓积分[:：]\s*(\d+)", t3) else None)

        rep["bait_decreased"] = (rep.get("bait_before") is not None
                                 and rep.get("bait_after") is not None
                                 and int(rep["bait_after"]) < int(rep["bait_before"]))
        rep["verifier"] = {
            "MINIGAME_STARTED": rep["minigame_started"],
            "CONTROL_SESSION_RAN": rep["control_session_ran"],
            "RESULT_PAGE": rep["result_page"],
            "BAIT_DECREASED": rep["bait_decreased"],
            "DEPTH_M": rep["depth_m"],
            "OCR_ZERO_INSIDE_REALTIME": rep["ocr_zero_inside_realtime"],
            "OCR_CALLS_OUTSIDE_REALTIME": rep["ocr_calls_outside_realtime"],
        }
        rep["FISHING_RUN_L4"] = all([rep["minigame_started"], rep["control_session_ran"],
                                     rep["result_page"], rep["bait_decreased"],
                                     rep["ocr_zero_inside_realtime"]])
        rep["phase"] = "DONE"
        (outd / "run.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

        print("\n================ FISHING RUN ================")
        print(json.dumps({"run_id": rid, "bait": f"{rep['bait_before']}->{rep['bait_after']}",
                          "depth_m": rep["depth_m"],
                          "verifier": rep["verifier"], "L4": rep["FISHING_RUN_L4"],
                          "control": {k: srep.to_dict()[k] for k in
                                      ("outcome", "frames", "duration_s", "presses",
                                       "moves_sent", "moves_skipped_dead_zone")},
                          "timings": srep.timings(),
                          "control_hz": rep.get("control_hz"),
                          "vision_hz": rep.get("vision_hz"),
                          "lost_target_frames": rep.get("lost_target_frames"),
                          "ocr_zero_inside_realtime": rep.get("ocr_zero_inside_realtime"),
                          "ocr_calls_outside_realtime": rep.get("ocr_calls_outside_realtime")},
                         ensure_ascii=False, indent=1))
        print("EVIDENCE:", outd)
        return 0 if rep["FISHING_RUN_L4"] else 1
    finally:
        lease.release(result="DONE", reason="fishing run finished")


if __name__ == "__main__":
    raise SystemExit(main())
