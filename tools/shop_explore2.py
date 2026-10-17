# -*- coding: utf-8 -*-
"""Live exploration 2: what every store tab offers, and what a free refresh actually does.

Two questions this run exists to answer, both of them things that must be measured on the
client rather than assumed:

  1. Does *any* store surface print the item name?  The operator's 神秘商店 rule turns on a
     name ("名称含英雄组件自选箱"), and the 游荡商人 rule turns on an item identity
     ("统帅经验").  The 游荡商人 cards print none -- measured 2026-10-04 -- so if some other
     tab does, that is where the name reader comes from.
  2. What does pressing 免费刷新 change?  The countdown, the stock, the button, or a counter
     we have to respect to stay inside "3 times a day".

Read-only apart from one free refresh, which the operator's rule permits.  Nothing is bought:
a card is a purchase control and is never tapped to "see what it is".

usage: python tools/shop_explore2.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NAV_SHOP = "商店"
TABS = ("游荡商人", "神秘商店", "竞技商店", "统帅市")
TAB_BAND = 0.93          # the store's tab strip sits in the bottom 7% of the frame
REFRESH_LABEL = "免费刷新"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_explore2_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="VISIT_WANDERING_MERCHANT",
        ttl_seconds=900, reason="map every store tab and measure one free refresh",
    )
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT)), "tabs": {}}
    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
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
            return f, read_all(Image.fromarray(f))

        def tap(c):
            ad.click(int(c[0]), int(c[1]))
            time.sleep(1.7)

        def rows(toks):
            return sorted(({"text": t["text"],
                            "centre": [int(t["centre"][0]), int(t["centre"][1])]}
                           for t in toks), key=lambda r: (r["centre"][1] // 22, r["centre"][0]))

        def find(toks, names, *, band=None, h=None, exact=False):
            hits = []
            for t in toks:
                text = t["text"].strip()
                ok_text = text in names if exact else any(n in text for n in names)
                if not ok_text:
                    continue
                if band is not None and h is not None and t["centre"][1] < band * h:
                    continue
                hits.append(t)
            return hits

        # ------------------------------------------------------------------ 1. reach the store
        f, toks = snap("00_start")
        h, w = f.shape[0], f.shape[1]
        out["frame_size"] = [w, h]
        nav = find(toks, (NAV_SHOP,), band=0.85, h=h, exact=True)
        presses = 0
        while not nav and presses < 6:
            presses += 1
            ad.press_back()
            time.sleep(1.6)
            f, toks = snap(f"01_back{presses}")
            nav = find(toks, (NAV_SHOP,), band=0.85, h=h, exact=True)
        if not nav:
            print("NAV 商店 NOT FOUND; tokens:", [r["text"] for r in rows(toks)][:40])
            return 4
        out["back_presses"] = presses
        tap(max(nav, key=lambda t: t["centre"][1])["centre"])

        f, toks = snap("02_shop")
        print(f"entered store after {presses} back press(es); frame {w}x{h}")

        # ---------------------------------------------------- 2. every tab, and what it prints
        for tab in TABS:
            hits = find(toks, (tab,), band=TAB_BAND, h=h)
            if not hits:
                print(f"  tab {tab}: NOT FOUND (stock changed? dumping)")
                out["tabs"][tab] = {"error": "tab not found"}
                continue
            tap(max(hits, key=lambda t: t["centre"][1])["centre"])
            f2, tk = snap(f"03_tab_{TABS.index(tab)}_{tab}")
            rr = rows(tk)[1:] if False else rows(tk)
            # What is on this tab, minus the chrome we have already described.
            body = [r for r in rr if not (r["centre"][1] > TAB_BAND * h)]
            out["tabs"][tab] = {"tokens": rr, "body_tokens": body}
            print(f"\n=== tab {tab} ===  tokens={len(rr)}")
            print("   TAB STRIP :", [t["text"] for t in tk if t["centre"][1] > TAB_BAND * h])
            print("   BANNER    :", [t["text"] for t in tk if t["centre"][1] < 0.30 * h])
            print("   BODY      :", [r["text"] for r in body][:60])
            # The tab strip tells us the tap landed; the frame is the evidence.
            toks = tk

        # --------------------------------------------------------- 3. one free refresh, watched
        back = find(toks, ("游荡商人",), band=TAB_BAND, h=h)
        if back:
            tap(max(back, key=lambda t: t["centre"][1])["centre"])
        f3, tk = snap("04_before_refresh")
        btn = find(tk, (REFRESH_LABEL,))
        out["refresh"] = {"button_found": bool(btn),
                          "countdown": [r["text"] for r in rows(tk)
                                        if "刷新" in r["text"] or ":" in r["text"]][:6]}
        print("\n--- before refresh ---")
        print("   button:", [list(t["centre"]) for t in btn])
        print("   refresh-ish tokens:", out["refresh"]["countdown"])
        if btn:
            tap(max(btn, key=lambda t: t["centre"][1])["centre"])
            f4, tk4 = snap("05_after_refresh")
            out["refresh"]["after"] = {
                "texts": [r["text"] for r in rows(tk4) if "刷新" in r["text"] or ":" in r["text"]][:8],
                "body": [r["text"] for r in rows(tk4) if r["centre"][1] < TAB_BAND * h][:60],
            }
            print("--- after refresh ---")
            print("   refresh-ish:", out["refresh"]["after"]["texts"])
            print("   body:", out["refresh"]["after"]["body"][:40])

        (outd / "explore2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        print("\nEVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="shop explore2 finished")


if __name__ == "__main__":
    raise SystemExit(main())
