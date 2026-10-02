"""Bounded live watch for WB-1002-24.

Answers the order's acceptance with production artifacts, not inference:

* did the diagnostic for the ``SCHEDULED_*`` rows change from MISSING_NAVIGATION to
  MISSING_OBSERVATION (i.e. did the route land), and does any row now report a safe entry?
* did any step get filed under a ``SCHEDULED_*`` goal (the attempt)?
* what did the verifier say, and is the failure path recorded so a retry is possible?
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
EPISODES = ROOT / "learning/episodes.jsonl"


def snapshot_rows() -> tuple[dict, list[dict]]:
    try:
        payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, []
    return payload, list(payload.get("capability_discovery") or [])


def scheduled_episodes(rev: str) -> list[dict]:
    if not EPISODES.is_file():
        return []
    size = EPISODES.stat().st_size
    with EPISODES.open("rb") as handle:
        handle.seek(max(0, size - 6_000_000))
        blob = handle.read().decode("utf-8", "replace")
    out = []
    for line in blob.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("repo_revision") or "").startswith(rev) and \
                str(row.get("goal_id") or "").startswith(("SCHEDULED_", "EVENT_")):
            out.append(row)
    return out


def report(snapshot: dict, rows: list[dict], episodes: list[dict]) -> None:
    reasons = collections.Counter(str(r.get("reason")) for r in rows)
    scheduled = [r for r in rows if str(r.get("goal_id") or "").startswith("SCHEDULED_")]
    print(f"snapshot updated_at={snapshot.get('updated_at')} state={snapshot.get('agent_state')}")
    print(f"  capability_discovery rows={len(rows)} reasons={dict(reasons)}")
    print(f"  SCHEDULED_ rows={len(scheduled)}")
    for row in scheduled[:8]:
        print("    %-46s reason=%-22s route=%-6s selectable=%-6s entry=%s"
              % (str(row.get("goal_id"))[:46], row.get("reason"), row.get("route_exists"),
                 row.get("scheduler_selectable"), row.get("safe_entry_exists")))
    ready = [r for r in rows if r.get("safe_entry_exists") or r.get("scheduler_selectable")]
    print(f"  rows with a safe entry / selectable: {len(ready)}")
    for row in ready[:10]:
        print("    %-46s reason=%-22s stage=%s skill=%s"
              % (str(row.get("goal_id"))[:46], row.get("reason"),
                 row.get("bootstrap_stage"), row.get("selected_skill")))
    print(f"  SCHEDULED_/EVENT_ episodes on the deployed revision: {len(episodes)}")
    for row in episodes:
        print("    %s | %-38s | %-8s | %s"
              % (str(row.get("recorded_at"))[11:19], str(row.get("skill"))[:38],
                 row.get("result"), str(row.get("failure_type"))[:30]))


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 540
    rev = sys.argv[2] if len(sys.argv) > 2 else "164de5e"
    deadline = time.time() + budget
    seen_live = False
    while time.time() < deadline:
        snapshot, rows = snapshot_rows()
        if str(snapshot.get("updated_at") or ""):
            episodes = scheduled_episodes(rev)
            if episodes:
                print("EPISODE UNDER A CALENDAR GOAL")
                report(snapshot, rows, episodes)
                return 0
            if not seen_live and rows:
                print("== first reading on the new revision ==")
                report(snapshot, rows, episodes)
                seen_live = True
        time.sleep(15)
    snapshot, rows = snapshot_rows()
    print(f"NO MATCH in {budget}s")
    report(snapshot, rows, scheduled_episodes(rev))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
