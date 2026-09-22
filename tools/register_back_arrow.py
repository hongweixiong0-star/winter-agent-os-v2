"""Register the client's own top-left back arrow as a template, and measure it.

Why this control, 2026-09-22
----------------------------
``LEAVE_FOREIGN_LAYER`` is bound to ``Page.ALLIANCE`` and taps ``BTN_CLOSE`` -- but the alliance
page draws no close button at all.  Its exit is the back arrow at the top left, the same control
the mail page draws.  Measured here: the crop is **identical** on the alliance and mail frames
(phash distance 0) and **completely different** on the city and the map (distance 32), so one
template is the client's own navigation control rather than an artefact of one screen.

That mismatch is the whole of the current top failure: ``SAFE_BACK_NOT_PROVEN`` -- 20 times, every
one of them ``BACK`` from ALLIANCE to ALLIANCE -- plus 7 ``SEMANTIC_TARGET_NOT_VERIFIED`` for
``BTN_CLOSE`` on ALLIANCE.  The system-key press works about two times in three and the tap that
would always work is aimed at a control this page does not have.

Usage:
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/register_back_arrow.py [--check]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from winter_agent_v2.image_hash import hamming, phash  # noqa: E402
from winter_agent_v2.vision import SemanticROIVision  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
OUT_DIR = ROOT / "dataset" / "candidate" / "back_arrow_20260922"
TEMPLATE_ID = "back_arrow_top_left"
SEMANTIC = "BTN_BACK_ARROW"

#: Cropped from the alliance page; verified identical on the mail page by --check.
SOURCE_FRAME = (
    ROOT / "dataset/truth_audit/printed_controls_20260922"
    / "alliance_page__no_popup_close_control__live_20260921T0700.png"
)
SOURCE_BOX = (20, 12, 72, 64)

#: ``(label, frame, whether the arrow must be found)``
CHECKS = (
    ("alliance", SOURCE_FRAME, True),
    ("mail", ROOT / "dataset/raw/control_panel/runtime_auto/20260920_093557_805245"
     / "20260920_093557_805245_step_001_before_20260920T013600934589.png", True),
    ("city", ROOT / "dataset/raw/control_panel/runtime_auto/20260921_095040_726092"
     / "20260921_095040_726092_step_003_before_20260921T015109182497.png", False),
    ("map", ROOT / "dataset/truth_audit/printed_controls_20260922"
     / "map_nav_bar__city_cell_printed__live_20260922T0222.png", False),
)


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
        "The client's own navigation back arrow, top-left, drawn next to the page title. "
        "Measured 2026-09-22: identical (phash d=0) on the alliance page and the mail page, "
        "and different (d=32) on the city and the map, so it is one control rather than one "
        "screen's decoration. Registered because LEAVE_FOREIGN_LAYER taps BTN_CLOSE, which the "
        "alliance page does not draw -- the mismatch behind SAFE_BACK_NOT_PROVEN (20, all of "
        "them BACK from ALLIANCE to ALLIANCE) and 7 SEMANTIC_TARGET_NOT_VERIFIED for BTN_CLOSE "
        "on ALLIANCE."
    )
    existing = next(
        (r for r in records if r.get("semantic") == SEMANTIC and r.get("template_id") == TEMPLATE_ID),
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
        print(f"updated existing record for {SEMANTIC}")
    else:
        records.append(record)
        print(f"appended record for {SEMANTIC}")
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {MANIFEST.relative_to(ROOT)}  ({len(records)} records)")


def check() -> int:
    """Does the registered template find the arrow where it is, and only there?"""
    vision = SemanticROIVision(MANIFEST)
    wrong: list[str] = []
    for label, frame, expected in CHECKS:
        if not frame.exists():
            print(f"{label:10} MISSING {frame.name}")
            wrong.append(f"{label} (missing)")
            continue
        match = vision.find(frame, SEMANTIC)
        found = match is not None
        distance = getattr(match, "distance", None)
        centre = getattr(match, "center_norm", None)
        agree = found == expected
        if not agree:
            wrong.append(f"{label}: expected found={expected}, got {found}")
        shown = "none" if centre is None else f"({centre[0]:.4f}, {centre[1]:.4f})"
        print(f"{label:10} found={str(found):5} d={distance} centre={shown:22} "
              f"{'ok' if agree else 'MISMATCH'}")
    print()
    print("cases that did not behave as measured:", wrong or "none")
    return 0 if not wrong else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(check())
    register()
    raise SystemExit(check())
