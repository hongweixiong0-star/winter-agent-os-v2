"""Register the two states of the 任务 panel's 每日任务 tab from the live frames.

Why this exists
---------------
The 任务 panel (`OPEN_DAILY`'s target) is tabbed -- 章节任务 / 成长任务 / 每日任务 -- and the
client always opens it on the **first** tab.  `OCRPageClassifier` names the page from the
literal string `每日任务`, which is drawn on the tab **bar** even while another tab is
selected, so `page is DAILY` never meant "the daily tab is showing".  Every daily skill was
calibrated on the daily tab, and the consequence is measurable value lost: on 2026-09-16 the
account stood at activity 285 with the three chests at 80/160/270 already passed, and the
agent could not see any of it because it was reading the 章节任务 content.

Which tab is showing is a **drawn state**, so it is read as a template:

    unselected  dark blue pill, white label      -> the daily tab is NOT the one showing
    selected    light pill, dark blue label      -> the daily tab IS showing

Both crops come from the archived probe pair (same client, 40 s apart, one tap between
them), so the provenance is a real before/after rather than a re-drawn rectangle:

    dataset/truth_audit/daily_tasks_tab_20260916/01_before_20260916_134609.png  章节任务
    dataset/truth_audit/daily_tasks_tab_20260916/02_after_tap_20260916_134609.png 每日任务

Usage
-----
    python tools/register_daily_tab_template.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
OUT_DIR = ROOT / "dataset" / "candidate" / "daily_tab_20260916"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "daily_tab_20260916"

BEFORE = ROOT / "dataset" / "truth_audit" / "daily_tasks_tab_20260916" / "01_before_20260916_134609.png"
AFTER = ROOT / "dataset" / "truth_audit" / "daily_tasks_tab_20260916" / "02_after_tap_20260916_134609.png"

# Measured on the 720x1280 live frames: the 每日任务 pill spans x 481..704, y 1091..1173.
# The label inside it (OCR) is x 538..649, y 1117..1154, so the tap centre lands on the text.
#
# The box stops at x=670 on purpose.  The tab draws a red claimable BADGE at its
# bottom-right (measured 2026-09-16 on live_runtime_step_003_before_20260916T163330128917:
# badge centre ~(688, 1158), radius ~9), and the first version of this registration
# included it: the two records then matched only 3 of the 13 frames of that run, and
# exactly those frames where the badge was absent.  This is the same defect that froze
# `BTN_OPEN_DAILY` for eight days (a badge appearing changes the hash), so the corner is
# excluded here and one record covers both badge states.
BOX = (481, 1091, 670, 1173)

RECORDS = (
    {
        "semantic": "BTN_DAILY_TAB_TASKS",
        "frame": BEFORE,
        "template_id": "btn_daily_tab_tasks_unselected_20260916",
        "note": ("the 每日任务 tab drawn UNSELECTED (dark blue pill) -- this is the tap "
                 "target of SELECT_DAILY_TAB, taken while the panel sat on 章节任务"),
        "status": "CANDIDATE",
    },
    {
        "semantic": "TAB_DAILY_TASKS_SELECTED",
        "frame": AFTER,
        "template_id": "tab_daily_tasks_selected_20260916",
        "note": ("the same tab drawn SELECTED (light pill, dark label) -- the drawn state "
                 "the verifier reads, one tap after the frame above"),
        "status": "CANDIDATE",
    },
)


def main() -> int:
    for path in (BEFORE, AFTER):
        if not path.is_file():
            raise SystemExit(f"missing frame: {path}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    added = []
    updated = 0
    changed = False

    for spec in RECORDS:
        with Image.open(spec["frame"]) as source:
            image = source.convert("RGB")
            width, height = image.size
            if (width, height) != (720, 1280):
                raise SystemExit(f"unexpected frame size {image.size}; re-measure BOX")
            crop = image.crop(BOX)
            template_path = OUT_DIR / f"{spec['semantic'].lower()}__live_20260916.png"
            crop.save(template_path)
            overlay = image.copy()
            draw = ImageDraw.Draw(overlay)
            draw.rectangle(BOX, outline=(255, 0, 0), width=2)
            cx = (BOX[0] + BOX[2]) // 2
            cy = (BOX[1] + BOX[3]) // 2
            draw.line((cx - 14, cy, cx + 14, cy), fill=(0, 255, 0), width=2)
            draw.line((cx, cy - 14, cx, cy + 14), fill=(0, 255, 0), width=2)
            overlay.crop((440, 1060, 720, 1200)).resize((280 * 3, 140 * 3), Image.NEAREST).save(
                ARCHIVE / f"_{spec['semantic']}_box.png")
        print(f"{spec['semantic']}: {crop.size} -> {template_path.relative_to(ROOT)}  "
              f"tap centre px=({cx},{cy})")

        if any(r.get("semantic") == spec["semantic"] and r.get("template_path") == str(template_path)
               for r in records):
            # Re-registration replaces the geometry rather than duplicating the record:
            # the crop changed once already (badge exclusion, see BOX) and a second
            # record for the same semantic would silently double the tap-target set.
            for row in records:
                if (row.get("semantic") == spec["semantic"]
                        and row.get("template_path") == str(template_path)):
                    row["roi_norm"] = {
                        "x_norm": round(BOX[0] / width, 6),
                        "y_norm": round(BOX[1] / height, 6),
                        "w_norm": round((BOX[2] - BOX[0]) / width, 6),
                        "h_norm": round((BOX[3] - BOX[1]) / height, 6),
                    }
                    row["width"] = crop.size[0]
                    row["height"] = crop.size[1]
                    row["note"] = spec["note"]
            print("  record updated in place (crop changed)")
            updated += 1
            changed = True
            continue
        records.append({
            "semantic": spec["semantic"],
            "template_path": str(template_path),
            "roi_norm": {
                "x_norm": round(BOX[0] / width, 6),
                "y_norm": round(BOX[1] / height, 6),
                "w_norm": round((BOX[2] - BOX[0]) / width, 6),
                "h_norm": round((BOX[3] - BOX[1]) / height, 6),
            },
            "source": f"{spec['frame'].parent.name}/{spec['frame'].name}",
            "provenance": "LIVE_CLIENT",
            "confidence": 0.99,
            "status": spec["status"],
            "template_id": spec["template_id"],
            "parent_screenshot": str(spec["frame"]),
            "width": crop.size[0],
            "height": crop.size[1],
            "note": spec["note"],
        })
        added.append(spec["semantic"])
        changed = True

    if changed:
        payload["count"] = len(records)
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest records: {len(records)} (+{len(added)} new, {updated} updated)")

    from winter_agent_v2.vision import SemanticROIVision

    semantic = SemanticROIVision(MANIFEST)
    run = "dataset/raw/live_runtime"

    # Every frame below has a known tab state by construction, and the 2026-09-16T16:33
    # run is where the badge state showed up.  Both templates are checked against BOTH
    # states, including the badge/no-badge pair for the selected one.
    expectations = (
        # The panel sitting on 章节任务: four live frames, all from the 13:44 / 13:51 runs
        # (the open-a-panel runs of 16:33 landed on the daily tab, because the client
        # remembers the last tab -- see below).
        ("BTN_DAILY_TAB_TASKS", True, [
            BEFORE,
            ROOT / run / "live_runtime_step_001_after_20260916T134403879899.png",
            ROOT / run / "live_runtime_step_001_after_20260916T135133924607.png",
            ROOT / run / "live_runtime_step_002_before_20260916T134413644454.png",
            ROOT / run / "live_runtime_step_002_before_20260916T135143672097.png",
        ]),
        # Frames where the daily tab is the one showing, or where no panel is open at
        # all (the 16:33 run's steps 1-2 ran on HOME: a real-money popup was dismissed,
        # then the panel was opened).  Neither is a "chapter tab showing" frame, so a
        # hit here would mean the tap target resolves where it must not.
        ("BTN_DAILY_TAB_TASKS", False, [
            AFTER,
            ROOT / run / "live_runtime_step_001_after_20260916T163302427970.png",
            ROOT / run / "live_runtime_step_002_before_20260916T163312198269.png",
            ROOT / run / "live_runtime_step_002_after_20260916T163323089794.png",
            ROOT / run / "live_runtime_step_003_before_20260916T163330128917.png",
            ROOT / run / "live_runtime_step_004_after_20260916T163354858821.png",
        ]),
        ("TAB_DAILY_TASKS_SELECTED", True, [
            AFTER,                                                     # selected, no badge
            ROOT / run / "live_runtime_step_002_after_20260916T163323089794.png",  # + badge
            ROOT / run / "live_runtime_step_003_before_20260916T163330128917.png",  # + badge
            ROOT / run / "live_runtime_step_004_after_20260916T163354858821.png",
            ROOT / run / "live_runtime_step_005_before_20260916T163401829788.png",
        ]),
        ("TAB_DAILY_TASKS_SELECTED", False, [
            BEFORE,
            ROOT / run / "live_runtime_step_001_after_20260916T163302427970.png",
            ROOT / run / "live_runtime_step_002_before_20260916T163312198269.png",
        ]),
    )

    print("\ncross-state check (both templates against every known state):")
    ok = True
    for name, should_hit, frames in expectations:
        for frame in frames:
            if not frame.is_file():
                print(f"  {name:<24} MISSING FRAME {frame.name}")
                ok = False
                continue
            hit = semantic.find(frame, name)
            good = (hit is not None) == should_hit
            ok = ok and good
            print(f"  {name:<24} {'HIT ' if should_hit else 'miss'} expected | "
                  f"{'d=' + str(hit.distance) if hit else 'rejected':<12} | {frame.name[:46]}"
                  f"{'' if good else '   *** WRONG ***'}")

    print("\ncorpus gate (both templates, whole dataset/raw):")
    corpus = sorted((ROOT / "dataset" / "raw").rglob("*.png"))
    for name in ("BTN_DAILY_TAB_TASKS", "TAB_DAILY_TASKS_SELECTED"):
        hits = []
        for frame in corpus:
            try:
                if semantic.find(frame, name) is not None:
                    hits.append(frame.relative_to(ROOT))
            except Exception:
                continue
        print(f"  {name:<24} matched {len(hits)} of {len(corpus)} frames")
        for entry in hits[:14]:
            print(f"      {entry}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
