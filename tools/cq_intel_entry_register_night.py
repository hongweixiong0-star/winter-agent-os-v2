"""Register a second (night-theme) template for BTN_OPEN_INTEL_WILD_HUD.

Measured 2026-09-16: the same world-map HUD control scores 0.739-0.979 in the
day theme but only 0.390-0.448 on the two night frames
(2026-09-14T13:12Z, 2026-09-14T13:13Z), while its position is identical
(centre 0.925, 0.6727).  So theme and position are two separate axes of
variation, and one day-colour template cannot cover both.

This script crops the control from the night frame at its measured position and
registers it as a second template of the same semantic.  It does not touch the
existing template or any route.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
SEMANTIC = "BTN_OPEN_INTEL_WILD_HUD"
CANDIDATE_DIR = ROOT / "dataset/candidate/intel_wild_entry_v2"

# The two night frames the corpus tagged as positives (page=MAP) that no day
# template covers.  Both place the control at the registered ROI.
NIGHT_PARENTS = [
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260914T131236556151.png",
    "dataset/raw/live_runtime/live_runtime_step_001_before_20260914T131355670095.png",
]


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records: list[dict] = payload["records"]
    day = next(r for r in records if r.get("semantic") == SEMANTIC)
    roi = day["roi_norm"]
    print("existing templates for %s: %d" % (SEMANTIC, sum(1 for r in records if r.get("semantic") == SEMANTIC)))

    added = 0
    for index, rel in enumerate(NIGHT_PARENTS, 1):
        parent = ROOT / rel
        if not parent.exists():
            print("MISSING", rel)
            continue
        with Image.open(parent) as opened:
            image = opened.convert("RGB")
        width, height = image.size
        bounds = (
            round(roi["x_norm"] * width),
            round(roi["y_norm"] * height),
            round((roi["x_norm"] + roi["w_norm"]) * width),
            round((roi["y_norm"] + roi["h_norm"]) * height),
        )
        crop = image.crop(bounds)
        template_id = "btn_open_intel_wild_hud__night_%d__0" % index
        target = CANDIDATE_DIR / (template_id + ".png")
        crop.save(target)
        print("wrote %s  %s  from %s at %s" % (target.name, crop.size, Path(rel).name, bounds))

        record = dict(day)
        record.update(
            template_id=template_id,
            template_path=str(target).replace("\\", "/"),
            parent_screenshot=str(parent).replace("\\", "/"),
            source="LIVE_CLIENT",
            status="CANDIDATE",
        )
        if not any(r.get("template_id") == template_id for r in records):
            records.append(record)
            added += 1

    payload["count"] = len(records)
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("manifest records: %d (added %d)" % (len(records), added))
    print("updated_at note: %s" % datetime.now(timezone.utc).isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
