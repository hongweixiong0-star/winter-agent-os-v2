"""Offline diagnosis of the two live defects, straight off the saved frames.

Defect 1 -- the anchor.  ``read_cards`` tapped ``(361, 897)`` for card r1c1 and nine taps in a row
opened nothing, while ``(140, 897)`` and ``(581, 897)`` -- same row, same y -- both opened the
purchase overlay.  So the anchor is not simply "the 剩余 label" for every card; this prints every
OCR token in that card's box so the real geometry is visible instead of guessed.

Defect 2 -- the price button.  ``inspect`` reported ``PRICE_BUTTON_AMBIGUOUS(2)`` on overlays that a
human can read at a glance (确定购买 / 铁矿 (安全) / 💎100).  This replays the exact filter and
prints which two tokens survived it, then shows where the orange button actually is.

usage: python tools/shop_overlay_diag.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr_full import read_all          # noqa: E402
from winter_agent_v2.shop_visit import prefer_whole, read_cards, merge_fragments  # noqa: E402

EVID = ROOT / "dataset/evidence/shop_visit_wandering_20261005T010327"


def load(name: str) -> np.ndarray:
    return np.array(Image.open(EVID / name).convert("RGB"))


def show(tag: str, toks: list[dict], ymin: int, ymax: int, xmin: int, xmax: int) -> None:
    print(f"\n=== {tag}: tokens inside x[{xmin},{xmax}] y[{ymin},{ymax}] ===")
    for t in sorted(toks, key=lambda t: (t["centre"][1], t["centre"][0])):
        cx, cy = int(t["centre"][0]), int(t["centre"][1])
        if xmin <= cx <= xmax and ymin <= cy <= ymax:
            print(f"   ({cx:4d},{cy:4d}) {t['box']!s:26s} {t['text']!r:34s} {t.get('source')}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    # ---------------------------------------------------------------- defect 1: the anchor
    list_img = load("03_tab_游荡商人.png")
    list_toks = read_all(Image.fromarray(list_img))
    cards = read_cards(list_img, list_toks)
    print("read_cards from 03_tab_游荡商人.png")
    for c in cards:
        print(f"   r{c.row}c{c.col} anchor={c.tap_xy} price={c.price_text}"
              f" price_xy={c.price_xy} diamond={c.price_is_diamond} disc={c.discount}")
    r1c1 = next((c for c in cards if (c.row, c.col) == (1, 1)), None)
    if r1c1:
        ax, ay = r1c1.tap_xy
        print(f"\n--- every token within 130 px of r1c1's anchor ({ax},{ay}) ---")
        for t in sorted(list_toks, key=lambda t: int(t["centre"][1])):
            cx, cy = int(t["centre"][0]), int(t["centre"][1])
            if abs(cx - ax) < 130 and abs(cy - ay) < 130:
                print(f"   ({cx:4d},{cy:4d}) {t['box']!s:26s} {t['text']!r:34s} {t.get('source')}")

    # ---------------------------------------------------------------- defect 2: the price
    for frame in ("40_card_r0c0_buy0_0.png", "40_card_r1c0_buy0_0.png"):
        img = load(frame)
        toks = read_all(Image.fromarray(img))
        h = img.shape[0]
        money_all = sorted((t for t in prefer_whole(toks)
                            if re.fullmatch(r"[\d,]{2,}", t["text"].strip())
                            and t["centre"][1] > 0.50 * h),
                           key=lambda t: -t["centre"][1])
        print(f"\n=== {frame}: {img.shape[1]}x{h}, money candidates (y > {int(0.5 * h)}) ===")
        for t in money_all:
            print(f"   ({int(t['centre'][0]):4d},{int(t['centre'][1]):4d}) {t['text']!r:12s}"
                  f" src={t.get('source')}")
        # every number below the mid-line, before the >=2-character filter, for comparison
        loose = [t for t in prefer_whole(toks)
                 if t["centre"][1] > 0.50 * h and re.fullmatch(r"[\d,]+", t["text"].strip())]
        print(f"   -- every number below the mid-line ({len(loose)}): "
              + ", ".join(f"{t['text']!r}@y{int(t['centre'][1])}" for t in
                          sorted(loose, key=lambda t: t["centre"][1])))
        oc = orange_button(img)
        if oc:
            print(f"   orange button bbox={oc['bbox']} centre={oc['centre']}"
                  f" px={oc['px']} -> "
                  + ", ".join(f"{t['text']!r}"
                              for t in money_all
                              if oc["bbox"][0] <= t["centre"][0] <= oc["bbox"][0] + oc["bbox"][2]
                              and oc["bbox"][1] <= t["centre"][1] <= oc["bbox"][1] + oc["bbox"][3]))
        else:
            print("   orange button: not found")

    # ---------------------------------------------------------------- the name reader
    tip = load("10_card_r1c1_tip65.png")
    tip_toks = read_all(Image.fromarray(tip))
    print("\n=== 10_card_r1c1_tip65.png: every token in the tooltip band (y 380..640) ===")
    for t in sorted(tip_toks, key=lambda t: (int(t["centre"][1]), int(t["centre"][0]))):
        cy = int(t["centre"][1])
        if 380 <= cy <= 660 and 100 <= int(t["centre"][0]) <= 620:
            print(f"   ({int(t['centre'][0]):4d},{cy:4d}) {t['text']!r:34s} src={t.get('source')}")
    return 0


def orange_button(img: np.ndarray) -> dict | None:
    """Largest orange blob in the lower half -- the 确定购买 price button."""
    import cv2
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = ((hh >= 8) & (hh <= 28) & (ss >= 120) & (vv >= 150)).astype(np.uint8)
    mask[: int(0.45 * h)] = 0
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if best is None or area > best["px"]:
            best = {"bbox": [int(x), int(y), int(bw), int(bh)], "px": int(area),
                    "centre": [int(cent[i][0]), int(cent[i][1])]}
    return best if best and best["px"] > 3000 else None


if __name__ == "__main__":
    raise SystemExit(main())
