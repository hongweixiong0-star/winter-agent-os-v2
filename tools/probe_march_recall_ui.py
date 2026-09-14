"""Find the recall control for an active march.

The operator directive (2026-09-14) explicitly allows recalling marches at any
time, including to free a slot for live-verification experiments.  ``RECALL_MARCH``
is already registered but has no verifier, so the live loop can never dispatch
it.  The missing piece is the UI: where the recall action actually lives.

This probe taps one march row and captures what opens.  It taps exactly once
per candidate and never confirms anything, so it cannot accidentally recall or
launch a march.
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

OUT = ROOT / "dataset/truth_audit"


def capture(device, ocr, vision, path: Path, label: str) -> dict:
    device.screenshot(path)
    state = vision.observe(path)
    result = ocr.recognize(path)
    tokens = [
        (token.text.strip(), round(token.confidence, 3), [
            round(min(p[0] for p in token.box)), round(min(p[1] for p in token.box)),
            round(max(p[0] for p in token.box)), round(max(p[1] for p in token.box)),
        ])
        for token in result.tokens
        if token.confidence >= 0.80 and token.box
    ]
    record = {"label": label, "file": path.name, "page": state.page.value,
              "stamina": state.stamina, "march": f"{state.march_used}/{state.march_max}",
              "tokens": tokens}
    print(f"--- {label}: page={state.page.value} march={record['march']} stamina={state.stamina.get('current')}")
    for text, conf, box in tokens[:26]:
        print(f"      {text!r:>14} {conf} px={box}")
    return record


def main() -> int:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = OUT / f"march_recall_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    probe_dir = ROOT / "dataset/raw/control_panel/probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    shot = probe_dir / "recall_probe.png"
    for _ in range(4):
        device.screenshot(shot)
        if vision.observe(shot).page.value == "MAP":
            break
        device.press_back()
        time.sleep(2.0)
    else:
        print("MAP not reached")
        return 1

    before = capture(device, ocr, vision, out / "01_map_before.png", "map_before")
    records.append(before)

    # Row 1 of the march list: 采集中 label at approximately (0.124, 0.223).
    status = device.status()
    width, height = status.resolution
    target_x, target_y = round(0.28 * width), round(0.2234 * height)
    print(f"\n>> tapping march row 1 at px ({target_x},{target_y})")
    device.tap(target_x, target_y)
    time.sleep(2.5)
    records.append(capture(device, ocr, vision, out / "02_after_row1_tap.png", "after_row1_tap"))

    (out / "probe.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    # A 2x crop of everything below the HUD for review.
    with Image.open(out / "02_after_row1_tap.png") as image:
        image = image.convert("RGB")
        w, h = image.size
        crop = image.crop((0, int(0.16 * h), w, int(0.92 * h)))
        crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS).save(out / "_review_after_tap.png")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
