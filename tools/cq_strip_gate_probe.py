"""Why does the reviewed-template gate reject a correct prediction?

The pitch measurement cleared the geometry (157/158 px measured against a
configured 157), and the live failure's bracket sits on tab index 1 at left=172,
which predicts MEAT at 486 -- and the frame really does show 生肉 starting at
about 486.  So the model is right and the gate is what refuses.

The gate compares the predicted cell against the four reviewed
``RESOURCE_TAB_*_SELECTED`` templates.  Print the actual distances, for the live
frame and for a calibration frame, so the reason is a number rather than a guess.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.vision import (  # noqa: E402
    SemanticWorldVision,
    _cell_signature,
    _cell_template_signature,
    _signature_distance,
)

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

CASES = [
    ("cal_MEAT (selected, offset 0)",
     "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png", 0.0),
    ("cal_IRON (selected, offset 0)",
     "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png", 0.0),
    ("live_fail (bracket on index 1, offset +399)",
     "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png", 399.0),
]


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    print("=== reviewed RESOURCE_TAB_*_SELECTED templates ===")
    for row in payload.get("records", []):
        semantic_name = str(row.get("semantic", ""))
        if semantic_name.startswith("RESOURCE_TAB_") and semantic_name.endswith("_SELECTED"):
            path = Path(row["template_path"])
            with Image.open(path) as template:
                size = template.size
            print("  %-34s %s  parent=%s"
                  % (semantic_name, size, Path(row.get("parent_screenshot", "")).name[:46]))
    print("  templates per resource: %s"
          % {k: len(v) for k, v in semantic.resource_tab_cell_templates.items()})
    print()

    width_norm = semantic.resource_tab_cell
    for title, rel, offset in CASES:
        path = ROOT / rel
        if not path.exists():
            print("MISSING", rel)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        y0, y1 = semantic._tab_band_rows(height)
        cell_px = round(width_norm * width)
        print("=" * 78)
        print(title)
        print("  frame %dx%d  band rows %d..%d  cell width %d px" % (width, height, y0, y1, cell_px))
        for name in semantic.resource_tab_order:
            nominal = (semantic.resource_tab_first_left
                       + semantic.resource_tab_order.index(name) * semantic.resource_tab_pitch) * width
            x0 = round(nominal + offset)
            if x0 < 0 or x0 + cell_px > width:
                print("  %-12s predicted left=%6d  OFF-SCREEN or clipped" % (name, x0))
                continue
            probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
            own_paths = semantic.resource_tab_cell_templates.get(name, [])
            if not own_paths:
                print("  %-12s predicted left=%6d  (no template: not a gatherable tab)" % (name, x0))
                continue
            own = min(_signature_distance(probe, _cell_template_signature(Path(p))) for p in own_paths)
            others = []
            for other, paths in semantic.resource_tab_cell_templates.items():
                if other == name:
                    continue
                others += [_signature_distance(probe, _cell_template_signature(Path(p))) for p in paths]
            runner = min(others) if others else own + 999
            verdict = "PASS" if own <= semantic.resource_tab_max_distance and runner - own >= semantic.resource_tab_min_margin else "reject"
            print("  %-12s predicted left=%6d  own=%6.2f  runner=%6.2f  margin=%6.2f  -> %s"
                  % (name, x0, own, runner, runner - own, verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
