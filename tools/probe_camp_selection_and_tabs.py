"""What text can actually be read on the frames the training route is stuck on?

Three questions, all answered from the client's own drawing rather than from a guess:

  1. the selected-building action bar -- ``详情 / 升级 / 训练`` -- on the render that has
     failed every ``NAVIGATE_INFANTRY_CAMP`` since 2026-09-21 16:24 (measured separately in
     probe_camp_action_bar.py: 训练 at conf 0.986-0.988, two frames agreeing within 3 px);
  2. WHICH building is selected, because the action bar is drawn for any selected building
     and claiming "the infantry camp is selected" without it would be an invention;
  3. the three camp tabs on the training page itself -- 盾兵营 / 矛兵营 / 射手营 -- which is
     the step after this one.

Frames are collected from the episodes rather than hardcoded, so the list is what the run
actually produced and a missing file is reported as missing instead of silently skipped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Everything below the top HUD.  Wide on purpose: this probe is a survey, and where the
#: bands end is something the tokens themselves decide.
MIN_Y = 0.28
MIN_CONFIDENCE = 0.85


def collect_frames() -> list[tuple[str, Path]]:
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("execution_mode")) != "PRODUCTION":
            continue
        skill = str(row.get("skill") or "")
        recorded = str(row.get("recorded_at") or "")
        if skill == "NAVIGATE_INFANTRY_CAMP" and recorded >= "2026-09-21T16:00":
            rows.append(("nav-fail " + recorded[11:16], row.get("after_screenshot")))
        elif skill == "OPEN_INFANTRY_TRAINING":
            rows.append(("training-page " + recorded[11:16], row.get("after_screenshot")))
    out = []
    for label, raw in rows:
        if not raw:
            continue
        path = Path(str(raw))
        out.append((label, path))
    return out


def build_ocr():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    module_path = Path(config["ocr"]["module_path"])
    if not module_path.exists():
        return None
    return OCRService(ResilientOCRBackend(RapidOCRBackend(module_path)))


def main() -> int:
    ocr = build_ocr()
    if ocr is None:
        print("OCR module path missing in config/v2.json - cannot measure")
        return 2

    for label, path in collect_frames():
        print("=" * 74)
        print(label, "|", path.name)
        if not path.exists():
            print("   MISSING ON DISK")
            continue
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        result = ocr.recognize(path)
        rows = []
        for token in result.tokens:
            if not token.box or token.confidence < MIN_CONFIDENCE:
                continue
            xs = [float(point[0]) for point in token.box]
            ys = [float(point[1]) for point in token.box]
            cx = (min(xs) + max(xs)) / 2.0 / width
            cy = (min(ys) + max(ys)) / 2.0 / height
            if cy >= MIN_Y:
                rows.append((cy, token.text.strip(), token.confidence, cx))
        if not rows:
            print("   nothing readable below the HUD")
        for cy, text, confidence, cx in sorted(rows):
            print(f"   y={cy:.3f} x={cx:.3f} px=({round(cx * width):>3}, {round(cy * height):>4})"
                  f"  conf={confidence:.3f}  {text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
