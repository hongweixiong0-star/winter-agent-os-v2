"""Stop and start the control panel at a safe point, by pid.

Why this exists
---------------
The panel has to be restarted to pick up panel-side code (the worker imports the
package fresh each cycle, so AUTO does not need it).  Doing that by hand is how
this went wrong on 2026-09-18: a process filter of ``control_panel|run_live``
matched far more than the panel -- it also matched the WorkBuddy desktop app, its
agent node processes and the shell running the command, because the workspace path
and ``tools/control_panel.py`` appear in *their* command lines too.  The kill took
out the development host along with the window.

So: no pattern matching over the process table, ever.  The panel writes its own pid
where this tool can read it, and this tool kills exactly that pid's tree.

Two more rules the incident made obvious:

* a restart waits for a safe point.  ``run_live.py`` drives the game, and killing
  the panel kills its child, so a restart during a run truncates an atomic action.
  The runtime snapshot is the project's own answer to "is a run in flight"; it is
  read here rather than re-derived, and a stale snapshot is not trusted.
* the gateway password comes from the user environment, which is where the
  operator put it.  The panel is launched with it, never with a copy of it on a
  command line or in a file this tool writes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The one place the operator's intent is persisted.  Read (never written) by the gateway
#: re-check below so a launcher cannot start work the operator has stopped.
PANEL_STATE = ROOT / "config/control_panel_state.json"
# Run as a script from ``tools/``, so the repo root has to be importable before any
# helper can reach the package.  Measured 2026-09-18: without this, routing the process
# helpers through ``winter_agent_v2.winproc`` made ``--status`` die with
# ``ModuleNotFoundError: No module named 'winter_agent_v2'`` -- a fix that broke the tool
# it was meant to protect.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PANEL_SCRIPT = ROOT / "tools/control_panel.py"
PID_PATH = ROOT / "learning/control_panel/panel.pid"
PEEK_LOG = ROOT / "learning/control_panel/panel_launch.log"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
VENV_PYTHONW = Path(r"E:\dongri-mumu-bot\.venv\Scripts\pythonw.exe")
GATEWAY_PASSWORD_ENV = "CODEBUDDY_GATEWAY_PASSWORD"

# A snapshot older than this says nothing about now, so it must not be used to
# decide that no run is in flight.
SNAPSHOT_FRESH_SECONDS = 90.0


def _emit(message: str) -> None:
    print(message, flush=True)


def user_env(name: str) -> str:
    """The user's persisted environment variable, then the process's own."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            if value:
                return str(value)
    except Exception:  # noqa: BLE001 - missing key, missing module, locked hive
        pass
    return os.environ.get(name, "")


def read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def alive(pid: int) -> bool:
    """Is this a live python process?  Queried by pid, never by matching the table.

    Checked by asking about that one pid so a recycled pid cannot be mistaken for
    the panel, and so the query cannot match the agent host the way a pattern over
    the whole table did on 2026-09-18.
    """
    if pid <= 0:
        return False
    # Through the one runner: a bare console call from a pythonw parent flashes a window,
    # and this one is called from the panel's own startup path (the one-clock check).
    from winter_agent_v2 import winproc

    return winproc.alive(pid)


def pump_process() -> tuple[int, float]:
    """``(pid, age_seconds)`` from the pump's own heartbeat, or ``(0, inf)``.

    The panel's ``pythonw.exe`` is a venv stub: it spawns the real interpreter and
    exits, so the pid this tool recorded is dead within a second of a successful
    start.  Measured 2026-09-18: the stub was gone while the real panel (its child)
    was writing pump.json every thirty seconds.  The heartbeat is therefore the
    authoritative liveness signal, and it is read rather than guessed.
    """
    try:
        payload = json.loads((ROOT / "learning/control_panel/pump.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, float("inf")
    try:
        written = datetime.fromisoformat(str(payload.get("written_at")))
    except ValueError:
        return 0, float("inf")
    if written.tzinfo is None:
        written = written.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - written).total_seconds()
    return int(payload.get("process") or 0), age


def live_pids() -> list[int]:
    """Every pid that is plausibly this panel's, stub and real."""
    found: list[int] = []
    recorded = read_pid()
    if recorded is not None and alive(recorded):
        found.append(recorded)
    heartbeat, age = pump_process()
    if heartbeat and age <= SNAPSHOT_FRESH_SECONDS and alive(heartbeat) and heartbeat not in found:
        found.append(heartbeat)
    return found


def current_worker(pid: int | None = None) -> list[str]:
    """Command lines of any ``run_live.py`` process, for the safe-point report."""
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process |"
        # The PowerShell query's own command line contains this literal, so without
        # the name filter the tool reports itself as a worker -- measured
        # 2026-09-18, right after the same class of mistake cost a host process.
        " Where-Object { $_.Name -notmatch 'powershell|pwsh' -and $_.CommandLine -like '*run_live*py*' } |"
        " ForEach-Object { \"$($_.ProcessId)|$($_.ParentProcessId)|$($_.CommandLine)\" }"
    )
    from winter_agent_v2 import winproc

    done = winproc.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=40,
    )
    rows = [line for line in (done.stdout or "").splitlines() if line.strip()]
    if pid is None:
        return rows
    # A worker the panel owns: its parent is the panel, or the panel's venv stub.
    return [row for row in rows if str(pid) in row.split("|")[:2]]


