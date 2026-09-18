"""Watch the live AUTO loop for the deferral to fire.  Read-only."""
from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(r"E:\无尽冬日智能体")
EPISODES = ROOT / "learning/episodes.jsonl"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
LOG = ROOT / "learning/control_panel/latest.log"
LEDGER = ROOT / "learning/workbuddy_escalations.jsonl"


def tail_rows(path: pathlib.Path, count: int = 400) -> list[dict]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - count * 4096))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows[-count:]


def streak(rows: list[dict], goal_id: str) -> int:
    """Consecutive runs of `goal_id` with no measured progress, newest first."""
    groups: list[list[dict]] = []
    index: dict[str, int] = {}
    for row in rows:
        key = str(row.get("episode_id") or "")
        if not key:
            groups.append([row])
            continue
        if key not in index:
            index[key] = len(groups)
            groups.append([])
        groups[index[key]].append(row)
    count = 0
    for group in reversed(groups):
        mine = [r for r in group if str(r.get("goal_id") or "") == goal_id]
        if not mine:
            continue
        measured = [r.get("goal_progress") for r in mine]
        if any(v is True for v in measured):
            break
        if all(v is None for v in measured):
            break
        count += 1
    return count


print("watch start", datetime.now().isoformat(sep=" "), flush=True)
deadline = time.time() + 60 * 13
saw_deferral = False
saw_progress_field = False
while time.time() < deadline:
    rows = tail_rows(EPISODES)
    measured = [r for r in rows if "goal_progress" in r]
    snap = {}
    try:
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    log = ""
    try:
        log = LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    new_field = [r for r in measured if r.get("goal_progress") is not None]
    if new_field:
        saw_progress_field = True
    deferred_line = "[schedule] deferred" in log
    if deferred_line:
        saw_deferral = True

    last = rows[-1] if rows else {}
    print(
        f"{datetime.now():%H:%M:%S} | {snap.get('agent_state')} {snap.get('mode')} "
        f"goal={snap.get('current_goal')} skill={snap.get('current_skill')} "
        f"page={snap.get('page')} | streak(AVOID_STAMINA_WASTE)="
        f"{streak(rows, 'AVOID_STAMINA_WASTE')} | last={last.get('goal_id')}/"
        f"{last.get('skill')}/prog={last.get('goal_progress')} | "
        f"deferral_seen={saw_deferral}",
        flush=True,
    )
    if saw_deferral:
        break
    time.sleep(15)

print()
print("=== worker stdout (learning/control_panel/latest.log) ===")
try:
    text = LOG.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("[schedule]") or line.startswith("[escalation]") or '"stop_reason"' in line:
            print("  ", line[:400])
except OSError:
    print("   (no log)")

print()
print("=== newest measured episodes ===")
for row in [r for r in tail_rows(EPISODES, 60) if r.get("goal_progress") is not None][-12:]:
    print(f"   {row.get('recorded_at')} {row.get('goal_id'):<24} {row.get('skill'):<22} "
          f"ok={row.get('verifier_ok')} prog={row.get('goal_progress')} cap={row.get('capture_backend')}")

print()
print("=== escalation ledger rows since watch start ===")
rows = tail_rows(LEDGER)
for row in rows[-6:]:
    print("   ", row.get("recorded_at") or row.get("ts"), row.get("event"),
          row.get("key"), "| job", row.get("job_id"), "|",
          str(row.get("reason") or row.get("dispatch_reason") or row.get("note") or "")[:110])

print()
print("saw_progress_field:", saw_progress_field, "| saw_deferral:", saw_deferral)
sys.exit(0)
