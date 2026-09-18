"""Preflight: can the interpreter that is about to run production actually do it?

Run this before trusting a run's numbers.

    python tools/preflight.py
    python tools/preflight.py --json

Exit code is 0 only when the resolved interpreter can import every module the
production loop depends on *and* -- unless MAA is switched off in
``config/v2.json`` -- MAA is among them.

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
        "want_resolution": list(want),
    }
    if not adb.is_file():
        out["error"] = "ADB_NOT_FOUND"
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
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return out

    got = tuple(status.resolution or ())
    front = str(status.foreground_package or "")
    out.update(
        ok=bool(status.connected) and (not want or got == want) and (not package or front == package),
        connected=bool(status.connected),
        resolution=list(got),
        foreground=front,
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
    core_ok = all(bool(sections[name].get("ok")) for name in CORE_SECTIONS)
    return {
        "root": str(ROOT),
        "maa_enabled": maa_enabled,
        "sections": sections,
        "core_sections": list(CORE_SECTIONS),
        "aux_sections": list(AUX_SECTIONS),
        "core_ok": core_ok,
        "ready_for_auto": core_ok,
        "blockers": [name for name in CORE_SECTIONS if not sections[name].get("ok")],
        "aux_unavailable": [name for name in AUX_SECTIONS if not sections[name].get("ok")],
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
    args = parser.parse_args(argv)

    data = report(args.ledger_limit)
    sections = data["sections"]
    interpreter = sections["interpreter"]
    device = sections["device"]
    gateway = sections["gateway"]

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data["core_ok"] else 1

    print("== Winter Agent OS V2 preflight ==")
    print(f"root        : {ROOT}")
    print(f"MAA enabled : {data['maa_enabled']}  (config/v2.json -> executor.maa.enabled)")
    print()
    print("-- core (AUTO may not start without these) --")
    print(f"[{'OK  ' if interpreter['ok'] else 'FAIL'}] runtime interpreter : {interpreter['exe']}")
    print(f"       verdict: {interpreter['reason']}")
    if interpreter["missing"]:
        print(f"       missing: {', '.join(interpreter['missing'])}")
    print(f"[{'OK  ' if device['ok'] else 'FAIL'}] MuMu / device       : {device.get('serial')} "
          f"{device.get('resolution') or device.get('want_resolution')} foreground={device.get('foreground')}")
    if not device["ok"]:
        print(f"       error: {device.get('error')}")
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
    if data["core_ok"]:
        print(f"VERDICT: PASS - {interpreter['exe']} can run production on {device.get('serial')}")
        if data["aux_unavailable"]:
            print(f"         auxiliary unavailable: {', '.join(data['aux_unavailable'])} "
                  "(AUTO still allowed; automatic development is marked unavailable)")
        return 0
    print(f"VERDICT: FAIL - core blocker(s): {', '.join(data['blockers'])}")
    if data["maa_enabled"] and "maa" in interpreter["missing"]:
        print("         MAA is enabled but not importable here. The production loop would")
        print("         silently fall back to ADB, which is a defect, not a degradation.")
    print("         Fix the interpreter (config/v2.json -> runtime.python_path) or the env.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
