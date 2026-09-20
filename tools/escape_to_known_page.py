"""Escape a stuck client screen using the system Back key only.

Why this exists: the agent can end a run parked on a screen nobody understands
(measured 2026-09-15T13:30Z: the 英雄招募 gacha page, classified UNKNOWN at
confidence 0.0).  That is the correct decision -- its buttons spend recruitment
tokens -- but the next run inherits the screen.  Getting back to a page the
brain understands is therefore a precondition for any further live work.

Back is the only action used.  It is a system key: it cannot buy, spend, or
confirm anything, which is what makes it safe to press on a screen whose
contents are not recognised.  The loop is bounded and stops as soon as the
vision reports a page the brain can act on.

    python tools/escape_to_known_page.py [max_backs]
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY = r"E:\无尽冬日智能体\.venv\Scripts\python.exe"

# Pages the brain can act on.  HOME/MAP are the ordinary entry points; INTEL and
# MARCH are accepted because some tasks deliberately start there.
KNOWN = {"MAP", "HOME", "INTEL", "MARCH", "RESOURCE_DETAIL", "EXPLORATION", "MAIL", "DAILY"}


def probe() -> tuple[str, float, str]:
    """Return (page, confidence, screenshot path) from the production vision."""
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
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice  # noqa: PLC0415

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(pathlib.Path(cfg["device"]["adb_path"]), cfg["device"]["serial"], production=True)
    device.resolve_connection()

    page, conf, shot = probe()
    print("start   page=%-16s confidence=%.2f  %s" % (page, conf, pathlib.Path(shot).name))
    if page in KNOWN:
        print("already on a known page; nothing to do")
        return 0

    for i in range(1, limit + 1):
        device.press_back()
        time.sleep(2.5)
        page, conf, shot = probe()
        print("back %-2d page=%-16s confidence=%.2f  %s" % (i, page, conf, pathlib.Path(shot).name))
        if page in KNOWN:
            print("reached a known page after %d back(s)" % i)
            return 0
    print("stopped after %d back(s) without reaching a known page" % limit)
    return 1


if __name__ == "__main__":
    sys.exit(main())
