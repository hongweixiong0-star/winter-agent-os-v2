"""Read-only: (a) did WB-1002-10 hold on the live revision, (b) what is SUBMIT_GIANT_BEAST_SEARCH
actually failing on.

Two questions, one pass over the real ledger tail.  Writes nothing, touches no device.
"""
from __future__ import annotations

import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = ROOT / "learning" / "episodes.jsonl"
FIXED_REV = "70b093f"

size = P.stat().st_size
chunk = min(size, 30 * 1024 * 1024)
with P.open("rb") as f:
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

on_fix = [r for r in rows if str(r.get("repo_revision") or "").startswith(FIXED_REV)]
print("rows in window:", len(rows), "| on the fixed revision:", len(on_fix))
print("window covers:", str(rows[0].get("recorded_at"))[11:19], "->", str(rows[-1].get("recorded_at"))[11:19])

print("\n=== (a) WB-1002-10 acceptance on %s ===" % FIXED_REV)
tab_fail = [r for r in on_fix if r.get("failure_type") in ("BEAST_SEARCH_TAB_NOT_PROVEN",
                                                           "GIANT_BEAST_SEARCH_NOT_PROVEN")]
beast_tab_steps = [r for r in on_fix if str(r.get("skill") or "").startswith(
    ("OPEN_BEAST_SEARCH_TAB", "SELECT_GIANT_BEAST_TAB", "SUBMIT_BEAST_SEARCH",
     "SUBMIT_GIANT_BEAST_SEARCH"))]
print("beast-search steps on the fixed revision:", len(beast_tab_steps))
for r in beast_tab_steps:
    sb = r.get("state_before") or {}
    sa = r.get("state_after") or {}
    print("   %s %-28s result=%-8s ft=%-30s before_tab=%-12s after_tab=%s" % (
        str(r.get("recorded_at"))[11:19], r.get("skill"), r.get("result"),
        str(r.get("failure_type"))[:30], sb.get("resource_selected_tab"), sa.get("resource_selected_tab")))
panel = [r for r in on_fix if (r.get("state_before") or {}).get("resource_search_open")]
vals = collections.Counter((r.get("state_before") or {}).get("resource_selected_tab") for r in panel)
print("search-panel frame readings on the fixed revision:", len(panel), "->", dict(vals))
print("BEAST_SEARCH_TAB_NOT_PROVEN on the fixed revision:", 
      sum(1 for r in tab_fail if r.get("failure_type") == "BEAST_SEARCH_TAB_NOT_PROVEN"))

print("\n=== (b) SUBMIT_GIANT_BEAST_SEARCH, all of today ===")
giant = [r for r in rows if r.get("skill") == "SUBMIT_GIANT_BEAST_SEARCH"]
print("steps:", len(giant),
      "| SUCCESS:", sum(1 for r in giant if r.get("result") == "SUCCESS"),
      "| FAILURE:", sum(1 for r in giant if r.get("result") == "FAILURE"))
print("by revision:", dict(collections.Counter(str(r.get("repo_revision"))[:7] for r in giant)))
print()
for r in giant:
    sb = r.get("state_before") or {}
    sa = r.get("state_after") or {}
    res = r.get("beast_search_result") or sa.get("beast_search_result") or {}
    print("   %s rev=%-8s result=%-8s ft=%-30s" % (
        str(r.get("recorded_at"))[11:19], str(r.get("repo_revision"))[:7], r.get("result"),
        str(r.get("failure_type"))[:30]))
    print("        before: tab=%-12s search_open=%-5s submitted=%s" % (
        sb.get("resource_selected_tab"), sb.get("resource_search_open"),
        sb.get("beast_search_submitted")))
    print("        after : tab=%-12s submitted=%-5s card=%s" % (
        sa.get("resource_selected_tab"), sa.get("beast_search_submitted"),
        json.dumps(res, ensure_ascii=False)[:150]))
    print("        action: %s" % json.dumps(r.get("action"), ensure_ascii=False)[:150])
    print("        reason: %s" % str(r.get("decision_reason"))[:160])
    print("        vev   : %s" % json.dumps(r.get("verifier_evidence"), ensure_ascii=False)[:260])
