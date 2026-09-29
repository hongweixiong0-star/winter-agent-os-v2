# -*- coding: utf-8 -*-
"""ROI-first OCR — small UI text (22-24 px) is missed by whole-frame OCR.

Measured 2026-09-28 on the gather search panel's resource tab strip
(dataset/evidence/gather_wood4_20260928_0035/02_wood_tab.png, 720x1280):

    whole-frame OCR        -> 木材/煤矿/铁矿  NOT detected
    label-row crop + OCR   -> 殖场(22px) 生肉(24px) 木材(22px) 煤矿(23px) 铁矿(24px)

The engine normalises the *candidate region*, so cropping to the text band
before recognition turns a miss into a hit.  Upscaling 3-4x further stabilises
the read but is not strictly required for these labels.

The same class of miss explains the earlier "tab 标签被图标压住读不出" notes:
the fix is ROI-first OCR, not more keywords.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Where the gather panel's resource tab labels sit (y bands in 720x1280 frames).
#: Two bands because the panel shifts vertically depending on the level slider row.
RESOURCE_TAB_BANDS: Tuple[Tuple[int, int], ...] = ((860, 960), (900, 1000), (830, 930))

#: Resource tab labels, including the truncated forms OCR sometimes returns
#: (「养殖场」 -> 「殖场」).
RESOURCE_TAB_WORDS: Tuple[str, ...] = (
    "野兽", "冰原巨兽", "大型养殖场", "养殖场", "殖场", "生肉",
    "木材", "煤矿", "铁矿", "石头", "食物",
)


def ocr_region(frame: Any, box: Sequence[int], upscale: int = 2,
               rapid_ocr=None) -> List[Dict[str, Any]]:
    """OCR a cropped region and return tokens in FULL-FRAME coordinates.

    box = (x0, y0, x1, y1) in the frame's own pixels.

    This IS the operating path for text under VISION_POLICY_V1 (section B):
    OpenCV/geometry locates the ROI, then OCR runs on the crop.  It is still banned
    inside a realtime control loop (section C/F).
    """
    from .vision_policy import guard_ocr as _vp_guard_ocr  # VISION_POLICY_V1 C/F
    _vp_guard_ocr("ocr_roi.ocr_region")
    if rapid_ocr is None:
        from winter_agent_v2.executor_router import _rapid_ocr_results as rapid_ocr  # type: ignore
    import numpy as np
    x0, y0, x1, y1 = (int(v) for v in box)
    crop = frame.crop((x0, y0, x1, y1))
    if upscale > 1:
        crop = crop.resize((crop.size[0] * upscale, crop.size[1] * upscale), 1)  # 1 = LANCZOS
    toks = rapid_ocr(np.asarray(crop.convert("RGB")), None, [])
    out: List[Dict[str, Any]] = []
    for t in toks:
        b = t.get("box") or ()
        if len(b) != 4:
            continue
        x, y, w, h = (float(v) / upscale for v in b)
        out.append({"text": t["text"],
                    "box": (x0 + x, y0 + y, w, h),
                    "centre": (int(x0 + x + w / 2), int(y0 + y + h / 2))})
    for t in out:
        # The tab control is ICON + LABEL as one element (constitution A §二: no
        # click offsets, no scaled label boxes).  Express the control as the
        # composite box and tap its centre.
        x, y, w, h = t["box"]
        ctrl_y0 = max(0, y - 90)          # icon band above the label
        t["control_box"] = (x, ctrl_y0, x + w, y + h)
        t["control_centre"] = (int(x + w / 2), int((ctrl_y0 + y + h) / 2))
    return out


def find_resource_tab(frame: Any, labels: Sequence[str] = RESOURCE_TAB_WORDS,
                      rapid_ocr=None) -> Optional[Dict[str, Any]]:
    """Return {"text","centre","box"} of the resource tab that matches ``labels``.

    ROI-first: only the label bands are recognised, so 22-px text is read.
    """
    for (y0, y1) in RESOURCE_TAB_BANDS:
        toks = ocr_region(frame, (0, y0, frame.size[0], y1), upscale=2, rapid_ocr=rapid_ocr)
        for t in toks:
            if any(w in t["text"] for w in labels):
                return t
    return None


def find_resource_tabs(frame: Any, rapid_ocr=None) -> List[Dict[str, Any]]:
    """All resource tabs visible in the strip (left→right sorted by x)."""
    best: List[Dict[str, Any]] = []
    for (y0, y1) in RESOURCE_TAB_BANDS:
        toks = ocr_region(frame, (0, y0, frame.size[0], y1), upscale=2, rapid_ocr=rapid_ocr)
        hits = [t for t in toks if any(w in t["text"] for w in RESOURCE_TAB_WORDS)]
        if len(hits) > len(best):
            best = hits
    return sorted(best, key=lambda t: t["centre"][0])
