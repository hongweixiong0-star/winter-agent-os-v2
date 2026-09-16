"""Verify the role-identity read through the production observation path.

Runs `HybridVision.read_role_identity` -- not the parser in isolation -- over the
real frames, and asserts both directions:

* the 领主档案 panel yields the identity the client drew;
* every frame that is not that panel yields ``None``.

The negative direction is the one that matters.  If a MAP or ALLIANCE frame could
produce an identity, persisted role state would be keyed to a role that was never
observed, which is worse than having no identity at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
from winter_agent_v2.vision import SemanticWorldVision

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
vision = HybridVision(
    SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
    OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
)

POSITIVE = ROOT / "dataset/truth_audit/role_identity_20260916/profile_panel_live_20260916T184004.png"
NEGATIVES = [
    ("world map, the frame before the tap", ROOT / "dataset/raw/role_identity/20260916_184004/20260916_184004_00_before.png"),
    ("world map, after backing out", ROOT / "dataset/raw/role_identity/20260916_184004/20260916_184004_02_after_back.png"),
    ("city view", ROOT / "dataset/raw/live_runtime/live_runtime_step_001_before_20260916T040807654821.png"),
    ("march-queue panel over the map", ROOT / "dataset/truth_audit/march_queue_20260914_134158/20260914_134158_map_before.png"),
]

failures = 0

print("== positive: the 领主档案 panel ==")
if not POSITIVE.is_file():
    print("   MISSING", POSITIVE)
    failures += 1
else:
    identity = vision.read_role_identity(POSITIVE)
    if identity is None:
        print("   FAIL: no identity read from the live profile panel")
        failures += 1
    else:
        print("   role_id     :", identity.role_id)
        print("   role_name   :", identity.role_name)
        print("   alliance_tag:", identity.alliance_tag)
        print("   kingdom     :", identity.kingdom)
        print("   power_text  :", identity.power_text)
        print("   confidence  : %.3f" % identity.confidence)
        if identity.role_id != "1171757165" or identity.role_name != "xhw小号":
            print("   FAIL: does not match what the panel drew")
            failures += 1
        if identity.alliance_tag != "zoe" or identity.kingdom != "4298":
            print("   FAIL: alliance tag / kingdom misread")
            failures += 1

print()
print("== negative: anything else must yield None ==")
for label, path in NEGATIVES:
    if not path.is_file():
        print("   %-38s MISSING" % label)
        failures += 1
        continue
    got = vision.read_role_identity(path)
    ok = got is None
    if not ok:
        failures += 1
    print("   %-38s -> %s" % (label, "None (correct)" if ok else "READ %r (WRONG)" % (got,)))

print()
print("failures:", failures)
raise SystemExit(1 if failures else 0)
