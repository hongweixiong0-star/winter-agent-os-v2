"""Fishing fast vision — the minimum a per-frame controller needs, and no more.

Scope, deliberately narrow (PHASE 11): this module reads ONE cropped water ROI and
returns numbers.  It never builds a world state, never calls OCR, never calls a
model.  Everything here was fitted to REAL frames from
``dataset/raw/fishing_tournament/run_20260929T225731/`` (capture-first), not to an
idea of what the UI probably looks like.

What the frames actually showed
-------------------------------
Measured on 38 real gameplay frames:

* the fishing **line is a thin dark vertical structure** in the water.  Counting
  dark pixels per column gives a best column with **149-600** hits while the next
  best column has **26** — a separation of 6-19x, so the line's x is unambiguous
  and needs no template.
* a **green glowing marker sits at the hook**, ~25x34 px, 396-450 px of mask when
  the hook is in the water; its centroid tracks the hook.
* **depth is readable straight off the pixels**: the dark-pixel count on the line
  column grows with depth (149 px when the hook was high at y=577, 600 px when it
  was deep at y=1027).  No OCR is needed per frame, which is what makes a 20 Hz
  loop possible at all.

So the control axis is ``line_x``, the depth proxy is ``hook_y`` (and the dark
count as a cross-check), and fish/obstacles are coloured blobs in the water.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

#: x0, y0, x1, y1 of the water body in the native 720x1280 frame.  Below the ice
#: line and inside the two side rails, so the HUD and the fisherman are excluded.
WATER_ROI = (120, 430, 620, 1180)

#: A column must beat the runner-up by this factor to count as "the line".
LINE_SEPARATION = 3.0
#: Minimum dark pixels on the best column for the line to be considered present.
LINE_MIN_DARK = 60


@dataclass
class FishingFrame:
    """Everything the controller gets for one frame.  All pixels, no OCR."""

    found: bool = False
    lost: bool = True
    line_x: int | None = None
    line_strength: int = 0
    line_separation: float = 0.0
    hook_x: int | None = None
    hook_y: int | None = None
    hook_area: int = 0
    depth_px: int | None = None
    fish: list[dict[str, Any]] = field(default_factory=list)
    obstacles: list[dict[str, Any]] = field(default_factory=list)
    surface_y: int = 0
    #: Filled in by VisualServoSession each tick so an outer control loop can turn
    #: "move the LINE to x" into "move the FINGER by dx".
    finger_x: int | None = None
    servo: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found, "lost": self.lost,
            "line_x": self.line_x, "line_strength": self.line_strength,
            "line_separation": round(self.line_separation, 2),
            "hook_x": self.hook_x, "hook_y": self.hook_y, "hook_area": self.hook_area,
            "depth_px": self.depth_px,
            "fish": self.fish[:6], "obstacles": self.obstacles[:6],
        }


def _line_column(gray: np.ndarray, dark_threshold: int = 60) -> tuple[int, int, float]:
    """Best dark column in the ROI -> (x, dark_count, separation_from_runner_up)."""
    dark = (gray < dark_threshold).astype(np.uint8)
    counts = dark.sum(axis=0)
    if counts.size == 0:
        return 0, 0, 0.0
    best = int(np.argmax(counts))
    best_v = int(counts[best])
    # runner-up away from the best column (the line is 2-3 px wide, so its own
    # neighbours must not be treated as competition)
    mask = np.ones(counts.shape, dtype=bool)
    mask[max(0, best - 4):best + 5] = False
    second = int(counts[mask].max()) if mask.any() else 0
    separation = float(best_v / second) if second > 0 else float(best_v)
    return best, best_v, separation


def detect_fishing(frame: np.ndarray, *, roi: tuple[int, int, int, int] = WATER_ROI,
                   camera_offset: tuple[int, int] = (0, 0)) -> FishingFrame:
    """Read the fishing scene out of one frame.

    ``roi`` is optional because the servo can pass an already-cropped image; when
    it does, ``camera_offset`` supplies the (x0, y0) that were removed so every
    coordinate returned is still in native frame space.
    """
    out = FishingFrame()
    if frame is None or frame.size == 0:
        return out

    if frame.shape[1] != roi[2] - roi[0] or frame.shape[0] != roi[3] - roi[1]:
        x0, y0, x1, y1 = roi
        view = frame[y0:y1, x0:x1]
        off_x, off_y = x0, y0
    else:
        view = frame
        off_x, off_y = camera_offset
    if view.size == 0:
        return out

    out.surface_y = off_y

    hsv = cv2.cvtColor(view, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(view, cv2.COLOR_RGB2GRAY)

    # ---- the line ----------------------------------------------------------
    col, dark_count, separation = _line_column(gray)
    out.line_strength = dark_count
    out.line_separation = separation
    if dark_count >= LINE_MIN_DARK and separation >= LINE_SEPARATION:
        out.line_x = int(col + off_x)

    # ---- the hook: green glowing marker near the end of the line -----------
    green = cv2.inRange(hsv, (40, 120, 150), (85, 255, 255))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_blob = None
    for c in cnts:
        area = int(cv2.contourArea(c))
        if area < 40:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w > 60 or h > 70:          # the marker is ~25x34; anything big is scenery
            continue
        if best_blob is None or area > best_blob[0]:
            best_blob = (area, x + w // 2 + off_x, y + h // 2 + off_y)
    if best_blob:
        out.hook_area, out.hook_x, out.hook_y = best_blob

    # fallback: bottom of the dark line == where the hook hangs
    if out.hook_x is None and out.line_x is not None and dark_count:
        colview = (gray[:, col] < 60).nonzero()[0]
        if colview.size:
            out.hook_y = int(colview.max() + off_y)
            out.hook_x = out.line_x
            out.meta["hook_from"] = "line_bottom"

    if out.hook_y is not None:
        out.depth_px = int(out.hook_y - off_y)

    # ---- coloured blobs in the water (fish / hazards) ---------------------
    warm = cv2.bitwise_or(
        cv2.inRange(hsv, (0, 110, 120), (35, 255, 255)),
        cv2.inRange(hsv, (160, 110, 120), (180, 255, 255)))
    warm = cv2.morphologyEx(warm, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _lab, stats, cents = cv2.connectedComponentsWithStats(warm)
    blobs: list[dict[str, Any]] = []
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < 60:
            continue
        x = int(stats[k, cv2.CC_STAT_LEFT])
        y = int(stats[k, cv2.CC_STAT_TOP])
        w = int(stats[k, cv2.CC_STAT_WIDTH])
        h = int(stats[k, cv2.CC_STAT_HEIGHT])
        if w > 220 or h > 260:        # scenery, not a fish
            continue
        blobs.append({"x": int(cents[k][0] + off_x), "y": int(cents[k][1] + off_y),
                      "w": w, "h": h, "area": area,
                      "top": int(y + off_y), "left": int(x + off_x)})
    blobs.sort(key=lambda b: b["y"])
    # A fish is what sits BELOW the hook; what sits above or beside it in the
    # upper band is the ice scenery (lantern, crates) and is reported separately.
    hook_y = out.hook_y if out.hook_y is not None else 10 ** 6
    out.fish = [b for b in blobs if b["y"] >= hook_y - 60]
    out.obstacles = [b for b in blobs if b["y"] < hook_y - 60]

    out.found = out.line_x is not None
    out.lost = not out.found
    out.meta["dark_count"] = dark_count
    return out


def free_corridor(frame: np.ndarray, line_x: int, hook_y: int, *,
                  probe_dx: int = 70, probe_h: int = 220, roi=WATER_ROI) -> dict[str, Any]:
    """How clear is the water just below (line_x +/- probe_dx)?

    Used by the descent phase: pick the direction with the most free space so the
    hook falls in a channel instead of into a fish body or a rock.  "Free" means
    "close to the water background colour", so it needs no object labels.

    Returns ``{"left": n, "centre": n, "right": n, "best": "left|centre|right"}``.
    """
    x0, y0, x1, y1 = roi
    h, w = frame.shape[:2]
    y_top = max(0, min(h - 1, hook_y + 20))
    y_bot = max(0, min(h, hook_y + 20 + probe_h))
    if y_bot - y_top < 20:
        return {"left": 0, "centre": 0, "right": 0, "best": "centre"}
    band = frame[y_top:y_bot, max(0, x0):min(w, x1)]
    if band.size == 0:
        return {"left": 0, "centre": 0, "right": 0, "best": "centre"}
    # water background = the modal colour of the band
    flat = band.reshape(-1, 3)
    med = np.median(flat, axis=0)
    dist = np.linalg.norm(flat.astype(np.float32) - med, axis=1).reshape(band.shape[:2])
    free = (dist < 55).astype(np.uint8)
    out: dict[str, Any] = {}
    for name, dx in (("left", -probe_dx), ("centre", 0), ("right", probe_dx)):
        cx = int(np.clip(line_x + dx - x0, 2, free.shape[1] - 3))
        strip = free[:, max(0, cx - 14):cx + 15]
        out[name] = int(strip.sum())
    out["best"] = max(("left", "centre", "right"), key=lambda k: out[k])
    return out
