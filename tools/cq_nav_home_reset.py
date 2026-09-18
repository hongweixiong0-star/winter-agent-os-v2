"""Bounded BACK until the live client reports HOME. Read + system-Back only.

Prints one line per BACK with the observed page afterwards, capped at --max.
Never taps a semantic target and never touches a purchase surface.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "dataset" / "truth_audit" / "nav_to_map_20260918"


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
    return device, HybridVision(template, ocr), template


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=5)
    parser.add_argument("--tag", default="home_reset")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    device, hybrid, template = build()

    for attempt in range(args.max + 1):
        frame = OUT_DIR / f"{args.tag}_{stamp}_{attempt:02d}.png"
        device.screenshot(frame)
        state = hybrid.observe(frame)
        print(f"[{attempt}] page={state.page.value} conf={state.confidence:.2f} "
              f"popup={state.popup} frame={frame.name}")
        if state.page.value == "HOME":
            print("RESULT: HOME")
            return 0
        if attempt == args.max:
            break
        device.press_back()
        time.sleep(2.0)
    print("RESULT: NOT_HOME")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
