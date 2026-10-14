"""Retire escalation records whose premise production data has falsified.

**Read-only by default**: it prints what it *would* retire and why.  ``--apply`` appends the
``premise_falsified`` events -- the only way this ledger changes, because it is append-only
(``fold`` replays it; nothing rewrites a row).

Which premises this retires, and why it may
-------------------------------------------
The three the **device itself** disproved, so no development job could ever retire them:

* ``FALSIFIED_SINCE_FILING`` -- the goal advanced *after* the record was filed;
* ``SKILL_NEVER_DISPATCHED`` -- the skill the record names has zero episodes in the stream;
* ``GOAL_NEVER_RAN`` -- the goal never appears at all.

The other two premises are deliberately **left alone**: ``HOLDS_NEVER_ADVANCED`` and
``RECOGNITION_CLAIM_NEEDS_A_FRAME`` both still need a live device to settle, and this tool
must not be the thing that decides them.

Why this exists
---------------
``capability_bootstrap.preload_gate`` is zero-tolerance: it refuses to dispatch while a single
record is pending.  Measured 2026-10-14, 11 of the 17 pending records were exactly the shape
above, so the whole preload route was held shut and AUTO ran with no work at all.  Retiring
them is what lets the gate say yes -- and the reason travels with each row
(``fold`` records the premise and the measurement), so a reader sees *why* rather than
inferring it from an absence.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from winter_agent_v2.escalation_queue import EscalationLedger  # noqa: E402
from audit_escalation_premises import audit  # noqa: E402

#: The premises the device disproved.  Everything else is left for a live device to settle.
UNFIXABLE_PREMISES = ("FALSIFIED_SINCE_FILING", "SKILL_NEVER_DISPATCHED", "GOAL_NEVER_RAN")


def plan(root: Path) -> list[dict]:
    """What would be retired, oldest first, with the premise that justifies it.

    ``audit()`` already returns exactly the records ``EscalationQueueAdapter.pending()``
    counts -- it is the same predicate (state NEW/QUEUED, condition in the five) -- so this
    only has to pick out the premises the device disproved.
    """
    rows = audit(root)
    return [row for row in rows if str(row.get("premise")) in UNFIXABLE_PREMISES]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true",
                        help="append the premise_falsified events (default: dry run)")
    args = parser.parse_args(argv)

    rows = plan(args.root)
    print(f"pending records that would be retired: {len(rows)}")
    for row in rows:
        print(f"  {row.get('premise'):<28} {row.get('capability', '')} "
              f"/ {row.get('skill', '')}  (filed {row.get('filed', '')})")
    if not rows:
        print("nothing to retire")
        return 0
    if not args.apply:
        print("\ndry run -- re-run with --apply to append the events")
        return 0

    ledger = EscalationLedger(args.root / "learning/workbuddy_escalations.jsonl")
    moment = datetime.now(timezone.utc).isoformat()
    written = 0
    for row in rows:
        key = str(row.get("key") or "")
        if not key:
            continue
        ledger.append({
            "event": "premise_falsified", "key": key,
            "reason": str(row.get("premise", "")),
            "premise": str(row.get("premise", "")),
            "measured_at": moment,
        })
        written += 1
    print(f"\nappended {written} premise_falsified event(s)")

    after = plan(args.root)
    print(f"pending unfixable records now: {len(after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
