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

from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--snapshot", type=Path, default=Path("learning/runtime_snapshot.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/runtime_soak_30m.json"))
    args = parser.parse_args()
    store = RuntimeSnapshotStore(args.snapshot)
    started = time.monotonic(); samples = []; contradictions = 0
    while time.monotonic() - started < args.minutes * 60:
        item = store.read()
        running = item.agent_state in {"AUTO_RUNNING", "GOAL_RUNNING", "RECOVERING"}
        contradiction = running and not (item.runtime_thread_alive and item.scheduler_loop_alive)
        contradictions += int(contradiction)
        samples.append({"at": datetime.now(timezone.utc).isoformat(), "state": item.agent_state,
                        "thread": item.runtime_thread_alive, "scheduler": item.scheduler_loop_alive,
                        "goal": item.current_goal, "skill": item.current_skill,
                        "last_tick": item.last_tick_time, "last_success": item.last_success_time,
                        "stop_reason": item.stop_reason, "contradiction": contradiction})
        time.sleep(max(1, args.interval))
    result = {"duration_minutes": args.minutes, "sample_count": len(samples), "state_contradictions": contradictions,
              "unexpected_worker_exits": store.read().unexpected_worker_exits,
              "watchdog_restart_count": store.read().watchdog_restart_count,
              "started_at": samples[0]["at"] if samples else None, "finished_at": datetime.now(timezone.utc).isoformat(),
              "samples": samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, ensure_ascii=False))
    return 0 if contradictions == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
