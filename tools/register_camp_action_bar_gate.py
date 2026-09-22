"""Register the selected-building action bar as a gate, and prove the gate separates.

Why a gate and not just the reading
-----------------------------------
Reading the bar on every HOME frame broke a contract this codebase keeps on purpose:
``tests/test_ocr.py::test_hybrid_is_template_first`` pins that **a page the template
layer fully resolves is not OCR'd**, because HOME is the most common frame in the loop.
That test caught the first version of this work (backend calls 0 -> 1 on a plain city
frame), and it was right to.

No existing template can serve as the gate: on the action-bar frames every registered
control scores NO MATCH, ``BTN_UPGRADE`` included -- which is the gate the 仓库 render
uses.  A cheap *pixel* gate was tried first and measured, not assumed: the three controls
are pale plates on a dimmed city, and "fraction of pixels with min channel >= 185" over
their own band separates nothing (action-bar frames 0.037-0.363, ordinary HOME frames
0.003-0.944 -- see tools/probe_action_bar_gate.py).  So the gate is the project's own
mechanism: a template.

What is cropped, and why that and not the plate
-----------------------------------------------
The plates are translucent, so their pixels carry whatever city is behind them and a
hash over one would move with the camera.  The icon drawn inside the middle plate is
opaque, and measured on the twelve action-bar frames (720x1280):

    white up-arrow icon   x 338-381   y 860-903   1043-1044 px   on every frame

Two frames report a wider white bbox because snow on the ground passes the same
threshold; the icon's own 44x44 box is identical on all twelve.  That box is the crop.

Usage
-----
    python tools/register_camp_action_bar_gate.py            # register, then measure
    python tools/register_camp_action_bar_gate.py --check     # measure only

``--check`` is the useful one after any client change: it prints the distance on every
action-bar frame (must be inside the gate) and on frames that must NOT match.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
OUT_DIR = ROOT / "dataset" / "candidate" / "camp_action_bar_20260922"

#: The kept evidence copy, not the prunable capture: a template whose parent frame has
#: been deleted cannot be re-cut, and the retention policy prunes dataset/raw.
SOURCE_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                / "camp_selected_action_bar__shield_camp__live_20260922T0747.png")
SOURCE_BOX = (338, 860, 382, 904)          # the white up-arrow, measured above
SEMANTIC = "TARGET_CAMP_ACTION_BAR"
TEMPLATE_ID = "target_camp_action_bar__shield_camp__20260922"

GOLD_RING_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                   / "camp_gold_ring_render__shield_camp__live_20260921T1307.png")
TRAINING_PAGE_FRAME = (ROOT / "dataset/truth_audit/camp_action_bar_20260922"
                       / "training_page__three_camp_tabs_and_queue__live_20260921T0953.png")


def action_bar_frames() -> list[tuple[str, Path]]:
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(episode.get("execution_mode")) != "PRODUCTION":
            continue
        if str(episode.get("skill")) != "NAVIGATE_INFANTRY_CAMP":
            continue
        recorded = str(episode.get("recorded_at") or "")
        after = episode.get("after_screenshot")
        if recorded >= "2026-09-21T16:00" and after:
            rows.append((recorded[11:16], Path(str(after))))
    return rows


def home_frames_that_must_not_match() -> list[tuple[str, Path]]:
    """PRODUCTION frames that ended on HOME without the action bar."""
    rows = []
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            episode = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(episode.get("execution_mode")) != "PRODUCTION":
            continue
        if str(episode.get("skill")) == "NAVIGATE_INFANTRY_CAMP":
            continue
        state = episode.get("state_after") or {}
        after = episode.get("after_screenshot")
        if state.get("page") == "HOME" and after:
            rows.append((str(episode.get("recorded_at") or "")[5:16], Path(str(after))))
    return rows[:: max(1, len(rows) // 10)][:10]


def register() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE_FRAME) as image:
        image = image.convert("RGB")
        width, height = image.size
        if (width, height) != (720, 1280):
            raise SystemExit(f"{SOURCE_FRAME.name}: unexpected size {image.size}")
        left, top, right, bottom = SOURCE_BOX
        crop = image.crop(SOURCE_BOX)
    template_path = OUT_DIR / f"{TEMPLATE_ID}.png"
    crop.save(template_path)
    print(f"wrote {template_path.relative_to(ROOT)}  {crop.size}")

    roi = {
        "x_norm": round(left / width, 6),
        "y_norm": round(top / height, 6),
        "w_norm": round((right - left) / width, 6),
        "h_norm": round((bottom - top) / height, 6),
    }
    note = (
        "The selected building's action bar, as a GATE for the OCR reading in "
        "ocr.read_selected_building_actions: the middle control's opaque icon, cropped "
        "from the 2026-09-22 render where all three plates are translucent.  Measured "
        "identical at x338-381 y860-903 on all twelve live frames that failed "
        "NAVIGATE_INFANTRY_CAMP between 16:24 and 23:47; it gates, it is not the tap "
        "target -- the 训练 label read off the frame is, so a moved bar still taps right."
    )
    existing = next(
        (r for r in records
         if r.get("semantic") == SEMANTIC and r.get("template_id") == TEMPLATE_ID),
        None,
    )
    record = {
        "semantic": SEMANTIC,
        "template_path": str(template_path.relative_to(ROOT)).replace("\\", "/"),
        "roi_norm": roi,
        "source": str(SOURCE_FRAME.relative_to(ROOT)).replace("\\", "/"),
        "provenance": "LIVE_CLIENT",
        "reviewed_from": "LIVE_CLIENT_SCREENSHOT",
        "confidence": 0.99,
        "status": "CANDIDATE",
        "template_id": TEMPLATE_ID,
        "parent_screenshot": str(SOURCE_FRAME.relative_to(ROOT)).replace("\\", "/"),
        "width": crop.size[0],
        "height": crop.size[1],
        "note": note,
    }
    if existing is not None:
        existing.update(record)
        print(f"updated {SEMANTIC}")
    else:
        records.append(record)
        print(f"added   {SEMANTIC}")
    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest records: {len(records)}")


def check() -> None:
    from winter_agent_v2.vision import SemanticROIVision

    vision = SemanticROIVision(MANIFEST)
    threshold = getattr(vision, "semantic_max_distance", {}).get(SEMANTIC, 6)
    print(f"gate for {SEMANTIC}: max_distance {threshold}")
    print("=" * 70)
    print("MUST MATCH  (the frames the route died on)")
    misses = 0
    for tag, path in action_bar_frames():
        if not path.exists():
            print(f"   {tag}  MISSING ON DISK")
            continue
        match = vision.find(path, SEMANTIC)
        state = "hit " if match else "MISS"
        if not match:
            misses += 1
        distance = getattr(match, "distance", None)
        print(f"   {tag}  {state} distance={distance}")
    print("=" * 70)
    print("MUST NOT MATCH  (HOME frames without the bar, and other renders)")
    wrong = []
    negatives = home_frames_that_must_not_match()
    for tag, path in negatives + [("gold-ring render", GOLD_RING_FRAME),
                                  ("training page", TRAINING_PAGE_FRAME)]:
        if not path.exists():
            print(f"   {tag}  MISSING ON DISK")
            continue
        match = vision.find(path, SEMANTIC)
        if match is not None:
            wrong.append((tag, getattr(match, "distance", None)))
        print(f"   {tag:<18} {'hit' if match else 'no match':<9}"
              f" distance={getattr(match, 'distance', None)}")
    print()
    print(f"action-bar frames missed: {misses}")
    print(f"false positives: {wrong if wrong else 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="measure only, change nothing")
    args = parser.parse_args()
    if not args.check:
        register()
    check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
