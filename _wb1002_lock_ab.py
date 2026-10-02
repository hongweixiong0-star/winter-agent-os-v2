"""Read-only A/B on real frames: the current bracket-to-label lock (0.03) vs a measured one.

For every archived frame whose ledger row says the resource search panel was open, this prints:
  * what the CURRENT production reader reports (`resource_selected_tab`),
  * how many bracket pairs the current 0.03 lock accepts, and which kinds they name,
  * the same with a 0.005 lock,
  * and the per-pair (gap, distance-to-nearest-label) evidence behind both.

The point is to decide, from data, whether tightening the lock can only remove spurious pairs
and can never remove the true one.  Writes nothing, touches no device.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.ocr import (  # noqa: E402
    OCRService, RapidOCRBackend, ResilientOCRBackend,
    read_resource_tab_labels, selected_tab_from_live_labels,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 40
PROPOSED = float(sys.argv[2]) if len(sys.argv) > 2 else 0.005
RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"

p = ROOT / "learning" / "episodes.jsonl"
size = p.stat().st_size
chunk = min(size, 60 * 1024 * 1024)
with p.open("rb") as f:
    f.seek(size - chunk)
    blob = f.read().decode("utf-8", "replace")
lines = blob.splitlines()
if size > chunk:
    lines = lines[1:]

rows = []
for line in lines:
    line = line.strip()
    if line.startswith("{"):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass

picked, seen = [], set()
for r in reversed(rows):
    sb = r.get("state_before")
    if not isinstance(sb, dict) or not sb.get("resource_search_open"):
        continue
    shot = str(r.get("before_screenshot") or "")
    ep = str(r.get("episode_id") or "")
    if not shot or not ep:
        continue
    path = RUNS / ep / Path(shot.replace("\\", "/")).name
    key = path.name
    if key in seen or not path.exists():
        continue
    seen.add(key)
    picked.append((r, path, sb.get("resource_selected_tab"), sb.get("resource_tab_kinds")))
    if len(picked) >= LIMIT:
        break

world_vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
semantic = world_vision.semantic
config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

print("frames measured:", len(picked), "| current lock 0.03 | proposed lock", PROPOSED)
print()
print("%-34s %-24s %-12s %-9s %-10s %s" % (
    "frame", "ledger says", "current", "pairs@.03", "pairs@%.3f" % PROPOSED, "detail"))
print("-" * 128)

changed_ok, changed_bad, same, true_dists, spur_dists = [], [], 0, [], []
for r, path, truth, kinds in picked:
    with Image.open(path) as src:
        image = src.convert("RGB")
        width = image.width
        strokes = semantic._bracket_strokes(image)
    labels = read_resource_tab_labels(path, ocr)
    if not labels:
        continue
    lo, hi = 130 * width / 720, 175 * width / 720
    pairs = []
    for i, (left, _) in enumerate(strokes):
        for right in [s for s, _ in strokes[i + 1:]]:
            if lo <= right - left <= hi:
                centre = (left + right) / 2 / width
                near = min(labels.items(), key=lambda kv: abs(kv[1][0] - centre))
                pairs.append((right - left, centre, near[0], abs(near[1][0] - centre)))
    cur = selected_tab_from_live_labels(path, labels, semantic)
    for lock in (0.03, PROPOSED):
        m = {k for _, _, k, d in pairs if d < lock}
        if len(m) == 1:
            (m.pop(),)
    def verdict(lock):
        m = {k for _, _, k, d in pairs if d < lock}
        return next(iter(m)) if len(m) == 1 else None
    after = verdict(PROPOSED)
    n03 = len({k for _, _, k, d in pairs if d < 0.03})
    npro = len({k for _, _, k, d in pairs if d < PROPOSED})
    detail = " ".join("g%.0f/%s/%.4f" % (g, k, d) for g, _, k, d in sorted(pairs, key=lambda x: x[3]))
    print("%-34s %-24s %-12s %-9s %-10s %s" % (
        path.name[-32:], str(truth)[:22], str(cur), n03, npro, detail[:64]))
    if cur != after:
        (changed_ok if after is not None else changed_bad).append((path.name, cur, after))
    else:
        same += 1
    best = min((d for *_, d in pairs), default=None)
    if best is not None:
        rest = sorted(d for *_, d in pairs)[1]
        true_dists.append(best)
        spur_dists.append(rest)

print()
print("verdict CHANGED with the proposed lock:", len(changed_ok) + len(changed_bad))
print("   -> resolved to a tab :", len(changed_ok))
for row in changed_ok:
    print("        ", row[0][-40:], "  None ->", row[2])
print("   -> LOST a tab        :", len(changed_bad))
for row in changed_bad:
    print("        ", row[0][-40:], "  ", row[1], "-> None")
print("unchanged:", same)
print()
if spur_dists:
    print("worst TRUE  distance across frames : %.5f" % max(true_dists))
    print("best SPURIOUS distance across frames: %.5f" % min(spur_dists))
    print("proposed lock sits %.1fx above the worst true and %.1fx below the best spurious" % (
        PROPOSED / max(true_dists), min(spur_dists) / PROPOSED))
    print("true-pair distance histogram:", Counter(round(d, 4) for d in true_dists).most_common())
