"""Replay the corrected strip gate through the production path.

For every frame: the page verdict (does the panel register at all), the selected
resource as production reads it, and the tap target the executor would receive for
each gatherable resource.  The point of the replay is that the six live failures
that motivated this must now resolve to the tab the frame visibly shows, while the
calibration frames must keep resolving to their known selection and the
panel-absent frames must keep refusing.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

LIVE_FAILURES = [
    ("23:37 step_003", "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png", "GIANT_BEAST"),
    ("23:37 step_001", "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T233739598714.png", "GIANT_BEAST"),
    ("16:06 step_003", "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png", "SAWMILL"),
]

KNOWN = [
    ("cells select_MEAT", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png", "MEAT"),
    ("cells select_WOOD", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png", "WOOD"),
    ("cells select_COAL", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png", "COAL"),
    ("cells select_IRON", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png", "IRON"),
    ("avail select_MEAT", "dataset/truth_audit/resource_availability_20260914_124753/20260914_124753_select_MEAT.png", "MEAT"),
    ("avail select_WOOD", "dataset/truth_audit/resource_availability_20260914_124753/20260914_124753_select_WOOD.png", "WOOD"),
]

NEGATIVES = [
    ("HOME", "dataset/raw/control_panel/probe/live_page_20260915_151524.png"),
    ("MAP no panel", "dataset/raw/control_panel/probe/live_page_20260915_133152.png"),
    ("resource tab anchor negative", "dataset/truth_audit/resource_tab_anchor_20260916/negative_map__live_page_20260915_133152.png"),
    ("resource tab anchor home", "dataset/truth_audit/resource_tab_anchor_20260916/negative_home__live_page_20260915_151524.png"),
]


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic

    print("=== live failures: must now resolve ===")
    for tag, rel, expected_anchor in LIVE_FAILURES:
        path = ROOT / rel
        if not path.exists():
            print("  %-16s MISSING" % tag)
            continue
        match = semantic.selected_resource(path)
        supported = None
        if match is not None and match.roi.get("offset_source"):
            supported = match.roi
        state = vision.observe(path)
        centres = {}
        for resource in ("MEAT", "WOOD", "COAL", "IRON"):
            centre = semantic.resource_cell_center_norm(resource)
            centres[resource] = None if centre is None else tuple(round(v, 4) for v in centre)
        print("  %-16s page=%-10s selected=%-34s offset=%s" % (
            tag, state.page, match.semantic if match else None,
            round(semantic.resource_tab_offset, 1) if semantic.resource_tab_offset is not None else None))
        print("      expected anchor %s | support=%s | tap targets %s"
              % (expected_anchor,
                 (supported or {}).get("supporting_reviewed_tabs"),
                 {k: (None if v is None else v[0]) for k, v in centres.items()}))

    print()
    print("=== calibration frames: must keep their known selection ===")
    for tag, rel, expected in KNOWN:
        path = ROOT / rel
        if not path.exists():
            print("  %-16s MISSING" % tag)
            continue
        match = semantic.selected_resource(path)
        got = match.semantic if match else None
        ok = got == ("RESOURCE_%s_SELECTED" % expected)
        print("  %-16s expected=%-24s got=%-34s %s" % (tag, expected, got, "OK" if ok else "**MISMATCH**"))

    print()
    print("=== panel-absent frames: must keep refusing ===")
    for tag, rel in NEGATIVES:
        path = ROOT / rel
        if not path.exists():
            print("  %-28s MISSING" % tag)
            continue
        match = semantic.selected_resource(path)
        state = vision.observe(path)
        print("  %-28s page=%-10s selected=%s" % (tag, state.page, match.semantic if match else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
