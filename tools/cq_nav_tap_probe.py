"""Measure the live tap mapping: tap a point, read the page, back out, repeat.

Bounded and honest: it only taps coordinates passed on the command line, only
from an observed HOME, and presses system BACK between taps to restore HOME.
It never touches a purchase surface, keeps every frame it read, and prints the
page before and after each tap.
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


def parse_point(raw: str) -> tuple[int, int]:
    x, y = raw.split(",")
    return int(x), int(y)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tap", action="append", type=parse_point, default=[])
    parser.add_argument("--tag", default="tapmap")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    device, hybrid, template = build()
    status = device.status()
    print(f"device resolution (wm size): {status.resolution} focus={status.foreground_package}")

    rows = []
    for index, (x, y) in enumerate(args.tap, start=1):
        # restore HOME with a bounded number of system BACKs
        for back in range(4):
            frame = OUT_DIR / f"{args.tag}_{stamp}_{index:02d}_pre{back}.png"
            device.screenshot(frame)
            state = hybrid.observe(frame)
            if state.page.value == "HOME":
                break
            device.press_back()
            time.sleep(2.0)
        else:
            print(f"ABORT at {x},{y}: could not recover HOME (stuck on {state.page.value})")
            break
        print(f"[{index}] HOME ok; tapping ({x},{y}) via {device.__class__.__name__}.tap")
        device.tap(x, y)
        time.sleep(2.5)
        after_frame = OUT_DIR / f"{args.tag}_{stamp}_{index:02d}_after_{x}_{y}.png"
        device.screenshot(after_frame)
        after = hybrid.observe(after_frame)
        template_state = template.observe(after_frame)
        print(f"      after -> page={after.page.value} conf={after.confidence:.2f} "
              f"popup={after.popup} | template-only={template_state.page.value} "
              f"{template_state.confidence:.2f} | {after_frame.name}")
        rows.append({"tap": [x, y], "page": after.page.value, "confidence": after.confidence,
                     "popup": after.popup, "template_only": template_state.page.value,
                     "frame": str(after_frame)})

    (OUT_DIR / f"tapmap_{stamp}.json").write_text(
        json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
                    "device_resolution": status.resolution, "rows": rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
