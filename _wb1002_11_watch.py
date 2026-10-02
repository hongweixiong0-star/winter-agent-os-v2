"""Bounded live check: does a real failure name its own reason now?

Reads ``learning/episodes.jsonl`` only.  Exits as soon as the deployed revision has produced a
failure with the new field, or at the deadline.  No device input, no writes.
"""
from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = ROOT / "learning" / "episodes.jsonl"
REV = "84e15e5"
DEADLINE_S = int(sys.argv[1]) if len(sys.argv) > 1 else 420


def rows_on(rev: str):
    size = P.stat().st_size
    with P.open("rb") as f:
        f.seek(max(0, size - 3_000_000))
        blob = f.read().decode("utf-8", "replace")
    out = []
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("repo_revision") or "").startswith(rev):
                out.append(row)
    return out


started = time.time()
last_report = 0.0
while True:
    rows = rows_on(REV)
    failed = [r for r in rows if r.get("result") == "FAILURE"]
    named = [r for r in failed if str(r.get("recognition_error") or "")]
    has_key = sum(1 for r in rows if "recognition_error" in r)
    print("[%s] rev %s rows=%d | key present %d | failures=%d | failures naming a reason=%d" % (
        time.strftime("%H:%M:%S"), REV, len(rows), has_key, len(failed), len(named)))
    for r in named[:10]:
        print("      %s %-30s %-30s -> %s" % (
            str(r.get("recorded_at"))[11:19], r.get("skill"),
            str(r.get("failure_type"))[:30], r.get("recognition_error")))
    if len({str(r.get("recognition_error")) for r in named}) >= 2:
        vals = collections.Counter(str(r.get("recognition_error")) for r in named)
        print("\ndistinct reasons on real failures:", len(vals))
        for k, v in vals.most_common():
            print("   %-52s %d" % (k, v))
        by_type = collections.Counter(str(r.get("failure_type")) for r in named)
        print("\nsame failure_type, several reasons? ->",
              {t: len({str(r.get('recognition_error')) for r in named if r.get('failure_type') == t})
               for t in by_type})
        break
    if time.time() - started > DEADLINE_S:
        print("\nno named failure on %s within %ds" % (REV, DEADLINE_S))
        break
    time.sleep(20)
