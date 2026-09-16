"""Every frame the resource-tab test asserts on, plus the independent offset check.

For each case: what the classifier now says, and -- computed WITHOUT the anchor,
by scanning offsets and asking which one puts the gatherable templates on their own
cells -- which tab the bracket is really on.  The second column is what makes it
legitimate to change an expectation: the identity has to be confirmed by evidence
that does not include the mechanism under test.
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

CASES = [
    ("home", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_001_home.png"),
    ("map", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_002_map.png"),
    ("beast", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_003_search_panel.png"),
    ("giant_beast", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_004_tab_tap_MEAT.png"),
    ("sawmill", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_005_tab_tap_WOOD.png"),
    ("meat", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_006_tab_tap_COAL.png"),
    ("wood_clipped", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_007_tab_tap_IRON.png"),
    ("select_meat", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png"),
    ("select_wood", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_003_select_WOOD.png"),
    ("select_coal", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_004_select_COAL.png"),
    ("select_iron", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_005_select_IRON.png"),
    ("home probe", "dataset/raw/control_panel/probe/live_page_20260915_151524.png"),
]

GATHERABLE = ("MEAT", "WOOD", "COAL", "IRON")


def independent_anchor(semantic, image, width, height, templates):
    """Which tab is the bracket on, per evidence that does not use the anchor.

    Slide the strip: the offset is right when the gatherable templates sit on their
    own cells.  Under that offset, invert the bracket's x to a tab index.  Returns
    (offset, index) or None.
    """
    y0, y1 = semantic._tab_band_rows(height)
    cell_px = round(semantic.resource_tab_cell * width)
    hits = []
    for offset in range(-500, 700):
        values = {}
        for name in GATHERABLE:
            nominal = (semantic.resource_tab_first_left
                       + semantic.resource_tab_order.index(name) * semantic.resource_tab_pitch) * width
            x0 = round(nominal + offset)
            if x0 < 0 or x0 + cell_px > width:
                continue
            probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
            values[name] = min(_signature_distance(probe, s) for s in templates[name])
        if values and all(v <= 8.0 for v in values.values()):
            hits.append((offset, len(values), values))
    if not hits:
        return None
    # Prefer the offset supported by the most cells.
    offset, count, values = max(hits, key=lambda item: (item[1], -item[0]))
    lefts = semantic.candidate_tab_lefts_from(image)
    if not lefts:
        return ("offset %+d, %d cells, no stroke pair" % (offset, count)) and None
    indices = []
    for left in lefts:
        index = (left - offset) / width
        index = (index - semantic.resource_tab_first_left) / semantic.resource_tab_pitch
        indices.append(round(index, 2))
    return offset, count, values, indices


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    templates = {
        name: [_cell_template_signature(Path(p)) for p in paths]
        for name, paths in semantic.resource_tab_cell_templates.items()
    }

    for label, rel in CASES:
        path = ROOT / rel
        if not path.exists():
            print("%-14s MISSING" % label)
            continue
        match = semantic.selected_resource(path)
        got = match.semantic[len("RESOURCE_"):-len("_SELECTED")] if match else None
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        found = independent_anchor(semantic, image, width, height, templates)
        if found is None:
            independent = "no offset satisfies the templates -> refuse is right"
        else:
            offset, count, values, indices = found
            integer = [i for i in indices if abs(i - round(i)) <= 0.05 and 0 <= round(i) < 7]
            independent = ("offset %+d, %d cells %s, bracket indices %s -> %s"
                           % (offset, count, values, indices,
                              semantic.resource_tab_order[round(integer[0])] if integer else "no integer index"))
        print("%-14s classifier=%-18s | %s" % (label, got, independent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
