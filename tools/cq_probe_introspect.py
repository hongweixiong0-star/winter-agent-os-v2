"""Does the page probe touch the device, or only read it?  Read-only introspection."""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEYS = ("tap", "click", "press", "swipe", "touch", "screenshot", "capture", "adb", "maa")

for rel in ("tools/probe_live_page.py", "tools/maa_live_case.py"):
    p = ROOT / rel
    if not p.exists():
        print("MISSING", rel)
        continue
    print("=" * 72)
    print(rel, p.stat().st_size)
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        low = ln.lower()
        if any(k in low for k in KEYS):
            print("%5d %s" % (i, ln.strip()[:160]))
