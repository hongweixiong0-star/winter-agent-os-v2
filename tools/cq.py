"""Codex Commander Queue executor.

Codex writes `.workbuddy-ai/commander/WORK_QUEUE.json`; this tool is the
WorkBuddy side of that contract.  It exists so the queue is read from one
place, the dependency graph is resolved the same way every session, and the
result/state/blocked files have a single writer with a validated schema.

Subcommands
-----------
plan                 resolve the READY set and print execution order
start   <task_id>    mark a task IN_PROGRESS
finish  <task_id>    record a result JSON and mark the task DONE
block   <task_id>    append to BLOCKED_QUEUE.json and mark BLOCKED
state                show EXECUTION_STATE.json
init                 create results/ and EXECUTION_STATE.json

Design notes
------------
* A task is runnable only when ``status == "READY"`` *and* every id in
  ``dependencies`` has a finished result.  ``QUEUED`` and
  ``WAITING_FOR_NATURAL_STATE`` are deliberately not runnable -- the first is
  Codex holding it back, the second needs the live client to reach a state
  nobody may manufacture by spending resources.
* Ordering is ``priority`` ascending (P0 < P1 < P2) then the queue's own
  declaration order, which is the order Codex reasoned about.
* ``finish`` refuses to write a result that does not carry live evidence,
  because a queue that accepts prose is a queue that launders claims.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
CMD = ROOT / ".workbuddy-ai" / "commander"
QUEUE = CMD / "WORK_QUEUE.json"
RESULTS = CMD / "results"
STATE = CMD / "EXECUTION_STATE.json"
BLOCKED = CMD / "BLOCKED_QUEUE.json"

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Report shape the commander contract asks for, in its own words.
RESULT_FIELDS = (
    "TASK_ID",
    "ROOT_CAUSE",
    "CHANGED_FILES",
    "TEST_RESULT",
    "LIVE_ATTEMPTS",
    "LIVE_SUCCESS",
    "LIVE_FAILURE",
    "BEFORE",
    "AFTER",
    "VERIFIER_RESULT",
    "EVIDENCE",
    "PATCH_STATUS",
    "REMAINING_ISSUE",
    "NEXT_RECOMMENDATION",
)

SKIP_STATUSES = {
    "QUEUED": "held back by Codex (dependencies not all satisfied at generation time)",
    "WAITING_FOR_NATURAL_STATE": "needs a live state nobody may manufacture",
    "DONE": "already finished",
    "BLOCKED": "already blocked",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_queue() -> dict:
    if not QUEUE.exists():
        raise SystemExit("no WORK_QUEUE.json at %s" % QUEUE)
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"updated_at": None, "queue_generated_at": None, "current_task": None, "tasks": {}}


def save_state(state: dict) -> None:
    state["updated_at"] = now()
    CMD.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def result_path(task_id: str) -> pathlib.Path:
    return RESULTS / ("%s.json" % task_id)


def finished_ids(state: dict) -> set[str]:
    return {
        tid
        for tid, info in (state.get("tasks") or {}).items()
        if info.get("status") in ("DONE", "BLOCKED")
    }


def order_tasks(orders: list[dict]) -> list[dict]:
    indexed = list(enumerate(orders))
    indexed.sort(key=lambda pair: (PRIORITY_ORDER.get(str(pair[1].get("priority")), 9), pair[0]))
    return [item for _, item in indexed]


def resolve() -> tuple[list[dict], list[tuple[dict, str]]]:
    """Return (runnable, skipped-with-reason) for the current queue + state."""
    queue = load_queue()
    state = load_state()
    done = finished_ids(state)
    runnable: list[dict] = []
    skipped: list[tuple[dict, str]] = []

    for task in order_tasks(queue.get("orders") or []):
        tid = task.get("task_id")
        status = str(task.get("status") or "")
        info = (state.get("tasks") or {}).get(tid) or {}
        local = info.get("status")

        if local in ("DONE", "BLOCKED"):
            skipped.append((task, "already %s in EXECUTION_STATE" % local))
            continue
        if local == "IN_PROGRESS":
            skipped.append((task, "already IN_PROGRESS"))
            continue
        if status != "READY":
            skipped.append((task, SKIP_STATUSES.get(status, "status=%s is not READY" % status)))
            continue
        missing = [d for d in (task.get("dependencies") or []) if d not in done]
        if missing:
            skipped.append((task, "waiting on %s" % ", ".join(missing)))
            continue
        runnable.append(task)

    return runnable, skipped


def cmd_plan(_args: argparse.Namespace) -> int:
    runnable, skipped = resolve()
    state = load_state()
    print("QUEUE generated_at : %s" % load_queue().get("generated_at"))
    print("STATE updated_at   : %s" % state.get("updated_at"))
    print("current_task       : %s" % state.get("current_task"))
    print()
    print("RUNNABLE (%d) — in execution order:" % len(runnable))
    for i, task in enumerate(runnable, 1):
        print(
            "  %d. [%s] %-30s timebox=%smin"
            % (i, task.get("priority"), task.get("task_id"), task.get("timebox_minutes"))
        )
        print("       %s" % (task.get("objective") or "")[:150])
    print()
    print("SKIPPED (%d):" % len(skipped))
    for task, why in skipped:
        print("  [%s] %-30s %s" % (task.get("priority"), task.get("task_id"), why))
    return 0


def cmd_init(_args: argparse.Namespace) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    state = load_state()
    queue = load_queue()
    state["queue_generated_at"] = queue.get("generated_at")
    for task in queue.get("orders") or []:
        tid = task.get("task_id")
        state.setdefault("tasks", {}).setdefault(
            tid,
            {
                "status": "PENDING",
                "priority": task.get("priority"),
                "queue_status": task.get("status"),
                "result_file": None,
            },
        )
    save_state(state)
    print("initialised: results/ + EXECUTION_STATE.json (%d tasks)" % len(state["tasks"]))
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    state = load_state()
    info = state.setdefault("tasks", {}).setdefault(args.task_id, {})
    info["status"] = "IN_PROGRESS"
    info["started_at"] = now()
    state["current_task"] = args.task_id
    save_state(state)
    print("started %s" % args.task_id)
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    payload = json.loads(pathlib.Path(args.result).read_text(encoding="utf-8"))
    missing = [f for f in RESULT_FIELDS if f not in payload]
    if missing:
        print("REFUSED: result is missing required fields: %s" % ", ".join(missing))
        return 2

    live = payload.get("LIVE_EVIDENCE")
    if args.require_live and not live:
        print("REFUSED: PATCH_STATUS=%r claims completion without LIVE_EVIDENCE" % payload.get("PATCH_STATUS"))
        return 2

    RESULTS.mkdir(parents=True, exist_ok=True)
    dst = result_path(args.task_id)
    payload["TASK_ID"] = args.task_id
    payload["recorded_at"] = now()
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state = load_state()
    info = state.setdefault("tasks", {}).setdefault(args.task_id, {})
    info["status"] = "DONE"
    info["finished_at"] = now()
    info["result_file"] = str(dst.relative_to(CMD)).replace("\\", "/")
    info["verdict"] = payload.get("PATCH_STATUS")
    info["summary"] = str(payload.get("AFTER") or "")[:300]
    state["current_task"] = None
    save_state(state)
    print("finished %s -> %s" % (args.task_id, info["result_file"]))
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    payload = json.loads(pathlib.Path(args.result).read_text(encoding="utf-8"))
    blocked = json.loads(BLOCKED.read_text(encoding="utf-8")) if BLOCKED.exists() else {"items": []}
    blocked["updated_at"] = now()
    entry = {"task_id": args.task_id}
    for f in (
        "root_cause_found",
        "attempts",
        "changes_made",
        "evidence",
        "blocker",
        "recommended_codex_review",
    ):
        entry[f] = payload.get(f)
    blocked.setdefault("items", []).append(entry)
    BLOCKED.write_text(json.dumps(blocked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    RESULTS.mkdir(parents=True, exist_ok=True)
    result_path(args.task_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    state = load_state()
    info = state.setdefault("tasks", {}).setdefault(args.task_id, {})
    info["status"] = "BLOCKED"
    info["finished_at"] = now()
    info["verdict"] = "BLOCKED"
    info["blocker"] = payload.get("blocker")
    state["current_task"] = None
    save_state(state)
    print("blocked %s (appended to BLOCKED_QUEUE.json)" % args.task_id)
    return 0


def cmd_state(_args: argparse.Namespace) -> int:
    state = load_state()
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("plan").set_defaults(func=cmd_plan)
    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("state").set_defaults(func=cmd_state)

    p = sub.add_parser("start")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("finish")
    p.add_argument("task_id")
    p.add_argument("--result", required=True)
    p.add_argument("--require-live", action="store_true")
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("block")
    p.add_argument("task_id")
    p.add_argument("--result", required=True)
    p.set_defaults(func=cmd_block)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
