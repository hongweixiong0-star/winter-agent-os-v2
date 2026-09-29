# -*- coding: utf-8 -*-
"""Live exploration round 2: try every plausible entry looking for FISHING_TOURNAMENT.

Round 1 established that 常规活动 currently lists 峡谷会战 / 军备竞演 / 联盟总动员
with a grid of locked cards below and several top tabs.  This script walks the
candidate entries and dumps each screen, searching for a fishing word.

Because the same page is revisited many times, every screen is announced with its
identifier plus the fishing-word verdict, so a negative result is as explicit as a
positive one — "the event is not up right now" must be distinguishable from
"I did not look".

usage: python tools/fishing_explore2.py
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

FISH_WORDS = ("钓鱼", "釣魚", "锦标赛", "錦標", "鱼饵", "魚餌", "钓", "魚")
#: Entry points on the 常规活动 page, then elsewhere.  Coordinates are in the
#: native 720x1280 frame; they come from the round-1 token dump, not from memory.
TOP_TABS_Y = 170
AGENDA_TABS = [("tab1_峡谷会战", 161), ("tab2_奖杯", 305),
               ("tab3_军备竞演", 470), ("tab4_右端", 640)]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"fishing_explore2_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISHING_EXPLORE2", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=600, reason="walk candidate entries for the fishing event")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT)), "visited": []}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"], serial=cfg["device"]["serial"],
                                production=True, template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3

        def frame():
            for _ in range(3):
                f = ad.capture()
                if f is not None:
                    return f
                time.sleep(0.4)
            raise RuntimeError("SCREENCAP_FAILED")

        def look(tag: str, note: str = "") -> tuple[np.ndarray, list, str]:
            f = frame()
            Image.fromarray(f).save(outd / f"{tag}.png")
            toks = read_all(Image.fromarray(f))
            txt = " ".join(t["text"] for t in toks)
            fish = sorted({w for w in FISH_WORDS if w in txt})
            row = {"tag": tag, "note": note, "tokens": len(toks),
                   "fish_words": fish, "text": txt[:260],
                   "all_tokens": [{"t": t["text"], "c": list(t["centre"])} for t in toks]}
            out["visited"].append(row)
            print(f"[{tag}] tokens={len(toks)} fish={fish or 'NONE'}")
            print(f"    {txt[:150]}")
            return f, toks, txt

        def tap(c, wait=1.9):
            ad.click(int(c[0]), int(c[1]))
            time.sleep(wait)

        def back(n=1):
            for _ in range(n):
                ad.press_back()
                time.sleep(1.4)

        def dismiss_dialogs():
            for _ in range(3):
                _f, toks, txt = look("dialogs", "dismiss check")
                if "退出游戏" in txt:
                    h = [t for t in toks if t["text"].strip() == "取消"]
                    if h:
                        tap(h[0]["centre"])
                    continue
                if any(w in txt for w in ("恭喜", "祝贺你", "欢迎回来")):
                    h = [t for t in toks if t["text"].strip() in ("确定", "关闭", "取消")]
                    if h:
                        tap(h[0]["centre"])
                    continue
                return

        # ---------- go to 常规活动 ----------
        dismiss_dialogs()
        _f, toks, txt = look("a0_start", "where we begin")
        hits = [t for t in toks if "常规活动" in t["text"]]
        if hits:
            tap(max(hits, key=lambda t: t["centre"][1])["centre"])
        time.sleep(1.0)
        look("a1_regular_events", "常规活动 page")

        # ---------- walk the top tabs ----------
        for name, x in AGENDA_TABS:
            tap((x, TOP_TABS_Y), 2.0)
            look(f"a2_{name}", f"top tab at x={x}")

        # ---------- scroll the card grid for more activities ----------
        for i in range(3):
            try:
                ad.swipe(360, 1000, 360, 700, 400)
            except Exception as exc:  # noqa: BLE001
                print("swipe failed", exc)
            time.sleep(1.4)
            look(f"a3_grid_scroll{i + 1}", "activity grid scrolled")

        # ---------- leave and check 超值活动 (seen on the world map) ----------
        back(2)
        dismiss_dialogs()
        _f, toks, txt = look("b0_map", "world map")
        hits = [t for t in toks if "超值活动" in t["text"]]
        if hits:
            tap(hits[0]["centre"])
            look("b1_super_value", "超值活动")
            back(2)
            dismiss_dialogs()

        # ---------- the event-calendar style entries on the world map ----------
        _f, toks, txt = look("c0_map", "world map again")
        for word in ("活动中心", "活动日历", "限时活动", "小游戏", "趣味", "休闲"):
            hits = [t for t in toks if word in t["text"]]
            if hits:
                print(f"  found entry token {word} at {hits[0]['centre']}")
                tap(hits[0]["centre"])
                look(f"c1_{word}", f"opened {word}")
                back(2)
                dismiss_dialogs()
                _f, toks, txt = look("c2_back", "back on the map")

        found = [v for v in out["visited"] if v["fish_words"]]
        out["FISHING_FOUND"] = bool(found)
        out["fishing_evidence"] = found
        (outd / "explore2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print("\n================ RESULT ================")
        print("FISHING_FOUND:", out["FISHING_FOUND"])
        if found:
            for v in found:
                print("  ", v["tag"], v["fish_words"])
        else:
            print("  No fishing-tournament wording appeared on any visited screen.")
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="fishing explore2 finished")


if __name__ == "__main__":
    raise SystemExit(main())
