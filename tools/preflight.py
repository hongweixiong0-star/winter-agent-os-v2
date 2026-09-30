"""Preflight: can the interpreter that is about to run production actually do it?

Run this before trusting a run's numbers.

    python tools/preflight.py
    python tools/preflight.py --json
    python tools/preflight.py --launch-gate   (what the desktop launcher asks)

Exit code is 0 only when the resolved interpreter can import every module the
production loop depends on *and* -- unless MAA is switched off in
``config/v2.json`` -- MAA is among them, and no core section is in a state the
runtime cannot repair.

There are two questions here and one exit code cannot carry both, so there are
two verdicts and ``--launch-gate`` picks the other one:

    may AUTO run?      interpreter AND a usable-or-repairable device   (default)
    may the window open?  interpreter only                             (--launch-gate)

The second is the desktop entry's gate.  A device that is down is *recoverable*
by ``control_panel._ensure_device`` and by the retry loop around it, so refusing
to open the window on it removes the only path that turns the device back on --
which is what happened on 2026-10-01.  A wrong interpreter is not recoverable
from inside the process, which is the failure this file was written for on
2026-09-17.

Why a command and not a paragraph: on 2026-09-17 the desktop launcher pinned a
generic Codex runtime python that ships numpy/PIL and nothing else, and the
control panel spawned its worker with its own interpreter, so the worker ran
with ``MAA_IMPORT_FAILED:ModuleNotFoundError`` and stayed on ADB.  No executed
step in those runs belonged to a skill promoted to MAA, so nothing had been
measured through the slow path yet -- but a promoted skill would have taken ADB
capture at 324 ms instead of MAA EmulatorExtras' 8.92 ms, and the run would have
looked healthy.  The only trace was one line inside a worker's piped stdout.

So this prints both halves of the question: what the interpreter *can* do, and
what the ledger says it *has been* doing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import runtime_env  # noqa: E402
from winter_agent_v2 import winproc  # noqa: E402

LEDGER = ROOT / "learning/executor_backend.jsonl"
CONFIG = ROOT / "config/v2.json"

# What AUTO may not start without: the interpreter's modules and a device that
# really answers.  The WorkBuddy gateway is deliberately *not* here -- a gateway
# outage is an automatic-development outage, not a reason to stop playing (the
# operator's rule of 2026-09-17: "WorkBuddy Gateway异常不得阻止游戏AUTO").
CORE_SECTIONS = ("interpreter", "device")
AUX_SECTIONS = ("gateway",)

#: A section a failing *core* check may still be recoverable from, and who recovers it.
#:
#: ``device`` is here on a measurement rather than a judgement.
#: ``tools/control_panel.py``'s ``_ensure_device`` launches a stopped emulator
#: (``MUMU_PATH``) and foregrounds the game (``self.device.launch(package)``), and
#: ``_run_unified_worker`` already wraps that whole call in
#: ``retry_until_ready(..., initial_delay_seconds=5.0, max_delay_seconds=60.0)``
#: with ``DEVICE_NOT_CONNECTED`` / ``DEVICE_CONNECT_TIMEOUT`` / ``MUMU_LAUNCH_FAILED``
#: / ``MUMU_LAUNCHER_NOT_FOUND`` all present in ``ENVIRONMENT_FAILURES``.  The
#: recovery loop exists, is bounded, is recorded (``DEVICE_RECOVERY_RETRY`` /
#: ``_record_device_recovered``), and is the project's own answer to
#: "环境异常自动恢复".
#:
#: So refusing AUTO because the device is down does not protect anything -- it
#: removes the only path that turns the device back on.  Measured 2026-10-01
#: 07:26: the emulator was up but parked on the Android launcher with
#: ``com.gof.china`` not running, which is exactly the state ``_ensure_device``
#: repairs.  Preflight read it as a core blocker, ``Start-Winter-Agent-V2.cmd``
#: refused to open the window on it, AUTO was never started, ``_ensure_device``
#: was therefore never reached, and each retry re-ran the same check.  The
#: condition could not converge by construction.
#:
#: The two device failures that are *not* recoverable are the two the runtime
#: cannot act on: a missing ``adb`` binary and a wrong configured resolution.
#: Both are host configuration, both are reported as blockers, and neither is
#: reachable by ``_ensure_device``.
REPAIRABLE_SECTIONS = ("device",)

#: What the *window* may not open without.  The interpreter is the whole list.
#:
#: The panel and the worker it spawns both inherit the interpreter, so nothing
#: inside the process can change it, and on 2026-09-17 exactly this was the
#: failure that looked healthy for a whole session: ``MAA_IMPORT_FAILED``, every
#: skill promoted to MAA quietly on ADB at 324 ms against MAA's 8.92 ms.  That is
#: the rule this gate keeps, and it is the rule the docstring above already
#: stated ("Exit code is 0 only when the resolved interpreter can import every
#: module the production loop depends on").
#:
#: It is a *separate* question from "may AUTO run", which is why it is a separate
#: list.  Folding the device into the launch gate -- which is what happened when
#: this file grew a device section on 2026-09-18 while ``Start-Winter-Agent-V2.cmd``
#: kept reading one exit code -- makes the window unable to open in the one
#: situation where the window is the fix.
LAUNCH_GATE_SECTIONS = ("interpreter",)

#: Which action repairs a device that is not ready.
DEVICE_REPAIRS = {
    "EMULATOR_DOWN": "LAUNCH_EMULATOR",
    "GAME_NOT_FOREGROUND": "LAUNCH_GAME",
}


def ledger_summary(limit: int = 200) -> dict[str, object]:
    """What the executor ledger says production has actually been using.

    Reads only; the ledger is append-only production evidence and is never
    rewritten.  ``used_backend`` is the axis that matters: it is what the step
    really did, not what was preferred.
    """
    if not LEDGER.is_file():
        return {"rows": 0, "note": "no ledger yet"}
    lines = LEDGER.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    recent = lines[-limit:]
    used: Counter[str] = Counter()
    capture: Counter[str] = Counter()
    parsed = 0
    last: dict[str, object] | None = None
    for line in recent:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed += 1
        used[str(row.get("used_backend") or "(none)")] += 1
        capture[str(row.get("capture_backend") or "(none)")] += 1
        last = row
    return {
        "rows": len(lines),
        "rows_examined": parsed,
        "used_backend": dict(used.most_common()),
        "capture_backend": dict(capture.most_common()),
        "last_recorded_at": (last or {}).get("recorded_at"),
        "last_skill": (last or {}).get("skill_id"),
        "last_used_backend": (last or {}).get("used_backend"),
    }


def config() -> dict[str, object]:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def device_report() -> dict[str, object]:
    """Does the emulator really answer, and is the game in front?

    Reconnects first, because that is what the panel's ``_ensure_device`` does
    before a cycle, then reads the device.  ``ok`` means all three things the
    runtime needs before a step can mean anything: attached, the configured
    resolution, and the configured package in the foreground.

    ``repairable`` answers the different question the gate needs.  ``ok`` is the
    reading the window displays ("游戏 运行中 / 未在前台"), and it must not be
    softened just because the runtime can fix it later.  ``repairable`` says
    whether ``_ensure_device`` can get from here to there -- see
    ``REPAIRABLE_SECTIONS`` for why that distinction had to exist.
    """
    device_cfg = config().get("device") or {}
    if not isinstance(device_cfg, dict):
        device_cfg = {}
    adb = Path(str(device_cfg.get("adb_path") or ""))
    serial = str(device_cfg.get("serial") or "")
    package = str(device_cfg.get("package_name") or "")
    want = tuple(device_cfg.get("resolution") or ())
    out: dict[str, object] = {
        "ok": False, "adb": str(adb), "serial": serial, "package": package,
        "want_resolution": list(want), "not_ready_reason": "", "repair": "",
        "repairable": False,
    }
    if not adb.is_file():
        out["error"] = "ADB_NOT_FOUND"
        out["not_ready_reason"] = "ADB_BINARY_MISSING"
        return out
    try:
        from winter_agent_v2.device import ADBDevice

        device = ADBDevice(adb, serial, production=True)
        # Hidden on purpose: the panel runs this file at startup from a process that owns
        # no console, and a console child of a console-less parent gets a *new* one
        # allocated -- which is a black window the operator sees (P0, 2026-09-18).
        connect = subprocess.run([str(adb), "connect", serial], capture_output=True,
                                 text=True, timeout=10, check=False,
                                 **winproc.hidden_kwargs())
        del connect
        device.resolve_connection()
        status = device.status()
    except Exception as exc:  # noqa: BLE001 - a dead emulator is an answer
        text = f"{type(exc).__name__}: {exc}"[:200]
        out["error"] = text
        # An import failure raised *here* belongs to the interpreter, and the
        # interpreter section already reports it.  Re-labelling it "the runtime
        # will fix the device" would let the one genuinely unrepairable failure
        # through under the repairable heading.
        out["not_ready_reason"] = "DEVICE_UNREACHABLE"
        if not (isinstance(exc, ImportError) or "ModuleNotFoundError" in text):
            out["repair"] = DEVICE_REPAIRS["EMULATOR_DOWN"]
            out["repairable"] = True
        return out

    got = tuple(status.resolution or ())
    front = str(status.foreground_package or "")
    if not status.connected:
        reason = "EMULATOR_DOWN"
    elif want and got != want:
        reason = "RESOLUTION_MISMATCH"
    elif package and front != package:
        reason = "GAME_NOT_FOREGROUND"
    else:
        reason = ""
    repair = DEVICE_REPAIRS.get(reason, "")
    out.update(
        ok=bool(status.connected) and (not want or got == want) and (not package or front == package),
        connected=bool(status.connected),
        resolution=list(got),
        foreground=front,
        not_ready_reason=reason,
        repair=repair,
        repairable=bool(repair),
    )
    return out


def gateway_report() -> dict[str, object]:
    """The WorkBuddy gateway -- reported always, blocking never.

    Requirement (operator, 2026-09-17): a refusing gateway is an
    *automatic-development* outage.  V2 keeps playing the capabilities it already
    has, the development card says 不可用, and the panel keeps retrying in the
    background.  So this section is aux: it is printed, it is never a reason to
    refuse the launch.
    """
    try:
        from winter_agent_v2.workbuddy_bridge import WorkBuddyBridge

        availability = WorkBuddyBridge().is_available()
        return {
            "ok": bool(availability.available),
            "reason": availability.reason,
            "base_url": availability.base_url,
            "detail": dict(availability.detail) if isinstance(availability.detail, dict) else {},
        }
    except Exception as exc:  # noqa: BLE001 - a missing bridge is an answer too
        return {"ok": False, "reason": f"{type(exc).__name__}", "detail": {"error": str(exc)[:200]}}


def report(ledger_limit: int = 200) -> dict[str, object]:
    """One preflight, in the shape both the CLI and the desktop launcher read."""
    maa_enabled = runtime_env.maa_enabled_from_config(ROOT)
    interpreter = runtime_env.resolve_for_project(ROOT)
    sections = {
        "interpreter": {
            "ok": interpreter.ok,
            "reason": interpreter.reason,
            "exe": str(interpreter.python_exe),
            "present": list(interpreter.present),
            "missing": list(interpreter.missing),
            "errors": interpreter.errors,
            "fell_back_from": str(interpreter.fell_back_from) if interpreter.fell_back_from else None,
        },
        "device": device_report(),
        "gateway": gateway_report(),
    }

    def _repairable(name: str) -> bool:
        return bool(sections[name].get("repairable"))

    def _broken(name: str) -> bool:
        return not bool(sections[name].get("ok"))

    # A core section that is not ready and that the runtime can repair is a
    # *recovery*, not a blocker.  It is still reported -- ``recovering`` exists so
    # that "AUTO may start" never reads as "everything is fine".
    blockers = [name for name in CORE_SECTIONS if _broken(name) and not _repairable(name)]
    recovering = [name for name in CORE_SECTIONS if _broken(name) and _repairable(name)]
    core_ok = not blockers
    launch_blockers = [name for name in LAUNCH_GATE_SECTIONS if _broken(name)]
    return {
        "root": str(ROOT),
        "maa_enabled": maa_enabled,
        "sections": sections,
        "core_sections": list(CORE_SECTIONS),
        "aux_sections": list(AUX_SECTIONS),
        "repairable_sections": list(REPAIRABLE_SECTIONS),
        "core_ok": core_ok,
        "ready_for_auto": core_ok,
        "blockers": blockers,
        "recovering": recovering,
        # The window's own question, kept separate from AUTO's.  See
        # LAUNCH_GATE_SECTIONS for why one exit code could not answer both.
        "launch_gate_sections": list(LAUNCH_GATE_SECTIONS),
        "launch_ok": not launch_blockers,
        "launch_blockers": launch_blockers,
        "aux_unavailable": [name for name in AUX_SECTIONS if _broken(name)],
        "interpreter": str(interpreter.python_exe),
        "candidates": [{"exe": exe, "ok": ok} for exe, ok in interpreter.candidates],
        "requirements": [
            {"module": module, "role": role, "why": why}
            for module, role, why in runtime_env.requirements_table(maa_enabled=maa_enabled)
        ],
        "ledger": ledger_summary(ledger_limit),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Winter Agent OS V2 runtime preflight")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--ledger-limit", type=int, default=200, help="ledger rows to summarise")
    parser.add_argument(
        "--launch-gate", action="store_true",
        help="exit on the window's question (the interpreter) instead of AUTO's "
             "(the interpreter and the device).  The desktop launcher uses this: the "
             "panel repairs the device and cannot repair the interpreter",
    )
    args = parser.parse_args(argv)

    data = report(args.ledger_limit)
    sections = data["sections"]
    interpreter = sections["interpreter"]
    device = sections["device"]
    gateway = sections["gateway"]

    # The two questions, resolved once so the JSON and the human path cannot
    # disagree -- the launcher reads the exit code and the panel parses the JSON,
    # and a verdict that differs between them is how "what the window reports" and
    # "what the launcher enforces" drift apart.
    if args.launch_gate:
        gate_ok = bool(data["launch_ok"])
        gate_blockers = list(data["launch_blockers"])
        gate_question = "the window may open"
    else:
        gate_ok = bool(data["core_ok"])
        gate_blockers = list(data["blockers"])
        gate_question = "AUTO may run"

    if args.json:
        # ensure_ascii default (True) on purpose, and it is not cosmetic.  The panel runs this
        # command with a piped stdout and decodes it with the OEM codepage, because that is what
        # console tools on this machine speak -- so a raw UTF-8 root path (E:\无尽冬日智能体) arrived
        # as mojibake whose last byte ate the closing quote, and json.loads raised Invalid \escape
        # on the field after it.  The window then reported "预检输出无法解析" and refused to start
        # AUTO.  Escaping non-ASCII makes this payload byte-identical under any decoding, which is
        # what a data format should be; the human-readable path below keeps the readable form.
        print(json.dumps(data, ensure_ascii=True, indent=2))
        return 0 if gate_ok else 1

    print("== Winter Agent OS V2 preflight ==")
    print(f"root        : {ROOT}")
    print(f"MAA enabled : {data['maa_enabled']}  (config/v2.json -> executor.maa.enabled)")
    print(f"question    : {gate_question}"
          f"{'  (--launch-gate: the interpreter only)' if args.launch_gate else ''}")
    print()
    print("-- core (AUTO may not start without these) --")
    print(f"[{'OK  ' if interpreter['ok'] else 'FAIL'}] runtime interpreter : {interpreter['exe']}")
    print(f"       verdict: {interpreter['reason']}")
    if interpreter["missing"]:
        print(f"       missing: {', '.join(interpreter['missing'])}")
    print(f"[{'OK  ' if device['ok'] else 'WARN'}] MuMu / device       : {device.get('serial')} "
          f"{device.get('resolution') or device.get('want_resolution')} foreground={device.get('foreground')}")
    if not device["ok"]:
        print(f"       error: {device.get('error')}")
        if device.get("repairable"):
            print(f"       not ready ({device.get('not_ready_reason')}) but repairable: "
                  f"the runtime does {device.get('repair')} and retries -- AUTO may start")
        else:
            print(f"       not repairable ({device.get('not_ready_reason')}): host configuration, "
                  f"the runtime cannot change it; AUTO will refuse")
    print()
    print("-- auxiliary (reported, never blocks AUTO) --")
    print(f"[{'OK  ' if gateway['ok'] else 'n/a '}] WorkBuddy gateway  : {gateway.get('reason')} "
          f"({gateway.get('base_url')})")
    if not gateway["ok"]:
        print("       自动开发不可用；V2 继续玩已知 Capability，面板后台周期重试。")
    print()
    print("candidates probed:")
    for candidate in data["candidates"]:
        print(f"  [{'OK  ' if candidate['ok'] else 'FAIL'}] {candidate['exe']}")
    print()
    ledger = data["ledger"]
    print("executor ledger (what production has really been using):")
    print(f"  rows              : {ledger.get('rows')}")
    print(f"  used_backend      : {json.dumps(ledger.get('used_backend'), ensure_ascii=False)}")
    print(f"  capture_backend   : {json.dumps(ledger.get('capture_backend'), ensure_ascii=False)}")
    print(f"  last step         : {ledger.get('last_skill')} via {ledger.get('last_used_backend')} "
          f"at {ledger.get('last_recorded_at')}")
    print()
    if gate_ok:
        verdict = "PASS" if not data["recovering"] else "PASS_WITH_RECOVERY"
        print(f"VERDICT: {verdict} - {gate_question}: {interpreter['exe']}"
              f"{'' if args.launch_gate else ' can run production on ' + str(device.get('serial'))}")
        for name in data["recovering"]:
            section = sections[name]
            print(f"         recovering: {name} is not ready ({section.get('not_ready_reason')}); "
                  f"the runtime does {section.get('repair')} and retries with backoff")
        if data["aux_unavailable"]:
            print(f"         auxiliary unavailable: {', '.join(data['aux_unavailable'])} "
                  "(AUTO still allowed; automatic development is marked unavailable)")
        if args.launch_gate and not data["core_ok"]:
            # Never let "the window may open" read as "AUTO will start".
            print(f"         and AUTO will refuse until: {', '.join(data['blockers'])}")
        return 0
    print(f"VERDICT: FAIL - {gate_question}: blocked by {', '.join(gate_blockers)}")
    if data["maa_enabled"] and "maa" in interpreter["missing"]:
        print("         MAA is enabled but not importable here. The production loop would")
        print("         silently fall back to ADB, which is a defect, not a degradation.")
    if not gate_ok and set(gate_blockers) - set(data["blockers"]):
        print("         Fix the interpreter (config/v2.json -> runtime.python_path) or the env.")
    elif not data["launch_ok"]:
        print(f"         the window may not open either: {'/'.join(data['launch_blockers'])}")
    else:
        print(f"         the window may still open: launch gate is "
              f"{'/'.join(LAUNCH_GATE_SECTIONS)} and it passed -- run with --launch-gate "
              f"for that verdict")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
