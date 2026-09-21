"""Start the production window and capture why it dies, instead of guessing.

``tools/_launch_panel_detached.py`` starts the window detached so it survives this process,
which is right for production but useless for diagnosis: a detached ``pythonw.exe`` has no
console, so a startup crash writes nothing anywhere.  Measured 2026-09-21 -- the window came
up ("控制台已启动"), began its acceptance soak, and was gone within three seconds, and
nothing on disk said why.

So this runs the *same* interpreter and the *same* entry point attached, with stdout and
stderr going to a file, for a bounded window.  A window that survives the window is a window
whose startup is fine and whose death is someone else's doing -- which is a different problem
with a different fix, and the distinction is the whole point.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "learning" / "control_panel" / "startup_trace.log"
SECONDS = 60


def main() -> int:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        print(f"missing interpreter: {python}")
        return 1

    env = dict(os.environ)
    env["WINTER_AGENT_LAUNCH_PATH"] = "desktop"
    env["PYTHONUNBUFFERED"] = "1"
    # Do not start a second soak while one is being traced; the soak itself is not the subject.
    env["WINTER_AGENT_SKIP_SOAK"] = "1"

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", encoding="utf-8", errors="replace") as handle:
        proc = subprocess.Popen(
            [str(python), "-u", str(ROOT / "tools" / "control_panel.py")],
            cwd=str(ROOT), env=env,
            stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        )
        print(f"started pid={proc.pid}; observing for {SECONDS}s; trace -> {LOG}")
        deadline = time.time() + SECONDS
        while time.time() < deadline:
            code = proc.poll()
            if code is not None:
                print(f"DIED after {SECONDS - int(deadline - time.time())}s with exit code {code}")
                break
            time.sleep(1.5)
        else:
            print("still alive at the end of the observation window")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()

    text = LOG.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        print("(the window wrote nothing at all)")
    else:
        tail = text.strip().splitlines()[-40:]
        print("\n".join(tail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
