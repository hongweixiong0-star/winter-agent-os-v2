"""Locate the registered control in the right-hand HUD band (two-stage search).

Coarse sweep at step 16 over the band, then a refinement at step 2 inside a
+-24 px window around the coarse winner.  The previous version swept at step 2
across the whole band and recomputed the template hash per position, which cost
~300k hashes per run; this one costs ~1k per frame and is exact where it matters.

Why this exists: the fixed-ROI path scores 14 on the known-good frames and 38 on
the six failures, while two unrelated negatives score 30-32.  That is not a
"slightly worse recognition" signal, it is a "the control is not where the ROI
says" signal.  This sweep answers where it actually is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"

X0, Y0, X1, Y1 = 540, 380, 720, 1080

FRAMES = {
    "P1": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "P2": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230612978098.png",
    "P3": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230638196592.png",
    "P4": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_004_before_20260915T231036773155.png",
    "P5": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231108075082.png",
    "P6": "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231134984875.png",
    "GOOD1": "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T133445437576.png",
    "GOOD2": "dataset/raw/control_panel/runtime_auto/codex_0ba_0bb_live_20260915/codex_0ba_0bb_live_20260915_step_005_before_20260915T123128206616.png",
    "NEG_home": "dataset/raw/control_panel/probe/live_page_20260915_151524.png",
    "NEG_panel": "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png",
}


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    row = next(r for r in payload.get("records", []) if r.get("semantic") == SEMANTIC)
    with Image.open(Path(row["template_path"])) as template:
        template = template.convert("RGB")
    tw, th = template.size
    template_hash = phash(template)
    print("template: %s  %dx%d" % (Path(row["template_path"]).name, tw, th))
    print("band: x %d..%d  y %d..%d" % (X0, X1, Y0, Y1))
    print()
    print("%-9s %-22s %-8s %s" % ("frame", "best dist@(x,y)", "at-ROI", "<=10 hits (x,y)"))

    for tag, rel in FRAMES.items():
        path = ROOT / rel
        if not path.exists():
            print("%-9s MISSING" % tag)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size

        coarse: list[tuple[int, int, int]] = []
        for y in range(Y0, Y1 - th, 16):
            for x in range(X0, X1 - tw, 16):
                coarse.append((hamming(phash(image.crop((x, y, x + tw, y + th))), template_hash), x, y))
        coarse.sort()
        cx, cy = coarse[0][1], coarse[0][2]
        hits: list[tuple[int, int, int]] = []
        for y in range(max(Y0, cy - 24), min(Y1 - th, cy + 25), 2):
            for x in range(max(X0, cx - 24), min(X1 - tw, cx + 25), 2):
                value = hamming(phash(image.crop((x, y, x + tw, y + th))), template_hash)
                hits.append((value, x, y))
        hits.sort()

        roi = row["roi_norm"]
        rx, ry = round(roi["x_norm"] * width), round(roi["y_norm"] * height)
        at_roi = hamming(phash(image.crop((rx, ry, rx + tw, ry + th))), template_hash)
        near = [(v, x, y) for v, x, y in hits if v <= 10]
        shown = ", ".join("(%d,%d)" % (x, y) for _, x, y in near[:4]) or "-"
        print("%-9s %3d@(%4d,%4d)   %6d   %s" % (tag, hits[0][0], hits[0][1], hits[0][2], at_roi, shown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
