"""Bounded live watch for WB-1002-22.

Exits as soon as a step for OPEN_BUILDING_UPGRADE appears on the deployed revision, or when the
budget runs out.  Records the whole revision's step mix either way, so "nothing happened" is a
measurement rather than an absence.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
EPISODES = ROOT / "learning/episodes.jsonl"
WANT = "OPEN_BUILDING_UPGRADE"


def rows_on(rev: str) -> list[dict]:
    if not EPISODES.is_file():
        return []
    size = EPISODES.stat().st_size
    with EPISODES.open("rb") as handle:
        handle.seek(max(0, size - 8_000_000))
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
        if str(row.get("repo_revision") or "").startswith(rev):
            out.append(row)
    return out


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 480
    rev = sys.argv[2] if len(sys.argv) > 2 else "5a04821"
    deadline = time.time() + budget
    while time.time() < deadline:
        rows = rows_on(rev)
        hits = [r for r in rows if r.get("skill") == WANT]
        if hits:
            print(f"MATCH after {len(rows)} rows on {rev}")
            for row in hits:
                before = row.get("state_before") or {}
                after = row.get("state_after") or {}
                building = before.get("building") or {}
                print("  %s | %s | %s | reason=%s"
                      % (str(row.get("recorded_at"))[11:19], row.get("result"),
                         row.get("failure_type"), row.get("decision_reason")))
                print("    recognition_error=%s executor_backend=%r"
                      % (row.get("recognition_error"), row.get("executor_backend")))
                print("    building=%s" % json.dumps(building, ensure_ascii=False)[:160])
                print("    after page=%s dialog=%s" % (after.get("page"),
                                                       (after.get("building") or {}).get("upgrade_dialog_visible")))
                print("    verifier=%s" % json.dumps(row.get("verifier_evidence") or {}, ensure_ascii=False)[:200])
            print()
            print("== all rows on", rev, "==")
            for row in rows:
                print("  %s %-38s %-8s %s"
                      % (str(row.get("recorded_at"))[11:19], str(row.get("skill"))[:38],
                         row.get("result"), str(row.get("failure_type"))[:30]))
            return 0
        time.sleep(10)
    rows = rows_on(rev)
    print(f"NO MATCH in {budget}s -- {len(rows)} rows on {rev}")
    for row in rows:
        print("  %s %-38s %-8s %s"
              % (str(row.get("recorded_at"))[11:19], str(row.get("skill"))[:38],
                 row.get("result"), str(row.get("failure_type"))[:30]))
    if rows:
        print("mix:", dict(collections.Counter(r.get("result") for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
