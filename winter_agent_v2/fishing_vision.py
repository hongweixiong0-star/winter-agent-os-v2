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
import time

#: x0, y0, x1, y1 of the water body in the native 720x1280 frame.  Below the ice
#: line and inside the two side rails, so the HUD and the fisherman are excluded.
WATER_ROI = (120, 430, 620, 1180)


def locate_normal_stage(frame: np.ndarray) -> tuple[int, int] | None:
    """Locate the wide blue normal-stage control on a confirmed fishing home frame.

    The gold treasure control is excluded by colour. Coordinates belong only to this frame;
    multiple eligible controls remain ambiguous rather than picking a remembered location.
    """
    if frame is None or frame.size == 0:
        return None
    height, width = frame.shape[:2]
    top = round(height * 0.85)
    hsv = cv2.cvtColor(frame[top:], cv2.COLOR_RGB2HSV)
    blue = cv2.inRange(hsv, (85, 80, 140), (125, 255, 255))
    components, _ = cv2.findContours(blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    targets = []
    for contour in components:
        x, y, w, h = cv2.boundingRect(contour)
        if w >= width * .25 and height * .035 <= h <= height * .12:
            targets.append((x + w // 2, top + y + h // 2))
    return targets[0] if len(targets) == 1 else None

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
        # Deep levels scroll the camera: the hook can be above the original water ROI.
        # When the hook is visible, anchor the line to its own nearby dark column rather
        # than allowing a background pole to win a whole-image column contest.
        if out.line_x is None:
            local_hook = int(out.hook_x - off_x)
            lo, hi = max(0, local_hook - 10), min(gray.shape[1], local_hook + 11)
            counts = (gray[:, lo:hi] < 60).sum(axis=0)
            if counts.size and int(counts.max()) >= LINE_MIN_DARK:
                col = lo + int(np.argmax(counts))
                dark_count = int(counts.max())
                out.line_x = col + off_x
                out.line_strength = dark_count

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


class FishingVision:
    """Temporal OpenCV refinement of the existing detector; never predicts a detection.

    Local search is merely an ordering of measured candidates. Missing pixels remain lost.
    The blue water scene separates end transitions from gameplay lost frames.
    """

    def __init__(self) -> None:
        self.last_x = None
        self.last_hook = None
        self.last_at = None
        self.vx = 0.0
        self.offset = 0.0
        self.lost_since = None
        self.lost_streak = 0
        self.max_lost_streak = 0
        self.frames = self.gameplay = self.valid = self.lost_frames = 0
        self.reacquire_count = self.reacquire_success = 0
        self.reacquire_ms = []
        self.tracks = {}
        self.next_id = 1
        self.track_lost = self.track_created = 0
        self.first_gameplay_at = self.first_valid_at = None
        self._previous_scene = None
        self.kernel = np.ones((5, 5), np.uint8)

    def __call__(self, frame: np.ndarray, *, timestamp: float | None = None) -> FishingFrame:
        if not isinstance(frame,np.ndarray) or frame.size == 0:
            return FishingFrame()
        at = time.monotonic() if timestamp is None else timestamp
        height, width = frame.shape[:2]
        roi = (round(width / 6), 0, round(width * .86), height)
        state = detect_fishing(frame, roi=roi)
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        water = cv2.inRange(hsv, (85, 150, 65), (115, 255, 235))
        interior = water[round(height*.2):round(height*.8), round(width*.3):round(width*.7)]
        coverage = float(np.mean(interior > 0)) if interior.size else 0.0
        gameplay = coverage >= .68
        state.meta.update(gameplay=gameplay, water_fraction=round(coverage, 3), timestamp=at)
        self.frames += 1
        if not gameplay:
            state.line_x = state.hook_x = state.hook_y = None
            state.found, state.lost = False, True
            state.meta['scene'] = 'TRANSITION_OR_RESULT'
            state.fish, state.obstacles = [], []
            return state
        self.gameplay += 1
        if self.first_gameplay_at is None:
            self.first_gameplay_at = at
        gray = cv2.cvtColor(frame[:, roi[0]:roi[2]], cv2.COLOR_RGB2GRAY)
        dark = gray < 60
        dark[:round(height*.18), :max(0, round(width*.24)-roi[0])] = False
        counts = dark.sum(axis=0)
        col, strength, separation = _line_column(np.where(dark, 0, 255).astype(np.uint8))
        hook_x = state.hook_x if state.hook_area >= 40 else None
        hook_y = state.hook_y if hook_x is not None else None
        dt = max(.001, at - self.last_at) if self.last_at is not None else .05
        predicted = self.last_x + np.clip(self.vx * dt, -80, 80) if self.last_x is not None else None
        locations = [(col+roi[0], strength, separation, 'REACQUIRE_L2')]
        for center, radius, rung in ((self.last_x, 24, 'REACQUIRE_L0'),
                                     (predicted, 70, 'REACQUIRE_L1'),
                                     (hook_x+self.offset if hook_x is not None else None, 14, 'HOOK_ALIGNMENT')):
            if center is None:
                continue
            lo = max(0, round(center)-radius-roi[0])
            hi = min(len(counts), round(center)+radius+1-roi[0])
            if hi <= lo:
                continue
            k = lo + int(np.argmax(counts[lo:hi]))
            locations.append((k+roi[0], int(counts[k]), separation, rung))
        candidates = []
        for x, hits, sep, rung in locations:
            aligned = hook_x is not None and abs(hook_x-x) <= 18
            jump = abs(x-predicted) if predicted is not None else 0
            # Real moves can cover more pixels at a low capture rate. A single unrelated
            # dark peak still cannot replace a stable track without its hook corroboration.
            bound = max(45, min(140, 900*dt))
            if hits < LINE_MIN_DARK or (sep < 2.0 and not aligned) or (jump > bound and not aligned):
                continue
            score = min(1.0, hits/180)*.45 + min(1.0, sep/5)*.2 + .4*aligned
            score += .2*max(0, 1-jump/bound)
            candidates.append((score, x, hits, sep, rung))
        if candidates:
            confidence, x, hits, sep, rung = max(candidates)
            if self.lost_since is not None:
                self.reacquire_success += 1
                self.reacquire_ms.append((at-self.lost_since)*1000)
            if self.last_x is not None and dt <= .25:
                self.vx = .75*self.vx + .25*np.clip((x-self.last_x)/dt, -900, 900)
            self.last_x, self.last_at = x, at
            if hook_x is not None and abs(hook_x-x) <= 18:
                self.offset = x-hook_x
                self.last_hook = (hook_x, hook_y)
            state.line_x, state.line_strength, state.line_separation = x, hits, sep
            state.hook_x = hook_x if hook_x is not None and abs(hook_x-x) <= 18 else x
            if hook_y is not None and abs(hook_x-x) <= 18:
                state.hook_y = hook_y
            else:
                pixels = np.flatnonzero(dark[:, x-roi[0]])
                state.hook_y = int(pixels[-1]) if pixels.size else None
            state.found, state.lost = True, False
            state.meta.update(line_confidence=round(confidence,3), reacquire_level=rung)
            self.valid += 1
            if self.first_valid_at is None:
                self.first_valid_at = at
            self.lost_streak, self.lost_since = 0, None
        else:
            state.line_x = state.hook_x = state.hook_y = None
            state.found, state.lost = False, True
            if self.lost_since is None:
                self.lost_since = at
                self.reacquire_count += 1
            self.lost_streak += 1
            self.lost_frames += 1
            self.max_lost_streak = max(self.max_lost_streak, self.lost_streak)
            state.meta.update(reacquire_level='REACQUIRE_L3', predicted_line_x=predicted)
        state.fish, state.obstacles = self._objects(hsv, at, width, height, state)
        scene = cv2.resize(cv2.cvtColor(frame[round(height*.2):round(height*.92)],cv2.COLOR_RGB2GRAY),
                           (180,230)).astype(np.float32)
        if self._previous_scene is not None:
            (_,dy),response = cv2.phaseCorrelate(self._previous_scene,scene)
            if response>.12 and abs(dy)<95:
                state.meta['scene_vy'] = dy*(height*.72/230)/dt
                state.meta['scene_motion_confidence'] = response
        self._previous_scene = scene
        return state

    def _objects(self, hsv, at, width, height, state):
        # The recorded grey/green fish fall outside the old warm-only HSV mask. Round,
        # tall pufferfish remain hazards regardless of their position relative to the hook.
        mask = cv2.bitwise_or(cv2.inRange(hsv, (0,70,80), (40,255,255)),
                             cv2.inRange(hsv, (150,70,80), (180,255,255)))
        mask |= cv2.inRange(hsv, (0,0,75), (180,130,245))
        mask |= cv2.inRange(hsv, (40,70,65), (85,255,210))
        mask[:round(height*.19)] = 0
        mask[:, :round(width*.04)] = 0
        mask[:, round(width*.94):] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        fish, obstacles = [], []
        for contour in contours:
            x,y,w,h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if area < 90 or w < 16 or h < 8 or w > width*.3 or h > height*.17:
                continue
            cx,cy = x+w/2,y+h/2
            if state.hook_x is not None and abs(cx-state.hook_x) < 35 and abs(cy-(state.hook_y or 0)) < 105:
                continue
            obj = dict(x=round(cx),y=round(cy),w=w,h=h,area=int(area),left=x,top=y)
            if h >= height*.045 and w/h < 1.55:
                obstacles.append({**obj, 'confidence':.85, 'kind':'ROUND_HAZARD'})
            elif 1.45 <= w/h <= 5.5 and h <= height*.075:
                fish.append({**obj, 'confidence':.75, 'kind':'FISH_CANDIDATE'})
        used, flow = set(), []
        predicted_fish = []
        for obj in fish:
            candidates = [(abs(t['x']+t['vx']*(at-t['last_seen'])-obj['x'])+
                           abs(t['y']+t['vy']*(at-t['last_seen'])-obj['y']), key,t)
                          for key,t in self.tracks.items() if key not in used]
            distance,key,track = min(candidates,default=(1e9,None,None))
            if track is None or distance > 100:
                key = self.next_id
                self.next_id += 1
                self.track_created += 1
                track = dict(vx=0.,vy=0.,age=0,last_seen=at,x=obj['x'],y=obj['y'])
            else:
                dt = max(.01, at-track['last_seen'])
                vy = (obj['y']-track['y'])/dt
                flow.append(vy)
                track['vx'] = .65*track['vx']+.35*(obj['x']-track['x'])/dt
                track['vy'] = .65*track['vy']+.35*vy
            track.update(obj, age=track['age']+1, last_seen=at, misses=0)
            self.tracks[key] = track
            used.add(key)
            obj.update(fish_id=key,vx=track['vx'],vy=track['vy'],age=track['age'],last_seen=at)
        for key in list(self.tracks):
            if key in used:
                continue
            self.tracks[key]['misses'] = self.tracks[key].get('misses',0)+1
            if self.tracks[key]['misses'] > 3:
                self.track_lost += 1
                del self.tracks[key]
            else:
                track = self.tracks[key]
                dt = at-track['last_seen']
                if track['age'] >= 2 and 0 <= dt <= .18:
                    predicted_fish.append({**track, 'fish_id':key, 'predicted':True,
                        'x':track['x']+track['vx']*dt,'y':track['y']+track['vy']*dt,
                        'confidence':.75-.03*track['misses']})
        state.meta['scene_vy'] = float(np.median(flow)) if len(flow)>=2 else None
        state.meta['fish_detection_count'] = len(fish)
        # Predictions are explicitly separate from this frame's actual detections.
        state.meta['predicted_fish'] = predicted_fish
        return fish, obstacles

    def summary(self):
        return {'gameplay_frames':self.gameplay,'transition_frames':self.frames-self.gameplay,
                'control_coverage':self.valid/max(1,self.gameplay),
                'lost_frame_ratio':self.lost_frames/max(1,self.gameplay),
                'max_lost_streak':self.max_lost_streak,
                'reacquire_count':self.reacquire_count,'reacquire_success':self.reacquire_success,
                'reacquire_success_rate':self.reacquire_success/self.reacquire_count if self.reacquire_count else None,
                'reacquire_latency_ms':float(np.mean(self.reacquire_ms)) if self.reacquire_ms else None,
                'fish_track_lost_rate':self.track_lost/max(1,self.track_created),
                'fish_track_duration_max':max((t['age'] for t in self.tracks.values()),default=0),
                'first_valid_frame_ms':((self.first_valid_at-self.first_gameplay_at)*1000
                    if self.first_valid_at is not None and self.first_gameplay_at is not None else None)}
