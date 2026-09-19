"""Register a tight plate template for BTN_OPEN_INTEL_WILD_HUD.

Follows the same shape as `tools/cq_intel_entry_register_night.py`, which added the day/night
variants for this control on 2026-09-16.  That tool's own note names the axis it was fixing --
"theme and position are two separate axes of variation" -- and the frames measured tonight show a
third: the *background* behind the HUD, which turns from light terrain to near-black unexplored map
when the run swipes the map five times before opening intel.

The three existing records are crops of 86x96 pixels around a control whose own plate is 69x68, so
most of what they encode is background.  Measured with this project's own phash and hamming:

    current ROI size 86x96 at (623,813)   d = 30 across the two frames   (threshold is 24)
    the plate itself 69x68 at (629,922)   d = 12 across the same two     under the threshold
    and over 1257 corpus frames the plate hits 321 times across brightness 96..226, including a
    daytime frame, while the eight known non-map frames still miss

So this is one template rather than another variant, and **the threshold is not touched**: 24 still
separates present from absent, and the measured distances are 6 or less against it.

Additive on purpose: the existing records stay.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"
CANDIDATE_DIR = ROOT / "dataset/candidate/intel_wild_entry_v2"

# The plate's own extent, measured on the failure frame (its background is black there, so the
# plate is the only blue in the picture): (629,922)-(698,990) on a 720x1280 frame.
PLATE = (629, 922, 698, 990)
FRAME_W, FRAME_H = 720, 1280

# A frame where the control was tapped successfully and the client moved to INTEL.
PARENT = ("dataset/raw/live_runtime/spend_handover/"
          "spend_handover_step_006_before_20260919T153324863150.png")


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records: list[dict] = payload["records"]
    existing = [r for r in records if r.get("semantic") == SEMANTIC]
    if not existing:
        print(f"no record for {SEMANTIC}; refusing to invent one")
        return 1
    print(f"existing templates for {SEMANTIC}: {len(existing)}")

    parent = ROOT / PARENT
    if not parent.is_file():
        print("MISSING parent frame:", PARENT)
        return 1
    with Image.open(parent) as opened:
        image = opened.convert("RGB")
    crop = image.crop(PLATE)

    template_id = "btn_open_intel_wild_hud__plate_tight__0"
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    target = CANDIDATE_DIR / f"{template_id}.png"
    crop.save(target)
    print(f"wrote {target.name}  {crop.size}  from {Path(PARENT).name} at {PLATE}")

    record = dict(existing[0])
    record.update(
        template_id=template_id,
        template_path=str(target).replace("\\", "/"),
        parent_screenshot=str(parent).replace("\\", "/"),
        source="LIVE_CLIENT",
        status="CANDIDATE",
        roi_norm={
            "x_norm": round(PLATE[0] / FRAME_W, 4),
            "y_norm": round(PLATE[1] / FRAME_H, 4),
            "w_norm": round((PLATE[2] - PLATE[0]) / FRAME_W, 4),
            "h_norm": round((PLATE[3] - PLATE[1]) / FRAME_H, 4),
        },
    )
    if any(r.get("template_id") == template_id for r in records):
        print("already registered; replacing in place")
        records[:] = [record if r.get("template_id") == template_id else r for r in records]
    else:
        records.append(record)

    payload["count"] = len(records)
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"manifest records: {len(records)}  roi_norm={record['roi_norm']}")
    print("updated_at note:", datetime.now(timezone.utc).isoformat())
    return 0


raise SystemExit(main())
