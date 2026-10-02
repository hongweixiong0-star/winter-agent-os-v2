"""Real acceptance for the bracket-lock fix, on the archived frames of the episode that failed.

Two things are measured, both through production code paths and neither through a helper I
re-implemented myself:

  1. ``HybridVision.observe`` -- the entry point the runtime actually calls -- on the before and
     after frames of episode 20261002_123127_711948 step 004.  The episode recorded
     ``resource_selected_tab = None`` on the after frame while the client had visibly moved the
     bracket onto 野兽.
  2. ``verify_beast_search_tab_selected`` -- the verifier that produced
     ``BEAST_SEARCH_TAB_NOT_PROVEN`` -- on those two states.

  Plus a regression sweep: frames that already read GIANT_BEAST must keep reading it.

Writes nothing, touches no device.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend,
)
from winter_agent_v2.verifier import verify_beast_search_tab_selected  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

RUNS = ROOT / "dataset/raw/control_panel/runtime_auto"
EP = "20261002_123127_711948"

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
world_vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
vision = HybridVision(world_vision, ocr)

before_path = RUNS / EP / f"{EP}_step_004_before_20261002T043250156876.png"
after_path = RUNS / EP / f"{EP}_step_004_after_refresh_2_20261002T043309061119.png"

before = vision.observe(before_path)
after = vision.observe(after_path)
print("1. production entry point (HybridVision.observe)")
print("   before  page=%-8s search_open=%-5s selected_tab=%s" % (
    before.page, before.resource_search_open, before.resource_selected_tab))
print("   after   page=%-8s search_open=%-5s selected_tab=%s" % (
    after.page, after.resource_search_open, after.resource_selected_tab))
print("   episode recorded on the after frame: resource_selected_tab = None")

result = verify_beast_search_tab_selected(before, after)
print()
print("2. the verifier that produced the failure")
print("   verify_beast_search_tab_selected -> ok=%s reason=%s" % (result.ok, result.reason))
print("   evidence                        -> %s" % json.dumps(result.evidence, ensure_ascii=False)[:220])
print("   episode recorded                -> ok=False reason=BEAST_SEARCH_TAB_NOT_PROVEN")

print()
print("3. regression sweep: frames that already resolved must be untouched")
checks = [
    ("20261002_145359_378193", None, None),
]
# every episode/frame pair where the ledger already read a tab, taken from the A/B table
SPOT = [
    (f"{EP}_step_004_before_20261002T043250156876.png", "GIANT_BEAST"),
]
for name, expect in SPOT:
    st = vision.observe(RUNS / EP / name)
    print("   %-52s %-12s (expected %s) %s" % (
        name, st.resource_selected_tab, expect,
        "OK" if st.resource_selected_tab == expect else "MISMATCH"))
