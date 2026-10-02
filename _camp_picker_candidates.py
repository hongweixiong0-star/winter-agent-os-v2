"""What did `focused_camp_body_tap_norm` actually see on the frames it failed on?

Instrumented copy of the picker's own gates (same crop, same mask, same 3x3 close, same stats) so
the *decision* can be read instead of inferred.  Prints every surviving candidate, then says which
one won and whether the ambiguity gate fired.  Read-only.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.camp_ring import _hsv  # noqa: E402

RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"

#: From the module's own documentation: a real focus ring measures ~0.28 x 0.088 of the frame,
#: which at 720x1280 is ~202 x 113 px, and the reference ring measured 205 x 112.
DOC_RING_W = 0.28
DOC_RING_H = 0.088

CASES = [
    ("M KSMAN 02:18:52", "20261002_101801_000068",
     "20261002_101801_000068_step_003_before_20261002T021844184010.png"),
    ("SHIELD  04:01:14", "20261002_115855_658460",
     "20261002_115855_658460_step_017_before_20261002T040105384740.png"),
    ("LANCER  04:12:39", "20261002_121119_112086",
     "20261002_121119_112086_step_008_before_20261002T041230401116.png"),
    ("SHIELD  04:13:21", "20261002_121119_112086",
     "20261002_121119_112086_step_015_before_20261002T041313350048.png"),
]

for label, run, name in CASES:
    path = RUNS / run / name
    print("=" * 96)
    print(label, "|", name)
    if not path.exists():
        print("   missing")
        continue
    with Image.open(path) as source:
        rgb = np.asarray(source.convert("RGB"))
    height, width = rgb.shape[:2]
    hue, saturation, value = _hsv(rgb)
    x0, x1 = int(width * 0.35), int(width * 0.65)
    y0, y1 = int(height * 0.40), int(height * 0.72)
    mask = (
        (hue[y0:y1, x0:x1] >= 20) & (hue[y0:y1, x0:x1] <= 70)
        & (saturation[y0:y1, x0:x1] >= 30) & (value[y0:y1, x0:x1] >= 160)
    ).astype(np.uint8)
    raw_area = int(mask.sum())
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    print("   crop x[%d,%d) y[%d,%d) | warm pixels in crop: %d | components: %d" % (
        x0, x1, y0, y1, raw_area, count - 1))
    print("   doc ring geometry: %.0f x %.0f px" % (DOC_RING_W * width, DOC_RING_H * height))
    print("   %-8s %-6s %-6s %-7s %-7s %-7s %-7s  %s" % (
        "area", "box_w", "box_h", "cx", "cy", "aspect", "w/frame", "gate"))
    survivors = []
    for index in range(1, count):
        bx, by, box_w, box_h, area = (int(v) for v in stats[index])
        aspect = box_w / max(1, box_h)
        fail = []
        if area < 350:
            fail.append("area<350")
        if area > 1500:
            fail.append("area>1500")
        if box_w < width * 0.09:
            fail.append("w<0.09f")
        if box_h < height * 0.035:
            fail.append("h<0.035f")
        if not 0.75 <= aspect <= 2.4:
            fail.append("aspect")
        cx, cy = x0 + bx + box_w / 2.0, y0 + by + box_h / 2.0
        print("   %-8d %-6d %-6d %-7.1f %-7.1f %-7.2f %-7.3f  %s" % (
            area, box_w, box_h, cx, cy, aspect, box_w / width, ",".join(fail) or "PASS"))
        if not fail:
            survivors.append((area, cx, cy, box_w, box_h))
    if not survivors:
        print("   -> no candidate; the picker returns None (safe: wait, do not tap)")
        continue
    survivors.sort(reverse=True)
    ambiguous = len(survivors) > 1 and survivors[1][0] >= survivors[0][0] * 0.75
    print("   -> survivors: %d | ambiguity gate fires: %s" % (len(survivors), ambiguous))
    if not ambiguous:
        area, cx, cy, box_w, box_h = survivors[0]
        print("   -> chosen: area=%d centre=(%.1f, %.1f) bbox=%dx%d  => tap_norm (%.4f, %.4f)" % (
            area, cx, cy, box_w, box_h, round(cx / width, 4), round(cy / height, 4)))
        print("      bbox vs the documented ring size: %.2fx wide, %.2fx tall" % (
            box_w / (DOC_RING_W * width), box_h / (DOC_RING_H * height)))
