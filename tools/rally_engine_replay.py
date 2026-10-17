# -*- coding: utf-8 -*-
"""Offline replay: generic JOIN_RALLY(target=BEAR) over 2026-09-27 live frames.

Validates the unified Rally Engine (rally.py + green-plus detector) on tonight's
real frames, and emits a generic rally dataset index:
  flow=JOIN_RALLY, target_type=BEAR  (per knowledge/rally/rally_engine_rules.json)

No device access -- pure image replay from dataset/evidence/.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path("E:/WinterAgent")
sys.path.insert(0, str(ROOT))

OUT_INDEX = ROOT / "dataset/raw/rally_join/RALLY_DATASET_INDEX.jsonl"
EVID = ROOT / "dataset/evidence"

# evidence dirs from the 2026-09-27 bear night (all flow=JOIN_RALLY, target=BEAR)
DIRS = sorted(
    [d for d in EVID.glob("bear_join_once_20260927*")]
    + [d for d in EVID.glob("bear_roleA_open_20260927*")]
    + [d for d in EVID.glob("operator_demo*_20260927*")]
)

# green + locator: HSV green pixel clustering in the rally detail band
GREEN_LO = np.array([40, 90, 90], np.uint8)
GREEN_HI = np.array([85, 255, 255], np.uint8)
BAND = (380, 520, 400, 700)  # y0, y1, x0, x1


def find_green_plus(img: Image.Image):
    """Return (centre, pixel_count, best_contour_bbox) of the strongest green blob."""
    y0, y1, x0, x1 = BAND
    arr = np.asarray(img.convert("RGB"))[y0:y1, x0:x1]
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, GREEN_LO, GREEN_HI)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < 60:
        return None
    bx, by, bw, bh = cv2.boundingRect(c)
    cx, cy = x0 + bx + bw // 2, y0 + by + bh // 2
    return (cx, cy), int(area), (x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh)


def main():
    OUT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    records = []
    pass_n = fail_n = 0
    for d in DIRS:
        frames = sorted(d.glob("*.png"))
        if not frames:
            continue
        best = None
        for f in frames:
            try:
                img = Image.open(f)
            except Exception:
                continue
            hit = find_green_plus(img)
            if hit and (best is None or hit[1] > best["green_area"]):
                best = {
                    "frame": str(f.relative_to(ROOT)),
                    "join_button_bbox": hit[2],
                    "join_button_centre": hit[0],
                    "green_area": hit[1],
                }
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime(d.stat().st_mtime)),
            "evidence_dir": d.name,
            "flow": "JOIN_RALLY",
            "target_type": "BEAR",
            "event": "BEAR_HUNT",
            "date": "2026-09-27",
            "row_schema": "knowledge/rally/rally_engine_rules.json#rally_row_schema",
            "join_hit": best,
        }
        if best:
            pass_n += 1
        else:
            fail_n += 1
        records.append(rec)
    with OUT_INDEX.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({
        "index": str(OUT_INDEX.relative_to(ROOT)),
        "dirs": len(records),
        "join_hit": pass_n,
        "no_hit": fail_n,
        "samples": [r["evidence_dir"] for r in records[:3]],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
