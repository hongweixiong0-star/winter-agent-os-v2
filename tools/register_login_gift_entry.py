"""Register the city HUD's 登录好礼 entry, so the ordinary AUTO can open the panel itself.

Why
---
The panel was opened twice on the real client, but both times from a development
tool: the closure probe tapped the entry by reading the element table off the
frame, and a person opened it before that.  The runtime has no skill that opens
it -- ``route_for`` answers None for every goal on the panel's page, and the
entry's template lives in ``knowledge/ui/icon_label_controls.json``, which
``SemanticROIVision`` (the resolver ``TAP_SEMANTIC`` consults) never reads.  A
skill pointing at ``CONTROL[登录好礼]`` would therefore fail with
``SEMANTIC_TARGET_NOT_VERIFIED`` -- that is the measured reason the ordinary
AUTO has never opened this panel.

What this registers, and what it does not
-----------------------------------------
The entry control's own crop (the blue calendar button with the brown 7, already
extracted for the element table) becomes a ``template_manifest`` record under the
semantic ``CONTROL[登录好礼]``, with the same shape the claim tile uses:
``matcher: "ccoeff"``, ``roi_norm`` where the crop was taken, ``search_band`` the
bounded window to look in on the CURRENT frame, and the match reports the bounds
it FOUND -- the tap target is wherever the control IS now, never the stored box
(Constitution A §24.2/§24.3).

Frames it must not resolve: the open 登录好礼 panel (the entry is not drawn there)
and the reward tile itself.

Usage
-----
    python tools/register_login_gift_entry.py --overlay   # annotated frame only
    python tools/register_login_gift_entry.py             # register + verify
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "login_gift_entry_20260924"

SEMANTIC = "CONTROL[登录好礼]"
TEMPLATE_ID = "login_gift_city_entry_20260924"
#: The crop already extracted and human-verified for the element table
#: (``knowledge/ui/icon_label_controls.json``, entry ``登录好礼``).
TEMPLATE = ROOT / "knowledge" / "ui" / "icon_templates" / "登录好礼.png"

#: The live city frame the element record was extracted from
#: (2026-09-24T10:10 local), where the probe's element table located the control
#: at score 0.9554.
SOURCE = ROOT / (
    "dataset/raw/control_panel/runtime_auto/20260924_101003_761338/"
    "20260924_101003_761338_step_001_after_20260924T021024299127.png"
)

#: Measured: the element record's box_norm (0.7306, 0.0969, 0.0778, 0.043) on the
#: 720x1280 frame -- the blue calendar button the label 登录好礼 sits under.
ENTRY_BOX = (526, 124, 582, 179)
#: Bounded search window around it (Constitution A §24.3).  Wide enough for the
#: HUD stack to shift a little; small enough that the 超值活动 icons above and the
#: 充值 row below stay outside it.
SEARCH_BOX = (475, 64, 634, 256)

#: Positive: the probe's own city frame, where the entry was tapped for real; and
#: the world map HUD, where the element record already lists the same control
#: (``pages: ["MAP", "HOME"]``) -- measured here at the same centre, d=0.
SECOND_POSITIVE = ROOT / "dataset/truth_audit/live_ops/20260924_claim_open/city_0.png"
MAP_POSITIVE = ROOT / "dataset/truth_audit/login_gift_entry_20260924/key/map_hud_panel_closed_20260924T040458.png"

#: Frames the crop must not resolve: the open 登录好礼 panel does not draw its own
#: entry.
NEGATIVES = {
    "panel_open": ROOT / "dataset/truth_audit/live_ops/20260924_claim_open/free_tab.png",
}


def _norm(box: tuple[int, int, int, int], size: tuple[int, int]) -> dict[str, float]:
    width, height = size
    return {
        "x_norm": round(box[0] / width, 6),
        "y_norm": round(box[1] / height, 6),
        "w_norm": round((box[2] - box[0]) / width, 6),
        "h_norm": round((box[3] - box[1]) / height, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", action="store_true", help="write the annotated frame only")
    args = parser.parse_args()

    if not SOURCE.is_file():
        raise SystemExit(f"missing live frame: {SOURCE}")
    if not TEMPLATE.is_file():
        raise SystemExit(f"missing template: {TEMPLATE}")

    ARCHIVE.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE) as handle:
        image = handle.convert("RGB")
        size = image.size
        if size != (720, 1280):
            raise SystemExit(f"unexpected frame size {size}; re-measure the boxes")

        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(SEARCH_BOX, outline=(0, 200, 255), width=2)
        draw.rectangle(ENTRY_BOX, outline=(255, 0, 0), width=3)
        draw.text((SEARCH_BOX[0], SEARCH_BOX[1] - 14), SEMANTIC, fill=(255, 255, 0))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"login_gift_entry_overlay_{stamp}.png"
        overlay.save(ARCHIVE / name)
        print(f"overlay -> {(ARCHIVE / name).relative_to(ROOT)}")

        if args.overlay:
            return 0

        shutil.copy2(SOURCE, ARCHIVE / f"city_entry_source_{stamp}.png")

    template_path = TEMPLATE
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    if any(r.get("semantic") == SEMANTIC and r.get("template_id") == TEMPLATE_ID for r in records):
        print(f"{SEMANTIC}: record already present; nothing added")
    else:
        records.append({
            "semantic": SEMANTIC,
            "template_path": str(template_path.relative_to(ROOT)),
            # Search-based, same contract as LOGIN_GIFT_DAY_CLAIM: the tap goes
            # where the control IS on the current frame.
            "matcher": "ccoeff",
            "matcher_note": ("search-based: the HUD stack can shift, so the match reports the "
                             "bounds it found inside the band rather than the registration box"),
            "roi_norm": _norm(ENTRY_BOX, size),
            "search_band": _norm(SEARCH_BOX, size),
            "max_distance": 16,
            "source": f"live_{stamp}/city HUD 登录好礼 entry",
            "provenance": "LIVE_CLIENT",
            "confidence": 0.99,
            "status": "CANDIDATE",
            "template_id": TEMPLATE_ID,
            "parent_screenshot": str(SOURCE.relative_to(ROOT)),
            "width": ENTRY_BOX[2] - ENTRY_BOX[0],
            "height": ENTRY_BOX[3] - ENTRY_BOX[1],
            "note": ("the city HUD's 登录好礼 calendar entry -- the control the element table "
                     "already taps by hand.  Navigation CANDIDATE: opening the panel is all it "
                     "does; what the panel offers is decided after the page is verified."),
        })
        payload["count"] = len(records)
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"manifest records: {len(records)} (+1)")

    from winter_agent_v2.vision import SemanticROIVision

    vision = SemanticROIVision(MANIFEST)
    for label, frame in (("source", SOURCE), ("second", SECOND_POSITIVE),
                         ("map", MAP_POSITIVE)):
        if not frame.is_file():
            print(f"positive {label}: frame absent, skipped")
            continue
        hit = vision.find(frame, SEMANTIC)
        print(f"positive {label:7} {frame.name:52} -> "
              + (f"d={hit.distance} centre={hit.center_norm}" if hit else "MISS"))
    for label, frame in NEGATIVES.items():
        if not frame.is_file():
            print(f"  negative {label}: frame absent, skipped")
            continue
        other = vision.find(frame, SEMANTIC)
        print(f"  negative {label:14} {frame.name:52} -> "
              + ("None (rejected)" if other is None else f"d={other.distance} MATCH"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
