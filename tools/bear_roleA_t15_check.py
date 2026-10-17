# -*- coding: utf-8 -*-
"""ROLE_A T-15 pre-battle live recheck (battle night).

Verify current role is [ioi]零氪纯盾流, re-read bear event reserve time
(must stay 2026-09-27 20:30), read AUTO_JOIN state via bear_state, and
capture the rally/alliance-war page for march queue evidence.
No switching, no development actions. Read-only except navigation taps.
"""
from __future__ import annotations

import json
import re
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
EVID = ROOT / "dataset" / "evidence" / f"bear_roleA_t15_{STAMP}"

TEMPLATE_SOURCE = ROOT / "dataset/evidence/bear_baseline_newaccount_20260927T095435Z/p8b_nudge_0.png"
TEMPLATE_BOX = (210, 88, 350, 168)  # 巨熊行动 tab

RESERVE_RE = re.compile(
    r"预约自动开启[：:]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})\s*(\d{1,2})[::](\d{2})")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2.bear_state import read_state_from_image
    import cv2  # noqa: E402

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_BEAR_T15_ROLEA", capability_id="BEAR_HUNT",
        ttl_seconds=900, reason="role A T-15 pre-battle recheck")
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

        def tap_token(img, needle, wait=2.5, exact=False):
            cands = [t for t in toks(img)
                     if ((t["text"].strip() == needle) if exact else (needle in t["text"]))]
            if not cands:
                return False

            def cy(t):
                box = t.get("box") or ()
                if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                    return box[1] + box[3] / 2
                ys = [float(p[1]) for p in box]
                return (min(ys) + max(ys)) / 2

            t = max(cands, key=cy)
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

        def dismiss_popups(max_rounds=4):
            for i in range(max_rounds):
                f = frame()
                if f is None:
                    return
                t = text(f)
                if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益", "新的一天")):
                    save(f, f"popup_{i}")
                    tap_token(f, "确定", 2.0) or tap_token(f, "确认", 2.0) or tap(360, 1080, 2.0)
                    time.sleep(1.5)
                else:
                    return

        def back_to_city(maxn=8):
            for _ in range(maxn):
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

        # ---- 1. role verify via profile ----
        dismiss_popups()
        back_to_city()
        tap(44, 44, 2.5)
        prof = frame()
        save(prof, "01_profile")
        pt = text(prof) if prof is not None else ""
        out["profile_text"] = pt[:400]
        out["role_confirmed"] = "零氪" in pt and "ioi" in pt
        back_to_city()

        # ---- 2. bear page: reserve time recheck ----
        tap(665, 190, 2.5)  # 常规活动
        best = None
        for i in range(14):
            f = frame()
            if f is None:
                break
            band = np.asarray(f.crop((0, 60, 636, 190)), dtype=np.uint8)
            res = cv2.matchTemplate(band, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if best is None or score > best[0]:
                best = (float(score), loc[0] + tw // 2, 60 + loc[1] + th // 2, i)
            if score >= 0.72:
                out["tab_match_score"] = round(float(score), 4)
                tap(loc[0] + tw // 2, 60 + loc[1] + th // 2, 3.0)
                break
            adapter.swipe(480, 122, 420, 122)
            time.sleep(1.8)
        if "tab_match_score" not in out and best and best[0] >= 0.55:
            out["tab_match_score_fallback"] = round(best[0], 4)
            tap(best[1], best[2], 3.0)
        page = frame()
        save(page, "02_bear_page")
        pt2 = text(page) if page is not None else ""
        out["bear_page_text"] = pt2[:800]
        m = RESERVE_RE.search(pt2)
        if not m:
            for t in toks(page) if page is not None else []:
                m = RESERVE_RE.search(t["text"])
                if m:
                    break
        if m:
            out["reserve_time_raw"] = m.group(0)
            out["reserve_time"] = (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                                   f"T{int(m.group(4)):02d}:{int(m.group(5)):02d}:00+08:00")
        out["ROLE_A_TIME_RECHECK"] = (out.get("reserve_time") == "2026-09-27T20:30:00+08:00")
        # event stage hint
        out["event_stage_hint"] = next(
            (t["text"] for t in (toks(page) if page is not None else [])
             if any(w in t["text"] for w in ("进行中", "开放中", "倒计时", "即将"))), None)
        back_to_city()

        # ---- 3. AUTO_JOIN state via alliance war rally page ----
        tap(511, 1243, 2.5)
        f = frame()
        save(f, "03_alliance")
        if not tap_token(f, "联盟战争", 2.5):
            tap(246, 669, 2.5)
        f = frame()
        save(f, "04_war")
        war_t = text(f) if f is not None else ""
        out["war_page_text"] = war_t[:500]
        if "集结" in war_t:
            if not tap_token(f, "集结", 2.5, exact=True):
                tap(160, 130, 2.0)
        f = frame()
        save(f, "05_rally")
        st = read_state_from_image(f) if f is not None else {}
        out["bear_state"] = {k: v for k, v in st.items() if not isinstance(v, (dict, list))}
        out["rally_page_text"] = text(f)[:500] if f is not None else None

        dest = ROOT / "learning" / "bear_roleA_t15_check.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="T-15 recheck done")


if __name__ == "__main__":
    raise SystemExit(main())
