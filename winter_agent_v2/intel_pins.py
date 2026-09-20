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

COLOUR COVERAGE (open issue #68, 2026-09-20)
--------------------------------------------
The mask list is what this detector can SEE, not what the board draws, and the
two drifted apart.  Measured on the 2026-09-20 board
(dataset/truth_audit/reward_popup_exit_20260920/readings/intel_page_20260920T131907.png):
the detector returned 4 while the board carried 9 markers.  Cropped and looked at
one by one, the five it missed are the same object as the ones it found -- teardrop
body, white head icon, orange base ring -- and differ only in body colour:

  counted   BLUE (266,692)  PURPLE (326,695)  PURPLE (283,841)  ORANGE (273,768)
  missed    GREEN (541,399) GREEN (210,614)   GREY (104,593)    GREY (344,765)

GREEN was a systematic omission: over the corpus of intel-page frames, 40 of 40
frames from 2026-09-20 carry at least one green pin the detector did not count
(69 in total), 20 of 40 from 2026-09-19, 11 of 11 from 2026-09-17, and 0 of 40 from
2026-09-14 -- every added blob measuring w 51-67, h 73-77, i.e. the same geometry
the counted pins have.  The detector reads the board's *pins*; which colours the
board happens to draw is not a property the caller can be asked to know in advance.

GREY is admitted with two bounds, because colour alone cannot separate it and the
neutral mask is the only one that admits the page's own chrome.  Measured over the
435-frame intel corpus, the two false positives are:

  * the page title 情報, a neutral blob with white pixels in it that is on
    essentially every intel frame -- w 165-166 at y 73-85, against every real pin's
    w 51-107.  Without a bound the grey mask is a title detector: 1-2 admissions on
    53 of 60 corpus frames.  Hence ``max_width``.
  * a top-left HUD element at y 38-57, x 30-42, on 23 of 435 frames.  Hence
    ``BOARD_TOP``: the topmost real pin of ANY colour in the corpus is y 261 (PURPLE
    at 354,261; ORANGE 278, BLUE 282, GREEN 321), and **only GREY** produced a blob
    with a tap point above 200.  The floor is therefore applied to the neutral class
    alone, so it cannot cost a coloured pin that a panned board might place higher.

No saturation bound separates the two populations: the title's median saturation is
54 and the two real grey pins' are 21-22, but tightening to 50, 40, 30 or 25 kept the
title (or swapped it for neutral terrain) while 20 dropped the real pins too.  The
orange base ring test drops one of the two real grey pins, because a grey blob's
vertical extent reaches past its own ring.

A false positive here is not cosmetic either -- ``available_count`` staying above zero
forever means the CLEAR_INTEL goal can never honestly complete, the mirror of the
false completion this module already records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

#: The lowest tap point the neutral (grey) mask may report.  Measured, not tuned: the
#: topmost real pin of any colour over the 435-frame intel corpus is y 261, while the
#: two neutral false positives are the page title (y 73-85) and a HUD element (y
#: 38-57).  See the module docstring.
BOARD_TOP = 200


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


def _neutral_mask(rgb: np.ndarray, sat_max: int = 60,
                  val_lo: int = 60, val_hi: int = 215) -> np.ndarray:
    """The grey / silver pin bodies, which have no hue to gate on.

    Saturation and value bounds only, so this is the loosest mask here and the only
    one that needs the width bound below to keep the page title out (see the module
    docstring).  The value band excludes both the pale snow field above it and the
    dark trees below it.
    """
    r = rgb[:, :, 0].astype(int)
    g = rgb[:, :, 1].astype(int)
    b = rgb[:, :, 2].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = 255 * (mx - mn) // np.maximum(mx, 1)
    return (sat <= sat_max) & (val_lo <= mx) & (mx <= val_hi)


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


def intel_pin_centers(image_path: Path, min_area: int = 800, max_area: int = 12000,
                      max_width: int = 130) -> list[IntelPin]:
    """Return the mission pins visible on an intel-page frame, top to bottom.

    Measured on the live client 2026-09-14: pin bodies are ~2700-3400 px, the
    claimable-beast pin's glow halo pushes its blob to ~6-9k, and the purple
    bodies are DARK (hsv hue ~286, sat ~251, val ~81), so the purple gate must
    not require a high value.  Anything below ~800 px is banner text, snow
    shading or the mail blimp, not a pin.

    ``max_width`` is measured, not tuned: over the intel-page corpus every real pin
    is w 51-107 (730-2600 px of body), while the one neutral blob that passes the
    shape and white-icon filters but is not a pin -- the page title 情报 on the
    header band -- is w 165-166.  130 sits between the two populations with ~20 %
    margin on the pin side.
    """
    with Image.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]

    # Pin bodies: saturated cool colours (purple/blue) plus orange claimables, green
    # (measured 2026-09-19/20), and the neutral grey/silver ones.  See the module
    # docstring for the measurement behind each.
    purple = _mask_for(rgb, 250, 330, 70, 50)
    blue = _mask_for(rgb, 195, 250, 90, 110)
    orange = _mask_for(rgb, 10, 55, 90, 120)
    green = _mask_for(rgb, 70, 170, 90, 90)
    grey = _neutral_mask(rgb)

    pins: list[IntelPin] = []
    # Only the neutral mask carries a floor: it is the one that admits the page's own
    # chrome, and every such admission measured is above BOARD_TOP while no real pin
    # of any colour is.  See the module docstring for the numbers.
    for name, mask, min_y in (("PURPLE", purple, 0), ("BLUE", blue, 0),
                              ("ORANGE", orange, 0), ("GREEN", green, 0),
                              ("GREY", grey, BOARD_TOP)):
        for blob in _components(mask):
            area = len(blob["pixels"])
            if not (min_area <= area <= max_area):
                continue
            xs = [p[0] for p in blob["pixels"]]
            ys = [p[1] for p in blob["pixels"]]
            w = max(xs) - min(xs) + 1
            h = max(ys) - min(ys) + 1
            if w > max_width:
                continue
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
            if cy < min_y:
                continue
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
