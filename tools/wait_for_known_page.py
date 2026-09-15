"""Wait for the live client to leave an unrecognised screen, then report it.

Why this exists: the runtime's unknown-page recovery presses BACK.  That is fine
on a menu nobody understands, but on 2026-09-15T15:14Z the client was found on an
*active auto-battle* (skill buttons, x2 speed, pause) classified UNKNOWN at
confidence 0.0.  Pressing BACK there is an action of unmeasured effect on a live
fight, so no agent run may be started until the screen resolves on its own.
Battles play out unattended, so this polls instead of acting.

It never presses anything.  Read-only; bounded.

    python tools/wait_for_known_page.py [max_waits] [seconds_between]
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = r"E:\dongri-mumu-bot\.venv\Scripts\python.exe"
KNOWN = {"MAP", "HOME", "INTEL", "MARCH", "RESOURCE_DETAIL", "EXPLORATION", "MAIL", "DAILY"}


def probe() -> tuple[str, float, str]:
    p = subprocess.run(
        [PY, "-u", "tools/probe_live_page.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    page, conf, shot = "UNKNOWN", 0.0, ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("page"):
            page = line.split(":", 1)[1].strip().replace("Page.", "")
        elif line.startswith("confidence"):
            try:
                conf = float(line.split(":", 1)[1].strip())
            except ValueError:
                conf = 0.0
        elif line.startswith("frame"):
            shot = line.split(":", 1)[1].strip()
    return page, conf, shot


def main() -> int:
    max_waits = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    gap = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0

    for attempt in range(max_waits + 1):
        page, conf, shot = probe()
        print(
            "probe %-2d page=%-16s confidence=%.2f  %s"
            % (attempt, page, conf, pathlib.Path(shot).name),
            flush=True,
        )
        if page in KNOWN:
            print("KNOWN PAGE REACHED after %d wait(s)" % attempt, flush=True)
            return 0
        if attempt < max_waits:
            time.sleep(gap)
    print("still unrecognised after %d wait(s); no action taken" % max_waits, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
