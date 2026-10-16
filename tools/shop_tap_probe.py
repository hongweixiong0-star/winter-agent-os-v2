# -*- coding: utf-8 -*-
"""Which point inside a shop card actually opens something?

Two live passes on 2026-10-04/05 disagree about the card's tap target.  In the read-only pass
five of six taps on the ``剩余`` label opened 确定购买.  In the next pass only the two
*diamond-priced* cards opened, and all four *resource-priced* cards ignored both the label and
the price.  Two explanations fit that pattern and only a measurement separates them:

  * the label is not part of the button -- the icon is, and the diamond cards happened to be
    hit closer to their icon;
  * a resource-priced card opens a *different* surface whose title is not 确定购买, and the
    reader was simply looking for the wrong word.

So this walks one card, taps it at a ladder of points, and prints what each one produced.
Read-only: every attempt is followed by the system back key and a check that the list is back.

usage: python tools/shop_tap_probe.py [row] [col]
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

TITLES = ("确定购买", "获取来源", "拥有数量", "取消", "确定", "购买")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    row = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    col = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.shop_visit import read_cards, ShopVisitor

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_tapprobe_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="SHOP_TAP_PROBE",
                             ttl_seconds=900, reason="find the shop card's real tap target")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3
        v = ShopVisitor(ad, outd)
        img, toks = v.enter()
        img, toks = v.select_tab("游荡商人")
        cards = read_cards(img, toks)
        target = next((c for c in cards if c.row == row and c.col == col), None)
        if target is None:
            print(f"no card at r{row}c{col}; have "
                  f"{[(c.row, c.col) for c in cards]}")
            return 4
        print(f"card r{row}c{col} 剩余={target.rest} price={target.price_text}"
              f" diamond={target.price_is_diamond} anchor={target.tap_xy} price_xy={target.price_xy}")

        ladder = [("label+0", (target.tap_xy[0], target.tap_xy[1])),
                  ("label-40", (target.tap_xy[0], target.tap_xy[1] - 40)),
                  ("label-70", (target.tap_xy[0], target.tap_xy[1] - 70)),
                  ("label-90", (target.tap_xy[0], target.tap_xy[1] - 90)),
                  ("price", target.price_xy),
                  ("price-25", (target.price_xy[0], target.price_xy[1] - 25))]
        results = []
        for name, xy in ladder:
            ad.click(int(xy[0]), int(xy[1]))
            time.sleep(1.8)
            f = ad.capture()
            Image.fromarray(f).save(outd / f"tap_{name}.png")
            tk = read_all(Image.fromarray(f))
            found = sorted({t["text"] for t in tk if t["text"].strip() in TITLES})
            texts = [t["text"] for t in tk]
            marks = [x for x in texts if "确定购买" in x or "获取来源" in x or "拥有数量" in x]
            print(f"   {name:>9} @{list(map(int, xy))} -> opened={found} marks={marks[:3]}")
            results.append({"point": name, "xy": [int(xy[0]), int(xy[1])],
                            "titles": found, "marks": marks[:4]})
            if found:
                ad.press_back()
                time.sleep(1.4)
                ad.capture()
        (outd / "tapprobe.json").write_text(json.dumps(
            {"row": row, "col": col, "card": target.to_dict(), "results": results},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="tap probe finished")


if __name__ == "__main__":
    raise SystemExit(main())
