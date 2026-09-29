# -*- coding: utf-8 -*-
"""Read EVERYTHING on a screenshot — standing rule (operator, 2026-09-28):

    "以后任意截图你都要能读出来，不要漏掉按钮信息"

Whole-frame OCR alone misses small UI text (resource tabs measured at 22-24 px,
see knowledge/formation/formation_policy_rules.json#ocr_roi_lesson_20260928).
This module runs several complementary passes and merges the结果:

  P1 whole frame                      — big text, always safe
  P2 grid tiling 3x5 with overlap, x2 — recovers small text the detector drops
  P3 UI bands (top bar / tab strip / button row / left+right rails) at x3
      — buttons and tabs live here; this is the pass that must not fail
  P4 optional HSV-contrast boost on bands (white-on-light labels)

Tokens are merged by text equality + centre proximity, keeping the highest score.
`read_all(frame)` is the single entry point every future tool should call instead
of a bare whole-frame OCR.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: UI bands in 720x1280 reference frames that carry buttons / tabs / labels
UI_BANDS: Tuple[Tuple[str, Tuple[int, int, int, int]], ...] = (
    ("top_bar", (0, 0, 720, 120)),
    ("mid_upper", (0, 120, 720, 400)),
    ("tab_strip_a", (0, 830, 720, 1010)),
    ("tab_strip_b", (0, 880, 720, 1060)),
    ("button_row", (0, 1120, 720, 1280)),
    ("left_rail", (0, 300, 140, 1100)),
    ("right_rail", (580, 300, 720, 1100)),
)


def _rapid():
    from winter_agent_v2.executor_router import _rapid_ocr_results
    return _rapid_ocr_results


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "") if not ch.isspace())


def _merge(tokens: List[Dict[str, Any]], new: List[Dict[str, Any]],
           min_dist: float = 14.0) -> List[Dict[str, Any]]:
    """Add tokens that are not already covered (same text & nearby centre)."""
    for t in new:
        keep = True
        for u in tokens:
            if _norm(t["text"]) == _norm(u["text"]):
                dx = abs(t["centre"][0] - u["centre"][0])
                dy = abs(t["centre"][1] - u["centre"][1])
                if dx <= min_dist and dy <= min_dist:
                    keep = False
                    break
        if keep:
            tokens.append(t)
    return tokens


def _tokens_from(raw: List[Dict[str, Any]], ox: int, oy: int, scale: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in raw:
        b = t.get("box") or ()
        if len(b) != 4:
            continue
        x, y, w, h = (float(v) / scale for v in b)
        out.append({
            "text": t["text"],
            "box": (ox + x, oy + y, w, h),
            "centre": (int(ox + x + w / 2), int(oy + y + h / 2)),
            "height": int(h),
            "source": t.get("source", "?"),
        })
    return out


def read_all(frame: Any, rapid_ocr=None, grid: Tuple[int, int] = (3, 5),
             overlap: float = 0.2, verbose: bool = False) -> List[Dict[str, Any]]:
    """All text on the frame, small UI text and buttons included.

    EVIDENCE / DEBUG tool.  Under VISION_POLICY_V1 this is NOT the operating path:
    operation goes OpenCV-first and, when text is genuinely needed, crops the ROI and
    calls RapidOCR on the crop (section B).  It stays because the operator's standing
    rule is that a screenshot handed over for review must be read completely — that
    rule is about reading evidence, not about driving the game.
    """
    from .vision_policy import guard_ocr as _vp_guard_ocr  # VISION_POLICY_V1 C/F
    _vp_guard_ocr("ocr_full.read_all")
    rapid = rapid_ocr or _rapid()
    W, H = frame.size
    sx, sy = W / 720.0, H / 1280.0
    tokens: List[Dict[str, Any]] = []

    # P1 whole frame
    p1 = _tokens_from(rapid(_as_array(frame), None, []), 0, 0, 1.0)
    for t in p1:
        t["source"] = "whole"
    tokens = _merge(tokens, p1)

    # P2 grid tiling
    cols, rows = grid
    tw, th = W / cols, H / rows
    for r in range(rows):
        for c in range(cols):
            x0 = max(0, int(c * tw - tw * overlap))
            y0 = max(0, int(r * th - th * overlap))
            x1 = min(W, int((c + 1) * tw + tw * overlap))
            y1 = min(H, int((r + 1) * th + th * overlap))
            crop = frame.crop((x0, y0, x1, y1))
            crop = crop.resize((crop.size[0] * 2, crop.size[1] * 2), 1)  # LANCZOS
            new = _tokens_from(rapid(_as_array(crop), None, []), x0, y0, 2.0)
            for t in new:
                t["source"] = "grid"
            tokens = _merge(tokens, new)

    # P3 UI bands at 3x (buttons / tabs / rails)
    for name, (bx0, by0, bx1, by1) in UI_BANDS:
        x0, y0 = int(bx0 * sx), int(by0 * sy)
        x1, y1 = int(bx1 * sx), int(by1 * sy)
        crop = frame.crop((x0, y0, x1, y1))
        crop = crop.resize((crop.size[0] * 3, crop.size[1] * 3), 1)
        new = _tokens_from(rapid(_as_array(crop), None, []), x0, y0, 3.0)
        for t in new:
            t["source"] = f"band:{name}"
        tokens = _merge(tokens, new)

    if verbose:
        counts: Dict[str, int] = {}
        for t in tokens:
            counts[t["source"]] = counts.get(t["source"], 0) + 1
        print("read_all sources:", counts, "total:", len(tokens))
    return sorted(tokens, key=lambda t: (t["centre"][1], t["centre"][0]))


def _as_array(img: Any):
    import numpy as np
    return np.asarray(img.convert("RGB") if hasattr(img, "convert") else img)


def read_text(frame: Any, **kw) -> str:
    return " ".join(t["text"] for t in read_all(frame, **kw))


def find_text(frame: Any, needles: Sequence[str], **kw) -> Optional[Dict[str, Any]]:
    """Locate any of ``needles`` anywhere on the frame (buttons included)."""
    for t in read_all(frame, **kw):
        if any(n in t["text"] for n in needles):
            return t
    return None
