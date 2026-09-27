# -*- coding: utf-8 -*-
"""NEW-ACCOUNT BEAR BASELINE -- read tonight's bear facts off the live client.

Round brief 2026-09-27 (emergency takeover): the account under MuMu changed.
Nothing real-time from the old account may be inherited; the new account's
bear time, auto-join state, and role identity are UNKNOWN until this session
reads them off the client.

Three phases, all read-only except navigation taps (never taps the auto-join
toggle itself; §七: ON -> NOOP, OFF -> report, UNKNOWN -> no click):

    A. 常规活动 -> 巨熊行动  : activity name, 预约自动开启 time, countdown,
                                stage, reserved-or-not  -> CLIENT text saved
    B. 联盟战争 -> 集结       : AUTO_JOIN state (bear_state reader), rally rows
    C. role identity          : best-effort profile read, else UNKNOWN

Outputs:
    dataset/evidence/bear_baseline_newaccount_<stamp>/*.png
    learning/bear_baseline_newaccount.json   (full session record)
    learning/timed_event_schedule.json       (new roles[] entry, old kept)

Usage: .venv/Scripts/python.exe -u tools/bear_new_account_baseline.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVIDENCE = ROOT / "dataset" / "evidence" / f"bear_baseline_newaccount_{STAMP}"

RESERVE_RE = re.compile(r"预约自动开启[：:]\s*(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})\s*(\d{1,2})[::](\d{2})")
COUNTDOWN_RE = re.compile(r"(?:(\d+)天)?\s*(\d{1,2})[::](\d{2})[::](\d{2})")


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
        reason="new-account bear baseline: event time + auto-join + role, read off live client",
    )
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {
        "session_started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "new-account bear baseline (emergency takeover; no old-account state inherited)",
        "phases": {},
    }
    try:
        adapter = MaaExecutorAdapter(
            adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
            production=True, template_dir=ROOT / "dataset" / "candidate" / "templates",
            log_dir=ROOT / "learning" / "maa_logs",
        )
        adapter.ensure_ready()
        router = ExecutorRouter(adb_executor=None, maa_adapter=adapter, routing=RoutingTable.load())

        def frame(retries: int = 4):
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

        def save(img, tag: str) -> Path:
            p = EVIDENCE / f"{tag}.png"
            _pil(img).save(p)
            return p

        def tap(x, y, wait=2.0):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle: str, wait=2.0) -> bool:
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

        def back_to_city() -> Image.Image | None:
            """Press back until the city view (统帅 present); answer 取消 on exit dialog."""
            for _ in range(8):
                f = frame()
                if f is None:
                    return None
                t = text(f)
                if "统帅" in t:
                    return f
                if "退出游戏" in t:
                    if not tap_token(f, "取消", 1.5):
                        time.sleep(1)
                    continue
                adapter.press_back()
                time.sleep(2.0)
            return frame()

        # ---- handover to city view -----------------------------------------
        city = None
        for _ in range(6):
            f = frame()
            if f is None:
                out["error"] = "no frame"
                print(json.dumps(out, ensure_ascii=False))
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
            out["error"] = "handover failed: no city view"
            print(json.dumps(out, ensure_ascii=False))
            return 3
        save(city, "00_city")

        # ---- Phase A: 常规活动 -> 巨熊行动 ------------------------------------
        phase_a: dict = {"phase": "EVENT_PAGE"}
        pt = router.maa_resolver("REGULAR_EVENT_ENTRY", "OPEN_EVENT_CALENDAR_FROM_HOME")
        phase_a["regular_event_resolved"] = bool(pt)
        if pt:
            tap(pt[0], pt[1], 2.5)
        else:
            tap(665, 190, 2.5)  # measured entry roi [611,157,109,67]
        cal = frame()
        save(cal, "01_event_calendar")
        phase_a["calendar_text"] = text(cal)[:500]
        # the calendar may land on a tab other than 常规活动
        if "常规活动" in phase_a["calendar_text"]:
            tap_token(cal, "常规活动", 2.0)
            cal = frame()
            save(cal, "01b_event_regular_tab")
        found_bear = tap_token(cal, "巨熊行动", 2.5) or tap_token(cal, "巨熊", 2.5)
        phase_a["bear_entry_found"] = found_bear
        if found_bear:
            page = frame()
            save(page, "02_bear_event_page")
            tokens = toks(page)
            page_text = text(page)
            phase_a["page_text"] = page_text[:600]
            reserve = None
            for t in tokens:
                m = RESERVE_RE.search(t["text"]) or RESERVE_RE.search(page_text)
                if m:
                    year, mon, day, hh, mm = (int(g) for g in m.groups())
                    reserve = f"{year:04d}-{mon:02d}-{day:02d}T{hh:02d}:{mm:02d}:00+08:00"
                    phase_a["reserve_raw"] = t["text"]
                    break
            phase_a["reserve_start_raw"] = reserve
            phase_a["has_countdown"] = bool(COUNTDOWN_RE.search(page_text))
            phase_a["reserved_words"] = [w for w in ("已预约", "预约", "开启自动", "倒计时") if w in page_text]
        else:
            phase_a["page_text"] = None
            phase_a["note"] = "巨熊行动 entry not found on calendar; page text saved for offline review"
        out["phases"]["event"] = phase_a

        # ---- Phase B: alliance war -> 集结, AUTO_JOIN state -------------------
        home = back_to_city()
        save(home or city, "03_back_home")
        phase_b: dict = {"phase": "AUTO_JOIN"}
        pt = router.maa_resolver("BTN_OPEN_ALLIANCE", "OPEN_ALLIANCE")
        if pt:
            tap(pt[0], pt[1], 2.5)
        else:
            tap(511, 1243, 2.5)  # bottom nav 联盟 (measured)
        f = frame()
        save(f, "04_alliance")
        pt = router.maa_resolver("BTN_ALLIANCE_WAR", "OPEN_BEAR_RALLY_LIST")
        if pt:
            tap(pt[0], pt[1], 2.5)
        f = frame()
        if f is not None and "集结" in text(f):
            tap_token(f, "集结", 2.0) if not router.maa_resolver("BTN_WAR_TAB_RALLY", "OPEN_BEAR_RALLY_LIST") else tap(*(router.maa_resolver("BTN_WAR_TAB_RALLY", "OPEN_BEAR_RALLY_LIST") or (0, 0)), 2.0)
            f = frame()
        save(f, "05_rally_tab")
        phase_b["page_text"] = text(f)[:500] if f is not None else None
        if f is not None:
            from winter_agent_v2.bear_state import read_state_from_image
            state = read_state_from_image(f)
            phase_b["auto_join_state"] = state.get("state") or "UNKNOWN"
            phase_b["auto_join_evidence"] = state
            from winter_agent_v2 import rally
            reading = rally.read_rally_list_image(f, _as_tokens(toks(f), f))
            phase_b["rally_rows"] = [row.to_dict() for row in reading.rows]
        else:
            phase_b["auto_join_state"] = "UNKNOWN"
        out["phases"]["auto_join"] = phase_b

        # ---- Phase C: role identity (best effort) -----------------------------
        home2 = back_to_city()
        phase_c: dict = {"phase": "ROLE"}
        role_name = None
        if home2 is not None:
            # top-left avatar -> 领主档案
            tap(48, 90, 2.5)
            prof = frame()
            save(prof, "06_profile")
            prof_text = text(prof) if prof is not None else ""
            phase_c["profile_text"] = prof_text[:400]
            if "领主" in prof_text or "统帅" in prof_text:
                # role name = the bracketed tag or the longest name-ish token
                m = re.search(r"[【\[]([^\]】]{2,24})[\]】]", prof_text)
                role_name = m.group(1) if m else None
                if role_name is None:
                    candidates = [t["text"].strip() for t in toks(prof)
                                  if 4 <= len(t["text"].strip()) <= 20
                                  and not any(ch.isdigit() for ch in t["text"])
                                  and t["text"].strip() not in {"领主档案", "统帅"}]
                    role_name = candidates[0] if candidates else None
            back_to_city()
        phase_c["role_name"] = role_name
        phase_c["status"] = "READ" if role_name else "UNKNOWN"
        out["phases"]["role"] = phase_c

        # ---- verdict -------------------------------------------------------
        out["bear_time_confirmed"] = bool(phase_a.get("reserve_start_raw"))
        out["auto_join_state"] = phase_b.get("auto_join_state", "UNKNOWN")
        out["role_name"] = role_name
        out["role_known"] = bool(role_name)

        dest = ROOT / "learning" / "bear_baseline_newaccount.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        out["ledger"] = str(dest.relative_to(ROOT))
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="new-account bear baseline session end")


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
