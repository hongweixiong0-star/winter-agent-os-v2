"""Measure the resource-tab strip pitch from frames where the selection is known.

Why this is the work: SELECT_RESOURCE is the last blocker on the gather chain.
SEARCH_RESOURCE succeeds and the chain then stops, every time, because a resource
tab's tap target comes from a strip model whose pitch was calibrated on
2026-09-14.  On the 2026-09-15T23:37 live frame the model placed MEAT about 56 px
from where the frame visibly shows it -- a third of a cell, enough to land between
two tabs.

The measurement does not need the offset at all.  If the selected tab is known for
each of several frames of the SAME panel, and the strip does not re-centre between
them, then the bracket's own left edge advances by exactly one pitch per tab:

    L(WOOD) - L(MEAT) = pitch

so the pitch can be read straight off the frames, with no model in the loop.
`dataset/truth_audit/resource_cells_20260914_120027/` is exactly that: MEAT, WOOD,
COAL and IRON selected in turn.

Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

KNOWN_SELECTION = [
    ("MEAT", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png"),
    ("WOOD", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png"),
    ("COAL", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png"),
    ("IRON", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png"),
]

SECOND_SET = [
    ("MEAT", "dataset/truth_audit/resource_availability_20260914_124753/20260914_124753_select_MEAT.png"),
    ("WOOD", "dataset/truth_audit/resource_availability_20260914_124753/20260914_124753_select_WOOD.png"),
]

THIRD_SET = [
    ("MEAT", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_004_tab_tap_MEAT.png"),
    ("WOOD", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_005_tab_tap_WOOD.png"),
    ("COAL", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_006_tab_tap_COAL.png"),
    ("IRON", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_007_tab_tap_IRON.png"),
]

LIVE_FAILURES = [
    "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png",
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T233739598714.png",
]


def bracket(semantic, rel: str):
    path = ROOT / rel
    if not path.exists():
        print("    MISSING %s" % rel)
        return None
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    lefts = semantic.candidate_tab_lefts_from(image)
    match = semantic.selected_resource(path)
    identity = match.semantic if match else None
    distance = match.distance if match else None
    return {"width": width, "lefts": lefts, "identity": identity, "distance": distance,
            "image": image, "rel": rel}


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    pitch = semantic.resource_tab_pitch * 720
    cell = semantic.resource_tab_cell * 720
    first_left = semantic.resource_tab_first_left * 720
    print("configured: pitch=%.1f  cell=%.1f  first_left=%.1f" % (pitch, cell, first_left))
    for name in semantic.resource_tab_order:
        nominal = first_left + semantic.resource_tab_order.index(name) * pitch
        print("    nominal %-12s left=%7.1f" % (name, nominal))
    print()

    for title, series in (("resource_cells_20260914_120027", KNOWN_SELECTION),
                          ("resource_availability_20260914_124753", SECOND_SET),
                          ("gather_live_20260914_115120", THIRD_SET)):
        print("=" * 78)
        print(title)
        measured = []
        for expected, rel in series:
            info = bracket(semantic, rel)
            if info is None:
                continue
            single = info["lefts"][0] if len(info["lefts"]) == 1 else None
            print("  expected=%-5s stroke-pairs=%-28s identity=%-34s distance=%s"
                  % (expected, info["lefts"], info["identity"], info["distance"]))
            if single is not None:
                measured.append((expected, single))
        print("  --- pitch from consecutive known selections ---")
        if len(measured) < 2:
            print("      not enough unambiguous frames")
        for (prev_name, prev_left), (name, left) in zip(measured, measured[1:]):
            print("      %-5s -> %-5s : %+7.1f px   (configured %.1f, delta %+.1f)"
                  % (prev_name, name, left - prev_left, pitch, (left - prev_left) - pitch))
        if measured:
            print("  --- absolute check ---")
            for name, left in measured:
                nominal = first_left + semantic.resource_tab_order.index(name) * pitch
                print("      %-5s measured left=%7.1f  nominal=%7.1f  implied offset=%+7.1f"
                      % (name, left, nominal, left - nominal))
        print()

    print("=" * 78)
    print("live failures (2026-09-15T23:37) -- what the model says vs what the frame shows")
    for rel in LIVE_FAILURES:
        info = bracket(semantic, rel)
        if info is None:
            continue
        print("  %s" % Path(rel).name[:58])
        print("      stroke pairs: %s" % info["lefts"])
        print("      identity: %s  distance: %s" % (info["identity"], info["distance"]))
        supported = semantic._supported_offsets(info["image"], info["width"], 1280)
        for count, margin, resource, offset in supported:
            if count:
                print("      supported anchor=%s offset=%+.1f support=%d margin=%.2f"
                      % (resource, offset, count, margin))
                for name in ("MEAT", "WOOD", "COAL", "IRON"):
                    nominal = first_left + semantic.resource_tab_order.index(name) * pitch
                    print("          predicted %-5s left=%7.1f" % (name, nominal + offset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
