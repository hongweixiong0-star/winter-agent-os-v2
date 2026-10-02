"""Are the 20 SELECT_RESOURCE misses designed retries (paired) or genuine misses?

Last round's rule: pair a failure with what the same skill does next before calling it a defect.
SELECT_RESOURCE misses arrive in twos ~6 s apart, so the pairing is the first thing to check.

Read-only.
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = ROOT / "learning" / "episodes.jsonl"

size = P.stat().st_size
with P.open("rb") as f:
    f.seek(max(0, size - 25_000_000))
    blob = f.read().decode("utf-8", "replace")
rows = []
for line in blob.splitlines():
    line = line.strip()
    if line.startswith("{"):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass

focus = ("SELECT_RESOURCE", "SELECT_BEAST_TARGET_MAMMOTH")
by_episode = collections.defaultdict(list)
for r in rows:
    if r.get("skill") in focus:
        by_episode[(r.get("episode_id"), r.get("skill"))].append(r)

print("episodes carrying %s: %d" % (str(focus), len(by_episode)))
for skill in focus:
    ep = [(k, v) for k, v in by_episode.items() if k[1] == skill]
    if not ep:
        continue
    print()
    print("=" * 96)
    print(skill, "-- %d episodes --" % len(ep))
    for (episode, _), steps in sorted(ep, key=lambda kv: str(kv[1][0].get("recorded_at"))):
        if len(steps) < 2:
            continue
        steps.sort(key=lambda r: r.get("step_id") or 0)
        print("  episode %s step(s) %s" % (episode, [r.get("step_id") for r in steps]))
        for r in steps:
            sb = r.get("state_before") or {}
            sa = r.get("state_after") or {}
            print("     t=%s step=%-4s result=%-8s ft=%-30s dur=%-7s" % (
                str(r.get("recorded_at"))[11:19], r.get("step_id"), r.get("result"),
                str(r.get("failure_type"))[:30], round(float(r.get("duration") or 0), 3)))
            print("        before: page=%-8s tab=%-12s lvl=%-4s avail=%-5s search_open=%s" % (
                sb.get("page"), sb.get("resource_selected_tab"), sb.get("resource_level"),
                sb.get("resource_available"), sb.get("resource_search_open")))
            print("        after : page=%-8s tab=%-12s lvl=%-4s avail=%-5s selected=%s" % (
                sa.get("page"), sa.get("resource_selected_tab"), sa.get("resource_level"),
                sa.get("resource_available"), sa.get("resource_selected")))
            print("        reason: %s" % str(r.get("decision_reason"))[:110])

print()
print("== how often does a failure's next step in the same episode succeed? ==")
outcome = collections.Counter()
for (episode, skill), steps in by_episode.items():
    steps.sort(key=lambda r: r.get("step_id") or 0)
    for i, r in enumerate(steps):
        if r.get("result") != "FAILURE":
            continue
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if nxt is None:
            outcome["failure is the last step of its episode"] += 1
        elif nxt.get("result") == "SUCCESS":
            outcome["next step of the same skill SUCCEEDED"] += 1
        else:
            outcome["next step of the same skill also failed"] += 1
for k, v in outcome.most_common():
    print("   %-44s %d" % (k, v))
