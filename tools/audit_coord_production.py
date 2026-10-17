"""Measure how much production tap traffic each forbidden tier actually carried.

Reads the real executor ledger (learning/executor_backend.jsonl) plus the episode
stream, and separates tap_points by the resolver tier that produced them.  The
point is not "does the code exist" but "how many real taps did it spend".
"""
import json
import collections
from pathlib import Path

ROOT = Path(r"E:\WinterAgent")
EXEC = ROOT / "learning/executor_backend.jsonl"
EPISODES = ROOT / "learning/episodes.jsonl"

print("=== executor_backend.jsonl ===")
rows = []
if EXEC.is_file():
    for line in EXEC.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    print(f"rows: {len(rows)}")
    if rows:
        print("keys sample:", sorted(rows[-1].keys()))
else:
    print("MISSING")

if rows:
    kinds = collections.Counter(r.get("action", {}).get("kind") if isinstance(r.get("action"), dict) else r.get("kind") for r in rows)
    print("\nkind histogram:", dict(kinds))
    taps = [r for r in rows if (r.get("action") or {}).get("kind") == "TAP_SEMANTIC" or r.get("kind") == "TAP_SEMANTIC"]
    print(f"TAP_SEMANTIC rows: {len(taps)}")
    tps = collections.Counter(r.get("tap_point") for r in taps)
    print("\ntop tap_points:")
    for tp, n in tps.most_common(15):
        print(f"  {str(tp):22s} x{n}")
    # ratio-normalised
    print("\nnormalised (assuming 720x1280):")
    norm = collections.Counter()
    for r in taps:
        tp = r.get("tap_point")
        if isinstance(tp, (list, tuple)) and len(tp) == 2 and tp[0] is not None:
            norm[(round(tp[0] / 720.0, 4), round(tp[1] / 1280.0, 4))] += 1
    for pt, n in norm.most_common(15):
        print(f"  {pt} x{n}")

print("\n=== episodes.jsonl markers ===")
for name, needle in [
    ("reusing a measured position", "REMEMBERED_COORD_REUSE"),
    ("[hint]", "DICTIONARY_HINT"),
    ("located by the dictionary", "DICTIONARY_HINT_EXPLICIT"),
]:
    count = 0
    total = 0
    if EPISODES.is_file():
        for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
            total += 1
            if needle in line:
                count += 1
    print(f"  {name!r:32s} -> {count} / {total} episodes")
