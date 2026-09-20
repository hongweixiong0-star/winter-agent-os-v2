"""Where the client's gold selection ring is drawn, on a city frame.

Why this module exists, measured rather than argued.

The training route reaches the infantry camp in two stages: stage A is the camp
highlighted with its radial menu not yet drawn, stage B is the menu.  Stage A is what the
route has been stuck on -- ``KEEP_TRAINING_PRODUCTIVE`` has spent 45 of its 127 steps in
``WAIT_FOR_CAMP_MENU`` and reaches the training page four times -- and the code's reason for
not tapping was that a tutorial finger covers the camp, on the strength of ONE attempt on
2026-09-17.

That reason does not survive its own frame.  Measured over 46 live stage A frames spanning
five separate sessions (2026-09-20 14:49, 15:07, 15:08, 16:05-16:07, 16:38):

                        x            y
    gold ring        306 - 319    578 - 594
    white camp icon  333 - 352    541 - 552
    template tap     346          682      (all 46 frames, identical)

The tap point is **103 px below the ring's centre and 88 px below the ring's own lower
edge** -- it lands on bare ground between the buildings, which the client reads as a map tap.
That is what ``step_004_after_refresh_2`` in
``dataset/raw/control_panel/runtime_training/20260917_train_homefix/`` shows: the map, not a
menu.  The finger was never covering that point.

So the defect is a coordinate one, and it has a measured answer: tap inside the ring.  The
ring is the client's own statement that this building is the selected one, and its position
is read from the frame rather than remembered, so it follows the camera.

What this module deliberately does NOT do: it does not find the ring by itself.  It is only
ever called with the ``roi_norm`` of a ``TARGET_INFANTRY_CAMP_HIGHLIGHTED`` match, so the
premise "this frame is stage A" is established by a template that measures d <= 2 on all 46
of those frames.  A ring detector running over a whole frame would be a detector for gold
UI generally -- the frame's right-hand activity rail is full of it, which is exactly what a
first, unwindowed version of this mask returned.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

#: The ring's own colours, read off the pixels of the 46 measured frames.  Saturated warm
#: yellow, well clear of the pale snow field and the blue chrome.
HUE_LO, HUE_HI = 30, 62
SAT_MIN = 110
VAL_MIN = 170

#: How big the ring has to be before the camp counts as SELECTED -- and this is the
#: discriminator the project had been looking for since 2026-09-17.
#:
#: Two human-verified frames carry the same semantic and were tapped to different ends:
#:
#:   camp_with_gold_ring__click_opens_menu__20260908.png    ring bbox 205 x 112   menu
#:   camp_with_officer_badge__click_jumps_to_map__20260917  ring bbox   7 x  15   map
#:
#: 205 against 7 is two orders of magnitude, and it is the ring *size* that separates them,
#: not the template distance -- that reads 0.0 against 8.0, i.e. the failing frame sits
#: exactly on the production gate, which is why
#: ``test_the_camp_highlight_signal_cannot_tell_the_two_states_apart`` concluded the signal
#: was nearly blind.  It was measuring the wrong quantity: what the failing frame has is a
#: sliver of gold (an officer badge's edge), not the selection ring at all.
#:
#: So a ring smaller than this is not a selection, and the honest answer is None -- which
#: makes the caller wait rather than tap, the safe side.  Thresholds are normalised and sit
#: far from both populations: real rings measure 0.28 x 0.088 of the frame.
MIN_WIDTH_NORM = 0.12
MIN_HEIGHT_NORM = 0.05


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = rgb[:, :, 0].astype(int)
    g = rgb[:, :, 1].astype(int)
    b = rgb[:, :, 2].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    diff = np.maximum(mx - mn, 1)
    hue = np.zeros_like(mx, dtype=float)
    mx_r = mx == r
    mx_g = (mx == g) & ~mx_r
    hue = np.where(mx_r, (60 * ((g - b) / diff) + 360) % 360, hue)
    hue = np.where(mx_g, 60 * ((b - r) / diff) + 120, hue)
    hue = np.where((mx == b) & ~mx_r & ~mx_g, 60 * ((r - g) / diff) + 240, hue)
    return hue, 255 * (mx - mn) // np.maximum(mx, 1), mx


def ring_centre_norm(
    image_path: Path,
    roi_norm: dict[str, float] | None,
) -> tuple[float, float] | None:
    """Centre of the selection ring inside ``roi_norm``, in frame-normalised coordinates.

    ``roi_norm`` is the matched template's own region, so no coordinate is hardcoded: the
    search covers exactly what the recogniser already looked at.  ``None`` -- no window, no
    ring pixels, or a box that degenerates to a point -- is the honest answer; a fallback to
    the template's own centre is the bug this replaces, so there is none.
    """
    if not isinstance(roi_norm, dict):
        return None
    try:
        x_norm = float(roi_norm["x_norm"])
        y_norm = float(roi_norm["y_norm"])
        w_norm = float(roi_norm["w_norm"])
        h_norm = float(roi_norm["h_norm"])
    except (KeyError, TypeError, ValueError):
        return None
    if w_norm <= 0 or h_norm <= 0:
        return None

    with Image.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]

    x0 = max(0, min(width, int(round(x_norm * width))))
    y0 = max(0, min(height, int(round(y_norm * height))))
    x1 = max(0, min(width, int(round((x_norm + w_norm) * width))))
    y1 = max(0, min(height, int(round((y_norm + h_norm) * height))))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None

    window = np.zeros((height, width), dtype=bool)
    window[y0:y1, x0:x1] = True

    hue, sat, val = _hsv(rgb)
    ring = window & (hue >= HUE_LO) & (hue < HUE_HI) & (sat >= SAT_MIN) & (val >= VAL_MIN)
    ys, xs = np.nonzero(ring)
    if len(xs) == 0:
        return None

    # A sliver of gold is not a selection.  See MIN_WIDTH_NORM: the frame whose tap jumped to
    # the map carries a 7 x 15 px fleck, and the one that opened the menu carries 205 x 112.
    if (xs.max() - xs.min()) < MIN_WIDTH_NORM * width:
        return None
    if (ys.max() - ys.min()) < MIN_HEIGHT_NORM * height:
        return None

    # The box's centre, not the pixel mean: the ring is an annulus and its lower arc is the
    # thickest part (it is drawn as a glowing ellipse), so a centroid is pulled downwards.
    cx = (float(xs.min()) + float(xs.max())) / 2.0
    cy = (float(ys.min()) + float(ys.max())) / 2.0
    if not (0.0 <= cx <= width and 0.0 <= cy <= height):
        return None
    return (round(cx / width, 4), round(cy / height, 4))
