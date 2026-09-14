"""Locate the stamina readout on the world-map HUD.

``world.stamina`` has never been populated: there is no STAMINA template in the
manifest and the only writer was an OCR read of a number on the Intel page, so
on the map -- where every decision is made -- ``AVOID_STAMINA_WASTE`` can never
be discovered and AUTO falls back to gathering.  The operator directive
(2026-09-14) makes stamina spending the top priority, so the readout must
become observable first.

This tool is READ-ONLY with respect to the game: it screenshots, crops candidate
HUD bands and prints the OCR tokens it finds.  It never taps.  The shop panel
that also shows 领主体力 is deliberately avoided because it contains a
"buy with diamonds" control.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.device import ADBDevice  # noqa: E402
from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend  # noqa: E402
from winter_agent_v2.vision import SemanticWorldVision  # noqa: E402


def main() -> int:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(
        Path(config["device"]["adb_path"]), config["device"]["serial"], production=True
    )
    device.resolve_connection()
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

    probe_dir = ROOT / "dataset/raw/control_panel/probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    shot = probe_dir / "hud_stamina.png"

    for attempt in range(4):
        device.screenshot(shot)
        state = vision.observe(shot)
        print(f"probe {attempt}: page={state.page.value} search_open={state.resource_search_open}")
        if state.page.value == "MAP":
            break
        device.press_back()
        time.sleep(2.0)
    else:
        print("could not reach MAP; aborting so we never probe the wrong screen")
        return 1

    status = device.status()
    print(f"resolution: {status.resolution}")
    with Image.open(shot) as image:
        print(f"screenshot size: {image.size}")

    # Candidate HUD bands, expressed as normalized y ranges plus the full width.
    bands = {
        "top": (0.00, 0.10),
        "upper": (0.08, 0.18),
        "mid_upper": (0.16, 0.26),
        "left_column": (0.20, 0.60),
    }
    for name, (top, bottom) in bands.items():
        if name == "left_column":
            roi = {"x_norm": 0.0, "y_norm": top, "w_norm": 0.45, "h_norm": bottom - top}
        else:
            roi = {"x_norm": 0.0, "y_norm": top, "w_norm": 1.0, "h_norm": bottom - top}
        # A magnified copy for visual inspection, and OCR over the production ROI path.
        with Image.open(shot) as image:
            image = image.convert("RGB")
            width, height = image.size
            box = (
                round(roi["x_norm"] * width),
                round(roi["y_norm"] * height),
                round((roi["x_norm"] + roi["w_norm"]) * width),
                round((roi["y_norm"] + roi["h_norm"]) * height),
            )
            crop = image.crop(box)
            crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).save(
                ROOT / f"dataset/truth_audit/_hud_{name}.png"
            )
        result = ocr.recognize(shot, roi)
        print(f"\n=== {name} {roi}")
        for token in result.tokens:
            print(f"    {getattr(token, 'text', token)!r} conf={getattr(token, 'confidence', None)}")

    print("\nscreenshot kept at", shot.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
