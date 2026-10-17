# -*- coding: utf-8 -*-
"""Where in a shop card does a tap open the purchase overlay -- and what closes a tooltip?

Two things are still assumptions and both are load-bearing, so both get measured here.

(1) **The tap that opens the overlay.**  ``read_cards`` puts the anchor on the ``剩余：1`` label
    and the 2026-10-05 pass opened the overlay from there on five of six cards -- but on card r1c1
    **nine taps in a row opened nothing**, while r1c0 and r1c2, at the *same* y, opened normally.
    The anchor is provably inside the ``剩余：1`` box, so geometry alone does not explain it.  The
    remaining candidate is that the tap never reached the game: it followed a ``press_back()``
    that closed a tooltip.  Phase B reproduces that exact sequence.

(2) **What closes the tooltip.**  ``_dismiss_tooltip`` uses the system back key, and that is the
    one call in the whole pass that is known to have swallowed the next card's taps.  If a plain
    tap outside the tooltip closes it, the back key leaves the card loop entirely.  Phase C tries
    candidates in order and reports the first that works.

Phase A then maps the whole card once, so the ladder is chosen from pixels rather than from the
two probes that disagreed with each other.

Nothing here taps the orange confirm button, and every overlay is closed with its own ✕.

usage: python tools/shop_tap_map.py
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

BODY_DY = (0, 20, 40, 60, 80)
ICON_DY = (-45, -65, -85)
# Candidates for "tap somewhere harmless" that should close a non-modal tooltip.
WIDE_TAPS = ((360, 250), (360, 1150), (195, 1015))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    from winter_agent_v2.device_lease import OWNER_DEVELOPMENT_VALIDATION, DeviceLease
    from winter_agent_v2.maa_executor import MaaExecutorAdapter
    from winter_agent_v2.ocr_full import read_all
    from winter_agent_v2.shop_visit import (DIALOG_TITLE, TOOLTIP_MARKERS, ShopVisitor,
                                           read_cards)

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    outd = ROOT / "dataset" / "evidence" / f"shop_tap_map_{stamp}"
    outd.mkdir(parents=True, exist_ok=True)

    lease = DeviceLease(ROOT)
    rec, why = lease.acquire(owner=OWNER_DEVELOPMENT_VALIDATION, capability_id="SHOP_TAP_MAP",
                             ttl_seconds=1800, reason="map the card tap zones and the tooltip exit")
    if rec is None:
        print(json.dumps({"refused": why}, ensure_ascii=False))
        return 2

    result: dict[str, object] = {"stamp": stamp}
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
        v.enter()
        v.select_tab("游荡商人")

        def look(tag: str, save: bool = False) -> tuple[str, list[dict]]:
            img, toks = v.see(tag, save=save)
            texts = " ".join(t["text"] for t in toks)
            if DIALOG_TITLE in texts:
                return "PURCHASE", toks
            if any(m in texts for m in TOOLTIP_MARKERS):
                return "tooltip", toks
            return "-", toks

        def close(kind: str, tag: str) -> None:
            if kind == "PURCHASE":
                _, toks = v.see(f"{tag}_close_probe", save=False)
                x = next((t for t in toks if t["text"].strip() in ("X", "x", "✕", "×", "╳")), None)
                if x is not None:
                    ad.click(int(x["centre"][0]), int(x["centre"][1]))
                    time.sleep(1.2)
            elif kind == "tooltip":
                ad.press_back()
                time.sleep(1.2)

        def any_card() -> tuple[int, int] | None:
            img, toks = v.see("00_locate", save=True)
            cards = read_cards(img, toks)
            print(f"   locate: {len(cards)} card(s) {sorted((c.row, c.col) for c in cards)}")
            if not cards:
                return None
            c = max(cards, key=lambda c: (c.row, c.col))
            return c.tap_xy

        # ---------------------------------------------------------------- Phase C
        print("\n=== Phase C: what closes the read-only tooltip ===")
        phase_c: list[dict] = []
        a = any_card()
        if a:
            ad.click(a[0], a[1] - 65)                  # icon zone -> the read-only tooltip
            time.sleep(1.5)
            kind, _ = look("C0_tooltip_open", save=True)
            print(f"   icon tap at ({a[0]},{a[1] - 65}) -> {kind}")
            if kind == "tooltip":
                for x, y in WIDE_TAPS:
                    ad.click(x, y)
                    time.sleep(1.5)
                    after, _ = look(f"C1_wide_{x}_{y}")
                    print(f"   tap ({x},{y}) -> {after}")
                    phase_c.append({"tap": [x, y], "after": after})
                    if after == "-":
                        break
                if not phase_c or phase_c[-1]["after"] != "-":
                    ad.press_back()
                    time.sleep(1.4)
                    print("   none of the wide taps closed it; the back key did")
            result["phase_c"] = phase_c

        # ---------------------------------------------------------------- Phase B
        print("\n=== Phase B: reproduce r1c1 -- tooltip, back, then the body ladder ===")
        phase_b: list[dict] = []
        a = any_card()
        if a:
            ad.click(a[0], a[1] - 65)
            time.sleep(1.5)
            kind, _ = look("B0_tooltip_open", save=True)
            print(f"   tooltip opened: {kind}")
            if kind == "tooltip":
                ad.press_back()
                time.sleep(1.4)
            for dy in BODY_DY:
                ad.click(a[0], a[1] + dy)
                time.sleep(1.5)
                kind, _ = look(f"B1_after_back_dy{dy}", save=True)
                print(f"   tap ({a[0]},{a[1] + dy}) after a back -> {kind}")
                phase_b.append({"dy": dy, "after": kind})
                close(kind, f"B1_dy{dy}")
            result["phase_b"] = phase_b

        # ---------------------------------------------------------------- Phase A
        print("\n=== Phase A: the card's tap map, no back press anywhere ===")
        phase_a: list[dict] = []
        a = any_card()
        if a:
            for dy in (*ICON_DY, *BODY_DY):
                ad.click(a[0], a[1] + dy)
                time.sleep(1.5)
                kind, _ = look(f"A_dy{dy}", save=True)
                print(f"   tap ({a[0]},{a[1] + dy:>4}) dy={dy:>+4} -> {kind}")
                phase_a.append({"dy": dy, "after": kind})
                close(kind, f"A_dy{dy}")
            result["phase_a"] = phase_a

        (outd / "tap_map.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
        print("\nEVIDENCE:", outd)
        return 0
    finally:
        lease.release(result="DONE", reason="tap map finished")


if __name__ == "__main__":
    raise SystemExit(main())
