"""Poll the AUTO for the acceptance evidence: 3 consecutive self-continuing rounds.

Read-only.  Writes a transcript to stdout and a JSON summary at the end, so the claim
"3 consecutive rounds kept AUTO alive" can be checked against files rather than recalled.

Measured how: the uptime ledger (learning/auto_uptime.jsonl) is written by the panel at the
single point where it has already decided whether another round follows, and each row records
the same ``halt_reason`` that decision used.  So a row with continues=true IS the panel saying
"another round starts".  The panel log supplies the human-readable side of the same events.

usage: python tools/measure_auto_uptime.py --need 3 --timeout-min 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime_snapshot import (  # noqa: E402
    read_uptime_ledger,
    summarize_uptime,
)

LEDGER = ROOT / "learning/auto_uptime.jsonl"
PANEL_LOG = ROOT / "learning/control_panel/panel.log"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
OUT = ROOT / "learning/auto_uptime_acceptance.json"


def _tail(path: Path, lines: int = 6) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--need", type=int, default=3)
    parser.add_argument("--timeout-min", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)

    deadline = time.time() + args.timeout_min * 60
    seen = 0
    while True:
        rows = read_uptime_ledger(LEDGER)
        if len(rows) != seen:
            seen = len(rows)
            for row in rows[-2:]:
                print(f"[row] {row.get('recorded_at')} stop={row.get('stop_reason')} "
                      f"category={row.get('stop_category')} healthy={row.get('healthy')} "
                      f"continues={row.get('continues')} failures={row.get('failures')} "
                      f"halt={row.get('halt_reason')!r}", flush=True)
            for line in _tail(PANEL_LOG, 4):
                print(f"[panel] {line}", flush=True)
        summary = summarize_uptime(rows)
        if summary["longest_consecutive_continues"] >= args.need:
            print(f"[done] longest_consecutive_continues="
                  f"{summary['longest_consecutive_continues']} "
                  f"window={summary['longest_window_seconds']:.0f}s", flush=True)
            break
        if time.time() >= deadline:
            print(f"[timeout] only {summary['longest_consecutive_continues']} of "
                  f"{args.need} consecutive continuing rounds after "
                  f"{args.timeout_min} minutes", flush=True)
            break
        time.sleep(args.poll_seconds)

    rows = read_uptime_ledger(LEDGER)
    summary = summarize_uptime(rows)
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "rows": rows,
        "panel_log_tail": _tail(PANEL_LOG, 25),
        "snapshot": json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        if SNAPSHOT.exists() else {},
        "ledger": str(LEDGER),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[written] {OUT}", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["acceptance_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
