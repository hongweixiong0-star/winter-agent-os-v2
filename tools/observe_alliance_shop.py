# -*- coding: utf-8 -*-
"""Observe the 联盟商店 page of the live client.  Read-only by construction.

    python tools/observe_alliance_shop.py [--probe-card]

Why this exists: 联盟商店 is reachable only from the ALLIANCE page, which is a different branch
of the bottom navigation from the 商店 the shop module was written against.  Two things are
already *known* and are treated as priors to check, not as coordinates to fire at:

  * the HOME bottom-nav 联盟 entry, measured live as a template with ``roi_norm x 0.7097
    y 0.9711 w 0.0694 h 0.0219`` (centre ~(536,1257) on 720x1280);
  * the ALLIANCE page's 联盟商店 tile label, measured 2026-09-26 at normalised bbox
    ``x 0.2361 y 0.7039 w 0.2111 h 0.0578`` -> centre (246,938), with the row's red dot at
    (335,884).

What is *not* known, and is the point of this tool:

  * what the 联盟商店 page looks like -- its header, its grid geometry, how many slots it
    shows, and whether the cards print a name (the store's four tabs do not, but this is a
    different page and the assumption must not be carried across);
  * what currency it is priced in (the store's 游荡商人 uses 钻石, 神秘商店 uses a gold coin);
  * whether tapping a card body opens the same 确定购买 overlay, i.e. whether the two-tap
    purchase this module implements applies here at all;
  * whether the operator's name-based rule (名称含「统帅经验」) is even evaluable from what the
    page and its overlay print.

Nothing is bought.  ``--probe-card`` opens exactly one card's overlay and closes it with the
client's own ✕.

The tap discipline is the module's: an orange price pill on screen means an overlay is already
armed, and the only legal move then is to dismiss it -- a tap aimed at "somewhere on the card"
must never be able to land on a spend button.
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

# The prior for the ALLIANCE page tile, from
# knowledge/perception/candidates/alliance_btn_shop__1ba620d5/metadata.yaml.  Printed next to
# what the live OCR actually reads so a drift is visible rather than silent.
PRIOR_TILE_CENTRE = (246, 938)


def _save(img: np.ndarray, path: Path) -> None:
    Image.fromarray(img).save(path)


def _tokens_json(toks: list[dict]) -> list[dict]:
    return [{"text": t["text"],
             "centre": [int(t["centre"][0]), int(t["centre"][1])],
             "box": [int(v) for v in t.get("box", [])]} for t in toks]


def _dump(say, toks: list[dict]) -> None:
    for t in sorted(toks, key=lambda t: (t["centre"][1], t["centre"][0])):
        if t["text"].strip():
            say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    probe_card = "--probe-card" in sys.argv[1:]
    shift_tab = "--tab-shift" in sys.argv[1:]
    scroll = "--scroll" in sys.argv[1:]

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2 import shop_visit as S

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_observe_alliance_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)
    log_file = (outd / "run.log").open("w", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION,
                             capability_id="VISIT_ALLIANCE_SHOP", ttl_seconds=2400,
                             reason=f"observe 联盟商店 UI (probe_card={probe_card})")
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

        # --- hop 1: HOME -> ALLIANCE -----------------------------------------
        img, toks = v.enter_alliance()
        _save(img, outd / "10_alliance_page_raw.png")
        (outd / "10_alliance_tokens.json").write_text(
            json.dumps(_tokens_json(toks), ensure_ascii=False, indent=1), encoding="utf-8")
        h, w = img.shape[:2]
        say(f"on the ALLIANCE page ({w}x{h}); tiles read: {v._any(toks, S.ALLIANCE_TILES)}")
        say("   ALL TEXT ON THE ALLIANCE PAGE (y, x, text):")
        _dump(say, toks)

        # --- the tile, against its prior -------------------------------------
        tile = v._at(toks, S.ALLIANCE_ENTRY, exact=False)
        if tile is None:
            say(f"\nSTOP: {S.ALLIANCE_ENTRY} is not readable on the alliance frame")
            return 4
        cx, cy = (int(tile["centre"][0]), int(tile["centre"][1]))
        say(f"\n{S.ALLIANCE_ENTRY} live centre = ({cx}, {cy})"
            f"   prior (alliance_btn_shop__1ba620d5) = {PRIOR_TILE_CENTRE}"
            f"   drift = ({cx - PRIOR_TILE_CENTRE[0]}, {cy - PRIOR_TILE_CENTRE[1]})")

        # --- hop 2: ALLIANCE -> the shop -------------------------------------
        img, toks = v.open_alliance_shop()
        _save(img, outd / "20_alliance_shop_page_raw.png")
        (outd / "20_alliance_shop_tokens.json").write_text(
            json.dumps(_tokens_json(toks), ensure_ascii=False, indent=1), encoding="utf-8")
        say(f"\non the 联盟商店 page; {len(toks)} tokens saved")
        say("   ALL TEXT ON THE 联盟商店 PAGE (y, x, text):")
        _dump(say, toks)

        # --- what the shared reader makes of it ------------------------------
        cards = S.read_cards(img, toks)
        say(f"\nread_cards -> {len(cards)} card(s)")
        for c in cards:
            say(f"   r{c.row}c{c.col} rest={c.rest} price={c.price_text!r}"
                f" diamond={c.price_is_diamond} discount={c.discount}"
                f" tap={list(map(int, c.tap_xy))}")
        (outd / "cards.json").write_text(
            json.dumps([c.to_dict() for c in cards], ensure_ascii=False, indent=1),
            encoding="utf-8")

        # --- the policy's own words, hunted explicitly ------------------------
        say("\ntokens containing 统帅/英雄/经验 (the rule keys on 统帅经验):")
        for t in toks:
            if any(k in t["text"] for k in "统帅英雄经验"):
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")
        say("\ntokens containing 刷新/免费/今日/次:")
        for t in toks:
            if any(k in t["text"] for k in "刷新免费今日次"):
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")
        say("\ntokens containing 剩余/兑换/捐献/币:")
        for t in toks:
            if any(k in t["text"] for k in "剩余兑换捐献币"):
                say(f"     {int(t['centre'][1]):>4} {int(t['centre'][0]):>4}  {t['text']!r}")
        say(f"\ntop bar numbers (diamond, coin): {S.top_bar_numbers(toks, h)}")
        say(f"orange_price_button(page) = {S.orange_price_button(img)}"
            "   (None means no purchase overlay is armed)")

        def dump_cards(tag: str, cds: list) -> None:
            say(f"   {tag}: read_cards -> {len(cds)} card(s)")
            for c in cds:
                say(f"      r{c.row}c{c.col} rest={c.rest} price={c.price_text!r}"
                    f" diamond={c.price_is_diamond} disc={c.discount}"
                    f" tap={list(map(int, c.tap_xy))}")

        # --- is the grid longer than the screen? ------------------------------
        # The first frame shows three complete rows and a fourth clipped by the bottom strip,
        # so the page is scrollable and a single screen is NOT the whole stock.  A rule that
        # must find a named item therefore cannot assume one frame sees it.
        if scroll:
            for i in range(2):
                say(f"\n--scroll {i}: swiping up inside the grid (no control is touched)")
                ad.swipe(w // 2, 1050, w // 2, 420, 420)
                time.sleep(1.8)
                img2, toks2 = v.see(f"50_scroll{i}")
                _save(img2, outd / f"50_scroll{i}_raw.png")
                (outd / f"50_scroll{i}_tokens.json").write_text(
                    json.dumps(_tokens_json(toks2), ensure_ascii=False, indent=1),
                    encoding="utf-8")
                dump_cards(f"scroll{i}", S.read_cards(img2, toks2))

        # --- 今日 / 本周 ------------------------------------------------------
        # The bottom strip of this page is NOT the store's tab strip (游荡商人/神秘商店/...):
        # it reads 今日 / 本周, i.e. two different stocks.  Which one is shown by default, and
        # whether they differ, is a fact the page has to supply.
        if shift_tab:
            node = v._at(toks, "本周", exact=False)
            if node is None:
                say("\n--tab-shift: 本周 is not readable on the shop frame")
            else:
                say(f"\n--tab-shift: tapping 本周 at {list(map(int, node['centre']))}")
                v._tap_xy(node["centre"])
                img2, toks2 = v.see("40_tab_week")
                _save(img2, outd / "40_tab_week_raw.png")
                (outd / "40_tab_week_tokens.json").write_text(
                    json.dumps(_tokens_json(toks2), ensure_ascii=False, indent=1),
                    encoding="utf-8")
                dump_cards("本周", S.read_cards(img2, toks2))
                say("   ALL TEXT ON THE 本周 FRAME (y, x, text):")
                _dump(say, toks2)
                back = v._at(toks2, "今日", exact=False)
                if back is not None:
                    say(f"   returning to 今日 at {list(map(int, back['centre']))}")
                    v._tap_xy(back["centre"])
                    _img3, toks3 = v.see("41_tab_today_back")
                    dump_cards("今日(back)", S.read_cards(_img3, toks3))

        # --- does this page use the same two-tap purchase? --------------------
        if probe_card and cards:
            target = next((c for c in cards if c.rest > 0), cards[0])
            say(f"\n--probe-card: opening r{target.row}c{target.col}"
                f" from anchor {list(map(int, target.tap_xy))} -- NOT buying")
            t0 = time.monotonic()
            opened, oimg, otoks = v.open_purchase(target)
            say(f"   open_purchase -> {opened} in {time.monotonic() - t0:.1f}s")
            if opened and oimg is not None:
                _save(oimg, outd / "30_card_overlay_raw.png")
                (outd / "30_card_overlay_tokens.json").write_text(
                    json.dumps(_tokens_json(otoks), ensure_ascii=False, indent=1),
                    encoding="utf-8")
                say("   ALL TEXT ON THE OVERLAY (y, x, text):")
                _dump(say, otoks)
                name, desc = S.item_name_from_dialog(otoks)
                say(f"   item_name_from_dialog -> {name!r} / {desc!r}")
                say(f"   decide_alliance({name!r}) -> {S.decide_alliance(name)}")
                pill = S.orange_price_button(oimg)
                say(f"   overlay orange_price_button = {pill}")
                if pill is not None:
                    says, ev = S.read_button_price(oimg, pill["bbox"])
                    say(f"   read_button_price -> {says!r}  (numbers seen: {ev.get('numbers')})")
                # Close it without spending.  The only tap allowed here is the client's own ✕.
                # The page is NOT the store, so the check is handed the right predicate.
                v._dismiss_dialog(on_page=lambda tk, hh: not v.on_alliance_page(tk, hh))
                chk = v._frame()
                say(f"   after dismiss: orange_price_button = {S.orange_price_button(chk)}")
            else:
                say(f"   overlay did not open ({v.trace[-1]['step'] if v.trace else '?'})")

        # --- leave the device where we found it -------------------------------
        img, toks = v.see("90_final")
        _save(img, outd / "90_final_raw.png")
        say(f"\nfinal page: alliance tiles={v._any(toks, S.ALLIANCE_TILES)}"
            f" orange={S.orange_price_button(img)}")
        say(f"backs_used={v._back_used} taps_refused={getattr(v, '_tap_refused', 0)}")
        say(f"EVIDENCE: {outd}")
        return 0
    finally:
        log_file.close()
        lease.release(result="DONE", reason="alliance shop observation finished")


if __name__ == "__main__":
    raise SystemExit(main())
