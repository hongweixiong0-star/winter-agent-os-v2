"""Live acceptance for the gateway's lifecycle: real process, real port, real restart.

Not a unit test.  Every seam is the production one -- the real CLI, the real port, the real
health endpoint -- because the three defects this工单 has already produced were all things a
stubbed test agreed with:

* the first live launch reported a live ``node.exe`` as a dead pid (the liveness check looked
  for the panel's interpreter name);
* the gateway announced its effective password on stdout, into a file inside the tree;
* a liveness question answered "gone" for a process that was holding the port.

Run it while ``tools/console_window_watch.py`` watches this pid to also cover §二十二.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2 import winproc  # noqa: E402
from winter_agent_v2.gateway_service import GatewayService  # noqa: E402

ROOT = Path(r"E:\无尽冬日智能体")
# The harness's own record, so the run never rewrites the window's production truth.  Reset
# by *writing* an empty record rather than deleting a file: a delete here tripped the
# repository's safe-delete guard (a bulk-delete confirmation the harness has no business
# answering), and an empty record is equivalent for the question §二 asks.
STATE = ROOT / "learning/control_panel/gateway_service_proof.json"
LEDGER = ROOT / "learning/workbuddy_escalations.jsonl"
OUT = ROOT / "learning/control_panel/live_gateway_proof.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ledger_rows() -> int:
    try:
        return len([ln for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()])
    except Exception:
        return -1


def listeners() -> list[tuple[int, str]]:
    """Every pid holding 8080.  More than one is the failure §五 names."""
    result = winproc.run(["netstat", "-ano"])
    found = []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and "LISTEN" in line.upper() and parts[1].endswith(":8080"):
            try:
                found.append((int(parts[-1]), ""))
            except ValueError:
                continue
    return found


def snapshot(service: GatewayService) -> dict:
    record = service.record()
    pid = int(record.get("pid") or 0)
    health, reason = service._probe_bridge()
    return {
        "at": now(),
        "state": record.get("state"),
        "action": record.get("action"),
        "pid": pid,
        "pid_name": winproc.process_name(pid) if pid else "",
        "pid_exists": winproc.pid_exists(pid) if pid else False,
        "failures": record.get("consecutive_failures"),
        "restart_attempts": record.get("restart_attempts"),
        "health": health,
        "health_reason": reason,
        "listeners": listeners(),
    }


def wait_health(service: GatewayService, *, seconds: float = 90.0) -> dict:
    deadline = time.time() + seconds
    last = snapshot(service)
    while time.time() < deadline:
        if last["health"] is True:
            return last
        time.sleep(3)
        last = snapshot(service)
    return last


def main() -> int:
    steps: list[dict] = []
    # Self-identify and pause, so ``console_window_watch`` can attach to *this* pid before
    # anything is spawned.  Without it the first launch happens in the ~1 s between the
    # shell starting this process and a watcher being pointed at it, and §二十二 would be
    # measured over a window that contains no launch at all.
    PID_FILE = ROOT / "learning/control_panel/gateway_acceptance.pid"
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    delay = float(os.environ.get("WINTER_AGENT_ACCEPT_DELAY", "0") or 0)
    if delay:
        print(f"pid {os.getpid()} ready; holding {delay:.0f}s for the window watcher", flush=True)
        time.sleep(delay)

    service = GatewayService(ROOT, state_path=STATE)

    # -- 0. precondition: a known starting point ---------------------------------------
    # The first version of this harness assumed a clean slate and then failed phases A and
    # B, because the state record survived from the previous run: the lifecycle owner
    # correctly took the *recovery* path for a pid it had launched and found dead, while the
    # harness was waiting for the *first-ever* path.  The product was right and the harness
    # was wrong, which is worth writing down: an acceptance run that does not establish its
    # precondition measures whatever the last run left behind.
    #
    # §二 is "nothing exists, so start one".  To put that branch under test rather than §三's
    # reuse branch, the port must actually be free first.  A node.exe holding it is this
    # project's gateway and is stopped; anything else is a port conflict and the run stops
    # rather than killing a stranger's process.
    stopped_pid = 0
    blocked = ""
    for pid, _ in listeners():
        name = winproc.process_name(pid)
        if "node" in name.lower():
            winproc.kill_tree(pid)
            stopped_pid = pid
            time.sleep(2)
        else:
            blocked = f"{name or 'unknown'} (pid {pid}) holds 8080"
    if blocked:
        steps.append({"step": "0_precondition", "blocked": blocked})
        OUT.write_text(json.dumps(steps, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"A_auto_start": False, "blocked": blocked}, ensure_ascii=False))
        return 2

    # An empty record, not a deleted file.
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text("{}", encoding="utf-8")
    service = GatewayService(ROOT, state_path=STATE)
    ledger_before = ledger_rows()
    steps.append({"step": "0_start", "stopped_pid": stopped_pid,
                  "listeners_now": listeners(), "ledger_rows": ledger_before,
                  **snapshot(service)})

    # -- A. §二/§三: nothing listening -> one gateway, started by the lifecycle owner ----
    first = service.ensure(operator_intent="RUNNING")
    steps.append({"step": "A_ensure", "action": first.get("action"),
                  "state": first.get("state"), "pid": first.get("pid"),
                  "detail": first.get("detail")})
    a = wait_health(service)
    steps.append({"step": "A_health", **a})
    pid_a = int(a.get("pid") or 0)
    started_by_us = first.get("action") == "START"

    # -- B. §五: a second pass must reuse, never start a second instance ----------------
    second = service.ensure(operator_intent="RUNNING")
    steps.append({"step": "B_reuse", "action": second.get("action"),
                  "state": second.get("state"), "pid": second.get("pid"),
                  "listeners": listeners(), "detail": second.get("detail")})

    # -- C. §二十七: kill it, and the ladder must bring back exactly one -----------------
    killed = winproc.kill_tree(pid_a) if pid_a else False
    time.sleep(2)
    steps.append({"step": "C_killed", "killed": killed, "target_pid": pid_a,
                  **snapshot(service)})
    ladder: list[dict] = []
    restarted_pid = 0
    for _ in range(8):
        rec = service.ensure(operator_intent="RUNNING")
        ladder.append({"action": rec.get("action"), "state": rec.get("state"),
                       "pid": rec.get("pid"), "failures": rec.get("consecutive_failures"),
                       "detail": rec.get("detail")})
        if rec.get("action") == "RESTART":
            restarted_pid = int(rec.get("pid") or 0)
            break
        time.sleep(1)
    steps.append({"step": "C_ladder", "steps": ladder, "restarted_pid": restarted_pid})
    c = wait_health(service)
    steps.append({"step": "C_recovered", **c})

    # -- D. §二十五: STOP must not spawn, and must not disturb a healthy gateway ---------
    stop = service.ensure(operator_intent="STOPPED")
    steps.append({"step": "D_stop", "action": stop.get("action"), "state": stop.get("state"),
                  "pid": stop.get("pid"), "detail": stop.get("detail")})

    # -- E. §七 / P: none of this may have created a ledger row -------------------------
    ledger_after = ledger_rows()
    steps.append({"step": "E_ledger", "before": ledger_before, "after": ledger_after,
                  "unchanged": ledger_before == ledger_after})

    final = snapshot(service)
    steps.append({"step": "F_final", **final})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(steps, ensure_ascii=False, indent=1), encoding="utf-8")

    # -- verdicts ----------------------------------------------------------------------
    verdict = {
        "A_auto_start": started_by_us and bool(pid_a) and a.get("health") is True,
        "B_single_instance": second.get("action") == "REUSE" and len(listeners()) == 1,
        "C_crash_recovery": bool(restarted_pid) and restarted_pid != pid_a
                            and c.get("health") is True
                            and len(c.get("listeners") or []) == 1,
        "D_stop_respected": stop.get("action") == "PASSIVE",
        "E_no_duplicate_ledger_rows": ledger_before == ledger_after,
        "F_pid_is_a_live_process": final.get("pid_exists") is True,
        "pid_before": pid_a,
        "pid_after": restarted_pid,
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    print(f"\nwrote {OUT}")
    failed = [k for k, v in verdict.items() if isinstance(v, bool) and not v]
    print("FAILED CHECKS:", failed or "none")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
