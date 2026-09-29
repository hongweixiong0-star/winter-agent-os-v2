# -*- coding: utf-8 -*-
"""Live exploration round 3: open the 钓鱼锦标赛 home page and read it, WITHOUT fishing.

The entry was found in round 2 on the world map's right rail:
    钓鱼锦标赛 @ (664, 476), with a 03:28 countdown.

This script opens it and dumps every token and every frame, then stops.  Bait is
a scarce timed resource, so the home page is read before anything is spent.

usage: python tools/fishing_explore3.py
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

ENTRY = (664, 476)
FISH_WORDS = ("钓鱼", "魚", "钓", "锦标赛", "魚餌", "鱼饵", "鱼钩", "鱼线")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"fishing_explore3_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISHING_EXPLORE3", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=480, reason="read the fishing tournament home page")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT)), "screens": []}
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

        def look(tag: str, note: str = ""):
            f = frame()
            Image.fromarray(f).save(outd / f"{tag}.png")
            toks = read_all(Image.fromarray(f))
            txt = " ".join(t["text"] for t in toks)
            out["screens"].append({"tag": tag, "note": note, "text": txt[:600],
                                   "tokens": [{"t": t["text"], "c": list(t["centre"]),
                                               "box": list(t["box"]), "s": t.get("source")}
                                              for t in toks]})
            print(f"\n=== [{tag}] {note}  tokens={len(toks)}")
            for t in toks:
                print(f"   {t['centre']} [{t.get('source'):>12}] {t['text']}")
            return f, toks, txt

        def tap(c, wait=2.0):
            ad.click(int(c[0]), int(c[1]))
            time.sleep(wait)

        def back(n=1):
            for _ in range(n):
                ad.press_back()
                time.sleep(1.4)

        def dismiss():
            for _ in range(4):
                f, toks, txt = look("z_dialog", "dismiss")
                if "退出游戏" in txt:
                    h = [t for t in toks if t["text"].strip() == "取消"]
                    if h:
                        tap(h[0]["centre"])
                    continue
                if any(w in txt for w in ("恭喜", "欢迎回来", "离线收益")):
                    h = [t for t in toks if t["text"].strip() in ("确定", "关闭", "取消")]
                    if h:
                        tap(h[0]["centre"])
                    continue
                return f, toks, txt
            return frame(), [], ""

        # ---------- reach the world map ----------
        dismiss()
        _f, toks, txt = look("f0_start", "start")
        if "钓鱼锦标赛" not in txt:
            # get onto the map: the bottom-right nav shows 野外 from the city
            for _ in range(4):
                _f, toks, txt = look("f1_nav", "looking for the map")
                if "钓鱼锦标赛" in txt:
                    break
                h = [t for t in toks if t["text"].strip() in ("野外", "城镇")]
                if h:
                    tap(h[0]["centre"])
                else:
                    back(1)

        _f, toks, txt = look("f2_map", "world map with the fishing entry")
        hit = [t for t in toks if "钓鱼锦标赛" in t["text"]]
        if not hit:
            print("ENTRY NOT VISIBLE — aborting rather than guessing")
            (outd / "explore3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
            return 4
        out["entry"] = hit[0]["centre"]
        print(f"\n>>> tapping 钓鱼锦标赛 at {hit[0]['centre']}")
        tap(hit[0]["centre"], 2.6)

        # ---------- the fishing event home ----------
        f, toks, txt = look("g1_fishing_home", "fishing tournament home")
        (outd / "explore3.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print("\nHOME TEXT:", txt[:400])
        return 0
    finally:
        lease.release(result="DONE", reason="fishing explore3 finished")


if __name__ == "__main__":
    raise SystemExit(main())
