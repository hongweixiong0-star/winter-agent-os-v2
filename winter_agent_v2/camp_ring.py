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
import cv2
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


def reproject_point_on_static_city_view(
    reference_path: Path,
    current_path: Path,
    point_norm: tuple[float, float] | list[float],
    *,
    min_correlation: float = 0.90,
    max_translation_px_half: float = 1.5,
) -> tuple[float, float] | None:
    """Carry a just-observed city target forward only when the new frame is the same view.

    This is deliberately narrower than a general stale-coordinate helper. It serves the
    quick-panel training handoff, where a current-frame camp tap can dismiss a tutorial
    overlay without opening the action bar. The next action is allowed only after a fresh
    screenshot proves HOME is still showing the same city camera. The changing HUD and the
    central tutorial/toast layer are excluded from the image registration; if the remaining
    city background cannot prove near-zero translation, no point is returned.

    The tiny accepted translation is not applied: below the limit its maximum error is under
    three pixels at the supported 720x1280 display, and the returned point remains scoped to
    the fresh frame passed as ``current_path``. Camera movement, page transitions, unreadable
    frames, and larger shifts all return ``None`` so the caller yields rather than tapping.
    """
    try:
        x_norm, y_norm = float(point_norm[0]), float(point_norm[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
        return None
    try:
        with Image.open(reference_path) as source:
            reference = np.asarray(source.convert("L").resize((360, 640)), dtype=np.uint8)
        with Image.open(current_path) as source:
            current = np.asarray(source.convert("L").resize((360, 640)), dtype=np.uint8)
    except (OSError, ValueError):
        return None
    if reference.shape != current.shape:
        return None

    # Only stable city scenery votes. Exclude HUD/event rails and the area occupied by the
    # selected building, tutorial hand, and transient power toast.
    mask = np.zeros((640, 360), dtype=np.uint8)
    mask[88:566, 8:352] = 255
    mask[210:352, 82:278] = 0
    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-6)
    try:
        correlation, warp = cv2.findTransformECC(
            reference.astype(np.float32) / 255.0,
            current.astype(np.float32) / 255.0,
            warp,
            cv2.MOTION_TRANSLATION,
            criteria,
            inputMask=mask,
            gaussFiltSize=5,
        )
    except (cv2.error, ValueError):
        return None
    dx, dy = float(warp[0, 2]), float(warp[1, 2])
    if (
        not np.isfinite(correlation)
        or float(correlation) < float(min_correlation)
        or max(abs(dx), abs(dy)) > float(max_translation_px_half)
    ):
        return None
    return (round(x_norm, 4), round(y_norm, 4))

def focused_camp_body_tap_norm(image_path: Path) -> tuple[float, float] | None:
    """Locate the barracks body after a completed quick-panel row focused it.

    The completed green tile is an entry, not a collect button. On the live 2026-09-25
    route it closes the panel and centers the city view on that camp, with a warm selection
    halo. The next tap belongs on the camp itself to open its 详情 / 升级 / 训练 actions.
    The tutorial hand is also warm-coloured and was previously selected as the largest
    component. The live frame at 14:32:31 has a 2100-pixel hand above a 747-pixel
    horizontal halo; the former produced a tap at (426, 533) and no action bar. Pick the
    current halo itself and tap inside its measured bounds. No reconstructed width or
    remembered offset is used.

    The search is limited to the centered city area where the panel's row-entry transition
    places the selected camp. It requires a large, near-round warm component and refuses
    ambiguous/missing matches. This prevents the many small gold HUD/activity icons around
    the frame from becoming a tap target.

    **What this function returns, stated as the code does it**: the centre of the surviving
    warm component -- i.e. the ring's own centre -- and not a point displaced from the ring.
    An earlier revision of this docstring claimed "the ring is a focus marker, not the
    building's hit area ... the body target is measured relative to the current-frame ring",
    which described a body offset the code has not applied since 2026-09-26. The offset was
    removed on evidence (`camp_ring.py`'s own note: the live Lancer route landed on the lower
    roof, dismissed the tutorial hand, and did not open the action bar), and re-adding one is
    not the fix for a first tap that does not open the bar -- see the measurement below.

    Measured 2026-10-02 over every ``TAP_FOCUSED_TRAINING_CAMP_*`` step that day (12 steps,
    all three camps): 6 FAILURE and 6 SUCCESS, and **every** failure is followed 4-5 s later by
    a success of the same skill on the same camp. The paired examples carry the *same*
    coordinate, so the coordinate is not what differed:

        02:18:52 MARKSMAN point=(0.5021, 0.4602) FAILURE   -> 02:18:56 same point SUCCESS
        04:01:14 SHIELD   point=(0.5021, 0.4613) FAILURE   -> 04:01:19 same point SUCCESS
        04:12:39 LANCER   point=(0.4632, 0.4660) FAILURE   -> 04:12:43 same point SUCCESS
        04:13:21 SHIELD   point=(0.5021, 0.4797) FAILURE   -> 04:13:26 same point SUCCESS

    and the successful frames are exactly the ones where this function returns ``None``
    (no halo left), because the runtime's gated retry then reuses the remembered point through
    ``REOBSERVED_STATIC_CITY_VIEW`` instead of re-measuring. The first tap is absorbed by the
    client's tutorial hand; the second reaches the building. That two-tap interaction is why
    ``verifier.can_reobserve_focused_training_camp_after_nonmenu_tap`` exists, and the honest
    answer to "the first tap did not open the bar" is to let that bounded retry run -- not to
    move this point, which two previous rounds tried on single frames and reverted.
    """
    with Image.open(image_path) as source:
        rgb = np.asarray(source.convert("RGB"))
    height, width = rgb.shape[:2]
    if width <= 0 or height <= 0:
        return None

    hue, saturation, value = _hsv(rgb)
    # The selection halo is translucent in the current client, so its saturation is lower
    # than the older solid-gold ring. The central crop excludes the gold event rail and the
    # upper HUD; the size/shape gates below reject unrelated central artwork.
    x0, x1 = int(width * 0.35), int(width * 0.65)
    y0, y1 = int(height * 0.40), int(height * 0.72)
    mask = (
        (hue[y0:y1, x0:x1] >= 20)
        & (hue[y0:y1, x0:x1] <= 70)
        & (saturation[y0:y1, x0:x1] >= 30)
        & (value[y0:y1, x0:x1] >= 160)
    ).astype(np.uint8)
    # On the live 2026-09-29 frame, a 5x5 close bridged two separate components:
    # the 90x78 selection halo (~970 pixels) and the 54x64 tutorial hand (~1450
    # pixels). Their merged 97x110 box exceeded the 1500-pixel ceiling, so the
    # production route stopped before tapping the focused camp. A 3x3 close keeps
    # the gap: the hand still fails the width gate, while the halo remains a unique
    # plausible target. The synthetic regression case is in
    # test_training_panel_focus_handoff; the live frame was replayed separately.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates: list[tuple[float, float, float, float]] = []
    for index in range(1, count):
        bx, by, box_w, box_h, area = (int(value) for value in stats[index])
        aspect = box_w / max(1, box_h)
        if (
            area < 350 or area > 1500
            or box_w < width * 0.09
            # Current production focus halos measure about 90x78 px at 720x1280.
            # Keep the lower bound relative to the live frame; the narrower tutorial
            # hand is rejected by the width gate after the 3x3 close above.
            or box_h < height * 0.035
            or not 0.75 <= aspect <= 2.4
        ):
            continue
        cx = x0 + bx + box_w / 2.0
        cy = y0 + by + box_h / 2.0
        candidates.append((float(area), cx, cy, float(box_w)))
    if not candidates:
        return None

    # There must be one plausible focus halo. If two similarly large components compete,
    # refuse instead of tapping an arbitrary building.
    candidates.sort(reverse=True)
    if len(candidates) > 1 and candidates[1][0] >= candidates[0][0] * 0.75:
        return None
    _area, ring_x, ring_y, _observed_width = candidates[0]
    # The live Lancer route on 2026-09-26 disproved the old down-left offset: it landed on
    # the lower roof, dismissed the tutorial hand, and did not open the building action bar.
    # The halo itself is centred on the selected building's interactive body. Use that
    # current-frame measurement directly instead of carrying a layout-specific displacement.
    tap_x = ring_x
    tap_y = ring_y
    if not (0.0 <= tap_x < width and 0.0 <= tap_y < height):
        return None
    return (round(tap_x / width, 4), round(tap_y / height, 4))
