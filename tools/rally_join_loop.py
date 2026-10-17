# -*- coding: utf-8 -*-
"""Rally JOIN loop (v2): badge entry + FormationPolicy slot rotation + speed.

- entry: city RALLY_JOIN_BADGE (HSV red ring) -> rally detail
- join : green + -> PAGE_FORMATION -> slot from pool [2..7] (state-aware)
         -> fingerprint verify -> 出征 -> verifier
- records per-join latency; probes whether a 发起集结 (START_RALLY) entry exists
- slot occupancy persisted to learning/formation_slot_state.json

usage: python tools/rally_join_loop.py ROLE_A [minutes]
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(ROOT))
from winter_agent_v2.formation_policy import (  # noqa: E402
    FormationPolicy, formation_selected_verified, RALLY_JOIN_PRESET_POOL)

STATE_PATH = ROOT / "learning" / "formation_slot_state.json"


def load_state(role: str) -> FormationPolicy:
    pol = FormationPolicy(role)
    if STATE_PATH.exists():
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        for k, v in d.get("roles", {}).get(role, {}).get("slots", {}).items():
            pol.mark(int(k), v)
    return pol


def save_state(role: str, pol: FormationPolicy) -> None:
    d = {"roles": {}, "note": "slot occupancy for FormationPolicy"}
    if STATE_PATH.exists():
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    d.setdefault("roles", {})[role] = {"slots": {str(s): pol.slots[s].state for s in range(1, 9)}}
    STATE_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    role = sys.argv[1] if len(sys.argv) > 1 else "ROLE_A"
    minutes = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    max_joins = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
    EVID = ROOT / "dataset" / "evidence" / f"rally_join_loop_{STAMP}"
    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=f"DEVICE_JOIN_LOOP_{role}", capability_id="RALLY_ENGINE",
                            ttl_seconds=int(minutes * 60) + 180, reason="rally join loop v2")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    pol = load_state(role)
    out = {"role": role, "flow": "JOIN_RALLY", "t0": datetime.now().strftime("%H:%M:%S"),
           "joins": [], "start_rally_entry_seen": False}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ad.ensure_ready()

        def frame(retries=3):
            for _ in range(retries):
                f = ad.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(0.5)

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            img.save(EVID / f"{tag}.png")

        def center(b):
            return int(b[0]) + int(b[2]) // 2, int(b[1]) + int(b[3]) // 2

        def tap(x, y, w=1.2):
            ad.click(int(x), int(y))
            time.sleep(w)

        def tap_tok(img, needle, w=1.5, exact=False):
            cs = [t for t in toks(img) if (t["text"].strip() == needle if exact else needle in t["text"])]
            if not cs:
                return False
            t = max(cs, key=lambda k: (k.get("box") or [0, 0, 0, 0])[1])
            tap(*center(t.get("box") or [0, 0, 0, 0]), w)
            return True

        def at_city(f):
            t = text(f)
            return "退出游戏" not in t and "领主档案" not in t and ("统帅" in t or "背包" in t)

        def to_city():
            for _ in range(7):
                f = frame()
                if f is None:
                    continue
                if "退出游戏" in text(f):
                    tap_tok(f, "取消", w=1.0, exact=True)
                    continue
                if at_city(f):
                    return f
                ad.press_back(); time.sleep(1.0)
            return frame()

        def find_badge(f):
            W, H = f.size
            y0, y1, x0, x1 = int(H * 0.20), int(H * 0.50), int(W * 0.64), int(W * 0.99)
            bgr = np.asarray(f.convert("RGB"))[:, :, ::-1].copy()
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            m = cv2.bitwise_or(cv2.inRange(hsv, (0, 110, 110), (10, 255, 255)),
                               cv2.inRange(hsv, (170, 110, 110), (180, 255, 255)))[y0:y1, x0:x1]
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:4]:
                if cv2.contourArea(c) < 500:
                    continue
                bx, by, bw, bh = cv2.boundingRect(c)
                if 0.6 <= bw / max(bh, 1) <= 1.7:
                    return (x0 + bx + bw // 2, y0 + by + bh // 2)
            return None

        def green_plus(f, band=(280, 720, 360, 740)):
            y0, y1, x0, x1 = band
            bgr = np.asarray(f.convert("RGB"))[:, :, ::-1].copy()
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (35, 120, 120), (85, 255, 255))[y0:y1, x0:x1]
            ys, xs = np.nonzero(mask)
            if len(xs) < 60:
                return None
            return int(np.mean(xs)) + x0, int(np.mean(ys)) + y0

        deadline = time.time() + minutes * 60
        while time.time() < deadline and len(out["joins"]) < max_joins:
            f = to_city()
            if f is None:
                continue
            badge = find_badge(f)
            if badge is None:
                time.sleep(5)
                continue
            t_cycle = time.time()
            out["badge"] = badge
            save(f, "badge")
            tap(*badge, 1.8)
            f = frame(); save(f, "detail")
            dt = text(f)
            if "发起集结" in dt:
                out["start_rally_entry_seen"] = True
            out["detail_sample"] = dt[:180]
            duration = None
            m = re.search(r"(\d{1,2}[:：]\d{2}[:：]\d{2})", dt)
            if m:
                duration = m.group(1)
            gp = green_plus(f)
            if gp is None:
                out.setdefault("notes", []).append("no green + on detail")
                time.sleep(4)
                continue
            tap(*gp, 1.8)
            f = frame(); save(f, "formation")
            ft = text(f)
            if "盾兵" not in ft:
                out.setdefault("notes", []).append("formation page not detected")
                time.sleep(3)
                continue
            before = FormationPolicy.fingerprint_from_ocr(ft)
            choice = pol.select({"task_type": "JOIN_RALLY"})
            slot = choice.get("formation_slot")
            if slot is None:
                pol.on_march_returned()
                choice = pol.select({"task_type": "JOIN_RALLY"})
                slot = choice.get("formation_slot")
            if slot is None:
                out.setdefault("notes", []).append("no available slot")
                time.sleep(5)
                continue
            x, y = FormationPolicy.slot_tap_point(slot, f.size[0])
            tap(x, y, 1.2)
            f2 = frame(); save(f2, f"formation_slot{slot}")
            after = FormationPolicy.fingerprint_from_ocr(text(f2))
            verified = formation_selected_verified(before, after)
            t_disp = time.time()
            dispatched = tap_tok(f2, "出征", w=1.8, exact=True)
            out["joins"].append({
                "ts": datetime.now().strftime("%H:%M:%S"),
                "slot": slot, "slot_verified": verified, "dispatched": dispatched,
                "duration_on_row": duration,
                "cycle_ms": int((t_disp - t_cycle) * 1000),
                "frame_to_dispatch_ms": int((t_disp - t_cycle) * 1000),
                "before_fp": before.get("troops"), "after_fp": after.get("troops"),
            })
            if dispatched:
                pol.mark(slot, "RALLYING")
                save_state(role, pol)
            time.sleep(4)
            vf = frame(); save(vf, "after")
            vt = text(vf)
            out["joins"][-1]["after_text"] = vt[:150]
            out["joins"][-1]["joined_seen"] = ("已抵达" in vt) or ("零氪" in vt)
            to_city()
            time.sleep(3)
        out["slot_states"] = {str(s): pol.slots[s].state for s in range(1, 9)}
        out["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        (ROOT / "learning" / f"rally_join_loop_{STAMP}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    finally:
        lease.release(result="DONE", reason="join loop done")


if __name__ == "__main__":
    raise SystemExit(main())
