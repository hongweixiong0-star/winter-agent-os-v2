"""Do any tests or tools actually drive the real device?  Read-only scan."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Things that physically act on the client.
ACT = ("press_back", "tap(", "tap_semantic", "swipe", "device.tap", "ADBDevice(", "screencap", "MuMuExtras")

print("=== tests/ that instantiate a real device or tap ===")
hits = 0
for p in sorted((ROOT / "tests").rglob("*.py")):
    if "_pt_" in str(p):
        continue
    txt = p.read_text(encoding="utf-8", errors="replace")
    found = [k for k in ACT if k in txt]
    prod = "production=True" in txt
    if found:
        hits += 1
        print("  %-46s %s%s" % (p.name, found, "  [production=True]" if prod else ""))
print("  total files:", hits)

print()
print("=== tools/ that instantiate production=True ===")
for p in sorted((ROOT / "tools").glob("*.py")):
    txt = p.read_text(encoding="utf-8", errors="replace")
    if "production=True" in txt:
        print("  %-46s production=True" % p.name)

print()
print("=== every call site of a real tap/press in winter_agent_v2 ===")
pat = re.compile(r"\.(press_back|tap|swipe|tap_semantic)\(")
for p in sorted((ROOT / "winter_agent_v2").glob("*.py")):
    for i, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if pat.search(ln):
            print("  %-26s %5d  %s" % (p.name, i, ln.strip()[:120]))
