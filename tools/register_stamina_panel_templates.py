"""Register the stamina-source panel templates and the free claim control.

The operator directive of 2026-09-14 asks for free stamina to be claimed.  The
panel is reached by tapping the 领主体力 gauge on the world map and lists every
source: exactly one row is free (「丰盛的招待」 with a bare 「领取」 and no price)
while the rest carry a diamond price or a 「前往」 store link.

This tool templates the panel title, the free claim button, and — as a negative
control — the paid button, so a test can prove the free control can never be
confused with the paid one.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
FRAME = ROOT / "dataset/truth_audit/free_stamina_20260914_140601/02_after_stamina_tap.png"
OUT_DIR = ROOT / "dataset/candidate/stamina_sources"

# Panels measured on the live 720x1280 frame.
TEMPLATES = {
    "POPUP_TITLE_GET_MORE_STAMINA": {
        "box": (288, 109, 433, 165),
        "note": "panel title 获取更多; identifies the stamina-source panel",
    },
    "BTN_CLAIM_FREE_STAMINA": {
        "box": (540, 355, 622, 411),
        "note": "the only free control: bare 领取 with no price beside it",
    },
    "BTN_PAID_STAMINA_PURCHASE": {
        "box": (508, 626, 650, 676),
        "note": "NEGATIVE CONTROL: 购买并使用 ?300, must never be tapped",
    },
}


def main() -> int:
    if not FRAME.is_file():
        raise SystemExit(f"missing panel frame: {FRAME}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(FRAME) as image:
        image = image.convert("RGB")
        width, height = image.size
        crops = {}
        for semantic, spec in TEMPLATES.items():
            box = spec["box"]
            crop = image.crop(box)
            path = OUT_DIR / f"{semantic.lower()}__live_stamina_panel.png"
            crop.save(path)
            crops[semantic] = (path, box)
            print(f"{semantic}: {crop.size} -> {path.name}")
        review = image.copy()
        draw = ImageDraw.Draw(review)
        for semantic, (_path, box) in crops.items():
            colour = (255, 0, 0) if "PAID" not in semantic else (0, 0, 255)
            draw.rectangle(box, outline=colour, width=2)
        review.crop((140, 90, 720, 720)).save(OUT_DIR / "_review_panel_boxes.png")

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    existing = {(str(r.get("semantic")), str(r.get("template_path"))) for r in records}
    added = 0
    for semantic, spec in TEMPLATES.items():
        path, box = crops[semantic]
        if (semantic, str(path)) in existing:
            continue
        records.append({
            "semantic": semantic,
            "template_path": str(path),
            "roi_norm": {
                "x_norm": round(box[0] / width, 6),
                "y_norm": round(box[1] / height, 6),
                "w_norm": round((box[2] - box[0]) / width, 6),
                "h_norm": round((box[3] - box[1]) / height, 6),
            },
            "source": "live_20260914_stamina_sources/02_after_stamina_tap.png",
            "provenance": "LIVE_CLIENT",
            "note": spec["note"],
        })
        added += 1
    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest records: {len(records)} (+{added})")

    from winter_agent_v2.vision import SemanticROIVision

    semantic = SemanticROIVision(MANIFEST)
    map_frame = ROOT / "dataset/truth_audit/free_stamina_20260914_140601/01_map_before.png"
    for name in TEMPLATES:
        on_panel = semantic.find(FRAME, name)
        on_map = semantic.find(map_frame, name)
        print(
            f"  {name}: panel distance={None if on_panel is None else on_panel.distance} "
            f"| map distance={None if on_map is None else on_map.distance} (must be rejected)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
