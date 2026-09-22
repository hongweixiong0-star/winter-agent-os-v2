"""Can the client's own action-bar labels be READ on the current render?

The question this answers, and why it is asked before any code is written.

``KEEP_TRAINING_PRODUCTIVE`` has 35 recorded attempts at ``NAVIGATE_INFANTRY_CAMP``:
13 passed (2026-09-20 / 09-21 up to 13:07) and every attempt since 2026-09-21 16:24 has
failed with ``INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN``.  Reading the two frames side by side
says why: the older one is a gold ring around the barracks and nothing else; the current
one is the selected-building treatment -- the scene dimmed, the building named, and the
client's own ``详情 / 升级 / 训练`` action bar drawn along the bottom, with its finger
hint on 训练.  The template gate ``ocr.SemanticWorldVision._building_is_selected`` looks
for ``BTN_UPGRADE`` / ``BTN_TRAINING_MENU_LABEL`` / ``BTN_OPEN_TRAINING_FROM_CAMP`` and
none of them match this rendering, so the frame is read as "nothing happened".

Before replacing a template gate with a text read, measure the text: if the labels are
unreadable on these frames, the whole idea is dead and no code should be written for it.

Reports, per frame: every OCR token whose centre lies in the bottom band, its text, its
confidence and its frame-normalised centre -- so a label's tap point is a measurement
rather than a fraction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: The band the action bar is drawn in.  Wide on purpose for this probe: the point is to
#: see everything that is there, and to narrow it afterwards from what is found.
BAND_Y = (0.55, 0.85)

#: 2026-09-21 16:24 onward -- the render that fails.  The last two are the gold-ring render
#: that passes, kept as a control so a reader can be checked against both.
FAILING = (
    "dataset/raw/control_panel/runtime_auto/20260922_001615_642151/"
    "20260922_001615_642151_step_011_after_refresh_2_20260921T162341609773.png",
    "dataset/raw/control_panel/runtime_auto/20260922_074040_411565/"
    "20260922_074040_411565_step_014_after_refresh_2_20260921T234723313640.png",
    "dataset/raw/control_panel/runtime_auto/20260922_074040_411565/"
    "20260922_074040_411565_step_007_after_refresh_2_20260921T233653073158.png",
    "dataset/raw/control_panel/runtime_auto/20260922_000410_756444/"
    "20260922_000410_756444_step_018_after_refresh_2_20260921T232037311251.png",
)
PASSING = (
    "dataset/raw/control_panel/runtime_auto/20260921_210726_713439/"
    "20260921_210726_713439_step_003_after_20260921T130749099300.png",
    "dataset/raw/control_panel/runtime_auto/20260921_100322_213410/"
    "20260921_100322_213410_step_008_after_20260921T100509926422.png",
)


def build_ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    module_path = Path(config["ocr"]["module_path"])
    if not module_path.exists():
        return None
    return OCRService(ResilientOCRBackend(RapidOCRBackend(module_path)))


def tokens_in_band(image_path: Path, ocr) -> list[tuple[str, float, tuple[float, float]]]:
    from PIL import Image

    result = ocr.recognize(image_path)
    with Image.open(image_path) as image:
        width, height = image.size
    rows = []
    for token in result.tokens:
        if not token.box:
            continue
        xs = [float(point[0]) for point in token.box]
        ys = [float(point[1]) for point in token.box]
        cx = (min(xs) + max(xs)) / 2.0 / width
        cy = (min(ys) + max(ys)) / 2.0 / height
        if BAND_Y[0] <= cy <= BAND_Y[1]:
            rows.append((token.text.strip(), float(token.confidence), (round(cx, 4), round(cy, 4))))
    return sorted(rows, key=lambda row: row[2][1])


def main() -> int:
    ocr = build_ocr()
    if ocr is None:
        print("OCR module path missing in config/v2.json - cannot measure")
        return 2

    for label, group in (("FAILING (current render)", FAILING), ("PASSING (gold ring)", PASSING)):
        print("=" * 72)
        print(label)
        for rel in group:
            path = ROOT / rel
            print("-" * 72)
            print(" ", Path(rel).name)
            if not path.exists():
                print("    MISSING ON DISK")
                continue
            rows = tokens_in_band(path, ocr)
            if not rows:
                print("    no tokens in the band")
            for text, confidence, (cx, cy) in rows:
                print(f"    {text!r:26} conf={confidence:.3f}  centre=({cx:.4f}, {cy:.4f})"
                      f"  px=({round(cx * 720)}, {round(cy * 1280)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
