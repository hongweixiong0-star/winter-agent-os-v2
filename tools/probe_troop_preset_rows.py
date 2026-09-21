"""Read-only probe: the exact vertical extent of a preset chip, row by row.

The previous probe sampled y=142..156 as the "name band" and got a muddle,
because the strip bar resumes below the chip. This prints the actual per-row
colour at a chip centre and at the chip's left edge, so the chip's true top,
bottom and border rows can be read off instead of guessed.

Read-only: writes only into ``out_troop_preset_band/``.
"""

from __future__ import annotations

import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out_troop_preset_band")

CHIP_CENTRES = (62, 139, 211, 283, 359, 434, 508, 576)


def scan(rel: str, centre: int, label: str, rep: list[str]) -> None:
    im = Image.open(os.path.join(ROOT, rel)).convert("RGB")
    px = im.load()
    rep.append(f"-- {label}: {rel} chip centre x={centre} --")
    for y in range(84, 176):
        row = [px[x, y] for x in (centre - 24, centre - 14, centre, centre + 14, centre + 24)]
        rep.append(
            f"  y={y:4d}  L24={row[0]} L14={row[1]} C={row[2]} R14={row[3]} R24={row[4]}"
        )
    crop = im.crop((centre - 36, 84, centre + 36, 176))
    crop.resize((crop.width * 5, crop.height * 5), Image.LANCZOS).save(
        os.path.join(OUT, f"col_{label}.png")
    )


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    rep: list[str] = []
    scan("dataset/raw/bear_live_20260909/bear_preset6.png", 434, "selected_bear6", rep)
    rep.append("")
    scan("dataset/raw/bear_live_20260909/bear_troop_setup.png", 434, "unselected", rep)
    with open(os.path.join(ROOT, "out_troop_preset_band.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep))
    print("\n".join(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
