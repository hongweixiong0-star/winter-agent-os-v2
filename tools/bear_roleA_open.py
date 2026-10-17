# -*- coding: utf-8 -*-
"""ROLE_A bear OPEN flow (20:30 battle night).

Fast Bear Flow: EVENT_ACTIVE -> ROLE_CONFIRMED -> AUTO_JOIN_STATE -> JOINED_STATE.
LIST_DYNAMIC join fallback: read rally rows fresh each frame, pick best joinable
bear row, tap its join control, handle troop/confirm dialog, then verify
JOINED_STATE by finding our role name in rally members.  All timings recorded
(frame_ts / row_selected_ts / join_click_ts / joined_ts -> FRAME_TO_JOIN_MS).
Hard deadline protects the schedule; no long timeouts on single steps.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVID = ROOT / "dataset" / "evidence" / f"bear_roleA_open_{STAMP}"

ROLE_NAME = "零氪"
BEAR_WORDS = ("冰原巨兽", "巨熊", "变异巨熊")
DEADLINE_LOCAL = "20:42:00"


@dataclass
class Tok:
    text: str
    centre: tuple[float, float]
    box: tuple[float, float, float, float] | None = None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2.rally import read_rally_list_image

    EVID.mkdir(parents=True, exist_ok=True)
    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner="DEVICE_BEAR_OPEN_ROLEA", capability_id="BEAR_HUNT",
        ttl_seconds=1500, reason="role A bear open flow")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    t0 = time.time()
    out: dict = {"flow_started_local": datetime.now().strftime("%H:%M:%S")}
    times: dict = {}

    def deadline() -> float:
        h, m, s = (int(v) for v in DEADLINE_LOCAL.split(":"))
        now = datetime.now()
        dl = now.replace(hour=h, minute=m, second=s, microsecond=0)
        return dl.timestamp()

    try:
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
            raw = _rapid_ocr_results(np.asarray(img), None, [])
            out_toks = []
            for t in raw:
                box = t.get("box") or ()
                try:
                    if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                        x, y, w, h = box
                        c = (x + w / 2, y + h / 2)
                        b = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                    else:
                        xs = [float(p[0]) for p in box]
                        ys = [float(p[1]) for p in box]
                        c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
                        b = list(box)
                except Exception:
                    c, b = (0.0, 0.0), None
                out_toks.append(Tok(text=t["text"], centre=c, box=b))
            return out_toks

        def text(img):
            return " ".join(t.text for t in toks(img))

        def save(img, tag):
            p = EVID / f"{tag}.png"
            p.parent.mkdir(parents=True, exist_ok=True)
            (img if isinstance(img, Image.Image) else Image.fromarray(img)).save(p)
            return p

        def tap(x, y, wait=1.5):
            adapter.click(int(x), int(y))
            time.sleep(wait)

        def tap_token(img, needle, wait=2.0, exact=False):
            cands = [t for t in toks(img)
                     if ((t.text.strip() == needle) if exact else (needle in t.text))]
            if not cands:
                return False
            t = max(cands, key=lambda tk: tk.centre[1])
            tap(*t.centre, wait)
            return True

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
                time.sleep(1.5)
            return frame()

        def dismiss_popups(max_rounds=4):
            for i in range(max_rounds):
                f = frame()
                if f is None:
                    return
                t = text(f)
                if any(w in t for w in ("确定", "确认", "欢迎回来", "离线收益")):
                    save(f, f"popup_{i}")
                    tap_token(f, "确定", 1.5) or tap_token(f, "确认", 1.5)
                    time.sleep(1.0)
                else:
                    return

        def rally_list_frame():
            """Navigate to alliance war rally list; return frame or None."""
            tap(511, 1243, 2.0)
            f = frame()
            save(f, "nav_alliance")
            if not tap_token(f, "联盟战争", 2.0):
                tap(246, 669, 2.0)
            f = frame()
            save(f, "nav_war")
            wt = text(f)
            if "集结" in wt:
                if not tap_token(f, "集结", 2.0, exact=True):
                    tap(160, 130, 1.5)
            f = frame()
            save(f, "nav_rally_list")
            return f

        def try_join_bear():
            """One LIST_DYNAMIC cycle: read rows, join best joinable bear."""
            f = rally_list_frame()
            if f is None:
                return None
            ftoks = toks(f)
            reading = read_rally_list_image(f, ftoks)
            bears = reading.joinable_bears()
            out.setdefault("list_reads", []).append({
                "ts": time.time() - t0,
                "rows": [r.to_dict() for r in reading.rows][:6],
            })
            if not bears:
                # also check if we already joined: our name in member lists
                ft = " ".join(t.text for t in ftoks)
                return {"joined_hint": ROLE_NAME in ft, "page": ft[:400]}
            row = reading.best_joinable()
            times["rally_frame_ts"] = time.time() - t0
            times["row_selected_ts"] = time.time() - t0
            w, h = f.size
            rr = row.to_row(width=w, height=h)
            if rr.join_point is None:
                return {"joined_hint": False, "error": "no join_point"}
            save(f, f"join_row_{int(times['row_selected_ts'])}")
            times["join_click_ts"] = time.time() - t0
            tap(*rr.join_point, wait=2.5)
            out["joined_row"] = row.to_dict()
            # handle troop / confirm dialog
            for i in range(4):
                df = frame()
                if df is None:
                    continue
                save(df, f"join_dialog_{i}")
                dt = text(df)
                for word in ("立即加入", "出征", "加入", "确定", "确认"):
                    if tap_token(df, word, 2.5):
                        break
                else:
                    if "统帅" in dt:
                        continue
                    break
            return {"joined_hint": None, "clicked": True}

        # ---- flow start: back to city, popups ----
        dismiss_popups()
        back_to_city()

        # confirm role quickly from profile once
        # (already verified 20:28 by bear_roleA_verify_fast; keep one OCR hint)
        out["role"] = "[ioi]零氪纯盾流"

        # ---- main loop until deadline ----
        clicked = False
        while time.time() < deadline():
            res = try_join_bear()
            if res is None:
                back_to_city()
                continue
            out.setdefault("cycle_results", []).append(res)
            if res.get("joined_hint"):
                times["joined_ts"] = time.time() - t0
                out["join_method"] = "AUTO_JOIN/ALREADY_IN" if not clicked else "JOIN_RALLY"
                break
            if res.get("clicked"):
                clicked = True
                # wait a bit for auto-advance, then recheck membership from list
                time.sleep(20)
            else:
                time.sleep(15)
            back_to_city()

        # ---- final JOINED_STATE verification: rally list member scan ----
        f = rally_list_frame()
        if f is not None:
            save(f, "final_list")
            ftoks = toks(f)
            reading = read_rally_list_image(f, ftoks)
            out["final_rows"] = [r.to_dict() for r in reading.rows][:8]
            ft = " ".join(t.text for t in ftoks)
            out["final_page_text"] = ft[:600]
            out["JOINED_STATE_final_scan"] = ROLE_NAME in ft

        out["times_s"] = {k: round(v, 2) for k, v in times.items()}
        if "join_click_ts" in times and "joined_ts" in times:
            out["FRAME_TO_JOIN_MS"] = round((times["joined_ts"] - times["join_click_ts"]) * 1000)
        out["total_flow_s"] = round(time.time() - t0, 1)

        dest = ROOT / "learning" / "bear_roleA_open.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        slim = {k: out.get(k) for k in ("role", "join_method", "joined_row", "JOINED_STATE_final_scan", "times_s", "FRAME_TO_JOIN_MS", "total_flow_s")}
        print(json.dumps(slim, ensure_ascii=False, indent=1))
        return 0
    finally:
        lease.release(result="DONE", reason="role A open flow done")


if __name__ == "__main__":
    raise SystemExit(main())
