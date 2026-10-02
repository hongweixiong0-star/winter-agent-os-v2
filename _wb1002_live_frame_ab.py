"""Closing evidence on the LIVE frame: the same frame, the old lock and the new one.

The before-frame of episode 20261002_152022_241791 step 002 (revision 70b093f, the deployed
fix) is a real production frame the runtime read at 07:21:11Z.  The old lock is emulated by
rebinding the module constant in this process only -- the deployed file is not touched.

Writes nothing, touches no device.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ocr as ocr_mod  # noqa: E402
from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

RUN = "20261002_152022_241791"
BEFORE = f"{RUN}_step_002_session_observe_session_bear_20261002T072111631818.png"
AFTER = f"{RUN}_step_002_session_observe_after_20261002T072119860155.png"

config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
world_vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
semantic = world_vision.semantic
service = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
vision = HybridVision(world_vision, service)

print("live frame:", BEFORE)
print("production reader lock in the deployed file:", ocr_mod.BRACKET_LABEL_LOCK)
for label, path in (("before", BEFORE), ("after", AFTER)):
    frame = ROOT / "dataset/raw/control_panel/runtime_auto" / RUN / path
    print("\n--", label, "frame exists:", frame.exists())
    if not frame.exists():
        continue
    state = vision.observe(frame)
    print("   deployed reader         -> resource_selected_tab =", state.resource_selected_tab)
    print("   episode recorded        -> %s" % (
        "BEAST" if label == "before" else "GIANT_BEAST"))
    saved = ocr_mod.BRACKET_LABEL_LOCK
    try:
        ocr_mod.BRACKET_LABEL_LOCK = 0.03
        old = vision.observe(frame)
        print("   old 0.03 lock (emulated) -> resource_selected_tab =", old.resource_selected_tab)
    finally:
        ocr_mod.BRACKET_LABEL_LOCK = saved
