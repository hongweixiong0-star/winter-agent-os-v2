# -*- coding: utf-8 -*-
"""Troop-class badges and hero-card controls on PAGE_FORMATION.

Live evidence 2026-09-28 corrected the earlier interpretation: blue upper-left
glyphs encode troop class (infantry/lancer/marksman), not gathering specialty.
Gathering identity comes from ``hero_portraits`` and the hero's client-read
expedition skill. These badge templates must never select a gather hero.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
BADGE_DIR = ROOT / "dataset" / "candidate" / "formation_badges"

#: hero band on PAGE_FORMATION (720x1280 reference)
HERO_BAND = (300, 380)


#: hero card centres on PAGE_FORMATION (720-wide reference) -> slot 1..3
CARD_SLOT_X = ((0, 270, 1), (270, 480, 2), (480, 720, 3))


def badge_slot(cx: int, frame_w: int = 720) -> int:
    """Map a badge x to the hero slot (1..3) by the card layout, not by list order."""
    x = cx * 720.0 / frame_w
    for x0, x1, slot in CARD_SLOT_X:
        if x0 <= x < x1:
            return slot
    return 3


def detect_badges(frame: Any) -> List[Dict[str, Any]]:
    """Find the blue badge squares in the hero band, left→right.

    Returns [{"box": (x,y,w,h), "centre": (cx,cy)}].
    """
    import cv2
    import numpy as np
    W, H = frame.size
    y0, y1 = int(HERO_BAND[0] * H / 1280), int(HERO_BAND[1] * H / 1280)
    band = np.asarray(frame.convert("RGB"))[y0:y1, :, :][:, :, ::-1].copy()
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (85, 80, 120), (115, 255, 255))     # badge blue
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: List[Dict[str, Any]] = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 250:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if not (0.6 <= w / max(h, 1) <= 1.6):
            continue
        if w < 18 or h < 18:
            continue
        out.append({"box": (int(x), int(y + y0), int(w), int(h)),
                    "centre": (int(x + w / 2), int(y + y0 + h / 2)),
                    "area": int(a)})
    # second pass: the badge sitting on a blue hero card is low-contrast in hue;
    # its glyph is still a small bright blob.  Add those the first pass missed.
    white = cv2.inRange(hsv, (0, 0, 200), (180, 60, 255))
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts2, _ = cv2.findContours(white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        a = cv2.contourArea(c)
        if a < 60:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w < 8 or h < 8 or w > 30 or h > 30:
            continue
        cx, cy = int(x + w / 2), int(y + y0 + h / 2)
        if any(abs(cx - d["centre"][0]) < 24 and abs(cy - d["centre"][1]) < 24 for d in out):
            continue
        # ``cy`` is already in full-frame coordinates; subtracting y0 here
        # placed fallback glyphs at y≈18 instead of the actual hero-card band.
        out.append({"box": (int(cx - 15), int(cy - 15), 30, 30),
                    "centre": (cx, cy), "area": int(a), "source": "glyph"})
    unique: List[Dict[str, Any]] = []
    for candidate in sorted(out, key=lambda d: (d.get("source") == "glyph", -int(d.get("area", 0)))):
        cx, cy = candidate["centre"]
        if any(abs(cx - item["centre"][0]) <= 40 and abs(cy - item["centre"][1]) <= 40 for item in unique):
            continue
        unique.append(candidate)
    return sorted(unique, key=lambda d: d["centre"][0])


def _glyph(frame: Any, badge: Dict[str, Any], pad: int = 3) -> Any:
    x, y, w, h = badge["box"]
    return frame.crop((x + pad, y + pad, x + w - pad, y + h - pad)).convert("RGB")


def load_templates() -> Dict[str, Any]:
    """Load registered glyph templates from BADGE_DIR (name -> PIL image)."""
    from PIL import Image
    tpl: Dict[str, Any] = {}
    if not BADGE_DIR.exists():
        return tpl
    for p in sorted(BADGE_DIR.glob("badge_*.png")):
        if p.name.startswith("_"):
            continue
        try:
            tpl[p.stem] = Image.open(p).convert("RGB")
        except Exception:
            continue
    return tpl


def classify_badge(frame: Any, badge: Dict[str, Any]) -> Optional[str]:
    """Best-matching troop class; this result is not a gather-specialty label."""
    import cv2
    import numpy as np
    tpls = load_templates()
    if not tpls:
        return None
    glyph = _glyph(frame, badge)
    best, score = None, 0.0
    for name, t in tpls.items():
        g = cv2.cvtColor(np.asarray(glyph), cv2.COLOR_RGB2BGR)
        tt = cv2.cvtColor(np.asarray(t.resize(glyph.size)), cv2.COLOR_RGB2BGR)
        res = cv2.matchTemplate(g, tt, cv2.TM_CCOEFF_NORMED)
        s = float(res.max())
        if s > score:
            best, score = name, s
    if not best:
        return None
    troop_class = {"badge_shovel": "LANCER", "badge_shield": "INFANTRY", "badge_axes": "MARKSMAN"}.get(best)
    return f"{troop_class or 'UNKNOWN_TROOP_CLASS'}:{score:.2f}"


def analyse_frame(frame: Any) -> List[Dict[str, Any]]:
    """One entry per hero card: badge box + classification."""
    out = []
    for b in detect_badges(frame):
        out.append({"slot": badge_slot(b["centre"][0], frame.size[0]), "box": b["box"], "centre": b["centre"],
                    "kind": classify_badge(frame, b)})
    return out


def gather_slot(frame: Any, threshold: float = 0.80) -> Optional[int]:
    """Deprecated: troop-class badges do not encode gathering specialty."""
    return None


def remove_button_point(frame: Any, slot: int) -> Optional[Tuple[int, int]]:
    """Current-frame-relative point for the red remove control on one card."""
    if slot not in (1, 2, 3):
        return None
    W, H = frame.size
    from .hero_portraits import HERO_CARD_RECTS
    x, y, w, h = HERO_CARD_RECTS[slot - 1]
    return (round((x + 0.94 * w) * W), round((y + 0.052 * h) * H))


def remove_other_heroes(frame: Any, keep: Optional[int], frame_w: int = 720,
                        frame_h: int = 1280) -> List[Tuple[int, int]]:
    """Current-frame red ⊖ taps for detected cards except ``keep``."""
    present = {badge_slot(int(item["centre"][0]), frame.size[0]) for item in detect_badges(frame)}
    return [point for slot in sorted(present, reverse=True) if slot != (keep or 0)
            if (point := remove_button_point(frame, slot)) is not None]
