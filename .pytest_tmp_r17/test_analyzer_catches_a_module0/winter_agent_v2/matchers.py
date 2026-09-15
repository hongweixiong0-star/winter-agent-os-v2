"""Template matchers for the vision layer, with an evidence-driven choice.

The original matcher crops a FIXED ROI and compares phash hamming distance.
That is brittle in three specific ways measured on 2026-09-14:

1. position - the crop must sit exactly where the template was registered, so
   a few pixels of layout drift push the distance up and the template is
   declared stale;
2. scale - one resolution only;
3. signature - a 64-bit global hash discards local structure, so unrelated
   controls can land within a few hamming units.

``match_ccoeff`` searches a window around the registered ROI with OpenCV's
normalised cross-correlation, multi-scale, and returns a 0..1 score plus the
best centre.  Scores separate positives from negatives far more cleanly than
hamming distance, which is what the A/B in tools/ab_matcher.py measures before
any default is changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

SCALES = (0.9, 1.0, 1.1)
SEARCH_MARGIN = 40  # px of slack around the registered ROI


@dataclass(frozen=True)
class CcoeffMatch:
    score: float
    center_norm: tuple[float, float]
    scale: float
    bounds: tuple[int, int, int, int]


def match_ccoeff(
    image_path: Path,
    template_path: Path,
    roi_norm: dict[str, float],
    *,
    margin: int = SEARCH_MARGIN,
    scales: tuple[float, ...] = SCALES,
) -> CcoeffMatch | None:
    """Best multi-scale normalised cross-correlation inside the search window."""
    with Image.open(image_path) as src:
        frame = np.asarray(src.convert("RGB"))
    with Image.open(template_path) as tpl:
        template0 = np.asarray(tpl.convert("RGB"))
    height, width = frame.shape[:2]

    x0 = max(0, round(roi_norm["x_norm"] * width) - margin)
    y0 = max(0, round(roi_norm["y_norm"] * height) - margin)
    x1 = min(width, round((roi_norm["x_norm"] + roi_norm["w_norm"]) * width) + margin)
    y1 = min(height, round((roi_norm["y_norm"] + roi_norm["h_norm"]) * height) + margin)
    window = frame[y0:y1, x0:x1]
    if window.size == 0:
        return None

    best: CcoeffMatch | None = None
    for scale in scales:
        tw = max(8, round(template0.shape[1] * scale))
        th = max(8, round(template0.shape[0] * scale))
        if th >= window.shape[0] or tw >= window.shape[1]:
            continue
        template = cv2.resize(template0, (tw, th), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if best is None or score > best.score:
            cx = x0 + location[0] + tw / 2
            cy = y0 + location[1] + th / 2
            best = CcoeffMatch(
                score=float(score),
                center_norm=(round(cx / width, 4), round(cy / height, 4)),
                scale=scale,
                bounds=(x0 + location[0], y0 + location[1], tw, th),
            )
    return best
