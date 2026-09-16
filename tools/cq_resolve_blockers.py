"""Mark the two now-resolved blockers in BLOCKED_QUEUE.json.

The blocker log is what Codex reads to decide what is stuck, so leaving a resolved
entry looking open is worse than not recording it at all.  Both entries are kept
(the log is a history, and the earlier diagnosis is what this round refuted), with
a status and a pointer to the result that closed them.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / ".workbuddy-ai/commander/BLOCKED_QUEUE.json"

RESOLVED = {
    "WB-R19-SELECT-RESOURCE-ANCHOR": (
        "RESOLVED 2026-09-16T04:15Z. The blocker's own diagnosis is REFUTED: the strip pitch was never wrong "
        "(measured 157/158 px on frames with a known selection, matching the configured 157). The defect was the "
        "template ceiling, 6.0, sitting BELOW the largest value its own calibration frames produce (correct "
        "population 0.00..6.49 vs wrong 10.65..25.09), plus a second defect found after it: the client draws no "
        "bracket until a tab is selected, so a freshly opened panel had no anchor at all and the offset stayed None. "
        "Both fixed; SELECT_RESOURCE now succeeds live and the gather chain completes end to end."
    ),
    "WB-R19-START-GATHER-MAA-LIVE-AB": (
        "RESOLVED (reachability) 2026-09-16T04:15Z. Its dependency is closed and START_GATHER ran live and passed "
        "with recognition/action/executor all MAA. Its historical 35/94 (37.2%) is explained: all 59 failures were "
        "MARCH_PAGE_NOT_OPEN, i.e. the chain never reached the skill. The order's alternating A/B sample is still "
        "incomplete (1 MAA arm, 0 fallback) because the brain's reserve_for_stamina policy stops further gather "
        "dispatches while a march is out -- that is policy, not a defect, and freeing a slot by recalling the march "
        "would be manufacturing state."
    ),
}


def main() -> int:
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    touched = 0
    for item in payload.get("items", []):
        task = item.get("task_id")
        if task in RESOLVED:
            item["status"] = "RESOLVED"
            item["resolved_at"] = "2026-09-16T04:15:00+00:00"
            item["resolution"] = RESOLVED[task]
            touched += 1
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("marked %d blocker(s) resolved" % touched)
    for item in payload.get("items", []):
        print("  %-42s %s" % (item.get("task_id"), item.get("status")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
