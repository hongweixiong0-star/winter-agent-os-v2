"""Move past attempts from the question's budget to the channel's, where the log proves it.

One-off audit, 2026-09-24.  ``unknown_dispatch`` records a ``failure_class`` on every reconcile
from now on, but the rows written before that vocabulary existed can only say ``failed / no answer
written``.  The conservative reading charges those to the question, and for most of them that is
right.  For some of them the proof is still on disk: the job's own log, written by the worker
process the gateway spawned.

This tool reads that log and nothing else.  When the log shows the worker died at start-up because
``bin/codebuddy`` could not resolve ``../dist/codebuddy`` -- the measured break of 2026-09-24, when
the shipped ``dist`` held only ``codebuddy-headless.js`` and ``codebuddy-lite-wb.mjs`` -- it appends
one ``reclassified`` row carrying the log path as evidence.  No log, no guess, no row.

Bounded and read-only apart from that append, and it never deletes a row: the ledger is append-only
by design, and a correction that erases its own cause is not a correction.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import unknown_dispatch  # noqa: E402

#: The proof, quoted from the job log.  Exact rather than fuzzy: this is the measured break, and a
#: loose match would let any module error anywhere in a log reclassify a real failure.
PROOF = "Cannot find module '../dist/codebuddy'"

#: Where the gateway keeps one log per job.  ``logPath`` in ``~/.codebuddy/jobs/<id>/state.json``
#: points here; the directory is derivable, which is what makes this auditable later.
DEFAULT_LOG_DIR = Path.home() / ".codebuddy" / "logs"


def _job_ids(dispatcher: unknown_dispatch.UnknownDispatcher) -> dict[str, list[str]]:
    """``request_id -> [job_id, ...]``, in ledger order, for requests without an answer."""
    out: dict[str, list[str]] = {}
    for row in dispatcher.rows():
        job_id = str(row.get("job_id") or "").strip()
        if row.get("event") == "submitted" and job_id:
            out.setdefault(str(row.get("request_id")), []).append(job_id)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--apply", action="store_true", help="append the corrections (default: report)")
    args = parser.parse_args()

    dispatcher = unknown_dispatch.UnknownDispatcher(root=ROOT)
    log_dir = Path(args.log_dir)
    answered = dispatcher.answered_ids()
    ledger_jobs = {job for jobs in _job_ids(dispatcher).values() for job in jobs}
    already = {
        (str(row.get("request_id")), str(row.get("job_id")))
        for row in dispatcher.rows() if row.get("event") == "reclassified"
    }

    corrections: list[tuple[str, str, Path]] = []
    for request in dispatcher.pending():
        if request.request_id in answered:
            continue
        for job_id in _job_ids(dispatcher).get(request.request_id, []):
            if (request.request_id, job_id) in already:
                continue
            log = log_dir / f"job-{job_id}.log"
            try:
                text = log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if PROOF in text:
                corrections.append((request.request_id, job_id, log))

    print(f"pending requests : {len(dispatcher.pending())}")
    print(f"jobs in the ledger: {len(ledger_jobs)}")
    print(f"log dir          : {log_dir}")
    if not corrections:
        print("no attempt can be reclassified from a job log that proves the worker never started")
        return 0

    for request_id, job_id, log in corrections:
        print(f"  {request_id:34} job {job_id}  <- {log.name}")
    if not args.apply:
        print("(report only; pass --apply to append the corrections)")
        return 0

    for request_id, job_id, log in corrections:
        dispatcher._append({
            "event": "reclassified",
            "request_id": request_id,
            "job_id": job_id,
            "failure_class": unknown_dispatch.FAILURE_WORKER_DIED,
            "evidence": str(log),
            "note": ("作业 worker 进程启动即崩溃（日志明确记录 " + PROOF + "）："
                     "该次尝试不属于问题本身，改由作答通道的预算承担"),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"reclassified {request_id} / {job_id}")

    after = unknown_dispatch.UnknownDispatcher(root=ROOT)
    state = after.state()
    print(f"health           : {state['health']} "
          f"(consecutive worker deaths {state['consecutive_worker_deaths']})")
    for item in state["budgets"].items():
        print(f"  budget {item[0]:34} {json.dumps(item[1], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
