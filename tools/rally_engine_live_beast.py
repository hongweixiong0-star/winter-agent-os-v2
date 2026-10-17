# -*- coding: utf-8 -*-
"""Live test of the generic Rally Engine on ICEFIELD_BEAST (2026-09-27).

Phase A: START_RALLY(target=ICEFIELD_BEAST)
  city -> magnifier -> beast tab -> search -> beast dialog -> 集结 -> dispatch
Phase B: JOIN_RALLY(target=ICEFIELD_BEAST)
  war page -> rally list -> find 巨兽 row -> green + -> dispatch

flow/target_type tags follow knowledge/rally/rally_engine_rules.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

STAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
EVID = ROOT / "dataset" / "evidence" / f"rally_engine_beast_{STAMP}"

TPL = {
    "MAGNIFIER": "dataset/candidate/templates/btn_open_resource_search__live_attempt8_idle__2.png",
    "BEAST_TAB": "dataset/candidate/templates/resource_beast__legacy_search_resource_panel__0.png",
    "SUBMIT": "dataset/candidate/templates/btn_resource_search_submit__live_executor_search_open__2.png",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    import cv2  # noqa: E402

    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_RALLY_ENGINE_BEAST", capability_id="RALLY_ENGINE",
                             ttl_seconds=600, reason="live test JOIN/START icefield beast rally")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"flow": "START_RALLY+JOIN_RALLY", "target_type": "ICEFIELD_BEAST",
                 "t0": datetime.now().strftime("%H:%M:%S")}
    try:
        tpls = {}
        for k, p in TPL.items():
            img = Image.open(ROOT / p).convert("RGB")
            tpls[k] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()

        def frame(retries=4):
            for _ in range(retries):
                f = adapter.frame()
                if f is not None:
                    return f if isinstance(f, Image.Image) else Image.fromarray(f)
                time.sleep(0.8)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(EVID / f"{tag}.png")

        def tap(x, y, wait=1.6):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle, wait=2.0, exact=False):
            cands = [t for t in toks(img)
                     if ((t["text"].strip() == needle) if exact else (needle in t["text"]))]
            if not cands:
                return False
            t = max(cands, key=lambda tk: (tk.get("box") or (0, 0, 0, 0))[1])
            box = t.get("box") or ()
            if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                x, y, w, h = (int(v) for v in box)
                tap(x + w // 2, y + h // 2, wait)
                return True
            return False

        def tap_tpl(img, key, thresh=0.8, wait=1.8):
            bgr = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)
            res = cv2.matchTemplate(bgr, tpls[key], cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if score < thresh:
                return False
            h, w = tpls[key].shape[:2]
            tap(loc[0] + w // 2, loc[1] + h // 2, wait)
            return True

        def back_to_city(maxn=8):
            for _ in range(maxn):
                f = frame()
                if f is None:
                    return
                if "统帅" in text(f):
                    return
                if "退出游戏" in text(f):
                    tap_token(f, "取消", 1.5)
                    continue
                adapter.press_back()
                time.sleep(1.2)

        def dismiss_popups(n=4):
            for _ in range(n):
                f = frame()
                t = text(f)
                if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益")):
                    tap_token(f, "确定", 1.5) or tap_token(f, "确认", 1.5) or tap(360, 1080, 1.5)
                else:
                    break

        def march_queues():
            back_to_city()
            time.sleep(1)
            f = frame()
            save(f, "z_city")
            import re
            m = re.search(r"行军\s*(\d)\s*/\s*(\d)", text(f))
            return m.group(0) if m else None

        # ---------- shared popup cleanup ----------
        dismiss_popups()
        back_to_city()
        out["march_before"] = march_queues()

        # ---------- Phase A: START_RALLY(ICEFIELD_BEAST) ----------
        f = frame()
        if not tap_tpl(f, "MAGNIFIER", 0.75, 2.0):
            # fallback: magnifier bottom-right of city screen
            tap(660, 990, 2.0)
        f = frame(); save(f, "A1_search_panel")
        if not tap_tpl(f, "BEAST_TAB", 0.75, 1.8):
            out["A_note"] = "beast_tab template miss"
        f = frame(); save(f, "A2_after_tab")
        if not tap_tpl(f, "SUBMIT", 0.75, 3.0):
            tap_token(f, "搜索", 3.0)
        f = frame(); save(f, "A3_world_target")
        wt = text(f)
        out["A_world_text"] = wt[:200]
        # beast dialog: tap centre where the client centred the beast
        tap(360, 620, 2.0)
        f = frame(); save(f, "A4_beast_dialog")
        dt = text(f)
        out["A_dialog_text"] = dt[:250]
        started = False
        for word in ("集结", "出征", "攻击"):
            if tap_token(f, word, 2.5, exact=True):
                started = True
                break
        if started:
            for i in range(4):  # formation dialog -> dispatch
                df = frame()
                if df is None:
                    continue
                save(df, f"A5_formation_{i}")
                if not any(tap_token(df, w, 2.2) for w in ("出征", "确定", "立即")):
                    break
        time.sleep(6)
        out["march_after_start"] = march_queues()
        out["A_started"] = out["march_after_start"] != out["march_before"] or "集结" in (out["march_after_start"] or "")
        back_to_city()

        # ---------- Phase B: JOIN_RALLY(ICEFIELD_BEAST) ----------
        tap(511, 1243, 1.8)
        f = frame()
        if not tap_token(f, "联盟战争", 1.8):
            tap(246, 669, 1.8)
        f = frame()
        if "集结" in text(f):
            tap_token(f, "集结", 1.8, exact=True) or tap(160, 130, 1.2)
        f = frame(); save(f, "B1_rally_list")
        bt = text(f)
        out["B_list_text"] = bt[:400]
        has_beast_row = any(w in bt for w in ("巨兽", "野兽"))
        out["B_beast_row_visible"] = has_beast_row
        joined = False
        if has_beast_row:
            # locate the beast row's y via its target token, then pick the nearest green +
            beast_y = None
            for t in toks(f):
                if any(w in t["text"] for w in ("巨兽", "野兽")):
                    box = t.get("box") or (0, 0, 0, 0)
                    if len(box) == 4:
                        beast_y = int(box[1] + box[3]) // 2
                        break
            bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, (35, 120, 120), (85, 255, 255))
            band = mask[180:760, 380:720]
            ys, xs = np.nonzero(band)
            out["B_green_pixels"] = int(len(xs))
            if len(xs) >= 80 and beast_y is not None:
                # cluster: pick blob whose centre y is closest to the beast row
                pts = sorted(zip(ys.tolist(), xs.tolist()))
                # coarse 1-D clustering on y
                clusters = []
                cur = [pts[0]]
                for p in pts[1:]:
                    if p[0] - cur[-1][0] <= 12:
                        cur.append(p)
                    else:
                        clusters.append(cur); cur = [p]
                clusters.append(cur)
                best = min(clusters, key=lambda c: abs(int(np.mean([p[0] for p in c])) + 180 - beast_y))
                cy = int(np.mean([p[0] for p in best])) + 180
                cx = int(np.mean([p[1] for p in best])) + 380
                out["B_join_centre"] = (cx, cy)
                save(f, "B2_before_click")
                tap(cx, cy, 2.5)
                for i in range(5):
                    df = frame()
                    if df is None:
                        continue
                    save(df, f"B3_dialog_{i}")
                    if not any(tap_token(df, w, 2.0) for w in ("出征", "立即加入", "确定", "加入")):
                        break
                time.sleep(6)
                vf = frame(); save(vf, "B4_after")
                out["B_after_text"] = text(vf)[:300]
                joined = "xhw" in out["B_after_text"] or "已抵达" in out["B_after_text"]
        else:
            out["B_note"] = "NO_ICEFIELD_BEAST_RALLY_IN_LIST"
        out["B_joined_seen"] = joined
        out["march_after_join"] = march_queues()
        out["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="rally engine beast test done")


if __name__ == "__main__":
    raise SystemExit(main())
