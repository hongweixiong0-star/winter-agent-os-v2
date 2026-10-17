# -*- coding: utf-8 -*-
"""Live exploration 4: harvest the *name* of every card in a shop, from the client itself.

explore3 found the one surface that names an item: a **long press** on a card opens a
tooltip with the item name, its description and 拥有数量 / 获取来源.  It is a pure overlay
-- no button, and the system back key dismisses it -- so it is read-only by construction.

This run harvests every card of a tab, so that the operator's rules can be applied to real
identities instead of guessed ones.  What it already settled, and why it mattered:

    游荡商人 的 Exp 蓝瓶  ->  「1,000点英雄经验」      NOT 统帅经验
    神秘商店 的 Exp 蓝瓶  ->  「50,000点英雄经验」

The operator's 游荡商人 rule says 钻石换**统帅经验** -> 买.  Had the bottle been taken for
统帅经验 on icon shape alone, the rule would have bought the wrong item.  So every card is
read here before any rule is allowed to fire.

Nothing is bought: a long press is a hold, never a click.  The top-bar wallet is compared
before and after each probe as the spend witness.

usage: python tools/shop_explore4.py [tab ...]      # default: 游荡商人
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

NAV_SHOP = "商店"
DEFAULT_TABS = ("游荡商人",)
TAB_BAND = 0.93
DETAIL_MARKERS = ("获取来源", "使用后获得", "拥有数量")
NAME = re.compile(r"^[\u4e00-\u9fff][\u4e00-\u9fff\w，,、·]{1,15}(点英雄经验|点统帅经验)?$")
STATS = re.compile(r"^(?:\d[\d,]*|[\d,]+点[\u4e00-\u9fff]+)$")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    tabs = tuple(sys.argv[1:]) or DEFAULT_TABS
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_explore4_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="VISIT_WANDERING_MERCHANT",
        ttl_seconds=1200,
        reason="harvest the real item names from the client's detail surface; buy nothing",
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
            time.sleep(1.6)

        def long_press(c, hold=1.3):
            ad.touch_down(int(c[0]), int(c[1]))
            time.sleep(hold)
            ad.touch_up()
            time.sleep(1.1)

        def wallet(toks):
            return [t["text"] for t in toks
                    if re.fullmatch(r"[\d,]{3,}", t["text"].strip())
                    and t["centre"][1] < 0.06 * 1280]

        def texts(toks):
            return [t["text"] for t in toks]

        def find(toks, names, *, band=None, h=None, exact=False):
            hits = []
            for t in toks:
                s = t["text"].strip()
                if (s in names) if exact else any(n in s for n in names):
                    if band is not None and h is not None and t["centre"][1] < band * h:
                        continue
                    hits.append(t)
            return hits

        # ------------------------------------------------------------- reach the store
        f, toks = snap("00_start")
        h, w = f.shape[0], f.shape[1]
        out["frame_size"] = [w, h]
        nav = find(toks, (NAV_SHOP,), band=0.85, h=h, exact=True)
        presses = 0
        while not nav and presses < 6:
            presses += 1
            ad.press_back()
            time.sleep(1.5)
            f, toks = snap(f"01_back{presses}")
            nav = find(toks, (NAV_SHOP,), band=0.85, h=h, exact=True)
        if not nav:
            print("NAV 商店 NOT FOUND:", texts(toks)[:40])
            return 4
        tap(max(nav, key=lambda t: t["centre"][1])["centre"])
        f, toks = snap("02_shop")

        for ti, tab in enumerate(tabs):
            hits = find(toks, (tab,), band=TAB_BAND, h=h)
            if not hits:
                print(f"tab {tab} NOT FOUND")
                continue
            tap(max(hits, key=lambda t: t["centre"][1])["centre"])
            f2, tk = snap(f"{10 + ti:02d}_tab_{tab}")
            before = wallet(tk)
            # Every card carries a 剩余：N label; long-pressing it lands inside that card.
            rest = sorted([t for t in tk if "剩余" in t["text"]],
                          key=lambda t: (t["centre"][1] // 100, t["centre"][0]))
            print(f"\n=== {tab} ===  cards={len(rest)}  wallet={before}")
            cards = []
            for ci, r in enumerate(rest):
                c = [int(r["centre"][0]), int(r["centre"][1])]
                long_press(c)
                f3, t3 = snap(f"{10 + ti:02d}_{tab}_card{ci}")
                opened = [m for m in DETAIL_MARKERS if any(m in x for x in texts(t3))]
                if not opened:
                    print(f"   card{ci} @{c} -> no detail (tokens {texts(t3)[:14]})")
                    cards.append({"index": ci, "probe_xy": c, "opened": False,
                                  "tokens": texts(t3)})
                else:
                    tt = texts(t3)
                    names = [x for x in tt if NAME.match(x.strip()) and len(x.strip()) >= 3]
                    desc = [x for x in tt if "使用后获得" in x]
                    own = [x for x in tt if "拥有数量" in x]
                    src = [x for x in tt if "获取来源" in x]
                    print(f"   card{ci} @{c} -> name={names[:3]}  desc={desc[:1]}  own={own[:1]}")
                    cards.append({"index": ci, "probe_xy": c, "opened": True,
                                  "names": names, "desc": desc, "own": own, "src": src,
                                  "tokens": tt})
                ad.press_back()
                time.sleep(1.1)
            f4, t4 = snap(f"{10 + ti:02d}_{tab}_end")
            after = wallet(t4)
            print(f"   wallet {before} -> {after}  moved={before != after}")
            out["tabs"][tab] = {"cards": cards, "wallet_before": before, "wallet_after": after,
                                "cards_seen": len(rest)}
            toks = t4

        out["wallet_at_end"] = wallet(toks)
        if not ad.touch_balance["balanced"]:
            ad.touch_up()
            time.sleep(0.4)
        out["touch_balance"] = ad.touch_balance
        print(f"\nwallet at end={out['wallet_at_end']}  touch_balance={out['touch_balance']}")

        (outd / "explore4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
        print("EVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="shop explore4 finished")


if __name__ == "__main__":
    raise SystemExit(main())
