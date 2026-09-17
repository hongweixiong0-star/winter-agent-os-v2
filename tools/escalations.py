"""Inspect and drive the escalation queue.

    python tools/escalations.py --state
    python tools/escalations.py --reconcile
    python tools/escalations.py --reload            # is a reload pending?
    python tools/escalations.py --reload-done       # clear the marker

The queue's state is a fold over ``learning/workbuddy_escalations.jsonl``, so this
command is read-only apart from two deliberate writes: reconciling (which appends
what it measured) and clearing the reload marker.  There is no other place that
holds escalation state, on purpose -- one ledger, one answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    EscalationLedger,
    EscalationPolicy,
    EscalationQueueAdapter,
    default_router,
)
from winter_agent_v2 import escalation_queue as q  # noqa: E402
from winter_agent_v2.runtime_reload import REQUEST_KIND, ReloadSignal, default_path as reload_path  # noqa: E402

EXIT_OK = 0
EXIT_PENDING = 1
EXIT_FAILED = 2


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def cmd_state(args: argparse.Namespace) -> int:
    ledger = EscalationLedger(args.ledger)
    snapshot = ledger.snapshot()
    if args.json:
        payload = {
            "counts": snapshot.count_by_state(),
            "records": {
                key: {
                    "state": r.state,
                    "capability": r.capability,
                    "failure_type": r.failure_type,
                    "skill": r.skill,
                    "condition": r.condition,
                    "attempts": r.attempts,
                    "repairs_used": r.repairs_used,
                    "outcome": r.outcome,
                    "job_id": r.job_id,
                    "model": r.model,
                    "escalated_from": r.escalated_from,
                    "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                    "settled_at": r.settled_at.isoformat() if r.settled_at else None,
                    "cooldown_until": r.cooldown_until.isoformat() if r.cooldown_until else None,
                    "code_changed": r.code_changed,
                    "notes": r.notes,
                }
                for key, r in sorted(snapshot.records.items())
            },
        }
        _emit(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK

    _emit("=" * 78)
    _emit("ESCALATION QUEUE")
    _emit("=" * 78)
    _emit(f"ledger       : {Path(args.ledger)}")
    _emit(f"events       : {len(ledger.events())}")
    counts = snapshot.count_by_state()
    _emit(f"by state     : {counts or '(empty)'}")
    _emit(f"active jobs  : {len(snapshot.active_jobs())}")
    _emit("")
    if not snapshot.records:
        _emit("(no escalations recorded yet)")
        return EXIT_OK

    header = f"{'state':9s} {'condition':22s} {'capability':26s} {'att':>3s} {'outcome':15s} {'model':20s} job"
    _emit(header)
    _emit("-" * len(header))
    for key, record in sorted(snapshot.records.items()):
        _emit(
            f"{record.state:9s} {record.condition[:22]:22s} {record.capability[:26]:26s} "
            f"{record.attempts:3d} {record.outcome[:15]:15s} {record.model[:20]:20s} "
            f"{record.job_id or '-'}"
        )
        if record.notes:
            for note in record.notes[-2:]:
                _emit(f"{'':9s}   {note[:110]}")
    _emit("")
    _emit(default_router(ROOT).report())
    return EXIT_OK


def cmd_reconcile(args: argparse.Namespace) -> int:
    adapter = EscalationQueueAdapter(
        root=ROOT, ledger=EscalationLedger(args.ledger), policy=EscalationPolicy()
    )
    settled, errors = adapter.reconcile()
    _emit(f"reconciled {len(settled)}: {list(settled) or '(none)'}")
    for error in errors:
        _emit(f"error: {error}")
    pending = adapter.reload_signal.pending()
    if pending is not None:
        _emit("")
        _emit(f"{REQUEST_KIND}: job {pending.job_id} -- {pending.reason}")
    return EXIT_FAILED if errors else EXIT_OK


def cmd_reload(args: argparse.Namespace) -> int:
    signal = ReloadSignal(reload_path(ROOT))
    pending = signal.pending()
    if pending is None:
        _emit(f"no {REQUEST_KIND} pending")
        return EXIT_OK
    deferral = signal.evaluate(active_jobs=0)
    _emit(f"{REQUEST_KIND}")
    _emit(f"  job         : {pending.job_id}")
    _emit(f"  reason      : {pending.reason}")
    _emit(f"  requested_at: {pending.requested_at.isoformat()}")
    _emit(f"  age         : {pending.age_seconds():.0f}s")
    _emit(f"  would defer : {bool(deferral)} -- {deferral.reason}")
    return EXIT_PENDING


def cmd_reload_done(args: argparse.Namespace) -> int:
    signal = ReloadSignal(reload_path(ROOT))
    _emit(f"cleared: {signal.clear('operator acknowledged')}")
    return EXIT_OK


def cmd_correct(args: argparse.Namespace) -> int:
    """Append a correcting ``reconciled`` event for one key.

    The ledger is append-only, so a wrong outcome is corrected by a later event
    rather than by rewriting history -- and the correction carries its reason, so
    the record shows both what was believed and why it changed.  Needed in
    practice: the first real escalation was recorded ``TEST_PASS`` on a tree diff
    that turned out to be the harness's own concurrent edit.
    """
    ledger = EscalationLedger(args.ledger)
    record = ledger.snapshot().get(args.correct)
    if record is None:
        _emit(f"no escalation with key {args.correct!r}")
        return EXIT_FAILED
    if not args.reason:
        _emit("--reason is required: a correction without its reason is just a second guess")
        return EXIT_FAILED
    ledger.append({
        "source": "queue",
        "event": "reconciled",
        "correction": True,
        "key": args.correct,
        "job_id": record.job_id,
        "job_state": q_state(record.state),
        "outcome": args.outcome or q.NO_IMPROVEMENT,
        "explanation": f"corrected by the operator: {args.reason}",
        # A correction does not spend a repair shot: it is not a new failure.
        "repair_used": False,
        "live_improvement": (args.outcome == q.LIVE_VERIFIED),
    })
    _emit(f"corrected {args.correct}: outcome -> {args.outcome or q.NO_IMPROVEMENT}")
    _emit(f"  was : {record.outcome or '(none)'}")
    _emit(f"  why : {args.reason}")
    return EXIT_OK


def q_state(state: str) -> str:
    """The job-state word that belongs with an escalation state."""
    return "FAILED" if state == "FAILED" else "DONE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", default=str(ROOT / "learning/workbuddy_escalations.jsonl"))
    parser.add_argument("--state", action="store_true", help="fold the ledger and print the queue")
    parser.add_argument("--reconcile", action="store_true", help="poll in-flight jobs and measure outcomes")
    parser.add_argument("--reload", action="store_true", help="report a pending RUNTIME_RELOAD_REQUIRED")
    parser.add_argument("--reload-done", action="store_true", help="clear the reload marker")
    parser.add_argument("--correct", metavar="KEY", help="append a correcting outcome for one key")
    parser.add_argument("--outcome", default="", help="the corrected outcome constant")
    parser.add_argument("--reason", default="", help="why the earlier outcome was wrong (required)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.reconcile:
        return cmd_reconcile(args)
    if args.reload:
        return cmd_reload(args)
    if args.reload_done:
        return cmd_reload_done(args)
    if args.correct:
        return cmd_correct(args)
    return cmd_state(args)


if __name__ == "__main__":
    raise SystemExit(main())
