"""Measure: among all stroke pairs and all tab identities, which offset do the
reviewed templates actually support?

If the direct anchor pick is wrong, the fix is not more templates -- it is to let
the reviewed templates choose the anchor.  This measures whether that search has
a unique, well-supported answer on the failing frame before anything is changed.

Read-only.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

FRAME = ROOT / "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T160609443785.png"
GOOD = ROOT / "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T160526845125.png"


def pairs(s, image):
    strokes = s._bracket_strokes(image)
    out = []
    for i, (a, _) in enumerate(strokes):
        for b, _ in strokes[i + 1:]:
            if 130 <= b - a <= 175:
                out.append((a, b))
    return strokes, out


def table(vision, frame) -> None:
    s = vision.semantic
    print("=" * 96)
    print(frame.name)
    with Image.open(frame) as opened:
        image = opened.convert("RGB")
        width, height = image.size
        strokes, prs = pairs(s, image)
        print("  strokes at:", [round(c, 1) for c, _ in strokes])
        print("  accepted pairs:", [(round(a, 1), round(b, 1)) for a, b in prs])
        print()
        print("  %-18s %-10s %-8s %s" % ("anchor(left)", "identity", "offset", "support(own/runner per reviewed tab)"))
        best = []
        for left, _right in prs:
            for identity in s.resource_tab_order:
                offset = s.resource_tab_offset_from(left, identity, width)
                detail = []
                support = 0
                for resource, paths in s.resource_tab_cell_templates.items():
                    predicted = (
                        s.resource_tab_first_left
                        + s.resource_tab_order.index(resource) * s.resource_tab_pitch
                    ) * width + offset
                    x0 = round(predicted)
                    cell_px = round(s.resource_tab_cell * width)
                    y0, y1 = s._tab_band_rows(height)
                    if x0 < 0 or x0 + cell_px > width:
                        detail.append("%s:off" % resource)
                        continue
                    from winter_agent_v2.vision import (
                        _cell_signature,
                        _cell_template_signature,
                        _signature_distance,
                    )

                    sig = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
                    own = min(
                        _signature_distance(sig, _cell_template_signature(pathlib.Path(p)))
                        for p in paths
                    )
                    others = [
                        _signature_distance(sig, _cell_template_signature(pathlib.Path(p)))
                        for r, ps in s.resource_tab_cell_templates.items()
                        if r != resource
                        for p in ps
                    ]
                    runner = min(others)
                    hit = own <= s.resource_tab_max_distance and runner - own >= s.resource_tab_min_margin
                    if hit:
                        support += 1
                    detail.append("%s:%s%.1f/%.1f" % (resource, "*" if hit else "", own, runner))
                print("  %-18s %-10s %8.1f  s=%d  %s" % (round(left, 1), identity, offset, support, " ".join(detail)))
                if support:
                    best.append((support, left, identity, offset))
        print()
        best.sort(reverse=True)
        print("  >>> supported candidates:", [(b[0], round(b[1], 1), b[2], round(b[3], 1)) for b in best[:6]])


def main() -> None:
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    table(vision, FRAME)
    print()
    table(vision, GOOD)


if __name__ == "__main__":
    main()
