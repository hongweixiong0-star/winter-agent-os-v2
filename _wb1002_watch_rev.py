"""Bounded poll: the first search-panel frame the live revision 70b093f reads, and its tab.

Reads ``learning/episodes.jsonl`` only.  Exits when it finds one, or at the deadline.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = ROOT / "learning" / "episodes.jsonl"
REV = "70b093f"
DEADLINE_S = int(sys.argv[1]) if len(sys.argv) > 1 else 360


def rows_since(rev: str):
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
seen_best = 0
while True:
    rows = rows_since(REV)
    panel = [r for r in rows if (r.get("state_before") or {}).get("resource_search_open")]
    beast = [r for r in rows if str(r.get("skill") or "").startswith(("OPEN_BEAST", "SUBMIT_BEAST",
                                                                       "SUBMIT_GIANT_BEAST"))]
    print("[%s] rev %s rows=%d | panel frames=%d | beast-search steps=%d" % (
        time.strftime("%H:%M:%S"), REV, len(rows), len(panel), len(beast)))
    for r in beast[-6:]:
        sb = r.get("state_before") or {}
        print("      %s %-28s result=%-8s ft=%-28s before_tab=%s" % (
            str(r.get("recorded_at"))[11:19], r.get("skill"), r.get("result"),
            str(r.get("failure_type"))[:28], sb.get("resource_selected_tab")))
    if panel:
        print("\nfirst search-panel frames on the live revision:")
        for r in panel[:8]:
            sb = r.get("state_before") or {}
            sa = r.get("state_after") or {}
            print("   %s %-28s result=%-8s before_tab=%-12s after_tab=%-12s" % (
                str(r.get("recorded_at"))[11:19], r.get("skill"), r.get("result"),
                sb.get("resource_selected_tab"), sa.get("resource_selected_tab")))
        break
    if time.time() - started > DEADLINE_S:
        print("\nno search-panel frame on %s within %ds" % (REV, DEADLINE_S))
        break
    time.sleep(20)
