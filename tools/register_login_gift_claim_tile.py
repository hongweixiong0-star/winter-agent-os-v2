"""Register the 登录好礼 panel's highlighted reward tile, so a claim tap has a measured target.

Why
---
The closure probe (``tools/probe_login_gift_claim.py``) reaches the panel and reads its tabs, but it
deliberately never taps a day node, because "whether an unlit-but-unlocked node is a claim control
was not measured, and a guessed reward position is what the directive forbids".  That leaves the
claim itself open.

What this tool does *not* do is guess a position.  It registers the tile the client itself drew with
a highlight ring -- the 免费 tab's current-day node, measured on the live frame -- as a template with
a bounded search region (Constitution A §24.2 forbids a stored coordinate as a tap target; §24.3 allows
a bounded search region; the tap target is wherever the *current* frame matches).  The record's status
is ``CANDIDATE``: it says "this is a picture of the tile", not "tapping it claims the reward".  What
the tile does is for the closure probe to measure, with before/after frames.

The two other states the same panel draws, and which must NOT match this crop:

    day 1   grey tile, big green tick        <- claimed
    day 2   bright tile, no ring             <- not this day

Usage
-----
    python tools/register_login_gift_claim_tile.py --overlay   # annotated frame only
    python tools/register_login_gift_claim_tile.py             # register + verify
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
OUT_DIR = ROOT / "dataset" / "candidate" / "login_gift_20260924"
ARCHIVE = ROOT / "dataset" / "truth_audit" / "login_gift_entry_20260924"

SEMANTIC = "LOGIN_GIFT_DAY_CLAIM"
TEMPLATE_ID = "login_gift_day_claim_tile_20260924"

#: The live frame the panel's 免费 tab was read on, 2026-09-24T14:30 (+08:00), with no input
#: between the capture and this measurement.
SOURCE = ROOT / "dataset/truth_audit/live_ops/20260924_claim_open/free_tab.png"

#: Measured on SOURCE by cropping and looking at it (``--overlay`` writes the annotation).  The box
#: covers the green tile *and* the gold ring the client drew around it, because the ring is what
#: makes this tile the highlighted one.
TILE_BOX = (92, 780, 189, 878)
#: The bounded search region, the tile plus a margin (Constitution A §24.3).  Tight on purpose: the
#: panel draws the same reward icon on other days, and the region is what keeps the match on *this*
#: node instead of on whichever icon happens to look most alike.
SEARCH_BOX = (60, 740, 240, 910)

#: The same node on the round's earlier capture.  It is a *positive*, not a negative: the client
#: still had this day highlighted, so the crop must reproduce there -- which is what makes the match
#: a measurement of the current frame rather than a lucky self-match.
SECOND_POSITIVE = (
    ROOT / "dataset/truth_audit/login_gift_entry_20260924/key/"
    "login_gift_PANEL_FREE_TAB_20260924T055924.png"
)

#: Frames the crop must not resolve: the city the entry sits on, and the world map with the panel
#: closed.  Both carry reward-shaped art and neither carries this tile.
NEGATIVES = {
    "city": ROOT / "dataset/truth_audit/live_ops/20260924_claim_open/city_0.png",
    "map": ROOT / "dataset/truth_audit/login_gift_entry_20260924/key/map_hud_panel_closed_20260924T040458.png",
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
        raise SystemExit(f"missing live frame: {SOURCE}  (run tools/probe_login_gift_claim.py first)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    with Image.open(SOURCE) as handle:
        image = handle.convert("RGB")
        size = image.size
        if size != (720, 1280):
            raise SystemExit(f"unexpected frame size {size}; re-measure the boxes")

        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(SEARCH_BOX, outline=(0, 200, 255), width=2)
        draw.rectangle(TILE_BOX, outline=(255, 0, 0), width=3)
        draw.text((SEARCH_BOX[0], SEARCH_BOX[1] - 14), SEMANTIC, fill=(255, 255, 0))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"login_gift_claim_tile_overlay_{stamp}.png"
        overlay.save(ARCHIVE / name)
        print(f"overlay -> {(ARCHIVE / name).relative_to(ROOT)}")

        if args.overlay:
            return 0

        template_path = OUT_DIR / f"{TEMPLATE_ID}.png"
        image.crop(TILE_BOX).save(template_path)
        print(f"template {image.crop(TILE_BOX).size} -> {template_path.relative_to(ROOT)}")

    shutil.copy2(SOURCE, ARCHIVE / f"panel_claim_source_{stamp}.png")

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    records = payload["records"]
    if any(r.get("semantic") == SEMANTIC and r.get("template_id") == TEMPLATE_ID for r in records):
        print(f"{SEMANTIC}: record already present; nothing added")
    else:
        records.append({
            "semantic": SEMANTIC,
            "template_path": str(template_path.relative_to(ROOT)),
            # A tap target may not be a stored position (Constitution A §24.2), so this record is
            # search-based: ``roi_norm`` records where the crop was taken, ``search_band`` is the
            # bounded window the matcher looks in on the *current* frame, and the match reports the
            # bounds it FOUND there -- which is what the executor taps.
            "matcher": "ccoeff",
            "matcher_note": ("search-based: the day nodes are drawn on the frame and the tap must "
                             "go where the tile IS, not where it was registered"),
            "roi_norm": _norm(TILE_BOX, size),
            "search_band": _norm(SEARCH_BOX, size),
            "max_distance": 16,
            "source": f"live_{stamp}/登录好礼 免费 tab",
            "provenance": "LIVE_CLIENT",
            "confidence": 0.99,
            "status": "CANDIDATE",
            "template_id": TEMPLATE_ID,
            "parent_screenshot": str(SOURCE.relative_to(ROOT)),
            "width": TILE_BOX[2] - TILE_BOX[0],
            "height": TILE_BOX[3] - TILE_BOX[1],
            "note": ("the 免费 tab's highlighted reward node -- the tile plus the gold ring the "
                     "client drew around it.  A tap CANDIDATE: the picture is measured, what the "
                     "tile does when tapped is what the closure probe measures."),
        })
        payload["count"] = len(records)
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"manifest records: {len(records)} (+1)")

    from winter_agent_v2.vision import SemanticROIVision

    vision = SemanticROIVision(MANIFEST)
    for label, frame in (("source", SOURCE), ("second", SECOND_POSITIVE)):
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
