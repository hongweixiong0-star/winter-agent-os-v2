"""Bounded live watch for WB-1002-20.

The four refusals this round answers happened on a revision that produced them in pairs about six
seconds apart, so the reachable signals are:

  * a SELECT_RESOURCE row that PASSED -- the acceptance;
  * a SELECT_RESOURCE row that FAILED but carries an after-frame -- a tap was delivered and the
    refusal moved to the verifier, which is progress from "never reached the device";
  * any SELECT_RESOURCE row at all, which is enough to judge the pair behaviour.

A window in which the strip is never opened is reported as unobserved with the row count.

    python _wb1002_20_watch.py <seconds> [revision]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EPISODES = ROOT / "learning" / "episodes.jsonl"


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
    revision = (sys.argv[2] if len(sys.argv) > 2 else "130d8bb").strip()
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
            strip = [r for r in fresh if r.get("skill") == "SELECT_RESOURCE"]
            if strip:
                print(f"\nSTRIP REACHED on {revision}:", flush=True)
                for row in strip:
                    state = row.get("state_before") or {}
                    print(f"   {str(row.get('recorded_at'))[11:19]} {row.get('result')} "
                          f"{row.get('failure_type')} kinds={state.get('resource_tab_kinds')} "
                          f"after_frame={bool(row.get('after_screenshot'))} "
                          f"duration={row.get('duration'):.2f}s", flush=True)
                if any(r.get("result") == "SUCCESS" for r in strip):
                    print("   => the tab was selected", flush=True)
                    return 0
                print("   => still refused, read the rows", flush=True)
                return 2
        time.sleep(15)

    rows = tail_rows()
    on_rev = [r for r in rows if str(r.get("repo_revision") or "").startswith(revision)]
    print(f"\nwindow closed. rows on {revision}: {len(on_rev)}", flush=True)
    if live_since is None:
        print("UNOBSERVED: the revision never went live inside the window.", flush=True)
        return 3
    strip = [r for r in on_rev if r.get("skill") == "SELECT_RESOURCE"]
    search = [r for r in on_rev if r.get("skill") in ("SEARCH_RESOURCE", "SUBMIT_RESOURCE_SEARCH")]
    print(f"strip steps: {len(strip)}; search steps: {len(search)}", flush=True)
    if not strip:
        print("UNOBSERVED: the resource strip was never opened in this window.", flush=True)
        return 3
    return 0 if any(r.get("result") == "SUCCESS" for r in strip) else 2


def _stamp(since: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(since - 120))


if __name__ == "__main__":
    raise SystemExit(main())
