import json, collections
from pathlib import Path

ROOT = Path(r"E:\WinterAgent")
EXEC = ROOT / "learning/executor_backend.jsonl"

rows = []
for line in EXEC.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if line:
        try: rows.append(json.loads(line))
        except Exception: pass
print(f"rows: {len(rows)}")
kinds = collections.Counter(r.get("action_kind") for r in rows)
print("action_kind histogram:", dict(kinds))

taps = [r for r in rows if r.get("action_kind") == "TAP_SEMANTIC"]
print(f"\nTAP_SEMANTIC rows: {len(taps)}")
print("executed:", collections.Counter(r.get("executed") for r in taps))
print("recognition_backend:", collections.Counter(r.get("recognition_backend") for r in taps))

withpt = [r for r in taps if isinstance(r.get("tap_point"), (list, tuple)) and len(r["tap_point"]) == 2]
print(f"rows carrying a tap_point: {len(withpt)}")
norm = collections.Counter()
for r in withpt:
    x, y = r["tap_point"]
    if x is None: continue
    norm[(round(x/720.0, 3), round(y/1280.0, 3))] += 1
print("\nmost-repeated normalised tap points (a fixed point repeated = a constant):")
for pt, n in norm.most_common(20):
    print(f"  {str(pt):22s} x{n}")

# Which distinct targets were tapped at exactly the same point many times?
by_target = collections.defaultdict(collections.Counter)
for r in withpt:
    x, y = r["tap_point"]
    if x is None: continue
    by_target[r.get("action_target")][(round(x/720.0,3), round(y/1280.0,3))] += 1
print("\ntargets whose taps are concentrated on ONE point (candidate constants):")
for tgt, c in sorted(by_target.items(), key=lambda kv: -sum(kv[1].values())):
    tot = sum(c.values())
    top_pt, top_n = c.most_common(1)[0]
    if tot >= 3 and top_n / tot >= 0.8 and top_n >= 3:
        print(f"  {str(tgt):40s} {top_n}/{tot} at {top_pt}")
