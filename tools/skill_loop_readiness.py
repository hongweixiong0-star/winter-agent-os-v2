"""Is the live half of the skill loop runnable right now? One read-only answer.

    python tools/skill_loop_readiness.py
    python tools/skill_loop_readiness.py --json

Why this exists
---------------
The loop's last step (MAA on the real client) is gated by things that change without any code
change: the runtime's mode latch, whether an emulator is up, which package is in the foreground,
and whether another automation is already driving the screen.  Running ``skill_loop_run.py``
blind and reading a refusal is a slow way to learn which one it was -- and a click issued while
two automations share a screen cannot be attributed to either.

So this checks the gates *before* anything is issued, and prints one row per gate with the
action that clears it.  It is read-only by construction: it starts no server, takes no lease and
issues no input; the only device calls are ``adb devices``, ``dumpsys window`` and ``ps``.

Exit code is 0 only when every gate passes, so a caller can gate on it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

GAME_PACKAGE = "com.gof.china"
#: The third-party helper observed on this machine 2026-10-18.  It is not part of this project;
#: it is listed because a screen driven by two automations cannot produce attributable evidence.
KNOWN_FOREIGN_AUTOMATION = "com.xm.wujindongri"


def _config(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _adb(config: dict, *args: str, timeout: float = 10.0) -> tuple[int, str]:
    """One hidden adb call.  Through ``winproc`` because this tree has exactly one policy about
    consoles: a tool started from the panel must never flash a window over the game, and
    ``tests/test_winproc.py`` refuses a bare ``subprocess.run`` here.  The pipes in the shell
    arguments are interpreted by the *device's* shell, not by cmd.exe, so no local shell is needed.
    """
    from winter_agent_v2 import winproc

    binary = str((config.get("device") or {}).get("adb_path") or "adb")
    try:
        proc = winproc.run([binary, *args], timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_focus(text: str) -> str:
    """The package in ``mCurrentFocus``, or ``""``.

    Split out because the dumpsys line is the one piece of parsing here that a test can pin:
    ``mCurrentFocus=Window{9118b96 u0 com.gof.china/com.gof.china.MainActivity}``.
    """
    for line in text.splitlines():
        marker = "mCurrentFocus="
        if marker not in line:
            continue
        window = line.split(marker, 1)[1].strip()
        body = window.split("}", 1)[0]
        parts = body.split()
        for part in parts:
            if "/" in part:
                return part.split("/", 1)[0]
        if parts:
            return parts[-1]
    return ""


def _gate(name: str, ok: bool, detail: str, action: str = "") -> dict:
    return {"gate": name, "ok": ok, "detail": detail, "action": "" if ok else action}


def collect(config_path: Path) -> dict:
    config = _config(config_path)
    serial = str((config.get("device") or {}).get("serial") or "127.0.0.1:7555")
    gates: list[dict] = []

    # 1. pin + commit + mounts -- the same verifier the production launcher runs.
    try:
        import launch_pinned_production as launcher
        commit, data_root = launcher.verify_pin()
        gates.append(_gate("pin", True, f"{commit[:8]} data_root={data_root}"))
    except Exception as exc:  # noqa: BLE001 - a broken pin is the report, not a crash
        gates.append(_gate("pin", False, f"{type(exc).__name__}: {exc}",
                           "python tools/repin_production.py --to <sha>  # or fix the dirty tree"))

    # 2. the runtime's own mode latch.  AUTO means Manual work may not run, and this tool
    #    cannot flip it (operator §4: WorkBuddy must not switch back to Manual by itself).
    try:
        from winter_agent_v2 import mode_state
        state = mode_state.load()
        mode = str(getattr(state, "mode", "") or "")
        gates.append(_gate("mode", mode.upper() == "MANUAL", f"mode={mode}",
                           "python -m winter_agent_v2.mode_state --to-manual --by USER "
                           "--reason 'skill loop live verify' --expected-minutes 10 "
                           "--done-when 'one verified close'"))
    except Exception as exc:  # noqa: BLE001
        gates.append(_gate("mode", False, f"{type(exc).__name__}: {exc}", "check learning/mode_state.json"))

    # 3. a device that adb can see.
    rc, out = _adb(config, "devices")
    online = any(serial in line and "device" in line for line in out.splitlines())
    gates.append(_gate("device", online, f"serial={serial} adb_rc={rc}",
                       f'"{config.get("device", {}).get("adb_path", "adb")}" connect {serial}'))

    if not online:
        # The rest needs the device; report them as unknown rather than guessing.
        for name in ("foreground", "foreign_automation", "game_process"):
            gates.append(_gate(name, False, "device offline, not observable", "bring the emulator up"))
        return {"checked_at": datetime.now(timezone.utc).isoformat(), "serial": serial,
                "gates": gates, "runnable": False}

    # 4. the game must be the package in front; anything else means the frame is not the client.
    rc, out = _adb(config, "-s", serial, "shell", "dumpsys window 2>/dev/null | grep mCurrentFocus")
    focus = parse_focus(out)
    gates.append(_gate("foreground", focus == GAME_PACKAGE, f"focus={focus or 'unknown'}",
                       f"foreground {GAME_PACKAGE} on the emulator"))

    # 5. another automation on the same screen makes any click unattributable.
    rc, out = _adb(config, "-s", serial, "shell",
                   f"ps -A 2>/dev/null | grep -c {KNOWN_FOREIGN_AUTOMATION}")
    try:
        count = int(out.strip().splitlines()[-1]) if out.strip() else 0
    except ValueError:
        count = 0
    gates.append(_gate("foreign_automation", count == 0,
                       f"{KNOWN_FOREIGN_AUTOMATION} processes={count}",
                       "close the third-party helper; two automations on one screen cannot be told apart"))

    # 6. the game process itself.
    rc, out = _adb(config, "-s", serial, "shell", f"ps -A 2>/dev/null | grep -c {GAME_PACKAGE}")
    try:
        game_count = int(out.strip().splitlines()[-1]) if out.strip() else 0
    except ValueError:
        game_count = 0
    gates.append(_gate("game_process", game_count > 0, f"{GAME_PACKAGE} processes={game_count}",
                       f"launch {GAME_PACKAGE}"))

    return {"checked_at": datetime.now(timezone.utc).isoformat(), "serial": serial,
            "gates": gates, "runnable": all(g["ok"] for g in gates)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(ROOT / "config" / "v2.json"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = collect(Path(args.config))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for gate in report["gates"]:
            mark = "OK  " if gate["ok"] else "STOP"
            print(f"{mark} {gate['gate']:<20} {gate['detail']}")
            if gate["action"]:
                print(f"     -> {gate['action']}")
        print()
        print("RUNNABLE" if report["runnable"] else "BLOCKED")
    return 0 if report["runnable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
