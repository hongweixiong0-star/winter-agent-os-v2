"""0bc measurement: what does the production vision say about the frames we have?

The suspicion (recorded as 0bc) is that page discrimination between the city
view (HOME) and the world map (MAP) rests on the 城镇 button, which the client
draws on BOTH pages -- so the same widget is being used to distinguish pages it
is present on.  Before proposing anything, measure: which archived frames does
the vision call HOME, which MAP, and with what confidence?

Read-only: no device access, no taps, no writes.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.ocr import (  # noqa: E402
    HybridVision,
    OCRService,
    RapidOCRBackend,
    ResilientOCRBackend,
)
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402

CANDIDATES = [
    # Note the 'T' before the time: the MAA probe names frames
    # state_maa_<YYYYmmdd>T<HHMMSS>.png.  An underscore here silently reports the
    # frame as MISSING, which once looked like evidence loss.
    "dataset/evidence/maa_live/state_maa_20260915T124440.png",
    "dataset/evidence/maa_live/state_adb_20260915T124440.png",
    "dataset/raw/control_panel/probe/live_page_20260915_133152.png",
    "dataset/raw/control_panel/probe/live_page_20260915_133012.png",
    "dataset/raw/control_panel/probe/live_page_20260915_151524.png",
    "dataset/raw/control_panel/probe/live_page_20260915_151446.png",
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T133220611709.png",
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260915T125843883794.png",
]


def main() -> None:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(pathlib.Path(config["ocr"]["module_path"]))))
    vision = HybridVision(template, ocr)

    print("%-64s %-10s %-6s %s" % ("frame", "page", "conf", "notable fields"))
    print("-" * 118)
    for rel in CANDIDATES:
        p = ROOT / rel
        if not p.exists():
            print("%-64s MISSING" % rel)
            continue
        state = vision.observe(p)
        notable = []
        for key in ("page", "popup", "stamina", "intel", "mail", "beast"):
            if key == "page":
                continue
            value = getattr(state, key, None)
            if value:
                notable.append("%s=%s" % (key, json.dumps(value, ensure_ascii=False)[:60]))
        print(
            "%-64s %-10s %-6s %s"
            % (p.name[:64], state.page.value, round(state.confidence, 2), " ".join(notable)[:60])
        )


if __name__ == "__main__":
    main()
