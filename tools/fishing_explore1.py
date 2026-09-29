# -*- coding: utf-8 -*-
"""Live exploration: find the FISHING_TOURNAMENT in the client and photograph it.

Capture-first discipline: nothing about the fishing UI is inferred offline.  Every
finding in this run is a PNG plus a token dump from the real client, so the
detector/ROI work in PHASE 8 can be built on measured pixels.

Step 1 (this script): reach 常规活动 and dump EVERYTHING on it.

usage: python tools/fishing_explore1.py
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

FISH_WORDS = ("钓鱼", "釣魚", "锦标赛", "錦標", "鱼", "魚", "Fishing", "钓")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"fishing_explore1_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner="DEVICE_FISHING_EXPLORE1", capability_id="FISHING_TOURNAMENT",
                             ttl_seconds=420, reason="discover the fishing tournament entry")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2
    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT))}
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

        def snap(tag: str):
            f = frame()
            Image.fromarray(f).save(outd / f"{tag}.png")
            toks = read_all(Image.fromarray(f))
            return f, toks

        def tap_centre(c):
            ad.click(int(c[0]), int(c[1]))
            time.sleep(1.8)

        def find(toks, *words, exact=False):
            hits = []
            for t in toks:
                if exact:
                    if t["text"].strip() in words:
                        hits.append(t)
                elif any(w in t["text"] for w in words):
                    hits.append(t)
            return hits

        # ---------- 1. make sure we are not inside a dialog ----------
        for _ in range(6):
            _f, toks = snap("00_state")
            txt = " ".join(t["text"] for t in toks)
            if "退出游戏" in txt:
                h = find(toks, "取消", exact=True)
                if h:
                    tap_centre(h[0]["centre"])
                continue
            break
        f, toks = snap("00_state")
        txt = " ".join(t["text"] for t in toks)
        out["state_text"] = txt[:300]
        print("STATE:", txt[:200])
        print(f"tokens={len(toks)}")

        # ---------- 2. open 常规活动 ----------
        route = []
        hits = find(toks, "常规活动", exact=True) or find(toks, "常规活动")
        if hits:
            h = max(hits, key=lambda t: t["centre"][1])
            route.append({"tap": "常规活动", "centre": h["centre"]})
            tap_centre(h["centre"])
            f, toks = snap("01_after_changggui")
            txt = " ".join(t["text"] for t in toks)
            print("AFTER 常规活动:", txt[:250])
        else:
            out["note"] = "常规活动 not visible on this screen"
            print("常规活动 NOT FOUND; dumping everything for route discovery")
            for t in toks:
                print("   ", t["centre"], repr(t["text"]))

        # ---------- 3. dump every token on the activity screen ----------
        f, toks = snap("02_activity_screen")
        rows = [{"text": t["text"], "centre": list(t["centre"]),
                 "box": list(t["box"]), "source": t.get("source")} for t in toks]
        out["activity_tokens"] = rows
        txt = " ".join(t["text"] for t in toks)
        out["activity_text"] = txt[:500]
        print("\n--- ACTIVITY SCREEN TOKENS ---")
        for r in rows:
            print(f"   {r['centre']} [{r['source']:>12}] {r['text']}")

        fish = [r for r in rows if any(w in r["text"] for w in FISH_WORDS)]
        out["fish_hits"] = fish
        print("\nFISH HITS:", json.dumps(fish, ensure_ascii=False))

        # ---------- 4. if a fishing token exists, open it ----------
        if fish:
            h = max(fish, key=lambda r: r["centre"][1])
            route.append({"tap": h["text"], "centre": h["centre"]})
            tap_centre(h["centre"])
            f, toks2 = snap("03_after_fish_tap")
            txt2 = " ".join(t["text"] for t in toks2)
            out["fishing_screen_text"] = txt2[:500]
            out["fishing_tokens"] = [{"text": t["text"], "centre": list(t["centre"]),
                                      "source": t.get("source")} for t in toks2]
            print("\nAFTER FISH TAP:", txt2[:300])
            print("\n--- FISHING SCREEN TOKENS ---")
            for t in toks2:
                print(f"   {t['centre']} [{t.get('source'):>12}] {t['text']}")

        out["route"] = route
        (outd / "explore1.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print("\nEVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="fishing explore1 finished")


if __name__ == "__main__":
    raise SystemExit(main())
