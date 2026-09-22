"""Answer the AUTO's UNKNOWN questions without a person in the loop.

    python tools/unknown_ai_worker.py --state        what is pending, what is in flight
    python tools/unknown_ai_worker.py --dry-run       exactly what would be submitted, prompt and all
    python tools/unknown_ai_worker.py --once          reconcile open jobs, then submit what is owed
    python tools/unknown_ai_worker.py --loop          the same pass, forever (for a bare console)

Why this exists
---------------
``unknown_advisor`` is the runtime's half of the channel: it writes a question and reads an answer
if one is there, and it cannot wait.  The answering half used to be a person running
``tools/unknown_advisor.py --list / --show / --answer``, which is manual work and not automatic AI
reasoning however it is described.  This tool is the consumer instead: it takes each pending question
and dispatches one **background agent job** through the project's own gateway bridge, whose task is
to look at the screenshot and write the answer file.  The AUTO keeps playing while that happens.

The panel runs the same pass on its own clock (``tools/control_panel.py``, the thread that already
pumps the escalation queue), so a running AUTO needs nobody to type anything.  This tool is for
watching it, for running it once by hand, and for driving the channel from a bare console where the
panel is not up.

What it will not do
-------------------
It does not answer anything itself, and it does not relax any bound: one job per question, at most
``MAX_IN_FLIGHT`` at a time, at most two attempts per question, and a cooldown between attempts.
``--dry-run`` prints the exact prompt and submits nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.unknown_dispatch import UnknownDispatcher  # noqa: E402


def _print_state(dispatcher: UnknownDispatcher) -> int:
    state = dispatcher.state()
    print(f"gateway     : {'up' if state['gateway'] else 'unreachable'}")
    print(f"pending     : {state['pending']}")
    print(f"answered    : {state['answered']}")
    print(f"in flight   : {state['in_flight'] or '(none)'}")
    if state["attempts"]:
        print(f"attempts    : {json.dumps(state['attempts'], ensure_ascii=False)}")
    print(f"ledger      : {dispatcher.ledger_path.as_posix()}")
    pending = dispatcher.pending()
    if pending:
        print()
        print("waiting on an answer:")
        for request in pending:
            record = dispatcher.records().get(request.request_id)
            where = f"job {record.job_id} ({record.state})" if record and record.open else "no job"
            print(f"  {request.request_id:34} {request.page_key[:28]:28} goal={request.goal[:20]:20} {where}")
    candidates = dispatcher.candidates()
    if candidates:
        print()
        print("would be submitted now:")
        for request, reason in candidates:
            print(f"  {request.request_id:34} {reason}")
    return 0


def _print_dry_run(dispatcher: UnknownDispatcher, limit: int) -> int:
    report = dispatcher.dispatch(limit=limit, dry_run=True)
    if not report["submitted"]:
        print("nothing to submit: every question already has an answer or a job")
        return 0
    for item in report["submitted"]:
        print("=" * 78)
        print(f"request : {item['request_id']}")
        print(f"why     : {item['reason']}")
        print(f"model   : {item['model'] or '(router had no opinion)'}")
        print("-" * 78)
        print(item["prompt"])
    print("=" * 78)
    print("(dry run: nothing was submitted)")
    return 0


def _once(dispatcher: UnknownDispatcher) -> int:
    result = dispatcher.worker()
    reconcile = result.get("reconcile") or {}
    dispatch = result.get("dispatch") or {}
    if result.get("lock"):
        # A pass that did nothing because someone else was doing it must say so: measured during the
        # first working session, a leaked lock made two passes print "nothing to do" while two open
        # jobs waited to be reconciled -- the quietest possible way for a channel to stop.
        print(f"skipped     : {result['lock']}")
        return 0
    print(
        "reconciled  : "
        f"checked={reconcile.get('checked', 0)} done={reconcile.get('done', 0)} "
        f"failed={reconcile.get('failed', 0)} lost={reconcile.get('lost', 0)}"
    )
    for error in list(reconcile.get("errors") or []) + list(dispatch.get("errors") or []):
        print(f"  error     : {error}")
    submitted = dispatch.get("submitted") or []
    print(f"submitted   : {len(submitted)}")
    for item in submitted:
        print(f"  {item['request_id']:34} job={item.get('job_id', '')} model={item.get('model', '')}")
    for item in dispatch.get("skipped") or []:
        print(f"  skipped     : {item['request_id']} ({item['reason']})")
    if not submitted and not (reconcile.get("checked") or 0):
        print("nothing to do")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="dispatch answering jobs for the AUTO's UNKNOWN questions")
    parser.add_argument("--state", action="store_true", help="what is pending / in flight")
    parser.add_argument("--dry-run", action="store_true", help="print the job prompt, submit nothing")
    parser.add_argument("--once", action="store_true", help="one pass: reconcile, then submit what is owed")
    parser.add_argument("--loop", action="store_true", help="the same pass on a timer, forever")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between --loop passes")
    parser.add_argument("--limit", type=int, default=1, help="how many questions one pass may submit")
    parser.add_argument("--root", default="", help="project root (default: this repository)")
    args = parser.parse_args()

    dispatcher = UnknownDispatcher(root=args.root or None)

    if args.state or not (args.dry_run or args.once or args.loop):
        return _print_state(dispatcher)
    if args.dry_run:
        return _print_dry_run(dispatcher, args.limit)
    if args.once:
        return _once(dispatcher)
    while True:
        _once(dispatcher)
        print(f"-- sleeping {args.interval:.0f}s --", flush=True)
        time.sleep(max(5.0, float(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
