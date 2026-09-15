"""Read-only-ish: one BACK from wherever the client is stuck, and where it lands.

Why this exists (2026-09-15)
---------------------------
The client can be left parked on a non-actionable beast card (`Page.BEAST`,
``available=false``), and from there ``brain.py`` has no exit: it returns
``SAFE_STOP / beast_not_actionable`` at the first step, so every following run
ends in about five seconds and the hourly automation produces nothing until a
human moves the client.  Recorded twice, independently
(``evidence/intel_pins_20260915_092119.json`` and ``..._095605.json``).

The fix is a recovery decision on that page, but the project's rule is that
navigation is never invented -- so the first step is to *measure* where BACK
goes from the page.  This does exactly that, once, and prints both states.

It presses exactly one key.  It never taps a game control and never spends
anything (BACK opens no paid surface, and the report says so if it sees one).

Usage
-----
    "E:/dongri-mumu-bot/.venv/Scripts/python.exe" tools/probe_back_from_beast.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "dataset" / "raw" / "control_panel" / "probe"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

FIELDS = ("popup", "beast", "intel", "stamina", "resource_target", "marches")


def build():
    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import (
        HybridVision,
        OCRService,
        RapidOCRBackend,
        ResilientOCRBackend,
    )
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(
        Path(config["device"]["adb_path"]),
        config["device"]["serial"],
        production=True,
    )
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(
        ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))
    )
    return device, HybridVision(template, ocr)


def describe(label: str, state) -> None:
    print(f"--- {label} ---")
    print(f"page       : {state.page}")
    print(f"confidence : {state.confidence}")
    for name in FIELDS:
        value = getattr(state, name, None)
        if value:
            print(f"{name:<11}: {json.dumps(value, ensure_ascii=False, default=str)}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, hybrid = build()

    before_frame = OUT_DIR / f"back_probe_before_{STAMP}.png"
    device.screenshot(before_frame)
    before = hybrid.observe(before_frame)
    describe("BEFORE (one frame, no action yet)", before)

    device.press_back()
    time.sleep(2.0)

    after_frame = OUT_DIR / f"back_probe_after_{STAMP}.png"
    device.screenshot(after_frame)
    after = hybrid.observe(after_frame)
    describe("AFTER one BACK", after)

    print()
    print(f"landed_on  : {after.page}")
    print(f"frame_before: {before_frame}")
    print(f"frame_after : {after_frame}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
