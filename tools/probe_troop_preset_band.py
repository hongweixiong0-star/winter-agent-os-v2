"""Read-only probe: locate the troop-preset row on the archived BEAR dispatch frames.

No device, no writes outside ``out_troop_preset_band/``.

What it answers (the questions the TROOP_PRESET design still has open):
  1. where the preset row is, in original 720x1280 pixels
  2. how many preset slots the client draws, and their pitch
  3. what "selected" looks like versus "not selected" (colour / border / fill)
  4. whether the row is the same widget on every archived frame of that page
"""

from __future__ import annotations

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_troop_preset_band")

# archived live frames of the 出征 (dispatch) page, 720x1280
FRAMES = [
    "dataset/raw/bear_live_20260909/bear_troop_setup.png",
    "dataset/raw/live_bear_troop_reduced.png",
    "dataset/raw/bear_live_20260909/bear_preset6.png",
    "dataset/raw/live_bear_preset6.png",
    "dataset/raw/bear_live_20260909/bear_trap_detail.png",
]

# the preset strip as read off the frames; deliberately generous vertically
BAND = (0, 78, 720, 180)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    report = []
    for rel in FRAMES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            report.append(f"{rel}: MISSING")
            continue
        im = Image.open(path).convert("RGB")
        w, h = im.size
        band = im.crop(BAND)
        zoom = band.resize((band.width * 2, band.height * 2), Image.LANCZOS)
        name = os.path.basename(rel).replace(".png", "")
        zoom.save(os.path.join(OUT, f"{name}_band2x.png"))

        # column profile: how blue is each column inside the band? preset chips
        # sit on the page background, so a chip shows up as a run of columns
        # whose mean colour differs from the page backdrop.
        px = band.load()
        cols = []
        for x in range(band.width):
            r = g = b = 0
            for y in range(band.height):
                pr, pg, pb = px[x, y]
                r += pr
                g += pg
                b += pb
            n = band.height
            cols.append((r // n, g // n, b // n))
        backdrop = cols[5]
        runs, start = [], None
        for x, c in enumerate(cols):
            far = sum(abs(c[i] - backdrop[i]) for i in range(3)) > 60
            if far and start is None:
                start = x
            elif not far and start is not None:
                if x - start >= 6:
                    runs.append((start + BAND[0], x + BAND[0]))
                start = None
        report.append(
            f"{rel}: size={w}x{h} band={BAND} backdrop={backdrop} "
            f"column_runs(n={len(runs)})={runs}"
        )
    report.append("")
    report.append(f"zoom tiles written to {OUT}")
    with open(os.path.join(ROOT, "out_troop_preset_band.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(report))
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
