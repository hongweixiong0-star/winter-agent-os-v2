"""Print the commander queue's orders compactly but completely, for execution."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUEUE = ROOT / ".workbuddy-ai/commander/WORK_QUEUE.json"

FIELDS = (
    "task_id", "priority", "status", "objective", "why_now", "current_evidence",
    "root_cause", "root_cause_confidence", "recommended_tool", "preferred_backend",
    "fallback_backend", "files_scope", "do_not_touch", "implementation_hint",
    "test_plan", "live_plan", "acceptance", "before_metric", "target_metric",
    "timebox_minutes", "stop_condition", "fallback_action", "dependencies",
)


def main() -> None:
    data = json.loads(QUEUE.read_text(encoding="utf-8"))
    orders = data.get("orders") or []
    print("queue generated_at:", data.get("generated_at"), "| orders:", len(orders))
    print("mode:", data.get("mode"), "| rules:", json.dumps(data.get("rules") or {}, ensure_ascii=False))
    for o in orders:
        if not str(o.get("task_id", "")).startswith("WB-R19"):
            continue
        print()
        print("=" * 100)
        for f in FIELDS:
            if f not in o:
                continue
            v = o[f]
            if isinstance(v, (dict, list)):
                print("  %-22s %s" % (f, json.dumps(v, ensure_ascii=False)))
            else:
                print("  %-22s %s" % (f, v))


if __name__ == "__main__":
    main()