def runtime_observation() -> str:
    """What the runtime snapshot says -- including "too stale to judge".

    For *display*.  Deliberately separate from :func:`runtime_claim`, because a stale
    snapshot is not evidence of a run: it is the absence of evidence, and an earlier
    version conflated the two and refused to stop whenever AUTO had been idle long
    enough for the snapshot to age out -- i.e. exactly when stopping is safest.
    """
    try:
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    stamp = str(snapshot.get("updated_at") or "")
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - when).total_seconds()
    if age > SNAPSHOT_FRESH_SECONDS:
        return f"snapshot is {age:.0f}s old, too stale to judge"
    state = str(snapshot.get("agent_state") or "")
    return (f"{state} · skill={snapshot.get('current_skill')} · goal={snapshot.get('current_goal')}"
            f" · updated {age:.0f}s ago") if state else ""


def runtime_claim() -> str:
    """A *positive* claim that a round is running.  Empty means "no evidence of one".

    Derived from the enum, not from a remembered list of state names.  The first version
    hardcoded ``("GOAL_RUNNING", "RECOVERING")`` and therefore reported "no claim" while
    the device was mid-round in ``AUTO_RUNNING`` -- two of the eight states.  A guard that
    under-reports is worse than no guard: it is the one that says "safe to stop".
    """
    observation = runtime_observation()
    if not observation or observation.startswith("snapshot is"):
        return ""
    # This tool is deliberately dependency-free (it has to run when the project's own
    # imports are what is broken), so the package is located at call time.
    import sys as _sys

    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    from winter_agent_v2.runtime_snapshot import AgentState

    # States in which nothing of ours is mid-transaction.  Everything else is a claim.
    idle = {AgentState.IDLE.value, AgentState.SAFE_STOP.value,
            AgentState.FATAL_STOPPED.value, AgentState.PAUSED.value}
    state = observation.split(" · ")[0]
    if state in idle or state not in {member.value for member in AgentState}:
        return ""
    try:
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if snapshot.get("runtime_thread_alive"):
        return observation
    return ""


def cmd_status() -> int:
    recorded = read_pid()
    heartbeat, age = pump_process()
    pids = live_pids()
    _emit(f"pid file    : {PID_PATH}")
    _emit(f"recorded pid: {recorded if recorded else '(none)'}"
          + (f"  alive={alive(recorded)}" if recorded else ""))
    _emit(f"pump process: {heartbeat or '(none)'}"
          f"  heartbeat age={age:.0f}s" if heartbeat else "pump process: (no heartbeat)")
    _emit(f"panel alive : {bool(pids)}" + (f"  pids={pids}" if pids else ""))
    claim = runtime_claim()
    _emit(f"runtime     : {claim or runtime_observation() or 'no run in flight'}")
    if not claim:
        _emit("              (no claim: stopping is safe, whatever the snapshot age)")
    workers = current_worker()
    _emit(f"workers     : {len(workers)}")
    for row in workers:
        _emit(f"    {row[:150]}")
    return 0


def cmd_stop(force: bool = False) -> int:
    pids = live_pids()
    if not pids:
        _emit("nothing to stop: no live panel pid on record and no fresh heartbeat")
        PID_PATH.unlink(missing_ok=True)
        return 0
    workers = current_worker()
    claim = runtime_claim()
    if (workers or claim) and not force:
        _emit("refusing to stop: a run is in flight, and killing the panel kills its worker")
        for row in workers:
            _emit(f"    worker {row[:140]}")
        if claim:
            _emit(f"    snapshot {claim}")
        _emit("        wait for the cycle to end, or pass --force to accept the truncation")
        return 1
    stale = runtime_observation()
    if stale and not claim:
        _emit(f"    snapshot {stale} -- not a claim, proceeding")
    for pid in pids:
        _emit(f"stopping panel tree at pid {pid}"
              + (" (forced during a run)" if (workers or claim) else ""))
        from winter_agent_v2 import winproc

        done = winproc.run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=60)
        _emit((done.stdout or "").strip() or (done.stderr or "").strip())
    time.sleep(2)
    left = current_worker()
    _emit(f"workers left after the kill: {len(left)}")
    still = live_pids()
    _emit(f"panel pids still alive: {still if still else 'none'}")
    PID_PATH.unlink(missing_ok=True)
    _ensure_gateway_after_stop()
    return 0 if not still else 1


