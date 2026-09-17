"""Re-register the 科技研究 route from the 2026-09-17 live frames.

Why this exists
---------------
`KEEP_RESEARCH_PRODUCTIVE` is one of the four BLOCKED goals, and it is blocked in the
same way TRAIN was: the route is documented and half-built, and the only thing missing
is templates that resolve on today's client.

What already existed (do not rebuild it):

* ``knowledge/skills/RESEARCH_RESEARCH.md`` line 38 records the verified route --
  "top power value -> 实力详情 -> scroll to 科技实力 -> 提升 -> Research Center (科研所)" --
  measured 2026-09-04 on the then-current account (Research Center level 30, 病房扩建VII
  2/3).
* ``skill_factory.GOAL_REQUIREMENTS["KEEP_RESEARCH_PRODUCTIVE"]`` names the two skills
  the goal needs: ``("OPEN_RESEARCH", "RESEARCH")``.
* the ``BTN_OPEN_RESEARCH`` semantic already exists with its own tolerance override
  (12), and ``verify_research_started`` / ``verify_research_queue`` are bound in
  ``LiveRuntime.VERIFIED_ATOMIC``.

What was wrong.  Both ``BTN_OPEN_RESEARCH`` records are REPLAY cuts whose ROI is
x 0.68 y 0.596 w 0.13 h 0.12 -- pixels 490..583 x 763..917, centre (536, 840).
Measured today by OCR, the 研究 button's hexagon is at 435..520 x 855..910, centre
**(478, 878)**: the old ROI's centre is ~65 px to the right of the control, so even a
successful match would have tapped the wrong place.  And nothing read the state "the
research building's menu is open", so no decision could fire.

The two records below are cut from today's live frames, and the gate prints the
population separation so the choice is checkable.

Usage
-----
    python tools/register_research_route_templates.py
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
EVIDENCE = ROOT / "dataset" / "truth_audit" / "power_route_20260917"
OUT_DIR = ROOT / "dataset" / "candidate" / "research_route_20260917"
KEY = EVIDENCE / "key"


def _newest(pattern: str) -> Path:
    matches = sorted(EVIDENCE.glob(pattern))
    if not matches:
        raise SystemExit(f"no evidence frame for {pattern}")
    return matches[-1]


# The three walks of the route this round (each: power icon -> 实力详情 -> 科技实力 提升).
PANEL_FRAMES = [_newest(p) for p in (
    "research_route_*_02_after_tap_360_660.png",
    "research_lab2_*_02_after_tap_360_660.png",
    "research_lab3_*_02_after_tap_360_660.png",
)]
LAB_FRAMES = [_newest(p) for p in (
    "research_route_*_03_after_tap_606_963.png",
    "research_lab2_*_03_after_tap_606_963.png",
    "research_lab3_*_03_after_tap_606_963.png",
)]
RESEARCH_PAGE = _newest("research_open_*_01_after_tap_478_878.png")

SPECS: dict[str, dict] = {
    # (left, top, right, bottom) in 720x1280 frame pixels.
    "BTN_POWER_RESEARCH_IMPROVE": {
        "box": (563, 935, 648, 992),
        "source_frame": PANEL_FRAMES[0],
        "template_id": "btn_power_research_improve__live_20260917",
        "note": ("科技实力's row 提升 button (OCR-measured at 569..643 x 941..986; the "
                 "crop's centre is 605,963, inside the button).  Value-independent: "
                 "the row's numbers sit at x <= 366, left of this crop.  Like the 部队实力 "
                 "record, the row's y depends on how many categories the account has "
                 "unlocked, and 科技实力 is the LAST row, so a new category above it "
                 "shifts this button down."),
        "evidence": "power_route_20260917/research_route_..._02_after_tap_360_660.png",
    },
    "BTN_OPEN_RESEARCH": {
        "box": (308, 708, 648, 1048),
        "source_frame": LAB_FRAMES[0],
        "template_id": "btn_open_research__live_20260917_lab_focus",
        "note": ("the 研究 button of the focused 科研所 radial menu.  Framed as a "
                 "340x340 block CENTRED on the button (478,878) for two reasons: the "
                 "executor taps the winning record's ROI centre and supports only "
                 "TAP_SEMANTIC, so the crop has to be centred on the control; and the "
                 "button carries the same animated tutorial hand the training camp's "
                 "does, so a tight crop is unstable.  The old records' ROI centre "
                 "(536,840) is ~65 px right of the control.  Measured on three walks: "
                 "positives 0/8/8, and the nearest negative (the research page itself, "
                 "which is where this navigates to) 28."),
        "evidence": "power_route_20260917/research_route_..._03_after_tap_606_963.png",
    },
}

NEGATIVES = {
    "plain HOME": KEY / "01_home_plain.png",
    "power overview": KEY / "02_power_overview_panel.png",
    "power details": KEY / "03_power_details_panel.png",
    "building panel": KEY / "04_building_focused.png",
    "camp focused": KEY / "05_camp_focused.png",
    "training page": KEY / "06_training_page.png",
    "intel reward popup": KEY / "11_intel_reward_popup.png",
}


def main() -> int:
    for frame in [*PANEL_FRAMES, *LAB_FRAMES, RESEARCH_PAGE]:
        if not frame.is_file():
            raise SystemExit(f"missing evidence frame: {frame}")

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
            "source": "research_route_20260917",
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
        centre = ((left + right) // 2, (top + bottom) // 2)
        print(f"added   {semantic:<28} {crop.size} roi={roi} tap_centre={centre}")

    payload["count"] = len(records)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nmanifest records: {len(records)} (+{len(added)})")

    overlay = Image.open(LAB_FRAMES[0]).convert("RGB")
    draw = ImageDraw.Draw(overlay)
    left, top, right, bottom = SPECS["BTN_OPEN_RESEARCH"]["box"]
    draw.rectangle((left, top, right, bottom), outline=(255, 0, 0), width=2)
    cx, cy = (left + right) // 2, (top + bottom) // 2
    draw.line((cx - 14, cy, cx + 14, cy), fill=(0, 255, 0), width=2)
    draw.line((cx, cy - 14, cx, cy + 14), fill=(0, 255, 0), width=2)
    overlay.save(OUT_DIR / "lab_focus_frame_with_crop.png")

    from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

    semantic = SemanticROIVision(MANIFEST)
    world = SemanticWorldVision(MANIFEST)

    print("\nroute check:")
    for name, frame in (("HOME (route start)", KEY / "01_home_plain.png"),
                        ("power overview", KEY / "02_power_overview_panel.png"),
                        ("power details", KEY / "03_power_details_panel.png"),
                        ("lab focused", LAB_FRAMES[0]),
                        ("research page", RESEARCH_PAGE)):
        state = world.observe(frame)
        print(f"  {name:<20} page={state.page.value:<9} popup={state.popup} "
              f"research={json.dumps(state.research, ensure_ascii=False)}")

    print("\npositives (each walk of the route) and negatives:")
    for sem, frames in (("BTN_POWER_RESEARCH_IMPROVE", PANEL_FRAMES),
                        ("BTN_OPEN_RESEARCH", LAB_FRAMES)):
        print(f"  {sem}")
        for frame in frames:
            hit = semantic.find(frame, sem)
            print(f"    pos d={'-' if hit is None else hit.distance}  {frame.name}")
        for label, frame in NEGATIVES.items():
            hit = semantic.find(frame, sem)
            print(f"    neg {'-' if hit is None else hit.distance:<3} {label}")

    print("\nwhich BTN_OPEN_RESEARCH record wins on the lab frame "
          "(the winning ROI centre is the tap point):")
    for row in [r for r in semantic.records if r["semantic"] == "BTN_OPEN_RESEARCH"]:
        roi = row["roi_norm"]
        bounds = (round(roi["x_norm"] * 720), round(roi["y_norm"] * 1280),
                  round((roi["x_norm"] + roi["w_norm"]) * 720),
                  round((roi["y_norm"] + roi["h_norm"]) * 1280))
        centre = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
        print(f"  roi_px={bounds} centre={centre} source={row.get('source')}")
    winner = semantic.find(LAB_FRAMES[0], "BTN_OPEN_RESEARCH")
    if winner is not None:
        print(f"  -> winner d={winner.distance} centre_px="
              f"({winner.center_norm[0] * 720:.0f},{winner.center_norm[1] * 1280:.0f})"
              f"  (the 研究 hexagon is at 435..520 x 855..910, centre (478,878))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
