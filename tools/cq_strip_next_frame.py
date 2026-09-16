"""Why does the frame the SELECT_RESOURCE step saw not resolve?

The SEARCH_RESOURCE step's after-frame resolved to GIANT_BEAST at offset 399, and
the very next step's before-frame -- the same panel, about twelve seconds later --
resolved to nothing, so `resource_tab_offset` stayed None and the scroll branch
(which requires an offset) was skipped, sending the run into the executor with a
None target.  Look at the frame and measure it the same way as the others.
"""

from __future__ import annotations

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

FRAMES = [
    ("SEARCH_RESOURCE after (resolved)", "dataset/raw/live_runtime/live_runtime_step_006_after_20260916T040909168667.png"),
    ("SELECT_RESOURCE before (did not)", "dataset/raw/live_runtime/live_runtime_step_007_before_20260916T040931067046.png"),
]

OLD_FRAMES = [
    ("23:37 failure (resolves now)", "dataset/truth_audit/resource_strip_20260916/live_fail_233727__live_runtime_step_003_before_20260915T233727132656.png"),
]


def independent_offsets(semantic, image, width, height, templates):
    y0, y1 = semantic._tab_band_rows(height)
    cell_px = round(semantic.resource_tab_cell * width)
    hits = []
    for offset in range(-500, 700):
        values = {}
        for name in ("MEAT", "WOOD", "COAL", "IRON"):
            nominal = (semantic.resource_tab_first_left
                       + semantic.resource_tab_order.index(name) * semantic.resource_tab_pitch) * width
            x0 = round(nominal + offset)
            if x0 < 0 or x0 + cell_px > width:
                continue
            probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
            values[name] = round(min(_signature_distance(probe, s) for s in templates[name]), 2)
        if values and all(v <= 8.0 for v in values.values()):
            hits.append((offset, values))
    return hits


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    templates = {
        name: [_cell_template_signature(Path(p)) for p in paths]
        for name, paths in semantic.resource_tab_cell_templates.items()
    }

    for title, rel in FRAMES + OLD_FRAMES:
        path = ROOT / rel
        if not path.exists():
            print("MISSING %s" % rel)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        lefts = semantic.candidate_tab_lefts_from(image)
        match = semantic.selected_resource(path)
        print("=" * 78)
        print("%s" % title)
        print("  file: %s" % Path(rel).name)
        print("  size: %dx%d  band rows %s  stroke pairs %s"
              % (width, height, semantic._tab_band_rows(height), lefts))
        print("  classifier: %s  offset=%s"
              % (match.semantic if match else None,
                 round(semantic.resource_tab_offset, 1) if semantic.resource_tab_offset is not None else None))
        hits = independent_offsets(semantic, image, width, height, templates)
        if hits:
            for offset, values in hits[:3]:
                indices = []
                for left in lefts:
                    index = (left - offset) / width
                    index = (index - semantic.resource_tab_first_left) / semantic.resource_tab_pitch
                    indices.append(round(index, 2))
                print("  independent: offset=%+d %s -> bracket indices %s" % (offset, values, indices))
        else:
            print("  independent: no offset satisfies the templates")
        # per-stroke-pair detail, to see whether any candidate has an integer index
        if lefts:
            print("  per stroke pair (assuming offset +399 and +0):")
            for left in lefts:
                for offset in (399, 0):
                    index = (left - offset) / width
                    index = (index - semantic.resource_tab_first_left) / semantic.resource_tab_pitch
                    if abs(index - round(index)) <= 0.05 and 0 <= round(index) < 7:
                        print("      left=%-7.1f offset=%+4d -> index %.2f = %s"
                              % (left, offset, index, semantic.resource_tab_order[round(index)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
