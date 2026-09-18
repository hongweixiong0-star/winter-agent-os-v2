"""Wait for the first episode that *measures* goal progress on the gather route.

Read-only.  Stops as soon as an episode records ``goal_progress`` for
KEEP_MARCHES_PRODUCTIVE, or when the deadline passes.
"""
from __future__ import annotations

import json
import pathlib
import time
from datetime import datetime

ROOT = pathlib.Path(r"E:\无尽冬日智能体")
EPISODES = ROOT / "learning/episodes.jsonl"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"


def rows() -> list[dict]:
    out = []
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


print("watch start", datetime.now().isoformat(sep=" "), flush=True)
deadline = time.time() + 60 * 11
found = []
while time.time() < deadline:
    current = rows()[-40:]
    found = [
        row for row in current
        if str(row.get("goal_id") or "") == "KEEP_MARCHES_PRODUCTIVE"
        and row.get("goal_progress") is not None
    ]
    snapshot = {}
    try:
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    newest = current[-1] if current else {}
    print(
        f"{datetime.now():%H:%M:%S} | {snapshot.get('agent_state')} goal={snapshot.get('current_goal')} "
        f"skill={snapshot.get('current_skill')} | newest={newest.get('goal_id')}/"
        f"{newest.get('skill')}/prog={newest.get('goal_progress')} | measured_gather={len(found)}",
        flush=True,
    )
    if any(row.get("goal_progress") is True for row in found):
        break
    time.sleep(15)

print()
print("=== measured gather-route episodes ===")
for row in found:
    print(f"   {row.get('recorded_at')} {row.get('skill'):<24} ok={row.get('verifier_ok')} "
          f"goal_progress={row.get('goal_progress')} idle={((row.get('state_before') or {}).get('march_used'))}"
          f"->{((row.get('state_after') or {}).get('march_used'))} cap={row.get('capture_backend')}")
print()
print("verdict:", "PROGRESS MEASURED" if any(r.get("goal_progress") is True for r in found) else "not yet")
