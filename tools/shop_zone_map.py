# -*- coding: utf-8 -*-
"""Map the tappable zones of a merchant card, live, one card at a time.

    python tools/shop_zone_map.py [--cards r1c1,r0c0] [--offsets -110,...,110]

Why this exists
---------------
Two earlier probes disagree, and the disagreement cost a real decision:

* ``tools/shop_tap_probe.py`` (card r1c0) -- taps 40/70/90 px *above* the 剩余 label opened
  the read-only tooltip; the 剩余 label and the price pill produced **nothing at all**.
* ``tools/shop_tap_map.py`` (one card) -- every offset from the 剩余 anchor's own y down to
  +80 opened the purchase overlay; -45/-65/-85 opened the tooltip.

The 2026-10-05 03:22 pass then split the difference in a way neither predicts: the four
diamond-priced cards opened their overlay from the body ladder, while the card whose price
was a resource (r1c1, 50,000 food) absorbed **twelve** taps at +0/+30/+55 and did nothing.
The ladder covers anchor+0..+55; what it never touches is the zone *above* the anchor.

So this tool walks a single fine ladder across the card's whole vertical extent -- icon,
label, pill -- and reports what each offset actually produced, for several cards in one
pass, so the answer can be read as a shape rather than as a single anecdote.

Classification is OpenCV-only and therefore instant: the purchase overlay is identified by
its own orange price button (``orange_price_button``), a tooltip by the size of the change
against the pre-tap frame.  Only a real hit pays for OCR.

Safety
------
Nothing here can spend: the only orange thing on the page is the overlay's price button,
and before **every** tap the current frame is checked and any open overlay is dismissed
first, so a tap can never land on a price button.  No refresh is ever tapped.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LADDER = (-110, -90, -70, -50, -30, -10, 0, 15, 30, 45, 60, 80, 100, 110)
PANEL_MIN_PX = 40000        # a tooltip is a big panel; the countdown contributes ~2k
CHANGE_MIN = 40             # per-pixel channel delta that counts as "changed"


def _changed(before: np.ndarray, after: np.ndarray) -> int:
    if before is None or before.shape != after.shape:
        return -1
    return int((np.abs(after.astype(np.int16) - before.astype(np.int16)).max(axis=2)
                > CHANGE_MIN).sum())


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    from PIL import Image

    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.shop_visit import (DIALOG_TITLE, TOOLTIP_MARKERS, ShopVisitor,
                                            orange_price_button, read_cards)

    argv = sys.argv[1:]
    want = [s.strip() for s in (_opt(argv, "--cards") or "auto").split(",") if s.strip()]
    ladder = tuple(int(v) for v in (_opt(argv, "--offsets") or "").split(",") if v.strip()) \
        or LADDER

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_zone_map_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(
        owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="VISIT_WANDERING_MERCHANT",
        ttl_seconds=1800,
        reason="VISIT_WANDERING_MERCHANT tap-zone map (no purchase, no refresh)")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    log_file = (outd / "run.log").open("w", encoding="utf-8")

    def say(line: str = "") -> None:
        print(line)
        log_file.write(str(line) + "\n")
        log_file.flush()

    try:
        ad = MaaExecutorAdapter(adb_path=cfg["device"]["adb_path"],
                                serial=cfg["device"]["serial"], production=True,
                                template_dir=ROOT / "dataset/candidate/templates",
                                log_dir=ROOT / "learning/maa_logs")
        ok, reason = ad.ensure_ready()
        if not ok:
            print(reason)
            return 3

        v = ShopVisitor(ad, outd, log=say)
        v.tag_prefix = "map_"
        v.enter()
        img, toks = v.select_tab("游荡商人")
        cards = read_cards(img, toks)
        say(f"roll: {len(cards)} cards")
        for c in cards:
            say(f"   [r{c.row}c{c.col}] 剩余={c.rest} price={c.price_text!r}"
                f"{'💎' if c.price_is_diamond else ' 资源'} disc={c.discount!r}"
                f" tap_xy={list(c.tap_xy)}")
        if not cards:
            say("!! no cards read; nothing to map")
            return 4

        # Default targets: one card priced in a resource and one priced in diamonds, because the
        # 03:22 pass opened the overlay on every diamond card and on no resource card.  Mapping
        # both shapes in the same roll is what separates a geometry answer from an anecdote.
        if want == ["auto"]:
            res = [c for c in cards if not c.price_is_diamond and c.price_text]
            dia = [c for c in cards if c.price_is_diamond and c.price_text]
            targets = ([res[0]] if res else []) + ([dia[0]] if dia else [])
            targets = targets or cards[:1]
            say(f"auto targets: {[f'r{c.row}c{c.col}' for c in targets]}")
        else:
            targets = [c for c in cards if f"r{c.row}c{c.col}" in want]
        if not targets:
            say(f"!! none of {want} are in this roll")
            return 4

        table: list[dict] = []
        for card in targets:
            tag = f"r{card.row}c{card.col}"
            say(f"\n=== {tag} anchor=({card.tap_xy[0]}, {card.tap_xy[1]}) "
                f"list-price={card.price_text!r} ===")
            before = np.asarray(ad.capture())
            for dy in ladder:
                # -- safety gate: never tap while an overlay is open ------------------
                here = np.asarray(ad.capture())
                if orange_price_button(here) is not None:
                    say("      !! an overlay was open -- dismissing before the next tap")
                    v._dismiss_dialog()
                    before = np.asarray(ad.capture())
                x, y = int(card.tap_xy[0]), int(card.tap_xy[1]) + dy
                v._tap_xy((x, y))
                after = np.asarray(ad.capture())
                btn = orange_price_button(after)
                px = _changed(before, after)
                if btn is not None:
                    kind, note = "OVERLAY", f"orange button at {btn['bbox']} ({btn['px']}px)"
                elif px > PANEL_MIN_PX:
                    kind, note = "PANEL", f"{px} px changed"
                else:
                    kind, note = "nothing", f"{px} px changed"
                row = {"card": tag, "dy": dy, "xy": [x, y], "kind": kind, "px": px,
                       "note": note}
                table.append(row)
                if kind != "nothing":
                    name = f"map_{tag}_dy{dy:+d}_{kind}.png"
                    Image.fromarray(after).save(outd / name)
                    row["frame"] = name
                    say(f"   dy={dy:+4d} ({x},{y})  {kind:8s} {note}  <- {name}")
                else:
                    say(f"   dy={dy:+4d} ({x},{y})  {kind:8s} {note}")
                if kind != "nothing":
                    # Name what opened, then close it so the next offset starts clean.
                    _, htoks = v.see(f"60_hit_{tag}_dy{dy:+d}")
                    texts = " ".join(t["text"] for t in htoks)
                    which = ("确定购买" if DIALOG_TITLE in texts else
                             "tooltip" if any(m in texts for m in TOOLTIP_MARKERS) else
                             "unrecognised")
                    row["opened"] = which
                    row["texts"] = [t["text"] for t in htoks][:18]
                    say(f"        opened={which}  texts={row['texts']}")
                    if which == "确定购买" or orange_price_button(np.asarray(ad.capture())):
                        v._dismiss_dialog()
                    elif which == "tooltip":
                        v._dismiss_tooltip()
                    else:
                        v._dismiss_dialog()
                before = np.asarray(ad.capture())
                time.sleep(0.25)

        say("\n--- zone map ---")
        for card in targets:
            tag = f"r{card.row}c{card.col}"
            rows = [r for r in table if r["card"] == tag]
            say(f"  {tag}: " + "  ".join(
                f"{r['dy']:+d}={r['kind']}" + (f"({r.get('opened')})" if r.get("opened") else "")
                for r in rows))
        hits = [r for r in table if r["kind"] != "nothing"]
        say(f"\n{len(hits)} hit(s) of {len(table)} taps")
        (outd / "zone_map.json").write_text(
            json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
        say(f"EVIDENCE: {outd}")
        if v._back_used:
            say(f"backs={v._back_used}")
        return 0
    finally:
        log_file.close()
        lease.release(result="DONE", reason="tap-zone map finished")


def _opt(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    raise SystemExit(main())
