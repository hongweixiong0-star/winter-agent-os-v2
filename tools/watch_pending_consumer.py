"""Wait for the queue's consumer to turn a NEW record into a real job.

Read-only.  Prints the queue counts and any new ledger row for the pending keys, and
stops the moment one of them carries a job id.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import datetime

ROOT = pathlib.Path(r"E:\无尽冬日智能体")
LEDGER = ROOT / "learning/workbuddy_escalations.jsonl"
LOG = ROOT / "learning/control_panel/latest.log"

KEYS = (
    "DISPATCH_GATHER_MARCH|SEMANTIC_TARGET_NOT_VERIFIED|DISPATCH_MARCH",
    "DISMISS_REAL_MONEY_OFFER|POPUP_CLOSE_NOT_PROVEN|DISMISS_REAL_MONEY_OFFER",
)


def rows() -> list[dict]:
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def state_of(all_rows: list[dict], key: str) -> tuple[str, str]:
    state, job = "NEW", ""
    for row in all_rows:
        if str(row.get("key") or "") != key:
            continue
        kind = str(row.get("event") or "")
        if kind == "submitted":
            state, job = "SUBMITTED", str(row.get("job_id") or job)
        elif kind == "job_state":
            value = str(row.get("state") or "")
            if value in ("WORKING", "DONE", "FAILED", "STOPPED"):
                state = value
        elif kind == "queued":
            state = "QUEUED"
    return state, job


before = len(rows())
print("watch start", datetime.now().isoformat(sep=" "), flush=True)
deadline = time.time() + 60 * 24
while time.time() < deadline:
    all_rows = rows()
    fresh = all_rows[before:]
    print(
        f"{datetime.now():%H:%M:%S} | " + " | ".join(
            f"{key.split('|')[0]}={state_of(all_rows, key)[0]}"
            + (f":{state_of(all_rows, key)[1]}" if state_of(all_rows, key)[1] else "")
            for key in KEYS
        ),
        flush=True,
    )
    for row in fresh:
        kind = str(row.get("event") or "")
        key = str(row.get("key") or "")
        if kind in ("submitted", "queued", "pending_consumed", "job_state") and key:
            print(f"     + {kind:16} {key[:52]} {row.get('job_id') or row.get('state') or ''}", flush=True)
    if any(state_of(all_rows, key)[1] for key in KEYS):
        print("CONSUMED", flush=True)
        break
    before = len(all_rows)
    time.sleep(15)

print()
print("=== worker narration ===")
try:
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("[escalation]") or line.startswith("[code]"):
            print("  ", line[:240])
except OSError:
    print("   (no log)")
print()
print("final:", {key: state_of(rows(), key) for key in KEYS})
sys.exit(0)
