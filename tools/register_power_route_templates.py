"""Re-register the 战力 route from the 2026-09-17 live frames.

Why this exists
---------------
`TRAIN` and `BUILD` are the capabilities the operator asked for, and both were
blocked on one thing: the vision never produced `world.training` /
`world.building` on today's client.  That is not a reasoning bug -- the whole
route existed in `brain.py` (lines 243-246 and 446-456) and in
`LiveRuntime.VERIFIED_ATOMIC`:

    HOME --tap power--> POPUP/POWER_OVERVIEW --实力详情--> POPUP/POWER_DETAILS
         --提升--> HOME (camp focused) --训练--> TRAINING

It was blocked because every template that would populate those readings was
cropped from 2026-09-08 frames of a *different account* (68x the power, a
different avatar, a zoomed-out city camera).  Measured 2026-09-17 on today's live
HOME frame:

    BTN_OPEN_POWER_OVERVIEW            MISS
    TARGET_INFANTRY_CAMP_HIGHLIGHTED   MISS
    BTN_OPEN_TRAINING_FROM_CAMP        MISS
    PAGE_TRAINING_INFANTRY             MISS
    BTN_START_TRAINING                 MISS

`tools/probe_power_route.py` then walked the route on the live client and every
hop was observed.  This tool turns those frames into records.

Two defects it fixes rather than reproduces
-------------------------------------------
1. **The power entry was a value-dependent template.**  The old
   `BTN_OPEN_POWER_OVERVIEW` crop (x 97..302) contained the account's power
   NUMBER, so it could only ever match the account it was cut from.  Measured: a
   crop of the fist icon alone has phash distance **2** between today's frame
   (826,444) and the 2026-09-08 frame (57,083,909) -- a 68x difference in the
   value -- while the old wide crop sits at **28** (threshold 8), and non-city
   frames sit at **30**.  One icon record covers both accounts.
2. **The 实力详情 panel's row positions move with the account.**
   `BTN_POWER_TROOP_IMPROVE` was registered at y 538..608 on 2026-09-08, when the
   advanced account's panel drew seven rows (建筑/部队/英雄/英雄装备/领主装备/
   领主宝石/科技).  Today's account draws five (no 领主装备/领主宝石), so the
   panel is shorter and 部队实力's 提升 button is at y 631..676 -- the old ROI now
   lands on 建筑实力's row.  A row-relative ROI cannot be right for both layouts,
   so the new record is registered alongside the old one and the gate below proves
   which one wins on today's frame (`find()` takes the minimum distance).

Usage
-----
    python tools/register_power_route_templates.py
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
EVIDENCE = ROOT / "dataset" / "truth_audit" / "power_route_20260917"
OUT_DIR = ROOT / "dataset" / "candidate" / "power_route_20260917"

HOME_FRAME = EVIDENCE / "build_route_20260916_233614_00_before.png"
OVERVIEW_FRAME = EVIDENCE / "build_route_20260916_233614_01_after_tap_115_72.png"
DETAILS_FRAME = EVIDENCE / "build_route_20260916_233614_02_after_tap_360_660.png"
BUILDING_FRAME = EVIDENCE / "build_route_20260916_233614_03_after_tap_605_550.png"
CAMP_FRAME = EVIDENCE / "power_route_hop3_20260916_233330_01_after_tap_605_653.png"
TRAINING_FRAME = EVIDENCE / "power_route_hop4_20260916_233412_01_after_tap_526_874.png"

# The 2026-09-08 frames the old records were cropped from -- kept as negative
# controls for the *new* records where the control is not drawn the same way.
OLD_HOME = ROOT / "dataset" / "raw" / "live_20260908_next_batch_home.png"
OLD_OVERVIEW = ROOT / "dataset" / "raw" / "live_20260908_power_entry.png"
OLD_DETAILS = ROOT / "dataset" / "raw" / "live_20260908_power_details.png"

SPECS: dict[str, dict] = {
    # (left, top, right, bottom) in 720x1280 frame pixels.
    "BTN_OPEN_POWER_OVERVIEW": {
        "box": (99, 50, 132, 95),
        "source_frame": HOME_FRAME,
        "template_id": "btn_open_power_overview__live_20260917_icon",
        "note": ("the fist icon only, deliberately excluding the power NUMBER: the "
                 "control's appearance is fixed but the digits are not, and the old "
                 "crop (x 97..302) could therefore only ever match the account it was "
                 "cut from (measured phash d=2 between two accounts for this crop "
                 "versus d=28 for the old one, threshold 8)"),
        "evidence": "power_route_20260917/build_route_..._00_before.png",
    },
    "POPUP_POWER_OVERVIEW": {
        "box": (20, 122, 700, 198),
        "source_frame": OVERVIEW_FRAME,
        "template_id": "popup_power_overview__live_20260917_titlebar",
        "note": ("title bar strip of the 加成总览 panel (title + close button).  The "
                 "body is deliberately excluded: it lists 部队实力/建筑实力/... with "
                 "the account's numbers, which is the defect the power entry had."),
        "evidence": "power_route_20260917/build_route_..._01_after_tap_115_72.png",
    },
    "BTN_OPEN_POWER_DETAILS": {
        "box": (272, 636, 448, 685),
        "source_frame": OVERVIEW_FRAME,
        "template_id": "btn_open_power_details__live_20260917",
        "note": ("the blue 实力详情 button at the bottom of the 加成总览 panel "
                 "(OCR: 277..443 x 641..680)"),
        "evidence": "power_route_20260917/build_route_..._01_after_tap_115_72.png",
    },
    "POPUP_POWER_DETAILS": {
        "box": (20, 246, 700, 322),
        "source_frame": DETAILS_FRAME,
        "template_id": "popup_power_details__live_20260917_titlebar",
        "note": ("title bar strip of the 实力详情 panel (title + close button).  The "
                 "body holds the per-category numbers and must not be in the crop."),
        "evidence": "power_route_20260917/build_route_..._02_after_tap_360_660.png",
    },
    "BTN_POWER_TROOP_IMPROVE": {
        "box": (563, 625, 648, 682),
        "source_frame": DETAILS_FRAME,
        "template_id": "btn_power_troop_improve__live_20260917_five_rows",
        "note": ("部队实力's 提升 button (OCR: 569..642 x 631..676).  Registered "
                 "alongside the 2026-09-08 record rather than replacing it, because "
                 "the row's y depends on how many categories the account has "
                 "unlocked -- seven rows on 2026-09-08 (y 538..608) and five today "
                 "(y 631..676).  The gate below reports which record wins on "
                 "today's frame; that ROI is also the tap target."),
        "evidence": "power_route_20260917/build_route_..._02_after_tap_360_660.png",
    },
    "BTN_OPEN_TRAINING_FROM_CAMP": {
        "box": (376, 705, 676, 1005),
        "source_frame": CAMP_FRAME,
        "template_id": "btn_open_training_from_camp__live_20260917_camp_focus",
        "note": ("the 训练 button of the focused-camp radial menu, framed so the crop "
                 "is centred on the button (tap centre (526,855)) while including "
                 "enough of the fixed ring around it to survive the client's "
                 "ANIMATED overlay: the button carries a pulsing highlight ring and a "
                 "tutorial pointing-hand, so a crop of the button alone swung between "
                 "phash d=12 and d=22 across one run (2026-09-17 07:41Z) and made "
                 "NAVIGATE_INFANTRY_CAMP burn its full refresh budget (~21 s) to "
                 "verify -- by which time the overlay had faded and the loop had to "
                 "re-walk the whole route.  This crop measures 0..8 on all seven "
                 "frames of that run while plain HOME is 16, the training page 36 and "
                 "the building panel 26.  The 详情 button is the most stable part of "
                 "the ring (d=0..2) but it cannot be used as the tap target, and the "
                 "executor only supports TAP_SEMANTIC -- no coordinate action -- so "
                 "the tap point has to come from a crop centred on 训练."),
        "evidence": "power_route_20260917/power_route_hop3_..._01_after_tap_605_653.png",
    },
}

# Reported, not registered: these already resolve today's client, which is why the
# last two hops of the route needed no new record.  The gate prints them so the
# claim is checkable rather than asserted.
ALREADY_WORKING = [
    "TARGET_INFANTRY_CAMP_HIGHLIGHTED",
    "BTN_OPEN_TRAINING_FROM_CAMP",
    "BTN_TRAINING_MENU_LABEL",
    "PAGE_TRAINING_INFANTRY",
    "BTN_START_TRAINING",
]

ROUTE_FRAMES = {
    "HOME": HOME_FRAME,
    "OVERVIEW": OVERVIEW_FRAME,
    "DETAILS": DETAILS_FRAME,
    "CAMP_FOCUSED": CAMP_FRAME,
    "TRAINING": TRAINING_FRAME,
    "BUILDING_FOCUSED": BUILDING_FRAME,
}


def main() -> int:
    for path in (HOME_FRAME, OVERVIEW_FRAME, DETAILS_FRAME, BUILDING_FRAME, CAMP_FRAME,
                 TRAINING_FRAME):
        if not path.is_file():
            raise SystemExit(f"missing evidence frame: {path}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]

    added = []
    for semantic, spec in SPECS.items():
        frame = spec["source_frame"]
        with Image.open(frame) as image:
            image = image.convert("RGB")
            width, height = image.size
            if (width, height) != (720, 1280):
                raise SystemExit(f"{frame.name}: unexpected size {image.size}")
            left, top, right, bottom = spec["box"]
            crop = image.crop(spec["box"])
        template_path = OUT_DIR / f"{spec['template_id']}.png"
        crop.save(template_path)

        roi = {
            "x_norm": round(left / width, 6),
            "y_norm": round(top / height, 6),
            "w_norm": round((right - left) / width, 6),
            "h_norm": round((bottom - top) / height, 6),
        }
        existing = next((r for r in records
                         if r.get("semantic") == semantic
                         and r.get("template_path") == str(template_path)), None)
        if existing is not None:
            existing.update({"roi_norm": roi, "note": spec["note"]})
            print(f"updated {semantic}")
            continue
        records.append({
            "semantic": semantic,
            "template_path": str(template_path),
            "roi_norm": roi,
            "source": "power_route_20260917",
            "provenance": "LIVE_CLIENT",
            "confidence": 0.99,
            "status": "CANDIDATE",
            "template_id": spec["template_id"],
            "parent_screenshot": str(frame),
            "width": crop.size[0],
            "height": crop.size[1],
            "note": spec["note"],
            "evidence": spec["evidence"],
        })
        added.append(semantic)
        print(f"added   {semantic:<26} {crop.size} roi={roi}")

    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\nmanifest records: {len(records)} (+{len(added)})")

    # ---- annotated evidence, so the crops can be re-checked by eye -----------
    overlay = Image.open(DETAILS_FRAME).convert("RGB")
    draw = ImageDraw.Draw(overlay)
    for semantic in ("POPUP_POWER_DETAILS", "BTN_POWER_TROOP_IMPROVE"):
        left, top, right, bottom = SPECS[semantic]["box"]
        draw.rectangle((left, top, right, bottom), outline=(255, 0, 0), width=2)
    overlay.save(OUT_DIR / "details_frame_with_crops.png")
    overlay2 = Image.open(OVERVIEW_FRAME).convert("RGB")
    draw2 = ImageDraw.Draw(overlay2)
    for semantic in ("POPUP_POWER_OVERVIEW", "BTN_OPEN_POWER_DETAILS"):
        left, top, right, bottom = SPECS[semantic]["box"]
        draw2.rectangle((left, top, right, bottom), outline=(255, 0, 0), width=2)
    overlay2.save(OUT_DIR / "overview_frame_with_crops.png")

    from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

    semantic = SemanticROIVision(MANIFEST)
    world = SemanticWorldVision(MANIFEST)

    print("\nroute check -- each hop's own frame, and the frame before it:")
    for name, frame in ROUTE_FRAMES.items():
        state = world.observe(frame)
        print(f"  {name:<16} page={state.page.value:<8} popup={state.popup} "
              f"training={json.dumps(state.training, ensure_ascii=False)}")
    for sem in list(SPECS) + ALREADY_WORKING:
        row = []
        for name, frame in ROUTE_FRAMES.items():
            hit = semantic.find(frame, sem)
            row.append(f"{name}=" + ("-" if hit is None else f"d{hit.distance}"))
        print(f"  {sem:<32} " + "  ".join(row))

    print("\nwhich record wins for BTN_POWER_TROOP_IMPROVE on today's frame "
          "(the winning ROI is also the tap target):")
    candidates = [r for r in semantic.records if r["semantic"] == "BTN_POWER_TROOP_IMPROVE"]
    for row in candidates:
        with Image.open(DETAILS_FRAME) as image:
            w, h = image.size
            roi = row["roi_norm"]
            bounds = (round(roi["x_norm"] * w), round(roi["y_norm"] * h),
                      round((roi["x_norm"] + roi["w_norm"]) * w),
                      round((roi["y_norm"] + roi["h_norm"]) * h))
        hit = semantic.find(DETAILS_FRAME, "BTN_POWER_TROOP_IMPROVE")
        print(f"  roi_px={bounds} source={row.get('source')}")
    winner = semantic.find(DETAILS_FRAME, "BTN_POWER_TROOP_IMPROVE")
    if winner is not None:
        cx = winner.center_norm[0] * 720
        cy = winner.center_norm[1] * 1280
        print(f"  -> winner d={winner.distance} centre_px=({cx:.0f},{cy:.0f}) "
              f"(部队实力's 提升 is OCR-measured at 569..642 x 631..676, centre (606,654))")

    print("\nnegatives (the 2026-09-08 frames of the other account):")
    for label, frame, sem in (("old HOME", OLD_HOME, "BTN_OPEN_POWER_OVERVIEW"),
                              ("old overview", OLD_OVERVIEW, "POPUP_POWER_OVERVIEW"),
                              ("old details", OLD_DETAILS, "POPUP_POWER_DETAILS"),
                              ("old details", OLD_DETAILS, "BTN_POWER_TROOP_IMPROVE")):
        if not frame.is_file():
            print(f"  {label:<14} {sem:<28} (frame missing)")
            continue
        hit = semantic.find(frame, sem)
        status = "rejected" if hit is None else f"d={hit.distance}"
        print(f"  {label:<14} {sem:<28} {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
