"""Re-register the city daily-entry tap target from the 2026-09-16 live frame.

Why this exists
---------------
`OPEN_DAILY` (HOME -> DAILY) is the entry point of the whole daily-mission
capability, and on 2026-09-16T13:10Z the live loop recorded:

    skill OPEN_DAILY  action TAP_SEMANTIC BTN_OPEN_DAILY  backend ADB
    executed=false    error SEMANTIC_TARGET_NOT_VERIFIED

The semantic was registered on 2026-09-08 from `live_20260908_offline_after.png`
with a ROI of 94x102 px covering the icon *and* its surroundings.  Measured on
today's live HOME frame (tools/probe_daily_entry.py):

    BTN_OPEN_DAILY        MISS d=18  thr=8
    BTN_OPEN_EXPLORATION  HIT  d=0
    BTN_OPEN_ALLIANCE     HIT  d=8

so the frame is fine and only this template is stale.  Two things changed
between the two dates: the red claimable badge on the icon's top-right is gone,
and the city drawn behind the button is a different one.

What is registered and why this crop
------------------------------------
`tools/probe_daily_entry_gate.py` measured three candidate crops over the whole
3480-frame corpus (`dataset/raw`), using `BTN_OPEN_EXPLORATION` (the city
bottom-nav button) as the HOME proxy:

    candidate      recall(home, n=1104)   false-pos(n=2371)   old-parent frame
    existing           24  ( 2.2%)                0                d=2
    full_circle        41  ( 3.7%)                0                d=16  (miss)
    lower_band        587  (53.2%)                0                d=2
    left_half        1054  (95.5%)                1                d=6   (hit)

`left_half` is the left 2/3 of the icon circle.  It is the only candidate that
matches BOTH states of the control (badge absent today, badge present on the
2026-09-08 frame, d=6 <= 8), so one record covers both rather than needing a
per-state pair.  It is admitted by the corpus gate with 1 false positive out of
2371 non-HOME frames, and `OPEN_DAILY` is only ever dispatched while the page is
HOME, so that surface costs nothing.  The old record is kept, not deleted:
`find()` takes the minimum distance over records, so keeping it preserves the
frames it does cover.

Usage
-----
    python tools/register_daily_entry_template.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
FRAME = (ROOT / "dataset" / "raw" / "live_runtime"
         / "live_runtime_step_002_before_20260916T131040296670.png")
SECOND_FRAME = (ROOT / "dataset" / "raw" / "live_runtime"
                / "live_runtime_step_001_after_20260916T131031271889.png")
OLD_PARENT = ROOT / "dataset" / "raw" / "live_20260908_offline_after.png"

OUT_DIR = ROOT / "dataset" / "candidate" / "daily_entry_20260916"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "daily_entry_template_20260916"

SEMANTIC = "BTN_OPEN_DAILY"
BOX = (12, 1026, 50, 1084)  # left 2/3 of the icon circle, badge excluded

# Frames that must NOT resolve the target (negative controls): the world map and
# the daily page itself, where the entry is not drawn.
NEGATIVES = [
    ROOT / "dataset" / "raw" / "live_runtime" / "live_runtime_step_001_before_20260916T131018406166.png",
]


def main() -> int:
    for path in (FRAME, SECOND_FRAME, OLD_PARENT):
        if not path.is_file():
            raise SystemExit(f"missing frame: {path}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    with Image.open(FRAME) as image:
        image = image.convert("RGB")
        width, height = image.size
        if (width, height) != (720, 1280):
            raise SystemExit(f"unexpected frame size {image.size}; re-measure the box")
        crop = image.crop(BOX)
        template_path = OUT_DIR / "btn_open_daily__live_20260916_home.png"
        crop.save(template_path)
        print(f"template {crop.size} -> {template_path.relative_to(ROOT)}")

        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(BOX, outline=(255, 0, 0), width=2)
        cx = (BOX[0] + BOX[2]) // 2
        cy = (BOX[1] + BOX[3]) // 2
        draw.line((cx - 12, cy, cx + 12, cy), fill=(0, 255, 0), width=2)
        draw.line((cx, cy - 12, cx, cy + 12), fill=(0, 255, 0), width=2)
        overlay.save(ARCHIVE / "01_home_frame_with_crop_and_tap_point.png")
        overlay.crop((0, 950, 220, 1140)).resize((220 * 3, 190 * 3), Image.NEAREST).save(
            ARCHIVE / "02_zoom_crop_and_tap_point.png")
        print(f"tap point px=({cx},{cy}) norm=({cx / width:.4f},{cy / height:.4f})")
        print(f"icon circle measured centre ~(42,1052) radius ~32 -> tap inside: "
              f"{((cx - 42) ** 2 + (cy - 1052) ** 2) ** 0.5 < 32}")

    shutil.copy2(FRAME, ARCHIVE / "00_live_home_20260916T131040Z.png")

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    if any(r.get("semantic") == SEMANTIC and r.get("template_path") == str(template_path)
           for r in records):
        print("record already present; nothing added")
    else:
        records.append({
            "semantic": SEMANTIC,
            "template_path": str(template_path),
            "roi_norm": {
                "x_norm": round(BOX[0] / width, 6),
                "y_norm": round(BOX[1] / height, 6),
                "w_norm": round((BOX[2] - BOX[0]) / width, 6),
                "h_norm": round((BOX[3] - BOX[1]) / height, 6),
            },
            "source": "live_20260916T131040Z/live_runtime_step_002_before",
            "provenance": "LIVE_CLIENT",
            "confidence": 0.99,
            "status": "CANDIDATE",
            "template_id": "btn_open_daily_current_20260916",
            "parent_screenshot": str(FRAME),
            "width": crop.size[0],
            "height": crop.size[1],
            "note": ("left 2/3 of the city daily-entry icon (scroll + quill), badge "
                     "excluded so one record covers the claimable and claimed states; "
                     "old 2026-09-08 record kept for the frames it still covers"),
        })
        payload["count"] = len(records)
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"manifest records: {len(records)}")

    from winter_agent_v2.vision import SemanticROIVision

    semantic = SemanticROIVision(MANIFEST)
    print("\nreplay check (find() takes the minimum over all records):")
    for label, frame in [("live 2026-09-16 (source)", FRAME),
                         ("live 2026-09-16 (2nd)", SECOND_FRAME),
                         ("2026-09-08 old parent", OLD_PARENT)]:
        hit = semantic.find(frame, SEMANTIC)
        print(f"  {label:<24} -> "
              + ("None (rejected)" if hit is None
                 else f"d={hit.distance} roi={hit.roi} centre={hit.center_norm}"))
    for frame in NEGATIVES:
        if not frame.is_file():
            continue
        hit = semantic.find(frame, SEMANTIC)
        print(f"  negative {frame.name:<34} -> "
              + ("None (rejected)" if hit is None
                 else f"d={hit.distance} roi={hit.roi}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
