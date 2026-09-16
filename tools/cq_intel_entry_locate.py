"""Locate the BTN_OPEN_INTEL_WILD_HUD template anywhere in each frame.

The ROI measurement showed the registered ROI holds the control on the good
frames (distance 14) but only empty sky on the six failures (38), with the
negatives sitting in between at 30-32 -- i.e. the fixed-ROI phash path is really
a "is the control still at the old place" test, not an "is the control visible"
test.

If the control is present but has moved, a whole-frame search will find it and
the fix is a search region rather than a new template.  If it is absent, no
template work can help and the answer is a page/context signal.  So measure
where it actually is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, dhash, phash  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"

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


def rows_for(semantic: str) -> list[dict]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [row for row in payload.get("records", []) if row.get("semantic") == semantic]


def main() -> int:
    rows = rows_for(SEMANTIC)
    row = rows[0]
    with Image.open(Path(row["template_path"])) as template:
        template = template.convert("RGB")
    tw, th = template.size
    print("template: %s  size=%dx%d" % (Path(row["template_path"]).name, tw, th))
    print("registered roi_norm: %s" % json.dumps(row["roi_norm"]))
    print()

    for tag, rel in FRAMES.items():
        path = ROOT / rel
        if not path.exists():
            print("  %-10s MISSING" % tag)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        best = (999, 0, 0)
        step = 4
        for y in range(0, max(1, height - th), step):
            for x in range(0, max(1, width - tw), step):
                value = hamming(phash(image.crop((x, y, x + tw, y + th))), phash(template))
                if value < best[0]:
                    best = (value, x, y)
        roi = row["roi_norm"]
        rx, ry = round(roi["x_norm"] * width), round(roi["y_norm"] * height)
        at_roi = hamming(phash(image.crop((rx, ry, rx + tw, ry + th))), phash(template))
        print("  %-10s best=%3d at (%4d,%4d)   at-ROI=%3d" % (tag, best[0], best[1], best[2], at_roi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
