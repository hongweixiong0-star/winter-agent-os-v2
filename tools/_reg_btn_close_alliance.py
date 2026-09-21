"""Register the measured close-X of the alliance chest layer as a BTN_CLOSE template.

Why this exists, measured rather than argued.

On 2026-09-21 the AUTO worker stopped a whole cycle with SAFE_BACK_NOT_PROVEN: the goal
KEEP_TRAINING_PRODUCTIVE found the client on the alliance chest layer (page ALLIANCE), and
the project's one leave-a-foreign-page hop is a Back. Measured on the frame:

    step_001_before  page ALLIANCE -> after PRESS_BACK page ALLIANCE, confidence 0.98

Back does not move this layer at all -- it is a sub-page with its own X in the top-right
corner, not a page with a back arrow. The existing BTN_CLOSE records cannot help either:
all three sit at x_norm 0.805-0.835, while the X on this layer measures x 668-695 y 26-50
of 720x1280 (x_norm 0.928-0.965, y_norm 0.020-0.039) -- outside every registered ROI, so
the phash comparison there crops empty background and can never match.

This registers the crop taken from that same live frame, at the ROI it was measured on.

    self-match    ccoeff 1.000 at (682, 38)
    separation    24 corpus frames without the X measured 0.432-0.580

Idempotent: a re-run with the same template_id changes nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"

SHOT_REL = (
    "dataset/raw/control_panel/runtime_auto/20260921_142158_026793/"
    "20260921_142158_026793_step_001_before_20260921T062201175425.png"
)
TPL_REL = "dataset/candidate/templates/btn_close__alliance_chest_layer__0.png"

#: The crop, in pixels of the 720x1280 frame. The white X itself measured x 668-695
#: y 26-50; 8 px of padding on each side carries the dark title bar the X sits on,
#: which is what the phash path compares against.
CROP = (660, 18, 44, 40)
FRAME_W, FRAME_H = 720, 1280

TEMPLATE_ID = "btn_close__alliance_chest_layer__0"


def main() -> int:
    shot = ROOT / SHOT_REL
    template = ROOT / TPL_REL
    if not shot.exists():
        raise SystemExit(f"parent frame missing: {shot}")
    if not template.exists():
        raise SystemExit(f"template missing: {template}")

    x0, y0, w, h = CROP
    record = {
        "confidence": 0.99,
        "height": h,
        "parent_screenshot": str(shot),
        "parent_sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
        "roi_norm": {
            "h_norm": round(h / FRAME_H, 4),
            "w_norm": round(w / FRAME_W, 4),
            "x_norm": round(x0 / FRAME_W, 4),
            "y_norm": round(y0 / FRAME_H, 4),
        },
        "semantic": "BTN_CLOSE",
        "source": "LIVE_CLIENT_REPLAY_VERIFIED",
        "status": "CANDIDATE",
        "template_id": TEMPLATE_ID,
        "template_path": str(template),
        "width": w,
    }

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = manifest["records"]
    if any(r.get("template_id") == TEMPLATE_ID for r in records):
        print(f"{TEMPLATE_ID} already registered; manifest unchanged ({manifest['count']} records)")
        return 0
    records.append(record)
    manifest["count"] = len(records)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"registered {TEMPLATE_ID}: roi {record['roi_norm']}, count -> {manifest['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
