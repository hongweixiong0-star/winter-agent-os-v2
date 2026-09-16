"""Pin the strip offset using only labels that cannot be misread, then check the anchor.

The gate change made two frames in the archived corpus resolve to BEAST and
GIANT_BEAST where the R19 test expected None.  That could be a capability gain or a
new false identity, and the difference matters: a wrong anchor still yields a
confident-looking tap target, just at the wrong tab.

The labels 生肉 (MEAT) and 木材 (WOOD) are unambiguous in the calibration set
(verified at template distance 0.00 with the bracket on them).  So the strip
position can be pinned independently of the anchor: slide the model over a range of
offsets and find the one that puts MEAT and WOOD on their own templates.  Whatever
anchor that offset then implies is the truth, and it can be compared with what the
classifier claims.
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
    ("gl_step003 (R19 expected None)", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_003_search_panel.png"),
    ("gl_step004 (R19 expected None)", "dataset/truth_audit/gather_live_20260914_115120/20260914_115120_step_004_tab_tap_MEAT.png"),
    ("live 233727 (anchor idx 1)", "dataset/raw/live_runtime/live_runtime_step_003_before_20260915T233727132656.png"),
    ("cal select_MEAT (offset 0)", "dataset/truth_audit/resource_cells_20260914_120027/20260914_120027_c_002_select_MEAT.png"),
]


def main() -> int:
    vision = SemanticWorldVision(MANIFEST)
    semantic = vision.semantic
    templates = {
        name: [_cell_template_signature(Path(p)) for p in paths]
        for name, paths in semantic.resource_tab_cell_templates.items()
    }

    for title, rel in FRAMES:
        path = ROOT / rel
        if not path.exists():
            print("MISSING %s" % rel)
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        y0, y1 = semantic._tab_band_rows(height)
        cell_px = round(semantic.resource_tab_cell * width)

        # Scan offsets; score every templated tab whose crop is fully on-screen.
        # Frames differ in how many are visible (on the 23:37 live frames WOOD is
        # clipped by the right edge), so ranking is by "most tabs scoreable, then
        # lowest total" rather than demanding all four -- the first version of this
        # script demanded both MEAT and WOOD and therefore reported "no offset" for
        # every frame where WOOD was clipped.
        results = []
        for offset in range(-450, 601, 1):
            total = 0.0
            matched = 0
            per = {}
            for name in ("MEAT", "WOOD", "COAL", "IRON"):
                nominal = (semantic.resource_tab_first_left
                           + semantic.resource_tab_order.index(name) * semantic.resource_tab_pitch) * width
                x0 = round(nominal + offset)
                if x0 < 0 or x0 + cell_px > width:
                    continue
                probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
                own = min(_signature_distance(probe, s) for s in templates[name])
                per[name] = round(own, 2)
                total += own
                matched += 1
            if matched:
                results.append((matched, total, offset, per))
        # A correct offset must put EVERY scoreable templated tab on its own
        # template, so filter to those and rank by how many tabs that is.
        results = [r for r in results if all(v <= 8.0 for v in r[3].values())]
        results.sort(key=lambda item: (-item[0], item[1]))

        print("=" * 78)
        print(title)
        if not results:
            print("  no offset puts the visible templated tabs on their own templates")
            continue
        seen_offsets = []
        for matched, total, offset, per in results:
            if any(abs(offset - other) <= 3 for other in seen_offsets):
                continue
            seen_offsets.append(offset)
            lefts = semantic.candidate_tab_lefts_from(image)
            implied = []
            for left in lefts:
                index = (left - offset) / width
                index = (index - semantic.resource_tab_first_left) / semantic.resource_tab_pitch
                implied.append((left, round(index, 2),
                                semantic.resource_tab_order[round(index)]
                                if 0 <= round(index) < len(semantic.resource_tab_order) else "?"))
            print("  offset=%+5d  tabs=%d  %s  ->  stroke pairs imply anchor %s"
                  % (offset, matched, per, implied))
            if len(seen_offsets) >= 4:
                break
        classifier = semantic.selected_resource(path)
        print("  classifier says: %s (offset %s)"
              % (classifier.semantic if classifier else None,
                 round(semantic.resource_tab_offset, 1) if semantic.resource_tab_offset is not None else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
