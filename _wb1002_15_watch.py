"""Bounded live watch for WB-1002-15.

Waits for the AUTO process to write episodes on the deployed revision, then watches for the two
things this order is about and exits as soon as it has either:

  * the new MAA vocabulary appearing on a real failure -- a ``recognition_error`` starting with
    ``MAA_TEMPLATE:`` / ``MAA_FRAME:`` / ``LIST_DYNAMIC:FALLBACK_ABSENT``.  That is the acceptance:
    a node-bearing skill's miss now explains itself instead of writing an empty string;
  * a *node-bearing* skill failing with an empty reason -- one of the three skills measured to have
    an MAA recognition node.  That would mean the hole is still open somewhere I did not cover.

Quiet windows are reported as unobserved rather than as a pass, because these routes are only
reached when the runtime happens to walk into them.

    python _wb1002_15_watch.py <seconds> [revision]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES = ROOT / "learning" / "episodes.jsonl"
NEW_PREFIXES = ("MAA_TEMPLATE:", "MAA_FRAME:", "LIST_DYNAMIC:FALLBACK_ABSENT")
# The three skills measured on 2026-10-02 to carry an MAA recognition node, i.e. the ones that
# reach ``maa_resolver``'s node branch and were silent there.
NODE_SKILLS = {"OPEN_HOME", "OPEN_BUILDING_UPGRADE", "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT"}


def tail_rows(window: int = 2_000_000):
    size = os.path.getsize(EPISODES)
    with EPISODES.open("rb") as stream:
        stream.seek(max(0, size - window))
        blob = stream.read().decode("utf-8", "replace")
    rows = []
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def main() -> int:
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 420.0
    revision = (sys.argv[2] if len(sys.argv) > 2 else "61adba7").strip()
    started = time.time()
    live_since = None
    print(f"watching for {budget:.0f}s; deployed revision {revision}", flush=True)

    while time.time() - started < budget:
        rows = tail_rows()
        on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
        if on_rev and live_since is None:
            live_since = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] revision went live "
                  f"({len(on_rev)} rows so far)", flush=True)
        if live_since is not None:
            fresh = [r for r in on_rev if str(r.get("recorded_at") or "") >= _stamp(live_since)]
            named = [r for r in fresh
                     if str(r.get("recognition_error") or "").startswith(NEW_PREFIXES)]
            still_empty = [r for r in fresh
                           if r.get("result") == "FAILURE"
                           and str(r.get("skill")) in NODE_SKILLS
                           and not str(r.get("recognition_error") or "")]
            if named:
                print(f"\nNEW VOCABULARY OBSERVED on {revision}:", flush=True)
                for row in named:
                    print(f"   {str(row.get('recorded_at'))[11:19]} {row.get('skill')}"
                          f"/{row.get('result')} -> {row.get('recognition_error')}", flush=True)
                return 0
            if still_empty:
                print(f"\nSTILL EMPTY on a node-bearing skill, {revision}:", flush=True)
                for row in still_empty:
                    print(f"   {str(row.get('recorded_at'))[11:19]} {row.get('skill')}"
                          f"/{row.get('failure_type')}", flush=True)
                return 2
        time.sleep(15)

    rows = tail_rows()
    on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
    print(f"\nwindow closed. rows on {revision}: {len(on_rev)}", flush=True)
    if live_since is None:
        print("UNOBSERVED: the revision never went live inside the window.", flush=True)
        return 3
    named = sum(1 for r in on_rev if str(r.get("recognition_error") or "").startswith(NEW_PREFIXES))
    empt = sum(1 for r in on_rev if r.get("result") == "FAILURE"
               and str(r.get("skill")) in NODE_SKILLS and not str(r.get("recognition_error") or ""))
    print(f"new-vocabulary rows: {named}; empty-reason node-bearing failures: {empt}", flush=True)
    if named == 0 and empt == 0:
        print("UNOBSERVED: no node-bearing miss happened in this window.", flush=True)
        return 3
    return 0 if empt == 0 else 2


def _stamp(since: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(since - 120))


if __name__ == "__main__":
    raise SystemExit(main())
