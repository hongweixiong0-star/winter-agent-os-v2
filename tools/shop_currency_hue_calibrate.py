# -*- coding: utf-8 -*-
"""Decide, by measurement, how to tell a diamond price from a resource price.

Two earlier attempts are worth recording because both *looked* right and were not:

  1. a hue rule written with OpenCV's 0-179 hue scale applied to PIL's 0-255 -- wrong scale;
  2. a template match that scored 1.00 -- but the "medal" and "coin" templates had been
     cropped over the *digits* of the price, not over the icons
     (dataset/evidence/shop_currency_templates_8x.png shows it plainly).  A template that
     matches itself perfectly is no evidence that it is the icon.

The lesson is that the crop has to be looked at, not just scored.  So this run reports the
colour of the price-row ink, which needs no crop guessing: the diamond is the only saturated
blue thing the shops ever print as a price, and wood/coal/meat/medal/coin are all orange,
brown, grey or gold.  Separation is printed as a histogram of hue, not asserted.

usage: python tools/shop_currency_hue_calibrate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (glob, ground truth read off the frames by eye)
ROWS = [
    ("shop_explore2_*/05_after_refresh.png", [
        (162, 659, "diamond 50"), (384, 659, "diamond 600"), (604, 660, "diamond 27"),
        (162, 949, "diamond 19"), (383, 949, "wood 10万"), (604, 949, "coal 80,000")]),
    ("shop_explore2_*/04_before_refresh.png", [
        (163, 659, "diamond 140"), (384, 659, "diamond 600"), (604, 660, "coal 1,600"),
        (382, 949, "coal 33,000"), (603, 949, "coal 10万")]),
    ("shop_explore1_*/02_shop.png", [
        (164, 659, "diamond 63"), (384, 660, "diamond 400"),
        (605, 660, "meat 15,000"), (164, 948, "diamond 63"), (604, 948, "diamond 100")]),
    ("shop_explore2_*/03_tab_3_统帅市.png", [
        (160, 422, "diamond 2"), (381, 422, "diamond 2"), (603, 422, "diamond 10"),
        (605, 705, "diamond 75"), (383, 989, "diamond 250")]),
    ("shop_explore2_*/03_tab_1_神秘商店.png", [
        (163, 659, "medal 2,500"), (383, 659, "medal 2,500"), (605, 949, "medal 1,000")]),
    ("shop_explore2_*/03_tab_2_竞技商店.png", [
        (162, 422, "coin 2,375"), (383, 422, "coin 12,000"), (162, 989, "coin 10,000")]),
]


def load(path: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def ink_stats(img: np.ndarray, x: int, y: int) -> dict:
    """Colour of the saturated ink in the price pill, left of and around the number."""
    hay = img[max(0, y - 18):y + 18, max(0, x - 95):x + 40]
    hsv = cv2.cvtColor(hay, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # Bright, saturated pixels only: exactly the currency icon's paint.
    sel = (s >= 120) & (v >= 130)
    n = int(sel.sum())
    if n < 12:
        return {"n": n, "hue": None, "blue_frac": 0.0}
    hue = h[sel]
    # OpenCV H is 0-179 with red at 0; a diamond sits around 95-115, everything else < 40.
    blue = ((hue >= 85) & (hue <= 125)).sum()
    return {"n": n, "hue": int(np.median(hue)), "blue_frac": round(float(blue) / n, 3),
            "hue_p10": int(np.percentile(hue, 10)), "hue_p90": int(np.percentile(hue, 90))}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for pattern, items in ROWS:
        matches = sorted((ROOT / "dataset" / "evidence").glob(pattern))
        if not matches:
            print("MISSING", pattern)
            continue
        img = load(matches[-1])
        print(f"\n=== {matches[-1].name} ===")
        for x, y, want in items:
            st = ink_stats(img, x, y)
            is_diamond = want.startswith("diamond")
            pred = st["blue_frac"] >= 0.5
            flag = "ok " if pred == is_diamond else "BAD"
            rows.append({"want": want, "is_diamond": is_diamond, "pred": pred, **st})
            print(f"  [{flag}] {want:>16} @({x},{y})  n={st['n']:>5} blue={st['blue_frac']:.3f} "
                  f"hue={st.get('hue')} p10={st.get('hue_p10')} p90={st.get('hue_p90')}")

    d = [r["blue_frac"] for r in rows if r["is_diamond"]]
    r_ = [r["blue_frac"] for r in rows if not r["is_diamond"]]
    print(f"\ndiamond rows: n={len(d)} min={min(d):.3f} max={max(d):.3f}")
    print(f"other   rows: n={len(r_)} min={min(r_):.3f} max={max(r_):.3f}")
    gap = min(d) - max(r_)
    print(f"separation gap = {gap:+.3f}  ->  "
          f"{'CLEAN, threshold ' + format((min(d) + max(r_)) / 2, '.3f') if gap > 0.15 else 'NOT clean'}")
    out = ROOT / "dataset" / "evidence" / "shop_currency_hue.json"
    out.write_text(json.dumps({"rows": rows, "gap": gap,
                               "threshold": round((min(d) + max(r_)) / 2, 3) if gap > 0 else None},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
