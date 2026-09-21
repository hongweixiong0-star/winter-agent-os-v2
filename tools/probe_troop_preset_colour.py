"""Read-only probe: the troop-preset chip, measured as a recognition feature.

Follows tools/probe_troop_preset_measure.py. Two questions left:
  1. the gold ring -- its exact colour and where in the chip it can be sampled
  2. false positives -- does this feature appear on frames that are NOT the
     dispatch page?

Read-only: writes only into ``out_troop_preset_band/``.
"""

from __future__ import annotations

import collections
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_troop_preset_band")

# chip geometry measured in probe_troop_preset_measure.py
CHIP_CENTRES = [62, 139, 211, 283, 359, 434, 508, 576]
CHIP_HALF_W = 27
CHIP_TOP, CHIP_BOTTOM = 102, 158
SAVE_BUTTON = (621, 682)

SELECTED = ("dataset/raw/bear_live_20260909/bear_preset6.png", 5)  # 熊6
UNSELECTED = [
    ("dataset/raw/bear_live_20260909/bear_troop_setup.png", 5),
    ("dataset/raw/live_bear_troop_reduced.png", 5),
]

# frames that must NOT be read as "preset strip present"
NEGATIVES = [
    "dataset/raw/live_bear_preset6.png",          # map / march frame
    "dataset/raw/bear_live_20260909/bear_trap_detail.png",
    "dataset/raw/current.png",
]


def ring_and_fill(im: Image.Image, centre: int):
    """Return the chip's outer-ring dominant colour and its inner fill."""
    px = im.load()
    ring = collections.Counter()
    for x in range(centre - CHIP_HALF_W, centre + CHIP_HALF_W + 1):
        for y in (CHIP_TOP, CHIP_TOP + 1, CHIP_BOTTOM, CHIP_BOTTOM - 1):
            ring[px[x, y]] += 1
    for y in range(CHIP_TOP, CHIP_BOTTOM + 1):
        for x in (centre - CHIP_HALF_W, centre - CHIP_HALF_W + 1,
                  centre + CHIP_HALF_W, centre + CHIP_HALF_W - 1):
            ring[px[x, y]] += 1
    fill = collections.Counter()
    for x in range(centre - 18, centre + 19):
        for y in (146, 150, 154):
            fill[px[x, y]] += 1
    return ring.most_common(3), fill.most_common(3)


def strip_signature(im: Image.Image):
    """A cheap, page-independent test: is this the light-blue preset bar?

    The bar is a horizontal band of near-uniform colour between the title and
    the hero cards. We test the row band y=90..100, which is above every chip
    and therefore only sees the bar itself.
    """
    px = im.load()
    if im.width != 720 or im.height != 1280:
        return None
    samples = [px[x, y] for y in (90, 94, 98) for x in range(30, 700, 10)]
    mean = tuple(sum(c[i] for c in samples) // len(samples) for i in range(3))
    spread = max(
        max(c[i] for c in samples) - min(c[i] for c in samples) for i in range(3)
    )
    return mean, spread


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    rep = []

    rel, idx = SELECTED
    im = Image.open(os.path.join(ROOT, rel)).convert("RGB")
    c = CHIP_CENTRES[idx]
    ring, fill = ring_and_fill(im, c)
    rep.append(f"SELECTED   {rel} chip{idx} centre={c}")
    rep.append(f"  ring(top3) = {ring}")
    rep.append(f"  fill(top3) = {fill}")
    crop = im.crop((c - CHIP_HALF_W - 6, CHIP_TOP - 6, c + CHIP_HALF_W + 6, CHIP_BOTTOM + 6))
    crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS).save(
        os.path.join(OUT, "chip_selected_4x.png")
    )

    for rel, idx in UNSELECTED:
        im = Image.open(os.path.join(ROOT, rel)).convert("RGB")
        c = CHIP_CENTRES[idx]
        ring, fill = ring_and_fill(im, c)
        rep.append(f"UNSELECTED {rel} chip{idx} centre={c}")
        rep.append(f"  ring(top3) = {ring}")
        rep.append(f"  fill(top3) = {fill}")
        crop = im.crop((c - CHIP_HALF_W - 6, CHIP_TOP - 6, c + CHIP_HALF_W + 6, CHIP_BOTTOM + 6))
        crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS).save(
            os.path.join(OUT, f"chip_unselected_{os.path.basename(rel).replace('.png','')}_4x.png")
        )

    rep.append("")
    rep.append("== strip signature (row band y=90..98, the bar above the chips) ==")
    for rel in [SELECTED[0]] + [r for r, _ in UNSELECTED] + NEGATIVES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            rep.append(f"  {rel}: MISSING")
            continue
        im = Image.open(p).convert("RGB")
        sig = strip_signature(im)
        rep.append(f"  {rel}: {sig}")

    rep.append("")
    rep.append("== the same test on every archived 720x1280 frame we can cheaply reach ==")
    seen = 0
    for base in ("dataset/raw", "dataset/raw/bear_live_20260909"):
        d = os.path.join(ROOT, base)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d))[:400]:
            if not name.lower().endswith(".png"):
                continue
            p = os.path.join(d, name)
            try:
                im = Image.open(p).convert("RGB")
            except Exception:
                continue
            if im.size != (720, 1280):
                continue
            sig = strip_signature(im)
            if sig is None:
                continue
            mean, spread = sig
            hit = mean[2] > 150 and mean[1] > 100 and spread < 40
            if hit:
                seen += 1
                rep.append(f"  HIT {base}/{name} mean={mean} spread={spread}")
    rep.append(f"  total hits: {seen}")

    with open(os.path.join(ROOT, "out_troop_preset_band.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
