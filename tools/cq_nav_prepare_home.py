"""Put the live client back on HOME so a navigation run has a real starting point.

Navigation only: it taps the bottom-right control when the client is already on
the world map (``城镇`` returns to the city; the same box shows ``野外`` on the
city screen), and otherwise presses the system Back a bounded number of times.
It never taps anything else, never starts a battle and never touches a purchase
surface.  Exits 0 only when the client really reads HOME.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "dataset" / "truth_audit" / "nav_to_map_20260918"
# The bottom-right control on the 720x1280 client.  Measured 2026-09-18: the
# production PAGE_MAP registration resolves here, and tapping it on MAP returns
# HOME while tapping it on HOME opens MAP (a toggle drawn in one box).
TOGGLE_PX = (665, 1221)


def build():
    from winter_agent_v2.device import ADBDevice
    from winter_agent_v2.ocr import HybridVision, OCRService, RapidOCRBackend, ResilientOCRBackend
    from winter_agent_v2.vision import SemanticWorldVision

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"],
                       production=True)
    device.resolve_connection()
    template = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))
    return device, HybridVision(template, ocr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-backs", type=int, default=3)
    parser.add_argument("--tag", default="prepare_home")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device, vision = build()

    def look(step: str):
        frame = OUT_DIR / f"{args.tag}_{step}.png"
        device.screenshot(frame)
        state = vision.observe(frame)
        print(f"{step:<10} page={state.page.value} conf={state.confidence:.2f} "
              f"popup={state.popup} frame={frame}", flush=True)
        return state

    state = look("00_start")
    if state.page.value == "HOME":
        return 0
    if state.page.value == "MAP":
        device.tap(*TOGGLE_PX)
        time.sleep(2.5)
        state = look("01_toggled")
        if state.page.value == "HOME":
            return 0
    for attempt in range(1, args.max_backs + 1):
        device.press_back()
        time.sleep(2.5)
        state = look(f"02_back{attempt}")
        if state.page.value == "HOME":
            return 0
    print(f"RESULT: NOT_HOME (last page {state.page.value})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
