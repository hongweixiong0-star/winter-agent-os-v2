# -*- coding: utf-8 -*-
"""Live exploration 1: reach the store and photograph what 游荡商人 actually shows.

Capture-first discipline, the same as ``tools/fishing_explore1.py``: nothing about the shop
UI is inferred offline.  Every finding in this run is a PNG plus an OCR token dump from the
real client, so the card reader and the purchase rule can be built on measured pixels.

What this script answers, and only this:

  1. Where is the store entry *on the current client*, and does OCR see it?
  2. What does the 游荡商人 tab contain -- which labels are text, and which are icon-only?
  3. Can the price currency (diamond vs resource) be told apart from text alone?  The rule
     the operator gave turns on exactly that, so if it cannot, that is the finding.

Nothing is purchased and nothing is refreshed here.  Coordinates are never written down: each
tap is the centre of a box OCR found *in that frame*.

usage: python tools/shop_explore1.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The bottom navigation's shop item, and the store's own tab labels.  The tab labels are
#: matched *after* entry, i.e. only on a frame that is already the store.
NAV_SHOP = "商店"
TABS = ("游荡商人", "神秘商店", "竞技商店", "统帅市", "统帅市集")
REFRESH = ("免费刷新", "刷新", "下次刷新")
#: Bottom navigation band, as a fraction of frame height.  The city screen puts its nav bar
#: at the very bottom; the store's own tab strip also lives low, so the band alone is not
#: enough -- the tabs are excluded by name instead.
NAV_BAND = 0.85
PRICE = re.compile(r"^\s*[\d,，]+\s*万?\s*$")
PERCENT = re.compile(r"(\d+)\s*%")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_explore1_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="VISIT_WANDERING_MERCHANT",
        ttl_seconds=600, reason="observe the store entry and the wandering merchant tab",
    )
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    out: dict = {"stamp": stamp, "dir": str(outd.relative_to(ROOT))}
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
            toks = read_all(Image.fromarray(f))
            return f, toks

        def dump(toks):
            """Tokens in reading order, so a layout can be read off the printout."""
            return sorted(({"text": t["text"], "centre": [int(t["centre"][0]), int(t["centre"][1])],
                            "box": [int(v) for v in t["box"]], "source": t.get("source")}
                           for t in toks), key=lambda r: (r["centre"][1] // 24, r["centre"][0]))

        def tap(c):
            ad.click(int(c[0]), int(c[1]))
            time.sleep(1.6)

        # ---------------------------------------------------------------- 1. where are we
        f, toks = snap("00_state")
        h, w = f.shape[0], f.shape[1]
        rows = dump(toks)
        out["frame_size"] = [w, h]
        print(f"frame {w}x{h}  tokens={len(rows)}")
        print("STATE:", " ".join(t["text"] for t in toks)[:220])
        print("\n--- 00_state tokens (reading order) ---")
        for r in rows:
            print(f"   {str(r['centre']):>14} [{r['source']:>12}] {r['text']}")

        # ------------------------------------------------- 2. find the bottom navigation shop
        def nav_shop(toks):
            hits = [t for t in toks
                    if t["text"].strip() == NAV_SHOP and t["centre"][1] > NAV_BAND * h]
            return max(hits, key=lambda t: t["centre"][1]) if hits else None

        target = nav_shop(toks)
        route: list[dict] = []
        presses = 0
        while target is None and presses < 6:
            presses += 1
            ad.press_back()
            time.sleep(1.6)
            f, toks = snap(f"01_back{presses}")
            print(f"\n--- after back {presses}:", " ".join(t["text"] for t in toks)[:160])
            target = nav_shop(toks)
        out["back_presses"] = presses

        if target is None:
            out["note"] = "bottom-navigation 商店 never became visible"
            print("\nNAV 商店 NOT FOUND -- dumping everything for route discovery")
            for r in dump(toks):
                print(f"   {str(r['centre']):>14} [{r['source']:>12}] {r['text']}")
            (outd / "explore1.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            print("\nEVIDENCE:", outd)
            return 0

        route.append({"tap": NAV_SHOP, "centre": list(target["centre"]),
                      "box": [int(v) for v in target["box"]]})
        tap(target["centre"])
        f, toks = snap("02_shop")
        rows = dump(toks)
        out["shop_tokens"] = rows
        txt = " ".join(t["text"] for t in toks)
        out["shop_text"] = txt[:600]
        print("\n--- 02_shop tokens (reading order) ---")
        for r in rows:
            print(f"   {str(r['centre']):>14} [{r['source']:>12}] {r['text']}")

        # ---------------------------------------------------- 3. tabs, refresh, discount
        out["tabs_seen"] = [t["text"] for t in toks if any(x in t["text"] for x in TABS)]
        out["refresh_seen"] = [{"text": t["text"], "centre": list(t["centre"])}
                               for t in toks if any(x in t["text"] for x in REFRESH)]
        out["percents_seen"] = [{"text": t["text"], "centre": list(t["centre"]),
                                 "box": [int(v) for v in t["box"]]}
                                for t in toks if PERCENT.search(t["text"])]
        out["prices_seen"] = [{"text": t["text"], "centre": list(t["centre"]),
                               "box": [int(v) for v in t["box"]]}
                              for t in toks if PRICE.match(t["text"])]
        print("\nTABS   :", out["tabs_seen"])
        print("REFRESH:", json.dumps(out["refresh_seen"], ensure_ascii=False))
        print("PERCENT:", [p["text"] for p in out["percents_seen"]])
        print("PRICES :", [p["text"] for p in out["prices_seen"]])

        # The price row in this client renders as [currency icon][number].  The icon is the
        # only thing that says whether the cost is diamonds -- the rule turns on it, so save
        # a crop to the left of every price and look at them.
        crops = []
        img = Image.fromarray(f)
        for p in out["prices_seen"]:
            x, y = p["centre"]
            box = (max(0, x - 62), max(0, y - 22), min(w, x + 62), min(h, y + 22))
            name = f"price_{y:04d}_{x:04d}.png"
            img.crop(box).resize(((box[2] - box[0]) * 3, (box[3] - box[1]) * 3),
                                 Image.LANCZOS).save(outd / name)
            crops.append({"price": p["text"], "crop": name, "box": list(box)})
        out["price_crops"] = crops
        print(f"\nsaved {len(crops)} price crops for currency-icon inspection")

        out["route"] = route
        (outd / "explore1.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print("\nEVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="shop explore1 finished")


if __name__ == "__main__":
    raise SystemExit(main())
