"""WB-R19-SELECT-RESOURCE-ANCHOR: print the anchor diagnostics on the failing frame.

The work order asks for exactly this before any fix: bracket left, fully_visible,
candidate scores and the resulting offset, on the production frame that failed.
Asserting that "the templates do not cover BEAST" without measuring would be a
guess dressed as a diagnosis.

Read-only.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.vision import (  # noqa: E402
    SemanticROIVision,
    SemanticWorldVision,
    _cell_signature,
    _cell_template_signature,
    _signature_distance,
)

FRAMES = [
    ROOT / "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png",
]


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    semantic: SemanticROIVision = vision.semantic

    print("=== configuration ===")
    for name in (
        "resource_tab_order",
        "resource_tab_first_left",
        "resource_tab_pitch",
        "resource_tab_cell",
        "resource_tab_band",
        "resource_tab_max_distance",
        "resource_tab_min_margin",
    ):
        print("  %-26s %s" % (name, getattr(semantic, name, "<missing>")))
    print("  cell templates for:      %s" % sorted(semantic.resource_tab_cell_templates.keys()))

    out = ROOT / "dataset/probe_output/resource_anchor_20260916"
    out.mkdir(parents=True, exist_ok=True)

    for frame in FRAMES:
        print()
        print("=" * 90)
        if not frame.exists():
            print("MISSING", frame)
            continue
        print(frame.name)

        left_px, fully_visible = semantic.selected_tab_left(frame)
        print("  selected_tab_left -> left_px=%s fully_visible=%s" % (left_px, fully_visible))

        with Image.open(frame) as opened:
            image = opened.convert("RGB")
            width, height = image.size
        print("  frame size: %dx%d" % (width, height))

        if left_px < 0:
            print("  NO BRACKET FOUND -> selected_resource returns None outright")
            continue

        y0, y1 = semantic._tab_band_rows(height)
        cell_px = round(semantic.resource_tab_cell * width)
        x0, x1 = round(left_px), round(left_px) + cell_px
        print("  anchored cell: x %d..%d  y %d..%d  (cell_px=%d)" % (x0, x1, y0, y1, cell_px))
        clipped = x0 < 0 or x1 > width
        print("  cell fits fully on screen: %s" % (not clipped))

        if clipped:
            print("  CLIPPED -> selected_resource returns None before scoring")
            continue

        with Image.open(frame) as opened:
            image = opened.convert("RGB")
            probe = image.crop((x0, y0, x1, y1))
            too_hot = image.crop((x0, y0, x1, y1))
        probe.save(out / "probe_engineered_bear.png")
        probe.resize((probe.width * 4, probe.height * 4), Image.NEAREST).save(out / "probe_engineered_bear_4x.png")

        probe_signature = _cell_signature(probe)
        print()
        print("  candidate scores (lower is closer):")
        scored = []
        for resource, paths in semantic.resource_tab_cell_templates.items():
            best = None
            for path in paths:
                signature = _cell_template_signature(pathlib.Path(path))
                if signature is None:
                    continue
                value = _signature_distance(probe_signature, signature)
                best = value if best is None else min(best, value)
            if best is not None:
                scored.append((best, resource))
        scored.sort()
        for distance, resource in scored:
            print("    %-14s %.2f" % (resource, distance))
        if scored:
            best_d, best_r = scored[0]
            runner = scored[1][0] if len(scored) > 1 else best_d + 999.0
            print()
            print("  best=%-10s %.2f   runner_up=%.2f   margin=%.2f" % (best_r, best_d, runner, runner - best_d))
            print("  gates: max_distance=%.2f margin_min=%.2f" % (
                semantic.resource_tab_max_distance, semantic.resource_tab_min_margin))
            print("  distance gate passes: %s" % (best_d <= semantic.resource_tab_max_distance))
            print("  margin gate passes:   %s" % (runner - best_d >= semantic.resource_tab_min_margin))
            print("  => selected_resource would return: %s" % (
                "a match" if (best_d <= semantic.resource_tab_max_distance
                              and runner - best_d >= semantic.resource_tab_min_margin) else "None"))

        match = semantic.selected_resource(frame)
        print()
        print("  selected_resource(frame) = %s" % (match.semantic if match else None))
        print("  resource_tab_offset after call = %s" % semantic.resource_tab_offset)
        print("  wrote probe crops to %s" % out)


if __name__ == "__main__":
    main()