def _ensure_gateway_after_stop() -> None:
    """Bring the gateway back if stopping the window took it down with it.

    The gateway is a **service**, not a child of the window (operator §24): it is started
    detached precisely so it outlives the window, and a window restart must not become a
    gateway outage.  Measured 2026-09-18 evening: it did.  ``taskkill /PID <panel> /T`` follows
    *parentage*, and ``DETACHED_PROCESS`` does not change parentage -- so the tree kill that
    stops the window also killed a perfectly healthy gateway, and the next window would have
    shown 工作Buddy 异常 until it started one again.  A failed start (which is exactly what
    happened on the development host) then leaves no gateway at all.

    Re-ensured through the one lifecycle owner rather than spawned here: two places that can
    start a gateway is how two gateways happen, and ``GatewayService`` already knows how to
    reuse a healthy one, refuse a port conflict and respect an operator STOP -- none of which
    this launcher has any business deciding for itself.
    """
    try:
        from winter_agent_v2.gateway_service import GatewayService

        service = GatewayService(ROOT)
        record = service.ensure(operator_intent=_operator_intent())
        if record.get("spawned"):
            _emit(f"gateway restarted after the stop (pid {record.get('pid')}) -- "
                  f"it is a service and must not die with the window")
        else:
            _emit(f"gateway left as it is ({record.get('state')}): {record.get('detail')}")
    except Exception as exc:  # noqa: BLE001 - the device must not be left unattended over this
        _emit(f"gateway re-check failed: {type(exc).__name__}: {exc}")


def _operator_intent() -> str:
    """The persisted operator intent, read without importing the window.

    Importing ``tools/control_panel.py`` for one string would pull in Tk and PIL, and this
    launcher runs before the window exists.  An unreadable state file reads as STOPPED: the
    safe answer to "we do not know what the operator asked for" is the passive one, and the
    cost of guessing wrong here is starting a developer nobody asked for.
    """
    try:
        return str(json.loads(PANEL_STATE.read_text(encoding="utf-8"))
                   .get("operator_intent") or "STOPPED").upper()
    except Exception:  # noqa: BLE001
        return "STOPPED"


def cmd_start(verify_seconds: float = 6.0) -> int:
    existing = read_pid()
    if existing is not None and alive(existing):
        _emit(f"already running at pid {existing}; stop it first")
        return 1
    if not VENV_PYTHONW.exists():
        _emit(f"the production interpreter is missing: {VENV_PYTHONW}")
        return 1
    env = dict(os.environ)
    password = user_env(GATEWAY_PASSWORD_ENV)
    env[GATEWAY_PASSWORD_ENV] = password
    PEEK_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(PEEK_LOG, "a", encoding="utf-8")
    _emit(f"starting {VENV_PYTHONW.name} {PANEL_SCRIPT.name}"
          f" (gateway credential: {'from the user environment' if password else 'ABSENT'})")
    from winter_agent_v2 import winproc

    log.close()
    process = winproc.spawn_detached(
        [str(VENV_PYTHONW), str(PANEL_SCRIPT)], cwd=str(ROOT), env=env, log_path=PEEK_LOG,
    )
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(process.pid), encoding="utf-8")
    _emit(f"launched pid {process.pid}; waiting {verify_seconds:.0f}s to see whether it survives")
    time.sleep(verify_seconds)
    if live_pids() or alive(process.pid):
        _emit("panel is up (the panel rewrites this file with the pid that is really running)")
        return 0
    _emit("")
    _emit("the panel did not survive the launch.  This host reclaims a detached child's")
    _emit("whole process tree when the calling process finishes its turn -- measured")
    _emit("2026-09-18: the window wrote pump.json once at +19s and was gone by +25s, with")
    _emit("no crash and no log line.  A launcher cannot outlive that, so start the panel")
    _emit("from a long-lived task instead:")
    _emit(f"    {VENV_PYTHONW} {PANEL_SCRIPT}")
    _emit("and use this tool for --status and --stop.")
    PID_PATH.unlink(missing_ok=True)
    return 1


def cmd_restart(force: bool = False) -> int:
    stopped = cmd_stop(force=force)
    if stopped != 0:
        return stopped
    return cmd_start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stop/start the Winter Agent OS V2 panel by pid")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="report the recorded pid and any run in flight")
    group.add_argument("--stop", action="store_true", help="stop the panel tree at a safe point")
    group.add_argument("--start", action="store_true", help="start the panel and record its pid")
    group.add_argument("--restart", action="store_true", help="stop then start")
    parser.add_argument("--force", action="store_true", help="stop even if a run is in flight")
    args = parser.parse_args(argv)

    if args.status:
        return cmd_status()
    if args.stop:
        return cmd_stop(force=args.force)
    if args.start:
        return cmd_start()
    if args.restart:
        return cmd_restart(force=args.force)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
