# -*- coding: utf-8 -*-
"""Single-shot manual bear rally join: war page -> green + -> dialog -> verify."""
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
EVID = ROOT / "dataset" / "evidence" / f"bear_join_once_{STAMP}"
JOIN_TPL = ROOT / "dataset/candidate/bear_rally/btn_join_row__rally_detail__20260927_2044__0.png"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    import cv2  # noqa: E402

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_BEAR_JOIN_ONCE", capability_id="BEAR_HUNT",
                             ttl_seconds=420, reason="single-shot manual join")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"t0": datetime.now().strftime("%H:%M:%S")}
    try:
        tpl = cv2.cvtColor(np.asarray(Image.open(JOIN_TPL).convert("RGB")), cv2.COLOR_RGB2BGR)
        th, tw = tpl.shape[:2]
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
            p = EVID / f"{tag}.png"
            (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(p)
            return str(p)

        def tap(x, y, wait=1.5):
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

        def back_to_city(maxn=8):
            for _ in range(maxn):
                f = frame()
                if f is None:
                    return
                t = text(f)
                if "统帅" in t:
                    return
                if "退出游戏" in t:
                    tap_token(f, "取消", 1.5)
                    continue
                adapter.press_back()
                time.sleep(1.2)

        # popups
        for _ in range(4):
            f = frame()
            t = text(f)
            if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益")):
                tap_token(f, "确定", 1.5) or tap_token(f, "确认", 1.5) or tap(360, 1080, 1.5)
                time.sleep(1.2)
            else:
                break
        back_to_city()

        # war -> rally
        tap(511, 1243, 1.8)
        f = frame()
        save(f, "01_alliance")
        if not tap_token(f, "联盟战争", 1.8):
            tap(246, 669, 1.8)
        f = frame()
        save(f, "02_war")
        if "集结" in text(f):
            if not tap_token(f, "集结", 1.8, exact=True):
                tap(160, 130, 1.2)
        f = frame()
        save(f, "03_rally_page")
        out["page_text"] = text(f)[:400]

        bgr = cv2.cvtColor(np.asarray(f.convert("RGB")), cv2.COLOR_RGB2BGR)
        # green-pixel detection: the + button is the only saturated green element
        # in the upper band (template match kept hitting the orange flag at 1.0)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (35, 120, 120), (85, 255, 255))
        band = mask[380:520, 400:700]  # top band where the + sits
        ys, xs = np.nonzero(band)
        out["green_pixels"] = int(len(xs))
        if len(xs) < 80:
            out["result"] = "NO_GREEN_PLUS"
            print(json.dumps(out, ensure_ascii=False))
            back_to_city()
            return 1
        cx, cy = int(xs.mean()) + 400, int(ys.mean()) + 380
        out["green_centre"] = (cx, cy)
        save(f, "04_before_click")
        t_click = time.time()
        tap(cx, cy, 2.5)
        # dialog: troop select / confirm
        for i in range(5):
            df = frame()
            if df is None:
                continue
            save(df, f"05_dialog_{i}")
            dt = text(df)
            hit = False
            for word in ("立即加入", "出征", "加入", "确定", "确认"):
                if tap_token(df, word, 2.0):
                    hit = True
                    break
            if not hit:
                break
        out["join_click_ts"] = t_click
        time.sleep(6)
        vf = frame()
        save(vf, "06_after")
        vt = text(vf) if vf is not None else ""
        out["after_text"] = vt[:400]
        out["joined_seen"] = "xhw" in vt
        out["done"] = datetime.now().strftime("%H:%M:%S")
        print(json.dumps(out, ensure_ascii=False))
        return 0
    finally:
        lease.release(result="DONE", reason="single-shot join done")


if __name__ == "__main__":
    raise SystemExit(main())
