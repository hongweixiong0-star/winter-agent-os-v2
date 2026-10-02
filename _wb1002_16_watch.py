"""Bounded live watch for WB-1002-16.

Watches the deployed revision for the three things this order is about, and exits as soon as it has
any of them:

  * a DISPATCH_MARCH row that PASSED -- the acceptance: the verifier no longer refuses a march the
    game accepted;
  * a DISPATCH_MARCH row whose evidence carries ``gather_formation_resource_clause`` -- proof the
    new clause is live, whichever way it judged;
  * a DISPATCH_MARCH row that FAILED for the new, named reason -- which would mean the refusal is
    real this time and the evidence now says which sub-condition it was.

A window in which the gather flow never reaches that hop is reported as unobserved, with the count of
rows on the revision, rather than as a pass.

    python _wb1002_16_watch.py <seconds> [revision]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES = ROOT / "learning" / "episodes.jsonl"
GATHER_HOP = "DISPATCH_MARCH"


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
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 480.0
    revision = (sys.argv[2] if len(sys.argv) > 2 else "76a5e90").strip()
    started = time.time()
    live_since = None
    print(f"watching for {budget:.0f}s; deployed revision {revision}", flush=True)

    while time.time() - started < budget:
        rows = tail_rows()
        on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
        if on_rev and live_since is None:
            live_since = time.time()
            print(f"  [{time.strftime('%H:%M:%S')}] revision went live ({len(on_rev)} rows so far)",
                  flush=True)
        if live_since is not None:
            fresh = [r for r in on_rev if str(r.get("recorded_at") or "") >= _stamp(live_since)]
            hop = [r for r in fresh if r.get("skill") == GATHER_HOP]
            if hop:
                for row in hop:
                    evidence = row.get("verifier_evidence") or {}
                    clause = evidence.get("gather_formation_resource_clause", "(field absent)")
                    print(f"\nTHE HOP WAS REACHED on {revision}:", flush=True)
                    print(f"   {str(row.get('recorded_at'))[11:19]} {row.get('result')} "
                          f"{row.get('failure_type')} clause={clause} "
                          f"policy={evidence.get('gather_formation_policy')}", flush=True)
                if any(r.get("result") == "SUCCESS" for r in hop):
                    print("   => the dispatch passed", flush=True)
                    return 0
                if any("gather_formation_resource_clause" in (r.get("verifier_evidence") or {})
                       for r in hop):
                    print("   => new clause is live and refused with a named reason", flush=True)
                    return 0
                print("   => FAILED, which warrants reading the evidence", flush=True)
                return 2
        time.sleep(15)

    rows = tail_rows()
    on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
    print(f"\nwindow closed. rows on {revision}: {len(on_rev)}", flush=True)
    if live_since is None:
        print("UNOBSERVED: the revision never went live inside the window.", flush=True)
        return 3
    hop = [r for r in on_rev if r.get("skill") == GATHER_HOP]
    gather = [r for r in on_rev if str(r.get("skill")) in
              {"START_GATHER", "SUBMIT_RESOURCE_SEARCH", "CLEAR_GATHER_HEROES", "SELECT_RESOURCE",
               "SEARCH_RESOURCE"}]
    print(f"gather-flow steps: {len(gather)}; DISPATCH_MARCH rows: {len(hop)}", flush=True)
    if not hop:
        print("UNOBSERVED: the flow did not reach the dispatch hop in this window.", flush=True)
        return 3
    return 0


def _stamp(since: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(since - 120))


if __name__ == "__main__":
    raise SystemExit(main())
