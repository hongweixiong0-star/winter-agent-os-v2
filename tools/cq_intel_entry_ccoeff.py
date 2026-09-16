"""Measure match_ccoeff over the whole right HUD band for the intel entry.

Two independent signals are collected for every frame, because the work order
forbids fixing this by lowering a threshold:

1. ccoeff score at the registered ROI + 40 px (what the matcher does today);
2. ccoeff score over the full right HUD band (what a search-based route would do).

Then the question becomes measurable: is there a score threshold, or a
score-plus-page-context rule, that accepts every positive frame and refuses every
negative one, without a marginal threshold sitting one pixel away from a negative.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.matchers import match_ccoeff  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"
TEMPLATE = ROOT / "dataset/candidate/intel_wild_entry_v2/btn_open_intel_wild_hud__wild_fresh_before__0.png"

# A generous band: everything on the right that is not the top status bar.
BAND = {"x_norm": 0.70, "y_norm": 0.28, "w_norm": 0.30, "h_norm": 0.62}

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
    roi = row["roi_norm"]
    print("template: %s" % TEMPLATE.name)
    print("registered roi_norm: %s" % json.dumps(roi))
    print("band: %s" % json.dumps(BAND))
    print()
    print("%-9s %-24s %-34s" % ("frame", "ccoeff at ROI+40", "ccoeff over band"))

    for tag, rel in FRAMES.items():
        path = ROOT / rel
        if not path.exists():
            print("%-9s MISSING" % tag)
            continue
        narrow = match_ccoeff(path, TEMPLATE, roi)
        wide = match_ccoeff(path, TEMPLATE, BAND)
        n_text = "%5.3f @ %s" % (narrow.score, narrow.center_norm) if narrow else "  n/a"
        w_text = (
            "%5.3f @ %s scale=%.2f" % (wide.score, wide.center_norm, wide.scale) if wide else "  n/a"
        )
        print("%-9s %-24s %s" % (tag, n_text, w_text))
    print()
    print("interpretation: a usable rule needs every P/GOOD above every NEG with a margin,")
    print("and the band centre should land on the same control the frame visibly shows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
