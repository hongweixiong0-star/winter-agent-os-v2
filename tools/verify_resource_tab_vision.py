"""Replay verification for the new resource-tab classifier.

Runs the shipped ``SemanticROIVision.selected_resource`` (not a copy) over every
labelled live frame and prints the verdict plus the derived strip offset, so the
fix is measured on real client frames instead of on the design intent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticWorldVision

vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
sem = vision.semantic

CASES: list[tuple[str, Path, str | None]] = []
# First session: the strip sat at a different scroll offset (beast first).
G1 = ROOT / "dataset/truth_audit/gather_live_20260914_115120"
CASES += [
    ("home", G1 / "20260914_115120_step_001_home.png", None),
    ("map", G1 / "20260914_115120_step_002_map.png", None),
    ("panel:beast", G1 / "20260914_115120_step_003_search_panel.png", None),
    ("panel:giant_beast", G1 / "20260914_115120_step_004_tab_tap_MEAT.png", None),
    ("panel:sawmill", G1 / "20260914_115120_step_005_tab_tap_WOOD.png", None),
    ("panel:MEAT", G1 / "20260914_115120_step_006_tab_tap_COAL.png", "MEAT"),
    ("panel:WOOD(clipped)", G1 / "20260914_115120_step_007_tab_tap_IRON.png", None),
]
# Second session: WOOD held selected throughout.
G2 = ROOT / "dataset/truth_audit/resource_strip_20260914_115635"
for n in sorted(G2.glob("*_s_*.png")):
    CASES.append((f"strip:{n.stem.split('_s_')[1]}", n, "WOOD"))
# Third session: an explicit select-each capture.
G3 = ROOT / "dataset/truth_audit/resource_cells_20260914_120027"
for res, name in (("MEAT", "c_002"), ("WOOD", "c_003"), ("COAL", "c_004"), ("IRON", "c_005")):
    CASES.append((f"select:{res}", G3 / f"20260914_120027_{name}_select_{res}.png", res))

ok = bad = skipped = 0
for label, path, expect in CASES:
    if not path.is_file():
        print(f"  -- {label:26s} frame missing, skipped")
        skipped += 1
        continue
    match = sem.selected_resource(path)
    got = match.semantic[len("RESOURCE_"):-len("_SELECTED")] if match else None
    good = got == expect
    ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
    offset = sem.resource_tab_offset
    centre_meat = sem.resource_cell_center_norm("MEAT")
    print(f"  {'OK ' if good else '!! '}{label:26s} got={str(got):5s} expect={str(expect):5s} "
          f"d={None if match is None else round(match.distance, 2)} offset={None if offset is None else round(offset, 1)} "
          f"meat_centre={None if centre_meat is None else round(centre_meat[0], 3)}")

print(f"\nsummary: {ok} correct, {bad} mismatched, {skipped} skipped, {len(CASES)} frames")
