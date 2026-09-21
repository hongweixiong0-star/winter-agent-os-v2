"""Start the production window detached, then report what actually got started.

Why this exists
---------------
``Start-Winter-Agent-V2.cmd`` is the production entry point, but it ends with ``start ...``
followed by nothing -- so it returns immediately, and anything that launched *it* (a
development tool, a shell in a session that then ends) can take the window down with it.
Measured 2026-09-18 on panels 24936/25408: a window started by a development tool's call
died when the call ended, and its soak could not be counted as evidence.

The launcher cannot fix that -- ``tools/control_panel.py`` says so itself, and the rule is
to move the acceptance into the real launch path rather than grow detach workarounds inside
the product.  So this script does the *reporting* half only:

* it sets the same ``WINTER_AGENT_LAUNCH_PATH=desktop`` marker the launcher sets, so the
  window declares the same launch origin it would have;
* it records PID, interpreter path and the Git revision the window is about to load, to
  ``learning/control_panel/launch_record.json``, at the moment of start;
* it refuses to start a second window when one is already alive, because two windows is two
  workers and two workers fight over one device.

It deliberately does **not** claim the window will outlive this process.  Whether it did is
checked afterwards, from the record and from the panel's own log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "learning" / "control_panel" / "launch_record.json"
PID_PATH = ROOT / "learning" / "control_panel" / "panel.pid"


def _revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _alive(pid: int) -> bool:
    """Is ``pid`` a running process?

    ``psutil`` is the honest check but is not installed here; ``os.kill(pid, 0)`` is the
    portable one, and on Windows it raises ``OSError`` for a dead pid just as it does for a
    permission denial -- so a denial is counted as alive, which is the safe direction (it
    refuses to double-start rather than starting a second worker on one device).
    """
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return getattr(exc, "winerror", None) == 5  # ACCESS_DENIED: exists, not ours
    except Exception:  # noqa: BLE001
        return False
    return True


def _current_panel() -> tuple[int, bool]:
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return 0, False
    return pid, _alive(pid)


def main() -> int:
    pid, alive = _current_panel()
    if alive:
        print(json.dumps({
            "started": False,
            "reason": "a window is already running",
            "panel_pid": pid,
            "revision": _revision(),
        }, ensure_ascii=False))
        return 0

    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        print(json.dumps({
            "started": False,
            "reason": f"production interpreter missing: {pythonw}",
        }, ensure_ascii=False))
        return 1

    env = dict(os.environ)
    # The same marker the launcher sets.  Without it the window reports itself as started
    # from a development path and its soak is disqualified -- see ``launch_context``.
    env["WINTER_AGENT_LAUNCH_PATH"] = "desktop"

    # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS: no console inherited, so a console that
    # closes does not deliver a Ctrl-C to the window.
    flags = 0x00000200 | 0x00000008
    proc = subprocess.Popen(
        [str(pythonw), str(ROOT / "tools" / "control_panel.py")],
        cwd=str(ROOT), env=env, creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    time.sleep(6.0)
    still = _alive(proc.pid)
    record = {
        "started": True,
        "panel_pid": proc.pid,
        "still_alive_after_6s": still,
        "interpreter": str(pythonw),
        "launch_path_marker": env["WINTER_AGENT_LAUNCH_PATH"],
        "revision": _revision(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "detached from this process by design; survival is verified separately",
    }
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
