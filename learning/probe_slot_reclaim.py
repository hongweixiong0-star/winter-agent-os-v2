"""Why the timebox reclaim does not fire, and what signal is missing.

Read-only probe.  Run with the project venv from the repo root.
"""

from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    DEFAULT_LEDGER,
    NEW,
    QUEUED,
    SUBMITTED,
    WORKING,
    EscalationLedger,
    EscalationPolicy,
    EscalationQueueAdapter,
)
from winter_agent_v2.workbuddy_bridge import WorkBuddyBridge  # noqa: E402

snapshot = EscalationLedger(ROOT / DEFAULT_LEDGER).snapshot()
adapter = EscalationQueueAdapter(root=ROOT, ledger=EscalationLedger(ROOT / DEFAULT_LEDGER))
policy = EscalationPolicy()

waiting = adapter.pending(snapshot=snapshot)
print("=== why the timebox reclaim will not fire ===")
print("  waiting (NEW/QUEUED) count :", len(waiting), [w.key[:44] for w in waiting])
print("  policy.job_timebox_minutes :", policy.job_timebox_minutes)
print("  policy.stuck_minutes       :", policy.stuck_minutes,
      "  <- that axis is 'gameplay with no verified episode', not 'job made no progress'")

print()
print("=== in flight ===")
now = datetime.datetime.now(datetime.timezone.utc)
for record in snapshot.records.values():
    if record.state in (SUBMITTED, WORKING):
        age = ((now - record.submitted_at).total_seconds() / 60
               if record.submitted_at else -1)
        print(f"  {record.key[:60]} state={record.state} job={record.job_id} age={age:.0f} min")

print()
print("  _reclaim_expired_slot() opens with:  if not waiting or record.submitted_at is None: return ''")
print("  waiting is empty  ->  the reclaim can never trigger  ->  a wedged job keeps the only slot")

print()
print("=== the signal that does exist, but nothing reads: the job's own progress clock ===")
status = WorkBuddyBridge().status("c743127e")
raw = status.raw
started_age = (time.time() * 1000 - int(raw["startedAt"])) / 1000
updated_age = (time.time() * 1000 - int(raw["updatedAt"])) / 1000
print(f"  startedAt age : {started_age / 60:.1f} min")
print(f"  updatedAt age : {updated_age / 60:.1f} min   <- frozen; only 6s after startedAt")
print(f"  tempo={raw.get('tempo')} state={raw.get('state')} alive={raw.get('alive')}")
print(f"  detail={str(raw.get('detail'))[:100]}")
print()
print("  A productive agent's updatedAt moves.  A wedged one's does not.")
print("  That is the discriminator the operator's rule needs and does not have.")
