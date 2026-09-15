"""Detect intel mission pins on the live intel page.

Live finding 2026-09-14 17:24: the operator pointed out the intel page holds
dozens of mission pins while our reader reported available_count=0.  The page
is a zoomed map sprinkled with teardrop pins (purple / blue / orange bodies,
white icon, thin white rim) on a pale snowy background with dark trees.  The
existing vision only recognised the mission CARD that opens after tapping a
pin, never the pins themselves, so whole batches of intel work were invisible.

Detector: HSV mask for saturated pin colours, connected components, then keep
blobs shaped like pins (area and aspect bounds) and report the tap point
(blob centre, slightly above the tip).

Colour classes are NOT a claimability signal.  The earlier note here said
"ORANGE -> completed / claimable missions (claim first)"; the live client
contradicts it.  Measured 2026-09-14:
- ORANGE pin at (211,664) opened 大师悬赏：20号, which the vision reads as
  ``INTEL_MASTER_BOUNTY`` with status ``BLOCKED`` (recommended power 189M) - an
  actionable target, not a reward to claim.
- ORANGE pin at (215,611) opened a Hero Journey mission card rendered with an
  orange banner.
So colour varies per pin and per mission; treat it as a rendering attribute and
decide from the card the brain reads, never from the colour.  What each colour
actually encodes is UNKNOWN - do not guess it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class IntelPin:
    x: int
    y: int
    color: str
    area: int

    @property
    def center_norm(self) -> tuple[float, float]:
        return (round(self.x, 4), round(self.y, 4))


def _mask_for(rgb: np.ndarray, hue_lo: int, hue_hi: int, sat_lo: int, val_lo: int) -> np.ndarray:
    r = rgb[:, :, 0].astype(int)
    g = rgb[:, :, 1].astype(int)
    b = rgb[:, :, 2].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    diff = np.maximum(mx - mn, 1)
    # hue 0-360
    hue = np.zeros_like(mx)
    mask_mx_r = mx == r
    mask_mx_g = (mx == g) & ~mask_mx_r
    hue = np.where(mask_mx_r, (60 * ((g - b) / diff) + 360) % 360, hue)
    hue = np.where(mask_mx_g, 60 * ((b - r) / diff) + 120, hue)
    hue = np.where((mx == b) & ~mask_mx_r & ~mask_mx_g, 60 * ((r - g) / diff) + 240, hue)
    sat = 255 * (mx - mn) // np.maximum(mx, 1)
    val = mx
    return (hue >= hue_lo) & (hue < hue_hi) & (sat >= sat_lo) & (val >= val_lo)


def _components(mask: np.ndarray) -> list[dict]:
    """Tiny 2-pass labelling; the masks are small (720x1280) so this is fine."""
    visited = np.zeros(mask.shape, dtype=bool)
    blobs: list[dict] = []
    height, width = mask.shape
    for y in range(height):
        row = mask[y]
        for x in np.nonzero(row & ~visited[y])[0]:
            stack = [(int(x), y)]
            pixels: list[tuple[int, int]] = []
            visited[y, x] = True
            while stack:
                cx, cy = stack.pop()
                pixels.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((nx, ny))
            blobs.append({"pixels": pixels})
    return blobs


def intel_pin_centers(image_path: Path, min_area: int = 800, max_area: int = 12000) -> list[IntelPin]:
    """Return the mission pins visible on an intel-page frame, top to bottom.

    Measured on the live client 2026-09-14: pin bodies are ~2700-3400 px, the
    claimable-beast pin's glow halo pushes its blob to ~6-9k, and the purple
    bodies are DARK (hsv hue ~286, sat ~251, val ~81), so the purple gate must
    not require a high value.  Anything below ~800 px is banner text, snow
    shading or the mail blimp, not a pin.
    """
    with Image.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]

    # Pin bodies: saturated cool colours (purple/blue) plus orange claimables.
    purple = _mask_for(rgb, 250, 330, 70, 50)
    blue = _mask_for(rgb, 195, 250, 90, 110)
    orange = _mask_for(rgb, 10, 55, 90, 120)

    pins: list[IntelPin] = []
    for name, mask in (("PURPLE", purple), ("BLUE", blue), ("ORANGE", orange)):
        for blob in _components(mask):
            area = len(blob["pixels"])
            if not (min_area <= area <= max_area):
                continue
            xs = [p[0] for p in blob["pixels"]]
            ys = [p[1] for p in blob["pixels"]]
            w = max(xs) - min(xs) + 1
            h = max(ys) - min(ys) + 1
            # Teardrop pins: taller than (or as wide as) they are long, and
            # never the flat refresh banner (h ~ 47) nor sprawling snow.
            #
            # The lower bound is 0.5, not 0.65, because an orange pin carries a
            # glow halo that inflates the blob DOWNWARD: the pin itself is a
            # normal teardrop but the measured blob reaches ratio ~0.62-0.64.
            # Measured 2026-09-15 over 22 live frames (5 independent boards,
            # plus 16 frames without such a pin): the halo'd pin measured
            # w 86-87, h 135-139, ratio 0.619-0.644, white icon present; and
            # moving the floor from 0.65 to 0.5 admitted EXACTLY that one blob
            # per affected board and zero blobs on every other frame.
            # At 0.65 the pin was dropped silently, which made a full board read
            # as empty - reproduced live 2026-09-15 07:36, where the client
            # showed 5 pins, the detector returned 4, and production reported
            # available_count=0 and stopped the goal as "complete".
            if h < 60 or w < 40 or not (0.5 <= w / max(h, 1) <= 1.3):
                continue
            fill = area / (w * h)
            if fill < 0.30:
                continue
            # Every pin carries a WHITE icon in its head; blue snow shadows
            # (the main false positive) have none inside their own body.
            if not _has_white_icon(rgb, xs, ys):
                continue
            cx = int(round(sum(xs) / len(xs)))
            # Tap the head of the pin (upper 2/3), not the snowy ground below.
            cy = int(round(min(ys) + (max(ys) - min(ys)) * 0.42))
            pins.append(IntelPin(x=cx, y=cy, color=name, area=area))
    # A pin's soft glow can split off low-fill fragments nearby; keep the
    # largest candidate per ~45 px neighbourhood.
    pins.sort(key=lambda p: -p.area)
    kept: list[IntelPin] = []
    for pin in pins:
        if all((pin.x - k.x) ** 2 + (pin.y - k.y) ** 2 > 45 ** 2 for k in kept):
            kept.append(pin)
    kept.sort(key=lambda p: (p.y, p.x))
    return kept


def _has_white_icon(rgb: np.ndarray, xs: list[int], ys: list[int]) -> bool:
    """True when the blob's head contains a compact white icon (pin) ."""
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    cx0, cx1 = x0 + (x1 - x0) // 4, x1 - (x1 - x0) // 4
    cy0, cy1 = y0 + (y1 - y0) // 5, y0 + (y1 - y0) * 3 // 5
    region = rgb[cy0:cy1, cx0:cx1]
    if region.size == 0:
        return False
    r = region[:, :, 0].astype(int)
    g = region[:, :, 1].astype(int)
    b = region[:, :, 2].astype(int)
    white = (r >= 235) & (g >= 235) & (b >= 235)
    return bool(white.sum() >= 40)


def annotate(image_path: Path, pins: list[IntelPin], out_path: Path) -> None:
    from PIL import ImageDraw

    with Image.open(image_path) as image:
        frame = image.convert("RGB")
    draw = ImageDraw.Draw(frame)
    for index, pin in enumerate(pins):
        draw.ellipse((pin.x - 16, pin.y - 16, pin.x + 16, pin.y + 16), outline=(255, 0, 0), width=3)
        draw.text((pin.x + 20, pin.y - 10), f"{index}:{pin.color}", fill=(255, 0, 0))
    frame.save(out_path)
