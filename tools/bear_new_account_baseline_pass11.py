# -*- coding: utf-8 -*-
"""Pass 11 -- template-match the 巨熊行动 tab while nudging the strip.

OCR cannot read the tab labels reliably (icon-overlapped text).  The bear tab
WAS visible in pass 8b nudge_0 at ~(280,127); that crop is the template.  Walk
the strip in 60 px nudges, match the template inside the strip band each step,
tap the tab when the match is strong.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVID = ROOT / "dataset" / "evidence" / f"bear_baseline_newaccount_{STAMP}"

TEMPLATE_SOURCE = ROOT / "dataset/evidence/bear_baseline_newaccount_20260927T095435Z/p8b_nudge_0.png"
TEMPLATE_BOX = (210, 88, 350, 168)  # 巨熊行动 tab in that frame
RESERVE_WORDS = ("预约自动开启",)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results

    import cv2  # noqa: E402 -- production venv ships OpenCV

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_BEAR_BASELINE_NEWACCOUNT", capability_id="BEAR_HUNT",
        ttl_seconds=900, reason="pass 11: template-match the bear tab")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat()}
    try:
        template = np.asarray(
            Image.open(TEMPLATE_SOURCE).convert("RGB").crop(TEMPLATE_BOX), dtype=np.uint8)
        th, tw = template.shape[:2]

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
                time.sleep(1)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            p = EVID / f"{tag}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(p)
            return p

        def tap(x, y, wait=2.0):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle, wait=2.5):
            for t in toks(img):
                if needle in t["text"]:
                    box = t.get("box") or ()
                    if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                        x, y, w, h = (int(v) for v in box)
                    else:
                        xs = [float(p[0]) for p in box]
                        ys = [float(p[1]) for p in box]
                        x, y = int(min(xs)), int(min(ys))
                        w, h = int(max(xs) - min(xs)), int(max(ys) - min(ys))
                    tap(x + w // 2, y + h // 2, wait)
                    return True
            return False

        def back_to_city():
            for _ in range(8):
                f = frame()
                if f is None:
                    return None
                t = text(f)
                if "统帅" in t:
                    return f
                if "退出游戏" in t:
                    tap_token(f, "取消", 1.5)
                    continue
                adapter.press_back()
                time.sleep(2.0)
            return frame()

        for _ in range(6):
            f = frame()
            t = text(f)
            if "统帅" in t:
                break
            if "退出游戏" in t:
                tap_token(f, "取消", 1.5)
                continue
            adapter.press_back()
            time.sleep(2.0)

        tap(665, 190, 2.5)  # 常规活动

        best = None  # (score, cx, cy, step)
        for i in range(14):
            f = frame()
            if f is None:
                break
            save(f, f"p11_step_{i}")
            band = np.asarray(f.crop((0, 60, 636, 190)), dtype=np.uint8)
            res = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            out.setdefault("scores", []).append(round(float(score), 4))
            # self-match sanity: the template's own score must stay below the live hit
            if best is None or score > best[0]:
                best = (float(score), loc[0] + tw // 2, 60 + loc[1] + th // 2, i)
            if score >= 0.72:
                cx, cy = loc[0] + tw // 2, 60 + loc[1] + th // 2
                out["matched_at_step"] = i
                out["match_score"] = round(float(score), 4)
                tap(cx, cy, 3.0)
                break
            adapter.swipe(480, 122, 420, 122)
            time.sleep(1.8)

        if best and "matched_at_step" not in out:
            # strongest seen match, if it clears a sane floor
            score, cx, cy, step = best
            out["best_score"] = round(score, 4)
            if score >= 0.55:
                out["tapped_best"] = True
                tap(cx, cy, 3.0)

        page = frame()
        if page is not None:
            save(page, "p11_bear_page")
            pt = text(page)
            out["page_text"] = pt[:1000]
            import re
            m = re.search(
                r"预约自动开启[：:]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})\s*(\d{1,2})[::](\d{2})", pt)
            if not m:
                for t in toks(page):
                    m = re.search(
                        r"预约自动开启[：:]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})\s*(\d{1,2})[::](\d{2})",
                        t["text"])
                    if m:
                        break
            if m:
                y_, mo, d, h, mi = (int(g) for g in m.groups())
                out["reserve_start"] = (
                    f"{y_:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:00+08:00")
            out["reserve_raw"] = m.group(0) if m else None

        returned = False
        for _ in range(6):
            f = frame()
            if f is None:
                break
            if "统帅" in text(f):
                returned = True
                break
            if "退出游戏" in text(f):
                tap_token(f, "取消", 1.5)
                continue
            adapter.press_back()
            time.sleep(2.0)
        out["returned_to_city"] = returned

        dest = ROOT / "learning" / "bear_baseline_newaccount_pass11.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="pass 11 done")


if __name__ == "__main__":
    raise SystemExit(main())
