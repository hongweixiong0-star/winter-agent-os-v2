# -*- coding: utf-8 -*-
"""NEW-ACCOUNT BASELINE pass 2 -- targeted: 限时活动 -> 巨熊行动 + rally tab.

Pass 1 read the role ([ioi]零氪纯盾流 / 1063040265 / ioi / 4298) but landed on
联盟争霸赛.  The calendar's red-badge 限时活动 icon (top-right, ~x600 y125) is
where 巨熊行动 lives.  This pass taps it, reads the bear page, then re-walks
联盟 -> 联盟战争 -> 集结 for the auto-join toggle.
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
EVIDENCE = ROOT / "dataset" / "evidence" / f"bear_baseline_newaccount_{STAMP}"

RESERVE_RE = re.compile(r"预约自动开启[：:]?\s*(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})\s*(\d{1,2})[::](\d{2})")


def _pil(x):
    return x if isinstance(x, Image.Image) else Image.fromarray(x)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import ExecutorRouter, RoutingTable, _rapid_ocr_results

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_BEAR_BASELINE_NEWACCOUNT",
        capability_id="BEAR_HUNT",
        ttl_seconds=900,
        reason="pass 2: bear event page time + auto-join toggle",
    )
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"session_started_at": datetime.now(timezone.utc).isoformat()}
    try:
        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()
        router = ExecutorRouter(adb_executor=None, maa_adapter=adapter, routing=RoutingTable.load())

        def frame(retries=4):
            for _ in range(retries):
                f = adapter.frame()
                if f is not None:
                    return _pil(f)
                time.sleep(1)
            return None

        def toks(img):
            return _rapid_ocr_results(np.asarray(img), None, [])

        def text(img):
            return " ".join(t["text"] for t in toks(img))

        def save(img, tag):
            p = EVIDENCE / f"{tag}.png"
            _pil(img).save(p)
            return p

        def tap(x, y, wait=2.0):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle, wait=2.0, exact=False):
            for t in toks(img):
                hit = (t["text"].strip() == needle) if exact else (needle in t["text"])
                if hit:
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

        # ---- city handover -------------------------------------------------
        city = None
        for _ in range(6):
            f = frame()
            if f is None:
                print(json.dumps({"error": "no frame"}))
                return 3
            if "统帅" in text(f):
                city = f
                break
            if "退出游戏" in text(f):
                tap_token(f, "取消", 1.5)
                continue
            adapter.press_back()
            time.sleep(2.0)
        if city is None:
            print(json.dumps({"error": "handover failed"}))
            return 3
        save(city, "00_city")

        # ---- Phase A: 常规活动 -> 限时活动(!) -> 巨熊行动 -----------------------
        out["event"] = {}
        tap(665, 190, 2.5)  # REGULAR_EVENT_ENTRY measured roi
        cal = frame()
        save(cal, "01_calendar")
        tap(600, 125, 2.5)  # red-badge 限时活动 icon (top-right)
        limited = frame()
        save(limited, "02_limited_tab")
        limited_text = text(limited)
        out["event"]["limited_text"] = limited_text[:800]
        bear_found = tap_token(limited, "巨熊行动", 2.5) or tap_token(limited, "巨熊", 2.5)
        out["event"]["bear_entry_found"] = bear_found
        if bear_found:
            page = frame()
            save(page, "03_bear_page")
            page_text = text(page)
            out["event"]["page_text"] = page_text[:800]
            m = RESERVE_RE.search(page_text)
            if not m:
                for t in toks(page):
                    m = RESERVE_RE.search(t["text"])
                    if m:
                        break
            if m:
                year, mon, day, hh, mm = (int(g) for g in m.groups())
                out["event"]["reserve_start"] = (
                    f"{year:04d}-{mon:02d}-{day:02d}T{hh:02d}:{mm:02d}:00+08:00")
            out["event"]["reserve_raw"] = m.group(0) if m else None
            out["event"]["stage_words"] = [w for w in ("进行中", "预告", "准备", "倒计时", "已预约", "预约") if w in page_text]
        else:
            out["event"]["note"] = "巨熊行动 not on limited tab; frames saved for offline review"
        back_to_city()

        # ---- Phase B: 联盟 -> 联盟战争 -> 集结 --------------------------------
        out["auto_join"] = {}
        tap(511, 1243, 2.5)  # bottom nav 联盟
        f = frame()
        save(f, "04_alliance")
        if f is not None and not tap_token(f, "联盟战争", 2.5):
            if not tap_token(f, "战争", 2.5):
                tap(246, 669, 2.5)  # BTN_ALLIANCE_WAR measured roi
        f = frame()
        save(f, "05_war")
        if f is not None and "集结" in text(f) and not tap_token(f, "集结", 2.5, exact=True):
            tap(160, 130, 2.0)  # BTN_WAR_TAB_RALLY measured roi
        f = frame()
        save(f, "06_rally")
        if f is not None:
            from winter_agent_v2.bear_state import read_state_from_image
            state = read_state_from_image(f)
            out["auto_join"]["state"] = state.get("state") or "UNKNOWN"
            out["auto_join"]["evidence"] = state
            from winter_agent_v2 import rally
            reading = rally.read_rally_list_image(f, _as_tokens(toks(f), f))
            out["auto_join"]["rally_rows"] = [row.to_dict() for row in reading.rows]
        else:
            out["auto_join"]["state"] = "UNKNOWN"
        back_to_city()

        dest = ROOT / "learning" / "bear_baseline_newaccount_pass2.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="pass 2 done")


def _as_tokens(raw_tokens, img):
    from winter_agent_v2.ocr import OCRToken

    made = []
    for token in raw_tokens:
        box = token.get("box") or ()
        corners: tuple[tuple[float, float], ...] = ()
        if len(box) == 4:
            if all(isinstance(v, (int, float)) for v in box):
                x, y, w, h = (float(v) for v in box)
                corners = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
            else:
                corners = tuple((float(p[0]), float(p[1])) for p in box)
        made.append(OCRToken(text=str(token.get("text", "")),
                             confidence=float(token.get("score", 0.0) or 0.0),
                             box=corners))
    return made


if __name__ == "__main__":
    raise SystemExit(main())
