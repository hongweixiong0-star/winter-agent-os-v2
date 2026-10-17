"""Objective check for the seven formation/result templates registered 2026-09-24.

Two questions, and the second is the one that matters.

1. **Does each template resolve on the frame it was cut from?**  Cheap, and it catches a
   box that landed outside the picture or on a blank area.

2. **Can the three troop rows tell each other apart?**  This is the real risk.  All three
   boxes are the same size (295x116) on the SAME frame, 136 px apart, and the controls
   they contain -- the pause glyph and the blue '+' -- are *pixel-identical* across rows.
   If the template is dominated by that shared furniture, the reader cannot say which row
   it is looking at, and "load the infantry preset" silently becomes "load whatever row
   matched".  The task book's §13.3 asks for exactly this class of test ("列表顺序改变时
   不点击固定行号"), applied to rows instead of a rally list.

   So the check is a pairwise pHASH distance among the three rows, against the same
   ``max_distance`` the vision layer uses (``SemanticROIVision.max_distance``, default 6).
   Distance <= max_distance means the two would be confused.

Why pHASH and not template matching: the vision layer's default matcher for these records
IS pHASH (``vision.SemanticROIVision._find_in_roi``), so measuring with the same hash is
measuring what production will actually do, not a proxy for it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(r"E:\WinterAgent")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.vision import SemanticROIVision, hamming, phash  # noqa: E402

RAW = ROOT / "dataset/raw/bear_live_20260909"
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

NEW = [
    "STATUS_TROOP_CAPACITY", "TAB_TROOP_PRESET_STRIP",
    "TARGET_TROOP_ROW_INFANTRY", "TARGET_TROOP_ROW_LANCER", "TARGET_TROOP_ROW_MARKSMAN",
    "STATUS_RALLY_JOINED", "STATUS_MARCH_GATHERING",
]
ROWS = ["TARGET_TROOP_ROW_INFANTRY", "TARGET_TROOP_ROW_LANCER", "TARGET_TROOP_ROW_MARKSMAN"]

POSITIVE = {
    "STATUS_TROOP_CAPACITY": "bear_troop_setup.png",
    "TAB_TROOP_PRESET_STRIP": "bear_troop_setup.png",
    "TARGET_TROOP_ROW_INFANTRY": "bear_troop_setup.png",
    "TARGET_TROOP_ROW_LANCER": "bear_troop_setup.png",
    "TARGET_TROOP_ROW_MARKSMAN": "bear_troop_setup.png",
    "STATUS_RALLY_JOINED": "bear_dispatched.png",
    "STATUS_MARCH_GATHERING": "bear_dispatched.png",
}
NEGATIVE = {
    "STATUS_TROOP_CAPACITY": "bear_dispatched.png",
    "TAB_TROOP_PRESET_STRIP": "bear_dispatched.png",
    "STATUS_RALLY_JOINED": "bear_troop_setup.png",
    "STATUS_MARCH_GATHERING": "special_buildings.png",
}

vision = SemanticROIVision(MANIFEST)
max_d = vision.max_distance

print("=" * 76)
print("1. positive / negative resolution")
print("=" * 76)
print(f"{'SEMANTIC':30s} {'POS':>6s} {'NEG':>6s} {'MAX':>4s}  VERDICT")
print("-" * 76)
ok = bad = 0
for semantic in NEW:
    p = vision.find(RAW / POSITIVE[semantic], semantic)
    pd = None if p is None else p.distance
    neg = NEGATIVE.get(semantic)
    nd = None if neg is None else (lambda m: None if m is None else m.distance)(
        vision.find(RAW / neg, semantic))
    if pd is None:
        verdict = "POS_MISS"
        bad += 1
    elif neg is None or nd is None or pd < nd:
        verdict = "OK"
        ok += 1
    else:
        verdict = "AMBIGUOUS"
        bad += 1
    print(f"{semantic:30s} {str(pd):>6s} {str(nd):>6s} {max_d:>4d}  {verdict}")
print("-" * 76)
print(f"resolved: {ok}/{len(NEW)}   problem: {bad}")

print()
print("=" * 76)
print("2. can the three troop rows tell each other apart?")
print("=" * 76)
# The template each semantic actually resolves to.
paths: dict[str, Path] = {}
for record in json.loads(MANIFEST.read_text(encoding="utf-8"))["records"]:
    if record["semantic"] in ROWS:
        paths[record["semantic"]] = Path(record["template_path"])

hashes = {}
for semantic, path in paths.items():
    with Image.open(path) as opened:
        hashes[semantic] = phash(opened.convert("RGB"), size=8)

print(f"max_distance in production: {max_d}  (distance <= {max_d} = the two are confused)")
print()
worst = 0
for i, a in enumerate(ROWS):
    for b in ROWS[i + 1:]:
        d = hamming(hashes[a], hashes[b])
        verdict = "COLLIDE — production would not tell these apart" if d <= max_d else "distinct"
        worst = max(worst, d) if d <= max_d else worst
        print(f"  {a.replace('TARGET_TROOP_ROW_',''):10s} vs {b.replace('TARGET_TROOP_ROW_',''):10s} d={d:2d}  {verdict}")
print()
if worst:
    print("VERDICT: at least one pair collides — the rows need a discriminative re-cut")
    raise SystemExit(1)
print("VERDICT: all three rows are separable by the matcher production uses")
