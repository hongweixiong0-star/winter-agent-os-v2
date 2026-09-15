"""Debug: why does the known-order resolution not resolve the failing frame?"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.vision import (  # noqa: E402
    SemanticWorldVision,
    _cell_signature,
    _cell_template_signature,
    _signature_distance,
)

FRAME = ROOT / "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png"


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    s = vision.semantic

    m = s.selected_resource(FRAME)
    print("SemanticMatch attrs:", [a for a in dir(type(m)) if not a.startswith("__")] if m else "(returned None)")

    left, fv = s.selected_tab_left(FRAME)
    print("left=%.0f fully_visible=%s" % (left, fv))
    print("templated tabs:", sorted(s.resource_tab_cell_templates))
    print("strip order   :", s.resource_tab_order)

    with Image.open(FRAME) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        y0, y1 = s._tab_band_rows(height)
        cell_px = round(s.resource_tab_cell * width)
        print()
        print("=== candidate offsets and their support ===")
        for resource, offset in s._offset_candidates_from_known_order(left, width):
            count, margin = s._offset_supported_by_reviewed_tabs(image, width, height, offset)
            print("  %-14s offset=%8.1f  supporting=%d  margin=%.2f" % (resource, offset, count, margin))

        print()
        print("=== per-predicted-cell detail, for each candidate ===")
        for resource, offset in s._offset_candidates_from_known_order(left, width):
            print("  candidate %s (offset %.1f):" % (resource, offset))
            for other, paths in s.resource_tab_cell_templates.items():
                predicted_left = (
                    s.resource_tab_first_left
                    + s.resource_tab_order.index(other) * s.resource_tab_pitch
                ) * width + offset
                x0 = round(predicted_left)
                if x0 < 0 or x0 + cell_px > width:
                    print("      %-6s predicted x0=%5d  OFF-SCREEN" % (other, x0))
                    continue
                signature = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
                own = min(
                    _signature_distance(signature, _cell_template_signature(pathlib.Path(p)))
                    for p in paths
                )
                others = [
                    _signature_distance(signature, _cell_template_signature(pathlib.Path(p)))
                    for r, ps in s.resource_tab_cell_templates.items()
                    if r != other
                    for p in ps
                ]
                print(
                    "      %-6s predicted x0=%5d  own=%6.2f  runner=%6.2f  %s"
                    % (other, x0, own, min(others),
                       "MATCH" if own <= s.resource_tab_max_distance
                       and min(others) - own >= s.resource_tab_min_margin else "-")
                )


if __name__ == "__main__":
    main()
