"""Bounded live watch for WB-1002-14.

Waits for the AUTO process to start writing episodes on the deployed revision, then watches for
either signal and exits as soon as it has one:

  * the guard firing -- a step whose ``decision_reason`` is one of the two new names, which means
    the fishing/building route met the open panel and closed it instead of tapping the covered door;
  * the defect still present -- a FAILURE whose ``decision_reason`` is
    ``fishing_entry_requires_city_hud`` / ``building_goal_requires_home``.

Neither being absent is a real outcome too: the routes are only reached when those goals are
selected, so a quiet window is reported as unobserved rather than as a pass.

    python _wb1002_14_watch.py <seconds> [revision]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES = ROOT / "learning" / "episodes.jsonl"
NEW_REASONS = {"close_resource_search_for_fishing_goal",
               "close_resource_search_for_building_goal"}
OLD_REASONS = {"fishing_entry_requires_city_hud", "building_goal_requires_home"}


def tail_rows(window: int = 1_500_000):
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
    revision = (sys.argv[2] if len(sys.argv) > 2 else "3ce3ef3").strip()
    started = time.time()
    live_since = None
    print(f"watching for {budget:.0f}s; deployed revision {revision}", flush=True)

    while time.time() - started < budget:
        rows = tail_rows()
        on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
        if on_rev and live_since is None:
            live_since = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] revision went live "
                  f"({len(on_rev)} rows in the window so far)", flush=True)

        if live_since is not None:
            fresh = [r for r in on_rev
                     if str(r.get("recorded_at") or "") >= _stamp(live_since)]
            hit_guard = [r for r in fresh if str(r.get("decision_reason")) in NEW_REASONS]
            still_broken = [r for r in fresh
                            if r.get("result") == "FAILURE"
                            and str(r.get("decision_reason")) in OLD_REASONS]
            if hit_guard:
                print(f"\nGUARD FIRED on {revision}:", flush=True)
                for row in hit_guard:
                    print(f"   {str(row.get('recorded_at'))[11:19]} "
                          f"{row.get('skill')}/{row.get('result')} "
                          f"reason={row.get('decision_reason')}", flush=True)
                return 0
            if still_broken:
                print(f"\nDEFECT STILL PRESENT on {revision}:", flush=True)
                for row in still_broken:
                    print(f"   {str(row.get('recorded_at'))[11:19]} "
                          f"{row.get('skill')}/{row.get('result')} "
                          f"reason={row.get('decision_reason')}", flush=True)
                return 2
        time.sleep(15)

    rows = tail_rows()
    on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
    print(f"\nwindow closed. rows on {revision}: {len(on_rev)}", flush=True)
    if live_since is None:
        print("UNOBSERVED: the revision never went live inside the window.", flush=True)
        return 3
    seen_new = sum(1 for r in on_rev if str(r.get("decision_reason")) in NEW_REASONS)
    seen_old = sum(1 for r in on_rev
                   if r.get("result") == "FAILURE" and str(r.get("decision_reason")) in OLD_REASONS)
    print(f"guard fired {seen_new} time(s); old defect seen {seen_old} time(s)", flush=True)
    if seen_new == 0 and seen_old == 0:
        print("UNOBSERVED: neither route was reached in this window.", flush=True)
        return 3
    return 0 if seen_old == 0 else 2


def _stamp(since: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(since - 120))


if __name__ == "__main__":
    raise SystemExit(main())
