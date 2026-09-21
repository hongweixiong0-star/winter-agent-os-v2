"""Read-only probe: measure the troop-preset chips (geometry + selected colour).

Follows tools/probe_troop_preset_band.py. Answers, in pixels:
  * chip centres and pitch along the strip
  * strip vertical extent
  * what "selected" is, as a colour, measured on a frame where it is known
    (bear_preset6.png shows 熊6 selected) versus one where it is not

No device, no writes outside ``out_troop_preset_band/``.
"""

from __future__ import annotations

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_troop_preset_band")

SELECTED_FRAME = "dataset/raw/bear_live_20260909/bear_preset6.png"   # 熊6 selected (gold)
OTHER_FRAMES = [
    "dataset/raw/bear_live_20260909/bear_troop_setup.png",
    "dataset/raw/live_bear_troop_reduced.png",
    "dataset/raw/live_bear_preset6.png",
]

STRIP_TOP, STRIP_BOTTOM = 78, 180


def col_profile(im: Image.Image, y0: int, y1: int):
    px = im.load()
    out = []
    for x in range(im.width):
        r = g = b = 0
        for y in range(y0, y1):
            pr, pg, pb = px[x, y]
            r += pr
            g += pg
            b += pb
        n = y1 - y0
        out.append((r // n, g // n, b // n))
    return out


def find_strip(im: Image.Image):
    """Vertical extent of the preset strip: the light-blue bar under the title."""
    px = im.load()
    rows = []
    for y in range(60, 220):
        r = g = b = 0
        for x in range(20, 700, 4):
            pr, pg, pb = px[x, y]
            r += pr
            g += pg
            b += pb
        n = len(range(20, 700, 4))
        rows.append((y, r // n, g // n, b // n))
    # the strip is the longest run of rows brighter than the page backdrop
    return rows


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    rep = []

    sel = Image.open(os.path.join(ROOT, SELECTED_FRAME)).convert("RGB")
    rep.append("== vertical profile of the strip (row -> mean colour, x 20..700) ==")
    for y, r, g, b in find_strip(sel):
        if y % 4 == 0:
            rep.append(f"  y={y:4d}  ({r:3d},{g:3d},{b:3d})")

    rep.append("")
    rep.append("== chip column profile, row band y=110..145 ==")
    for rel in [SELECTED_FRAME] + OTHER_FRAMES:
        im = Image.open(os.path.join(ROOT, rel)).convert("RGB")
        cols = col_profile(im, 110, 145)
        # a chip is brighter/more saturated than the strip backdrop behind it;
        # sample the backdrop at the far left of the strip
        back = cols[16]
        runs, start = [], None
        for x in range(18, 715):
            c = cols[x]
            far = sum(abs(c[i] - back[i]) for i in range(3)) > 45
            if far and start is None:
                start = x
            elif not far and start is not None:
                if x - start >= 12:
                    runs.append((start, x - 1, x - start))
                start = None
        if start is not None and 715 - start >= 12:
            runs.append((start, 714, 715 - start))
        centres = [ (a + b) // 2 for a, b, _ in runs ]
        pitches = [ centres[i + 1] - centres[i] for i in range(len(centres) - 1) ]
        rep.append(f"  {rel}")
        rep.append(f"    backdrop@x16={back}  runs={runs}")
        rep.append(f"    centres={centres}")
        rep.append(f"    pitch={pitches}")

    rep.append("")
    rep.append("== selected vs unselected, as colour (sampled at each chip centre) ==")
    for rel in [SELECTED_FRAME] + OTHER_FRAMES:
        im = Image.open(os.path.join(ROOT, rel)).convert("RGB")
        px = im.load()
        cols = col_profile(im, 110, 145)
        back = cols[16]
        runs, start = [], None
        for x in range(18, 715):
            c = cols[x]
            far = sum(abs(c[i] - back[i]) for i in range(3)) > 45
            if far and start is None:
                start = x
            elif not far and start is not None:
                if x - start >= 12:
                    runs.append((start, x - 1))
                start = None
        rep.append(f"  {rel}")
        for i, (a, b) in enumerate(runs):
            cx = (a + b) // 2
            # the chip's top edge carries the border colour; sample just inside
            top_edge = [px[cx, y] for y in range(96, 112)]
            inner = px[cx, 150]
            rep.append(
                f"    chip{i} x{a}-{b} centre={cx} top_edge={top_edge[0]}..{top_edge[-1]}"
                f"  inner@y150={inner}"
            )

    with open(os.path.join(ROOT, "out_troop_preset_band.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
