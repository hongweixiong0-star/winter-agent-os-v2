"""Locate the free-stamina claim entry on the world map.

The operator directive (2026-09-14) asks for free stamina to be claimed.  A
previously captured panel shows the sources of 领主体力, and one row carries a
bare 「领取」 with **no price next to it**, while the paid rows carry a diamond
price (「购买并使用 ?300」).  This probe confirms which control opens that panel
and captures it fresh, so the free entry can be templated and the paid entries
explicitly rejected.

The probe taps once (the stamina gauge) and taps nothing inside the panel.
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


def describe(ocr, path: Path, label: str) -> list[tuple[str, float, list[float]]]:
    result = ocr.recognize(path)
    rows = [
        (token.text.strip(), round(token.confidence, 3), [
            round(min(p[0] for p in token.box)), round(min(p[1] for p in token.box)),
            round(max(p[0] for p in token.box)), round(max(p[1] for p in token.box)),
        ])
        for token in result.tokens
        if token.confidence >= 0.80 and token.box
    ]
    print(f"--- {label} ({path.name})")
    for text, confidence, box in rows:
        print(f"      {text!r:>18} {confidence} px={box}")
    return rows


def main() -> int:
    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    device = ADBDevice(Path(config["device"]["adb_path"]), config["device"]["serial"], production=True)
    device.resolve_connection()
    vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
    ocr = OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"]))))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = OUT / f"free_stamina_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    probe_dir = ROOT / "dataset/raw/control_panel/probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    shot = probe_dir / "free_stamina_probe.png"
    for _ in range(4):
        device.screenshot(shot)
        state = vision.observe(shot)
        print("probe page:", state.page.value, "search_open:", state.resource_search_open)
        if state.page.value == "MAP":
            break
        device.press_back()
        time.sleep(2.0)
    else:
        print("MAP not reached")
        return 1

    before = out / "01_map_before.png"
    device.screenshot(before)
    describe(ocr, before, "map_before")

    width, height = device.status().resolution
    # Centre of the 领主体力 gauge number, measured at px (30..68, 101..119).
    target_x, target_y = round(49 / 720 * width), round(110 / 1280 * height)
    print(f"\n>> tapping the stamina gauge at px ({target_x},{target_y})")
    device.tap(target_x, target_y)
    time.sleep(2.5)

    after = out / "02_after_stamina_tap.png"
    device.screenshot(after)
    rows = describe(ocr, after, "after_stamina_tap")

    texts = {text for text, _confidence, _box in rows}
    free_entry = "领取" in texts
    paid_entry = any("购买并使用" in text for text in texts)
    print(f"\npanel title 获取更多: {'获取更多' in texts}")
    print(f"free 领取 present: {free_entry}   paid 购买并使用 present: {paid_entry}")

    with Image.open(after) as image:
        image = image.convert("RGB")
        w, h = image.size
        image.crop((0, int(0.05 * h), w, int(0.42 * h))).resize(
            (w * 2, int(0.37 * h) * 2), Image.LANCZOS
        ).save(out / "_review_panel.png")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
