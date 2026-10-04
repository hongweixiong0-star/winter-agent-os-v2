# -*- coding: utf-8 -*-
"""Observe the 神秘商店 page of the live client.  Read-only by construction.

    python tools/observe_mystery_shop.py [--probe-card]

Why this exists: the operator's policy for 神秘商店 is a rule about a *name* and a
*discount* ("名称含「英雄组件自选箱」且折扣=50%"), and neither of those words appears in the
游荡商人 page that the shop module was written against.  So the page has to be looked at
before anything is written, and the things that have to be seen are:

  * the card grid's geometry (the wandering merchant's 剩余/价格 arrangement is not assumed to
    hold here),
  * where a **discount** is displayed at all, and in what form (percent? a struck-through
    original price? a badge?),
  * the refresh control and the day's free-refresh count (base 1, up to 5 with 艾格尼丝),
  * whether tapping a card body opens the same 确定购买 overlay.

Nothing is bought and nothing is refreshed.  ``--probe-card`` opens exactly one card's overlay
and closes it again, because "does this page use the same two-tap purchase" is a question the
page itself must answer.

The tap discipline is the same one ``tools/shop_zone_map.py`` uses: an orange price pill on
screen means an overlay is already armed, and the only legal move then is to dismiss it -- a
tap aimed at "somewhere on the card" must never be able to land on a spend button.
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

TAB = "神秘商店"


def _save(img: np.ndarray, path: Path) -> None:
    Image.fromarray(img).save(path)


def _tokens_json(toks: list[dict]) -> list[dict]:
    return [{"text": t["text"],
             "centre": [int(t["centre"][0]), int(t["centre"][1])],
             "box": [int(v) for v in t.get("box", [])]} for t in toks]


def _orange_census(img: np.ndarray) -> list[dict]:
    """Every orange-ish blob above a noise floor, so a discount badge cannot hide in plain sight."""
    import cv2
    from winter_agent_v2.shop_visit import ORANGE_HUE, ORANGE_SAT_MIN, ORANGE_VAL_MIN
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, (ORANGE_HUE[0], ORANGE_SAT_MIN, ORANGE_VAL_MIN),
                       (ORANGE_HUE[1], 255, 255))
    n, _lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 400:                      # below this it is texture, not a control
            continue
        out.append({"bbox": [int(x), int(y), int(w), int(h)], "area": int(area),
                    "w_over_h": round(float(w) / max(1, h), 2),
                    "centre": [int(cents[i][0]), int(cents[i][1])]})
    return sorted(out, key=lambda b: -b["area"])[:25]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    probe_card = "--probe-card" in sys.argv[1:]

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2 import shop_visit as S

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_observe_mystery_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)
    log_file = (outd / "run.log").open("w", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION,
                             capability_id="VISIT_MYSTERY_SHOP", ttl_seconds=2400,
                             reason=f"observe 神秘商店 UI (probe_card={probe_card})")
    if rec is None:
        say(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    try:
        # A lease is a request, not a handover: AUTO keeps acting until its next safe point
        # (measured 2026-10-05: 22 s).  Tapping before that races the loop's current action.
        S.wait_for_the_device(ROOT, log=say)
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            say(reason)
            return 3

        v = S.ShopVisitor(ad, outd, log=say)
        img, toks = v.enter()
        h, w = img.shape[:2]
        say(f"entered the store from a {w}x{h} frame; tabs visible: {v._any(toks, S.STORE_TABS)}")

        # --- the tab itself ---------------------------------------------------
        img, toks = v.select_tab(TAB)
        _save(img, outd / "10_mystery_page_raw.png")
        (outd / "10_mystery_tokens.json").write_text(
            json.dumps(_tokens_json(toks), ensure_ascii=False, indent=1), encoding="utf-8")
        say(f"on {TAB}: raw frame + {len(toks)} tokens saved")
        say("   ALL TEXT ON THE PAGE (y, x, text):")
        for t in sorted(toks, key=lambda t: (t["centre"][1], t["centre"][0])):
            if t["text"].strip():
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")

        # --- what the shared reader makes of it ------------------------------
        cards = S.read_cards(img, toks)
        say(f"\nread_cards -> {len(cards)} card(s)")
        for c in cards:
            say(f"   r{c.row}c{c.col} rest={c.rest} price={c.price_text!r}"
                f" diamond={c.price_is_diamond} discount={c.discount}"
                f" tap={list(map(int, c.tap_xy))}")
        (outd / "cards.json").write_text(
            json.dumps([c.to_dict() for c in cards], ensure_ascii=False, indent=1), encoding="utf-8")

        # --- discount hunting -------------------------------------------------
        say(f"\ntokens containing 折/原/省/限/惠:")
        for t in toks:
            if any(k in t["text"] for k in "折原省限惠价"):
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")
        say(f"\ntokens containing 刷新/免费/今日/次:")
        for t in toks:
            if any(k in t["text"] for k in "刷新免费今日次"):
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")
        say(f"\ntokens containing 艾格尼丝/组件/自选/英雄:")
        for t in toks:
            if any(k in t["text"] for k in "艾格尼丝组件自选英雄"):
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")

        say("\norange census (>=400 px), area / w_over_h / bbox / centre:")
        for b in _orange_census(img):
            say(f"   area={b['area']:>7}  w/h={b['w_over_h']:>4}  bbox={b['bbox']}"
                f"  centre={b['centre']}")
        box = S.orange_price_button(img)
        say(f"orange_price_button(page) = {box}   (None means no purchase overlay is armed)")

        # --- does this page use the same two-tap purchase? --------------------
        if probe_card and cards:
            target = next((c for c in cards if c.rest > 0), cards[0])
            say(f"\n--probe-card: opening r{target.row}c{target.col}"
                f" from anchor {list(map(int, target.tap_xy))} -- NOT buying")
            t0 = time.monotonic()
            opened, oimg, otoks = v.open_purchase(target)
            say(f"   open_purchase -> {opened} in {time.monotonic() - t0:.1f}s")
            if opened and oimg is not None:
                _save(oimg, outd / "20_card_overlay_raw.png")
                (outd / "20_card_overlay_tokens.json").write_text(
                    json.dumps(_tokens_json(otoks), ensure_ascii=False, indent=1), encoding="utf-8")
                for t in sorted(otoks, key=lambda t: (t["centre"][1], t["centre"][0])):
                    if t["text"].strip():
                        say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")
                name, desc = S.item_name_from_dialog(otoks)
                say(f"   item_name_from_dialog -> {name!r} / {desc!r}")
                pill = S.orange_price_button(oimg)
                say(f"   overlay orange_price_button = {pill}")
                if pill is not None:
                    says, ev = S.read_button_price(oimg, pill["bbox"])
                    say(f"   read_button_price -> {says!r}  (numbers seen: {ev.get('numbers')})")
                else:
                    _save(oimg, outd / "20_card_overlay_raw.png")
                # Close it without spending.  The only tap allowed here is the client's own ✕.
                v._dismiss_dialog()
                chk = v._frame()
                say(f"   after dismiss: orange_price_button = {S.orange_price_button(chk)}")
            else:
                say(f"   overlay did not open ({v.trace[-1]['step'] if v.trace else '?'})")

        # --- leave the device where we found it -------------------------------
        img, toks = v.see("90_final")
        _save(img, outd / "90_final_raw.png")
        say(f"\nfinal page: tabs possible={v._any(toks, S.STORE_TABS)}"
            f" orange={S.orange_price_button(img)}")
        say(f"backs_used={v._back_used} taps_refused={getattr(v, '_tap_refused', 0)}")
        say(f"EVIDENCE: {outd}")
        return 0
    finally:
        log_file.close()
        lease.release(result="DONE", reason="mystery shop observation finished")


if __name__ == "__main__":
    raise SystemExit(main())
