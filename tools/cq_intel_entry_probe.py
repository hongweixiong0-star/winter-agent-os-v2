"""Measure BTN_OPEN_INTEL_WILD_HUD recognition across the R19 corpus.

READ EVIDENCE step for WB-R19-OPEN-INTEL-MAA-RECOVERY.

The work order says the six 2026-09-16 07:05-07:11 failures are MAP frames that
visibly show the telescope entry, and that the old single template plus a fixed
threshold no longer covers the current animated variants.  That is a hypothesis;
this script measures it instead of assuming it.

For every frame it reports, at the manifest ROI (and at a small local search
around it), the phash distance to every registered template of the semantic,
plus the frame's own page verdict.  Nothing is written; this is read-only
measurement.
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

# The six failures recorded 2026-09-15T23:05Z-23:11Z (= 2026-09-16 07:05-07:11 CST).
POSITIVES = [
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_002_before_20260915T230548379879.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230612978098.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230510_nav_00/intel_pins_20260915_230510_nav_00_step_001_before_20260915T230638196592.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_004_before_20260915T231036773155.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231108075082.png",
    "dataset/raw/control_panel/runtime_auto/intel_pins_20260915_230917_nav_01/intel_pins_20260915_230917_nav_01_step_001_before_20260915T231134984875.png",
]

# Frames that must NOT be matched: the same control is absent on these pages.
NEGATIVES = [
    "dataset/raw/control_panel/probe/live_page_20260915_151524.png",   # HOME city
    "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png",  # resource search panel
]

# The last known-good recognitions, for the same measurement.
CONTROLS_OK = [
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T133445437576.png",
    "dataset/raw/control_panel/runtime_auto/codex_0ba_0bb_live_20260915/codex_0ba_0bb_live_20260915_step_005_before_20260915T123128206616.png",
]


def templates() -> list[tuple[str, dict]]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        (row["template_id"], row)
        for row in payload.get("records", [])
        if row.get("semantic") == SEMANTIC
    ]


def distance_at(image: Image.Image, row: dict, width: int, height: int, dx: int = 0, dy: int = 0) -> int:
    roi = row["roi_norm"]
    bounds = (
        round(roi["x_norm"] * width) + dx,
        round(roi["y_norm"] * height) + dy,
        round((roi["x_norm"] + roi["w_norm"]) * width) + dx,
        round((roi["y_norm"] + roi["h_norm"]) * height) + dy,
    )
    with Image.open(Path(row["template_path"])) as template:
        return hamming(phash(image.crop(bounds)), phash(template))


def main() -> int:
    rows = templates()
    print("semantic:", SEMANTIC)
    print("registered templates: %d" % len(rows))
    for template_id, row in rows:
        print("   %-52s roi=%s" % (template_id, json.dumps(row["roi_norm"])))
    print()

    groups = (("POSITIVE (must match)", POSITIVES), ("NEGATIVE (must refuse)", NEGATIVES), ("LAST-KNOWN-GOOD", CONTROLS_OK))
    for title, paths in groups:
        print("=" * 78)
        print(title)
        for rel in paths:
            path = ROOT / rel
            if not path.exists():
                print("  MISSING %s" % rel)
                continue
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                width, height = image.size
                values = [distance_at(image, row, width, height) for _, row in rows]
                best = min(values) if values else 999
                text = ", ".join("%s=%d" % (tid.split("__")[-2][:10], v) for (tid, _), v in zip(rows, values))
                print("  %-58s %dx%d best=%3d  [%s]" % (path.name[:58], width, height, best, text))
                # Local search: does the control sit somewhere other than the ROI?
                for _, row in rows:
                    best_local = (999, 0, 0)
                    for dy in range(-40, 41, 8):
                        for dx in range(-60, 61, 8):
                            value = distance_at(image, row, width, height, dx, dy)
                            if value < best_local[0]:
                                best_local = (value, dx, dy)
                    print("        local search: best=%3d at (%+d,%+d)" % best_local)
                    break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
