"""Register the march-recall dialog templates from the 2026-09-14 live frame.

``RECALL_MARCH`` is registered but has no verifier, so the live loop can never
dispatch it.  The operator directive of 2026-09-14 explicitly allows recalling
marches at any time (including to free a slot for a verification experiment),
so the recall path has to become dispatchable.

Measured on the live dialog frame (720x1280):
  - title 「召回」        OCR box px (325,429)-(395,469), horizontally centred
  - confirm 「确定」      OCR box px (472,766)-(552,813)

The templates are drawn from the dialog itself, so the crop is authoritative
rather than re-drawn.  Both records carry ``source`` and ``provenance`` like the
other live-reviewed templates in the manifest.
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
FRAME = ROOT / "dataset/truth_audit/march_recall_20260914_135242/02_after_row1_tap.png"
OUT_DIR = ROOT / "dataset/candidate/march_recall"

# box: (left, top, right, bottom) in pixels on the 720x1280 dialog frame.
TEMPLATES = {
    "POPUP_TITLE_RECALL": {
        "box": (318, 421, 403, 477),
        "note": "dialog title 召回; the only place this string appears",
    },
    "BTN_CONFIRM_RECALL": {
        "box": (438, 744, 586, 832),
        "note": "the blue 确定 button of the recall dialog; tap target",
    },
}


def main() -> int:
    if not FRAME.is_file():
        raise SystemExit(f"missing dialog frame: {FRAME}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with Image.open(FRAME) as image:
        image = image.convert("RGB")
        width, height = image.size
        crops = {}
        for semantic, spec in TEMPLATES.items():
            box = spec["box"]
            crop = image.crop(box)
            path = OUT_DIR / f"{semantic.lower()}__live_recall_dialog.png"
            crop.save(path)
            crops[semantic] = (path, box, crop)
            print(f"{semantic}: {crop.size} -> {path.name}")
        review = image.copy()
        draw = ImageDraw.Draw(review)
        for semantic, (_path, box, _crop) in crops.items():
            draw.rectangle(box, outline=(255, 0, 0), width=2)
        review.crop((0, int(0.28 * height), width, int(0.70 * height))).resize(
            (width, int(0.42 * height)), Image.LANCZOS
        ).save(OUT_DIR / "_review_dialog_boxes.png")

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    existing = {(str(r.get("semantic")), str(r.get("template_path"))) for r in records}
    added = 0
    for semantic, spec in TEMPLATES.items():
        path, box, _crop = crops[semantic]
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
            "source": "live_20260914_march_recall_dialog/02_after_row1_tap.png",
            "provenance": "LIVE_CLIENT",
            "note": spec["note"],
        })
        added += 1
    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest records: {len(records)} (+{added})")

    # Replay verification: both templates must match their own dialog frame and
    # must NOT match a normal map frame (negative control).
    from winter_agent_v2.vision import SemanticROIVision

    semantic = SemanticROIVision(MANIFEST)
    map_frame = ROOT / "dataset/truth_audit/march_recall_20260914_135242/01_map_before.png"
    for name in TEMPLATES:
        on_dialog = semantic.find(FRAME, name)
        on_map = semantic.find(map_frame, name)
        print(
            f"  {name}: dialog distance={None if on_dialog is None else on_dialog.distance} "
            f"| map distance={None if on_map is None else on_map.distance} (must be rejected)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
