"""Measure the world-map HUD stamina ROI from live frames.

Eyeballing normalized coordinates is what produced the original resource-tab
bug, so the ROI here is *measured*: the script prints the OCR token boxes for
the top HUD band and the bounding box of the saturated pill that carries the
number, then writes a reviewed zoom for a human to confirm.

Read-only with respect to the game (screenshot + OCR only, never taps).
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


def saturated_pill_box(image_path: Path, roi: dict[str, float]) -> tuple[int, int, int, int] | None:
    """Bounding box of the highly saturated pixels inside ``roi``.

    Hue is deliberately not constrained: the pill is green at full stamina and
    may change colour as stamina drains, but it stays a saturated block over a
    desaturated HUD panel.
    """
    with Image.open(image_path) as source:
        rgb = source.convert("RGB")
        width, height = rgb.size
        box = (
            round(roi["x_norm"] * width),
            round(roi["y_norm"] * height),
            round((roi["x_norm"] + roi["w_norm"]) * width),
            round((roi["y_norm"] + roi["h_norm"]) * height),
        )
        crop = rgb.crop(box)
    pixels = crop.load()
    rows: dict[int, list[int]] = {}
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b = pixels[x, y]
            if max(r, g, b) >= 110 and max(r, g, b) - min(r, g, b) >= 60:
                rows.setdefault(y, []).append(x)
    if not rows:
        return None
    ys = sorted(rows)
    xs = [x for values in rows.values() for x in values]
    return (box[0] + min(xs), box[1] + ys[0], box[0] + max(xs), box[1] + ys[-1])


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
        if vision.observe(shot).page.value == "MAP":
            break
        device.press_back()
        time.sleep(2.0)
    else:
        print("MAP not reached")
        return 1

    status = device.status()
    width, height = status.resolution
    print(f"resolution {width}x{height}")

    # A generous search band around the top-left HUD corner.
    band = {"x_norm": 0.0, "y_norm": 0.05, "w_norm": 0.30, "h_norm": 0.07}
    result = ocr.recognize(shot, band)
    print(f"\n=== OCR tokens in band {band}")
    for token in result.tokens:
        if not token.box:
            continue
        xs = [p[0] for p in token.box]
        ys = [p[1] for p in token.box]
        print(
            f"    {token.text!r:>12} conf={token.confidence:.3f} "
            f"px=({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f}) "
            f"norm=({min(xs)/width:.4f},{min(ys)/height:.4f})-({max(xs)/width:.4f},{max(ys)/height:.4f})"
        )

    pill = saturated_pill_box(shot, {"x_norm": 0.0, "y_norm": 0.06, "w_norm": 0.25, "h_norm": 0.05})
    print(f"\nsaturated pill bbox px: {pill}")
    if pill:
        print(
            "pill norm: "
            f"x {pill[0]/width:.4f}-{pill[2]/width:.4f}  y {pill[1]/height:.4f}-{pill[3]/height:.4f}"
        )
        with Image.open(shot) as source:
            image = source.convert("RGB")
            crop = image.crop((pill[0] - 6, pill[1] - 6, pill[2] + 6, pill[3] + 6))
            crop.resize((crop.width * 8, crop.height * 8), Image.LANCZOS).save(
                ROOT / "dataset/truth_audit/_hud_stamina_pill.png"
            )
    print("zoom written to dataset/truth_audit/_hud_stamina_pill.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
