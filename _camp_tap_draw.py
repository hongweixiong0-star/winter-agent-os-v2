"""Draw the production resolver's own tap point on the frames it failed on.

Rule this follows (recorded in this project after a previous incident): a click coordinate is not
verified by a template matching it -- the self-match is circular.  It is verified by drawing the
point on the frame and looking at it.

Read-only: writes annotated crops under out/, touches no device and no runtime state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from winter_agent_v2.camp_ring import focused_camp_body_tap_norm, ring_centre_norm  # noqa: E402

RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"
OUT = ROOT / "out/beast_none" if False else ROOT / "out/camp_tap_check"
OUT.mkdir(parents=True, exist_ok=True)

CASES = [
    ("M KSMAN 02:18:52", "20261002_101801_000068",
     "20261002_101801_000068_step_003_before_20261002T021844184010.png"),
    ("SHIELD 04:01:14", "20261002_115855_658460",
     "20261002_115855_658460_step_017_before_20261002T040105384740.png"),
    ("LANCER 04:12:39", "20261002_121119_112086",
     "20261002_121119_112086_step_008_before_20261002T041230401116.png"),
    ("SHIELD 04:13:21", "20261002_121119_112086",
     "20261002_121119_112086_step_015_before_20261002T041313350048.png"),
]

for label, run, name in CASES:
    path = RUNS / run / name
    print("=" * 90)
    print(label, "|", name)
    if not path.exists():
        print("   missing")
        continue
    point = focused_camp_body_tap_norm(path)
    print("   focused_camp_body_tap_norm ->", point)
    try:
        ring = ring_centre_norm(path)
        print("   ring_centre_norm           ->", ring)
    except Exception as exc:  # noqa: BLE001
        print("   ring_centre_norm raised:", type(exc).__name__, exc)

    image = Image.open(path).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)
    if point:
        x, y = round(point[0] * width), round(point[1] * height)
        draw.line((x - 26, y, x + 26, y), fill=(255, 0, 0), width=3)
        draw.line((x, y - 26, x, y + 26), fill=(255, 0, 0), width=3)
        draw.ellipse((x - 14, y - 14, x + 14, y + 14), outline=(255, 0, 0), width=3)
        print("   tap pixel -> (%d, %d) of %dx%d" % (x, y, width, height))
    crop = image.crop((int(0.20 * width), int(0.25 * height), int(0.85 * width), int(0.78 * height)))
    dest = OUT / f"{label.split()[0]}_{label.split()[1].replace(':','')}_tap.png"
    crop.save(dest)
    print("   wrote", dest.relative_to(ROOT))
