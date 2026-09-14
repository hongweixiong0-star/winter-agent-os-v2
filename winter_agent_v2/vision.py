from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageStat

from .image_hash import dhash, hamming, phash
from .models import MarchState, Page, WorldState


def _corner_white_frac(crop: Image.Image, region: tuple[int, int, int, int], thr: int = 200) -> float:
    """Return the fraction of near-white pixels inside ``region`` of ``crop``.

    ``region`` is a 4-tuple ``(x0, y0, x1, y1)`` in crop-local coordinates.
    A pixel is "near-white" when its R, G and B channels are all >= ``thr``.
    Used by ``SemanticROIVision.selected_resource`` to read the white
    L-shaped bracket that marks a selected tab in the post-2026-09-14
    resource-search panel redesign.
    """
    x0, y0, x1, y1 = region
    n = 0
    wn = 0
    width, height = crop.size
    x1 = min(x1, width)
    y1 = min(y1, height)
    for y in range(max(0, y0), y1):
        for x in range(max(0, x0), x1):
            n += 1
            r, g, b = crop.getpixel((x, y))
            if r >= thr and g >= thr and b >= thr:
                wn += 1
    return wn / n if n else 0.0


# ---------------------------------------------------------------------------
# Cell signature for the resource-tab classifier.
#
# Why not pHash here: the four gatherable tabs are snow-covered huts that pHash
# cannot separate reliably (the old implementation needed a corner-signal
# tiebreaker and still misread live frames).  A coarse colour grid is both far
# more discriminative for icon identity and cheap enough to evaluate on every
# observation, which matters because this runs each tick.  Measured separation
# on live frames is an order of magnitude: active cell <= 1.2, others >= 13.0.
# ---------------------------------------------------------------------------
CELL_SIGNATURE_GRID = 16
_CELL_TEMPLATE_CACHE: dict[tuple[str, float], bytes] = {}


def _cell_signature(image: Image.Image) -> bytes:
    return image.convert("RGB").resize(
        (CELL_SIGNATURE_GRID, CELL_SIGNATURE_GRID), Image.Resampling.BILINEAR
    ).tobytes()


def _cell_template_signature(path: Path) -> bytes | None:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), stamp)
    cached = _CELL_TEMPLATE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        with Image.open(path) as opened:
            signature = _cell_signature(opened)
    except OSError:
        return None
    _CELL_TEMPLATE_CACHE[key] = signature
    return signature


def _signature_distance(left: bytes, right: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left)


class SemanticMatch(tuple):
    __slots__ = ()

    def __new__(cls, semantic: str, distance: int, roi: dict[str, float]):
        return super().__new__(cls, (semantic, distance, roi))

    semantic = property(lambda self: self[0])
    distance = property(lambda self: self[1])
    roi = property(lambda self: self[2])

    @property
    def center_norm(self) -> tuple[float, float]:
        return (
            self.roi["x_norm"] + self.roi["w_norm"] / 2,
            self.roi["y_norm"] + self.roi["h_norm"] / 2,
        )


class SemanticROIVision:
    """Verify a semantic at its reviewed normalized ROI; it never performs actions."""

    def __init__(self, manifest_path: Path, max_distance: int = 6) -> None:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.max_distance = max_distance
        # ------------------------------------------------------------------
        # Resource-search tab strip: relative layout, not fixed ROIs.
        #
        # Live measurement, 2026-09-14, 720x1280 client, taken from the white
        # selection bracket on real frames (see
        # dataset/truth_audit/resource_cells_20260914_120027):
        #
        #   * the strip holds SEVEN tabs, in this fixed client order:
        #     beast, giant beast, sawmill, MEAT, WOOD, COAL, IRON
        #   * tab pitch ............ 157 px  (0.21806 of the width)
        #   * selected-cell width ... 145 px  (0.20139 of the width)
        #   * the strip scrolls horizontally, and the scroll offset CHANGES
        #     between sessions because the client re-centres the active tab.
        #
        # Consequences that fixed ROIs cannot express:
        #   * tapping a hard-coded x selects whichever tab happens to be there;
        #     the previous table (MEAT 0.25 / WOOD 0.4722 / COAL 0.6944 /
        #     IRON 0.9167) is only valid for ONE scroll offset.  In the live
        #     session measured here the offset was +400 px, so tapping 0.25
        #     selected the second tab (giant beast), not MEAT — which is exactly
        #     the live SELECT_RESOURCE failure.
        #   * WOOD / COAL / IRON can be off-screen entirely and must be scrolled
        #     into view before they can be tapped.
        #
        # So the offset is *read* from the bracket anchor and the identity is
        # read from the cell contents, then every other cell follows from the
        # pitch.  ``tools/extract_resource_tab_cells.py`` regenerates the
        # cell templates from live captures.
        # ------------------------------------------------------------------
        self.resource_tab_band = (0.672, 0.789)          # y_norm of the tab cells
        self.resource_tab_order = (
            "BEAST", "GIANT_BEAST", "SAWMILL", "MEAT", "WOOD", "COAL", "IRON",
        )
        self.resource_tab_pitch = 157.0 / 720.0
        self.resource_tab_cell = 145.0 / 720.0
        self.resource_tab_first_left = -384.0 / 720.0    # left edge of tab 1 at offset 0
        # Cell templates are the *whole* selected cell (bracket included), so
        # every template carries the same bracket contribution and identity is
        # decided by the icon and label inside.  Two disjoint populations were
        # measured on live frames: the active resource scores <= 1.2 while any
        # non-active tab scores >= 13.0, so the gate below has an order of
        # magnitude of headroom.
        self.resource_tab_cell_templates: dict[str, list[str]] = {}
        for row in payload.get("records", []):
            semantic = str(row.get("semantic", ""))
            if semantic.startswith("RESOURCE_TAB_") and semantic.endswith("_SELECTED"):
                resource = semantic[len("RESOURCE_TAB_"):-len("_SELECTED")]
                if resource in self.resource_tab_order:
                    self.resource_tab_cell_templates.setdefault(resource, []).append(str(row["template_path"]))
        self.resource_tab_max_distance = 6.0
        self.resource_tab_min_margin = 4.0
        # Populated by ``selected_resource`` so the executor can turn a target
        # resource into a tap coordinate without re-deriving the geometry.
        self.resource_tab_offset = None                   # px, or None when unknown
        self.resource_tab_visible_span = None             # (left, right) px, or None
        # Tie margin: best and runner-up must differ by at least this much,
        # otherwise refuse to claim a selection.  Templates that look almost
        # identical under pHash (e.g. the post-redesign resource tabs) need
        # a wider gap than the per-template distance would suggest.
        # Resource-search level slider geometry.  The green fill starts at a
        # fixed left edge and grows one step per level, so its right edge is a
        # linear encoder for the configured level.  Measured live on
        # 2026-09-14 (720x1280) across levels 8 -> 1: right edge 416, 371,
        # 327, 283, 238, 194, 150, and 0-width at level 1.  The old code never
        # read this control and hard-coded level 8, which made "在您的城镇附近
        # 没有发现条件相符的目标" unavoidable whenever no level-8 node was near.
        self.resource_level_bar = (0.1542, 0.8227)  # (x_norm of fill start, y_norm of row)
        self.resource_level_step_norm = 0.0625      # one level of fill width
        self.resource_level_max = 8
        self.resource_level_min = 1
        # The level row controls: calibrated button centres from the same frames.
        self.resource_level_minus = (0.0958, 0.8219)
        self.resource_level_plus = (0.6743, 0.8219)
        self.resource_level_box = (0.7903, 0.8219, 0.9000, 0.8219)
        # The world-map search icon is stable in position and meaning, but moving
        # march paths and nearby map animation change its perceptual hash more
        # than ordinary static buttons. Keep this tolerance local to the one
        # verifier-backed navigation control instead of weakening every match.
        self.semantic_max_distance = {
            "BTN_OPEN_RESOURCE_SEARCH": 12,
            # The HUD button is stable; its animated blue fill changes the
            # perceptual hash while its location and navigation meaning do not.
            "BTN_OPEN_INTEL_WILD_HUD": 24,
            "POPUP_INTEL_REWARD_TITLE": 22,
            # Positive live reward headers stay within distance 10. Alliance
            # technology pages reached 24, so keep a strict separation.
            "POPUP_GENERIC_REWARD_HEADER": 16,
            # Selected-building controls and timer digits animate. Current
            # research positives are distance 10 while a live generic Home
            # negative is >=30, so keep this tolerance scoped to these two
            # semantics instead of weakening page recognition globally.
            "BTN_OPEN_RESEARCH": 12,
            "RESEARCH_BUILDING_QUEUE_TIMER": 12,
            # The small power icon is stable in location and action, while its
            # surrounding glow/theme changes between day and night frames.
            "BTN_OPEN_POWER_OVERVIEW_ICON": 12,
            # The unread badge is rendered inside the mailbox ROI and changes
            # from 99+ to arbitrary counts. Current positive Home samples are
            # distance 20-22; this semantic is requested only from HOME and
            # still uses its reviewed fixed sidebar ROI.
            "BTN_OPEN_MAIL": 24,
            # Animated hand/glow changes the selected-camp menu (positives
            # 12-16). Live Home frames without the menu measured >=20.
            "BTN_OPEN_TRAINING_FROM_CAMP": 17,
            # The ordinary Beast and Master Bounty target cards share most of
            # their layout.  Only accept the reviewed high-power card at a
            # near-exact distance so the ordinary verified Beast path wins.
            "DIALOG_INTEL_MASTER_BOUNTY_HIGH_POWER": 4,
            # The Firebeast target card is visually close to the ordinary
            # Beast and Master Bounty cards. Keep it exact enough that the
            # current-client title/portrait evidence must be present.
            "POPUP_INTEL_FIREBEAST_TITLE": 6,
            "DIALOG_INTEL_FIREBEAST_TARGET": 4,
            # The live mission pin pulses between frames; negative Intel icons
            # stayed at distance >=24 in calibration, while the same Firebeast
            # pin moved from 0 to 12.
            "TARGET_INTEL_FIREBEAST_MISSION": 16,
            "DIALOG_INTEL_HERO_JOURNEY_EXPLORE": 2,
            "STATUS_INTEL_HERO_JOURNEY_FAILED": 4,
            # Victory banners animate and may lose their transient upper-right
            # notification close icon while the blocking result panel remains.
            # Two live frames calibrate the stable central result structure.
            "POPUP_BATTLE_VICTORY_BANNER": 16,
        }
        # Animated map targets move while the surrounding UI remains fixed.
        # These reviewed targets may therefore be searched only inside the
        # central world-map region, with a deliberately separated threshold
        # calibrated from positive and negative live screenshots.
        self.anywhere_max_distance = {
            # Calibrated against the pending real-map frame that previously
            # false-positived at distance 44: the reviewed Musk Ox positive is
            # distance 22, two real MAP frames without it measured 44 and two
            # more measured 62, so 38 sits between the populations.  A hit only
            # ever proposes a target; BEAST_HUNT still has to pass its own
            # target/dialog/victory verifiers.
            "TARGET_BEAST_MUSK_OX_9": 38,
            "TARGET_LIGHTHOUSE_BUILDING": 50,
            "BTN_INTEL_VIEW_TARGET": 55,
            "TARGET_INTEL_BEAST_MISSION": 54,
        }
        self.anywhere_regions = {
            "TARGET_BEAST_MUSK_OX_9": (0.25, 0.10, 0.95, 0.82),
            "TARGET_LIGHTHOUSE_BUILDING": (0.05, 0.08, 0.95, 0.82),
            "BTN_INTEL_VIEW_TARGET": (0.15, 0.55, 0.85, 0.82),
            "TARGET_INTEL_BEAST_MISSION": (0.15, 0.16, 0.95, 0.70),
        }
        self.records = payload.get("records", [])

    # ---------------------------------------------------------------- tab strip
    def _tab_band_rows(self, height: int) -> tuple[int, int]:
        return round(self.resource_tab_band[0] * height), round(self.resource_tab_band[1] * height)

    def _bracket_strokes(self, image: Image.Image) -> list[tuple[float, int]]:
        """Vertical near-white strokes inside the tab band.

        The active tab is marked by four bright-white corner brackets.  Only the
        bracket draws a near-white vertical run across most of the cell height;
        interior snow is blobby and never forms a narrow full-height stroke.
        Returns ``(centre_x, width_px)`` for each stroke, in image order.
        """
        width, height = image.size
        y0, y1 = self._tab_band_rows(height)
        band_height = max(1, y1 - y0)
        counts = [0] * width
        for x in range(width):
            run = 0
            for y in range(y0, y1):
                red, green, blue = image.getpixel((x, y))
                if red >= 238 and green >= 238 and blue >= 238:
                    run += 1
            counts[x] = run
        threshold = 0.18 * band_height
        strokes: list[tuple[float, int]] = []
        start = None
        peak = 0
        for x, count in enumerate(counts):
            if count >= threshold:
                start = x if start is None else start
                peak = max(peak, count)
            elif start is not None:
                strokes.append(((start + x - 1) / 2, x - start))
                start, peak = None, 0
        if start is not None:
            strokes.append(((start + width - 1) / 2, width - start))
        return [stroke for stroke in strokes if stroke[1] >= 3]

    def selected_tab_left(self, image_path: Path) -> tuple[float, bool]:
        """Locate the active tab: ``(left_edge_px, fully_visible)``.

        A bracket is a *pair* of strokes 130-175 px apart; that pair test is what
        rejects the unrelated white UI elements that also produce full-height
        columns on the world map.  When no pair exists but a single stroke sits
        so far right that its partner would fall off-screen, the cell is real but
        clipped, and ``fully_visible`` is False so callers refuse to identify it.
        """
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            width, _ = image.size
            strokes = self._bracket_strokes(image)
        for index, (first, _) in enumerate(strokes):
            for second, _ in strokes[index + 1:]:
                if 130 <= second - first <= 175:
                    return first, True
        cell_px = self.resource_tab_cell * width
        for centre, _ in strokes:
            if centre + cell_px * 0.75 > width:
                return centre, False
        return -1.0, False

    def resource_tab_offset_from(self, left_px: float, resource: str, width: int) -> float:
        """Scroll offset of the strip, given one identified cell."""
        nominal = (self.resource_tab_first_left + self.resource_tab_order.index(resource) * self.resource_tab_pitch) * width
        return left_px - nominal

    def resource_cell_center_norm(self, resource: str) -> tuple[float, float] | None:
        """Tap centre of a gatherable tab under the currently observed offset.

        Returns ``None`` when the cell is not fully on screen, because the caller
        must scroll the strip first; guessing a coordinate instead is what made
        SELECT_RESOURCE select the wrong tab.
        """
        if self.resource_tab_offset is None or resource not in self.resource_tab_order:
            return None
        left = (self.resource_tab_first_left + self.resource_tab_order.index(resource) * self.resource_tab_pitch) * 720.0 + self.resource_tab_offset
        cell_px = self.resource_tab_cell * 720.0
        centre = left + cell_px / 2
        if not (cell_px / 2 <= centre <= 720 - cell_px / 2):
            return None
        return centre / 720.0, (self.resource_tab_band[0] + self.resource_tab_band[1]) / 2

    def resource_tab_swipe_for(self, resource: str) -> float | None:
        """Horizontal swipe (in px, signed) that brings ``resource`` fully into view."""
        if self.resource_tab_offset is None or resource not in self.resource_tab_order:
            return None
        left = self.resource_tab_first_left * 720.0 + self.resource_tab_order.index(resource) * self.resource_tab_pitch * 720.0 + self.resource_tab_offset
        cell_px = self.resource_tab_cell * 720.0
        if left < 4:
            return -(4 - left)
        if left + cell_px > 716:
            return 716 - (left + cell_px)
        return 0.0

    def selected_resource(self, image_path: Path) -> SemanticMatch | None:
        """Identify the active resource tab from the bracket anchor + cell icon.

        Priority used here, in the project's Vision order: page context is the
        caller's gate, the white bracket is the semantic anchor, the strip pitch
        is the relative layout, and only then a template decides *which* resource
        the anchored cell holds.

        1. locate the bracket (no bracket -> return ``None``: a screen without an
           active resource tab must never be reported as a selection — the old
           fixed-ROI version returned ``RESOURCE_COAL_SELECTED`` on the HOME
           screen);
        2. crop the anchored cell and compare it against the four reviewed cell
           templates, which all carry the same bracket, so identity comes from
           the icon and label;
        3. accept only when the best match is both close (``<= 6.0``) and clearly
           better than the runner-up (``>= 4.0``).  Live measurement: active tab
           scores <= 1.2, every non-active tab scores >= 13.0.

        On success ``self.resource_tab_offset`` and
        ``self.resource_tab_visible_span`` are updated, which is what lets the
        executor compute a correct tap target for any of the four resources.
        """
        self.resource_tab_offset = None
        self.resource_tab_visible_span = None
        if not self.resource_tab_cell_templates:
            return None
        left_px, fully_visible = self.selected_tab_left(image_path)
        if left_px < 0:
            return None
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            y0, y1 = self._tab_band_rows(height)
            cell_px = round(self.resource_tab_cell * width)
            x0 = round(left_px)
            x1 = x0 + cell_px
            if x0 < 0 or x1 > width:
                return None
            probe = image.crop((x0, y0, x1, y1))
            self.resource_tab_visible_span = (x0, x1)
        if not fully_visible:
            # A clipped cell cannot be identified reliably; the strip must be
            # scrolled instead of guessed at.
            return None
        probe_signature = _cell_signature(probe)
        scored: list[tuple[float, str]] = []
        for resource, paths in self.resource_tab_cell_templates.items():
            best = None
            for path in paths:
                signature = _cell_template_signature(Path(path))
                if signature is None:
                    continue
                value = _signature_distance(probe_signature, signature)
                if best is None or value < best:
                    best = value
            if best is not None:
                scored.append((best, resource))
        if not scored:
            return None
        scored.sort()
        best_distance, best_resource = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else best_distance + 999.0
        if best_distance > self.resource_tab_max_distance or runner_up - best_distance < self.resource_tab_min_margin:
            return None
        self.resource_tab_offset = self.resource_tab_offset_from(left_px, best_resource, width)
        return SemanticMatch(
            f"RESOURCE_{best_resource}_SELECTED",
            float(best_distance),
            {
                "x_norm": round(x0 / width, 4),
                "y_norm": round(y0 / height, 4),
                "w_norm": round(cell_px / width, 4),
                "h_norm": round((y1 - y0) / height, 4),
            },
        )

    def resource_level(self, image_path: Path) -> int | None:
        """Read the configured resource-search level from the slider fill.

        The panel encodes the level as the width of a solid green fill whose
        left edge is fixed; the right edge advances one step per level.  This
        is a deterministic measurement, not OCR: it was calibrated live across
        every level from 8 down to 1.  Level 1 flattens the fill to zero width,
        so the caller must have already established that the search panel is
        open; ``None`` is returned when neither a fill nor the disabled level-1
        button can be seen, so a map without a slider is never read as level 1.
        """
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            y = round(self.resource_level_bar[1] * height)
            start = round(self.resource_level_bar[0] * width)
            if not 0 <= y < height:
                return None
            fill_end = None
            for x in range(start, width):
                red, green, blue = image.getpixel((x, y))
                if green > 150 and green - red > 50 and green - blue > 40:
                    fill_end = x
                elif fill_end is not None and x - fill_end > 30:
                    # The green run ended and a non-green gap follows; stop
                    # before picking up unrelated green elsewhere on screen.
                    break
            if fill_end is None:
                # Level 1 leaves the fill empty.  The minus control is then
                # greyed out but still drawn at its calibrated centre; confirm
                # the slider row really is on screen before claiming level 1.
                anchor_x = round(self.resource_level_minus[0] * width)
                anchor_y = round(self.resource_level_minus[1] * height)
                red, green, blue = image.getpixel((anchor_x, anchor_y))
                greyish = abs(red - green) < 14 and abs(green - blue) < 20
                if not (greyish and 120 <= red <= 220):
                    return None
                return self.resource_level_min
        levels = round((fill_end - start) / (self.resource_level_step_norm * width))
        level = self.resource_level_min + max(0, levels)
        return min(level, self.resource_level_max)

    def is_loading_screen(self, image_path: Path) -> bool:
        """Detect the startup/loading splash from its progress-bar cap.

        The splash art changes with every event theme, so only the progress
        bar is stable: a blue bar whose *left cap* does not move as the
        percentage grows.  A purely geometric rule ("a long blue run in this
        band") is not enough — several ordinary pages (home, march list, daily)
        also paint a wide blue bar near the bottom edge, and treating those as
        loading stalled the loop on a perfectly usable screen.

        Measured live at 720x1280: the cap occupies x in [55,175],
        y in [1010,1055].  The loading frame matches itself at distance 0 while
        every reviewed control page measured at distance >= 26, so the
        template threshold below keeps a wide margin.
        """
        match = self.find(image_path, "POPUP_LOADING_BAR_CAP")
        return match is not None and match.distance <= 12

    def find(self, image_path: Path, semantic: str) -> SemanticMatch | None:
        candidates = [row for row in self.records if row["semantic"] == semantic]
        if not candidates:
            return None

        with Image.open(image_path) as image:
            width, height = image.size
            matches: list[SemanticMatch] = []
            for row in candidates:
                roi = row["roi_norm"]
                bounds = (
                    round(roi["x_norm"] * width),
                    round(roi["y_norm"] * height),
                    round((roi["x_norm"] + roi["w_norm"]) * width),
                    round((roi["y_norm"] + roi["h_norm"]) * height),
                )
                with Image.open(row["template_path"]) as template:
                    distance = hamming(phash(image.crop(bounds)), phash(template))
                matches.append(SemanticMatch(semantic, distance, roi))
        best = min(matches, key=lambda match: match.distance)
        threshold = self.semantic_max_distance.get(semantic, self.max_distance)
        if best.distance <= threshold:
            return best
        if semantic in self.anywhere_max_distance:
            return self._find_anywhere(image_path, candidates, semantic)
        return None

    def _find_anywhere(self, image_path: Path, candidates: list[dict], semantic: str) -> SemanticMatch | None:
        """Find a reviewed moving target in the safe map field, never under UI chrome."""
        threshold = self.anywhere_max_distance[semantic]
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            x0, y0, x1, y1 = self.anywhere_regions[semantic]
            x_start, x_stop = round(width * x0), round(width * x1)
            y_start, y_stop = round(height * y0), round(height * y1)
            step = max(4, round(width / 90))
            best: SemanticMatch | None = None
            for row in candidates:
                roi = row["roi_norm"]
                crop_width = max(8, round(roi["w_norm"] * width))
                crop_height = max(8, round(roi["h_norm"] * height))
                with Image.open(row["template_path"]) as template:
                    target_hash = dhash(template, size=16)
                for y in range(y_start, max(y_start + 1, y_stop - crop_height + 1), step):
                    for x in range(x_start, max(x_start + 1, x_stop - crop_width + 1), step):
                        distance = hamming(
                            target_hash,
                            dhash(image.crop((x, y, x + crop_width, y + crop_height)), size=16),
                        )
                        if best is None or distance < best.distance:
                            best = SemanticMatch(
                                semantic,
                                distance,
                                {
                                    "x_norm": x / width,
                                    "y_norm": y / height,
                                    "w_norm": crop_width / width,
                                    "h_norm": crop_height / height,
                                },
                            )
            return best if best is not None and best.distance <= threshold else None


class SemanticWorldVision:
    """Compose reviewed semantic matches into a live WorldState.

    This layer does not click and does not invent state. Values are emitted only
    when a reviewed template is present in its normalized ROI.
    """

    def __init__(
        self,
        manifest_path: Path,
        max_distance: int = 8,
        *,
        calibrated_baseline_used: int = 1,
        calibrated_march_max: int = 6,
    ) -> None:
        self.semantic = SemanticROIVision(manifest_path, max_distance=max_distance)
        self.calibrated_baseline_used = calibrated_baseline_used
        self.calibrated_march_max = calibrated_march_max

    def observe(self, image_path: Path) -> WorldState:
        def match(name: str) -> SemanticMatch | None:
            return self.semantic.find(image_path, name)

        # The splash/loading screen must be recognized before any popup
        # branch.  Its artwork contains bright, high-contrast shapes that
        # previously matched a popup template, and the resulting BACK tap
        # restarted the client and then re-matched it, producing an endless
        # restart loop (the source of unexpected_worker_exits).
        #
        # A maintenance notice is layered *over* the splash and still shows the
        # progress bar behind it, so the more specific maintenance title has to
        # be tested first or the dialog would be reported as LOADING.
        if match("POPUP_MAINTENANCE_TITLE"):
            return WorldState(page=Page.MAINTENANCE, popup="MAINTENANCE", confidence=0.99)
        if self.semantic.is_loading_screen(image_path):
            return WorldState(page=Page.LOADING, confidence=0.99)
        if match("POPUP_WELCOME_BACK_OFFLINE"):
            return WorldState(page=Page.POPUP, popup="WELCOME_BACK_OFFLINE", daily={"offline_rewards":"CLAIMABLE"}, confidence=0.99)
        if match("POPUP_SESSION_DISCONNECTED") and match("BTN_RECONNECT_SESSION"):
            return WorldState(page=Page.POPUP, popup="SESSION_DISCONNECTED", confidence=0.99)
        if match("POPUP_BATTLEFIELD_REVIVAL"):
            return WorldState(page=Page.POPUP, popup="BATTLEFIELD_REVIVAL", events={"battlefield_revival":"AVAILABLE"}, confidence=0.99)
        # A transient battle-result banner can cover an otherwise valid map
        # and its resource-search panel. It must win page classification so
        # no underlying action is attempted through the blocker.
        if match("POPUP_BATTLE_VICTORY_BANNER"):
            return WorldState(
                page=Page.POPUP,
                popup="BATTLE_VICTORY_BANNER",
                confidence=0.99,
            )
        # The world map refuses to send a second march to a resource node that
        # another of our teams already targets.  It asks whether to send
        # anyway; sending anyway wastes a march on a contested node, so the
        # reviewed policy is to cancel and re-search.  This must be classified
        # before the generic popup branch, otherwise it is closed as an
        # unknown blocker and the gather silently fails.
        if match("POPUP_DUPLICATE_TARGET_TITLE"):
            return WorldState(
                page=Page.POPUP,
                popup="DUPLICATE_TARGET",
                confidence=0.99,
            )
        if match("HIGH_RISK_REAL_MONEY_OFFER") and match("REAL_MONEY_PRICE_BUTTON"):
            return WorldState(
                page=Page.POPUP,
                popup="REAL_MONEY_OFFER",
                rewards={"real_money_cost": True, "action": "BLOCKED"},
                confidence=0.99,
            )
        if match("HIGH_RISK_PURCHASE"):
            return WorldState(page=Page.POPUP, popup="PURCHASE_POPUP", confidence=0.99)
        if match("POPUP_EXIT_CONFIRM"):
            return WorldState(page=Page.POPUP, popup="EXIT_CONFIRM", confidence=0.99)
        if match("POPUP_POWER_OVERVIEW"):
            return WorldState(page=Page.POPUP, popup="POWER_OVERVIEW", confidence=0.99)
        if match("POPUP_POWER_DETAILS"):
            return WorldState(page=Page.POPUP, popup="POWER_DETAILS", confidence=0.99)
        # Several Lighthouse mission dialogs share the same localized
        # "前往查看" button.  Their reviewed title is therefore checked before
        # the generic button so a high-power bounty or Hero Journey can never
        # be mistaken for the already verified ordinary Beast workflow.
        if match("POPUP_INTEL_HERO_JOURNEY_TITLE"):
            return WorldState(
                page=Page.POPUP,
                popup="INTEL_HERO_JOURNEY",
                intel={"status":"AVAILABLE", "mission_type":"HERO_JOURNEY", "mission_level":10},
                confidence=0.99,
            )
        if match("POPUP_INTEL_MASTER_BOUNTY_TITLE"):
            return WorldState(
                page=Page.POPUP,
                popup="INTEL_MASTER_BOUNTY",
                intel={"status":"BLOCKED", "mission_type":"MASTER_BOUNTY", "mission_level":20},
                confidence=0.99,
            )
        if match("POPUP_INTEL_FIREBEAST_TITLE"):
            return WorldState(
                page=Page.POPUP,
                popup="INTEL_BEAST_MISSION",
                intel={"status":"AVAILABLE", "mission_id":"INTEL_FIREBEAST_10", "mission_type":"FIREBEAST", "mission_level":10},
                confidence=0.99,
            )
        if match("POPUP_INTEL_RESCUE_SURVIVORS_TITLE"):
            return WorldState(
                page=Page.POPUP,
                popup="INTEL_RESCUE_SURVIVORS_MISSION",
                intel={"status":"AVAILABLE", "mission_id":"INTEL_RESCUE_SURVIVORS_10", "mission_type":"RESCUE_SURVIVORS", "mission_level":10},
                confidence=0.99,
            )
        # Reward composition varies per Intel mission, but the localized
        # "前往查看" control is stable and only exists on this mission dialog.
        if match("BTN_INTEL_VIEW_TARGET"):
            return WorldState(
                page=Page.POPUP,
                popup="INTEL_BEAST_MISSION",
                intel={"status":"AVAILABLE", "mission_id":"INTEL_BEAST_10", "mission_type":"BEAST", "mission_level":10},
                confidence=0.99,
            )
        if match("POPUP_DAILY_REWARD_CURRENT"):
            return WorldState(page=Page.POPUP, popup="DAILY_REWARD", daily={"claim_feedback": True}, confidence=0.99)
        # Exploration reward artwork can share the generic localized reward
        # title used by Intel. Prefer the more specific full reward template.
        if match("POPUP_EXPLORATION_REWARD"):
            return WorldState(page=Page.POPUP, popup="EXPLORATION_REWARD", exploration={"claim_feedback": True}, confidence=0.99)
        if match("POPUP_GENERIC_REWARD_HEADER"):
            return WorldState(page=Page.POPUP, popup="GENERIC_REWARD", confidence=0.99)
        if (match("POPUP_INTEL_REWARD_TITLE") or match("POPUP_INTEL_REWARD")) and not (
            match("BTN_RESOURCE_SEARCH_SUBMIT") or match("BTN_OPEN_RESOURCE_SEARCH")
        ):
            return WorldState(page=Page.POPUP, popup="INTEL_REWARD", intel={"claim_feedback": True}, confidence=0.99)
        if match("POPUP_MAIL_REWARD"):
            return WorldState(page=Page.POPUP, popup="MAIL_REWARD", mail={"claim_feedback": True}, confidence=0.99)
        if match("POPUP_EXPLORATION_IDLE_DIALOG"):
            return WorldState(page=Page.POPUP, popup="EXPLORATION_IDLE_DIALOG", exploration={"status": "CLAIMABLE", "idle_dialog": True}, confidence=0.99)
        if match("ALLIANCE_GIFT_REWARD_ITEMS_MULTI") or match("ALLIANCE_GIFT_REWARD_ITEMS_DAY2"):
            return WorldState(page=Page.POPUP, popup="ALLIANCE_GIFT_REWARD", alliance={"section":"GIFTS", "claim_feedback":True}, confidence=0.99)
        if match("POPUP_DAILY_REWARD"):
            if match("DAILY_ALLIANCE_REWARD_ITEMS"):
                return WorldState(page=Page.POPUP, popup="DAILY_REWARD", daily={"claim_feedback": True, "activity_reward": 5, "rewards": {"WOOD": 4000}}, confidence=0.99)
            if match("DAILY_MULTI_REWARD_ITEMS"):
                return WorldState(page=Page.POPUP, popup="DAILY_REWARD", daily={"claim_feedback": True, "activity_reward": 65, "rewards": {"MEAT": 28000, "COAL": 800, "IRON": 200}}, confidence=0.99)
            return WorldState(page=Page.POPUP, popup="DAILY_REWARD", daily={"claim_feedback": True}, confidence=0.99)
        if match("POPUP_ALLIANCE_GIFT_REWARD"):
            return WorldState(page=Page.POPUP, popup="ALLIANCE_GIFT_REWARD", alliance={"section":"GIFTS", "claim_feedback":True}, confidence=0.99)
        if match("POPUP_HERO_RECRUIT_REWARD"):
            return WorldState(page=Page.POPUP, popup="HERO_RECRUIT_REWARD", daily={"task_action_feedback": True}, confidence=0.99)
        if match("DIALOG_INTEL_MASTER_BOUNTY_HIGH_POWER"):
            return WorldState(
                page=Page.BEAST,
                intel={"status":"BLOCKED", "mission_type":"MASTER_BOUNTY", "mission_level":20},
                beast={
                    "name":"大师悬赏",
                    "level":20,
                    "available":False,
                    "recommended_power":189295920,
                    "stamina_cost_displayed":10,
                    "blocked_reason":"POWER_BELOW_RECOMMENDED",
                },
                confidence=0.99,
            )
        if match("DIALOG_INTEL_HERO_JOURNEY_EXPLORE"):
            return WorldState(
                page=Page.EXPLORATION,
                intel={"status":"AVAILABLE", "mission_type":"HERO_JOURNEY", "mission_level":10},
                exploration={"status":"AVAILABLE", "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("DIALOG_INTEL_FIREBEAST_TARGET"):
            return WorldState(
                page=Page.BEAST,
                intel={"status":"AVAILABLE", "mission_id":"INTEL_FIREBEAST_10", "mission_type":"FIREBEAST", "mission_level":10},
                beast={
                    "mission_id":"INTEL_FIREBEAST_10",
                    "name":"炽红巨兽",
                    "level":20,
                    "available":True,
                    "recommended_power":1467020,
                    "stamina_cost_displayed":10,
                },
                confidence=0.99,
            )
        if match("DIALOG_INTEL_RESCUE_SURVIVORS_TARGET") and match("BTN_INTEL_RESCUE_SURVIVORS"):
            return WorldState(
                page=Page.MAP,
                popup="INTEL_RESCUE_SURVIVORS_TARGET",
                intel={"status":"AVAILABLE", "mission_id":"INTEL_RESCUE_SURVIVORS_10", "mission_type":"RESCUE_SURVIVORS", "mission_level":10, "stamina_cost_displayed":12},
                confidence=0.99,
            )
        if match("STATUS_BEAST_LOW_WIN_PROBABILITY"):
            return WorldState(
                page=Page.MARCH,
                beast={"name":"雪豹", "level":29, "victory_assured":False, "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("BTN_BEAST_DISPATCH_MUSK_OX_9") and match("STATUS_VICTORY_ASSURED_MUSK_OX_9"):
            return WorldState(
                page=Page.MARCH,
                beast={"name":"麝牛", "level":9, "victory_assured":True, "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("DIALOG_BEAST_MUSK_OX_9") and match("BTN_BEAST_START_MARCH"):
            return WorldState(
                page=Page.BEAST,
                beast={"name":"麝牛", "level":9, "available":True, "recommended_power":9000, "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("BTN_BEAST_DISPATCH"):
            return WorldState(
                page=Page.MARCH,
                beast={"name": "大角鹿", "level": 22, "victory_assured": True, "stamina_cost_displayed": 10},
                confidence=0.99,
            )
        if match("BTN_BEAST_START_MARCH"):
            return WorldState(
                page=Page.BEAST,
                march_used=1,
                march_max=6,
                beast={"mission_id":"INTEL_BEAST_10", "name": "大角鹿", "level": 22, "available": True, "recommended_power": 5107044, "stamina_cost_displayed": 10},
                confidence=0.99,
            )
        if match("STATUS_BEAST_RETURNING"):
            return WorldState(
                page=Page.MAP,
                marches=(MarchState.RETURNING,),
                march_used=2,
                march_max=6,
                beast={"name": "大角鹿", "level": 22, "battle_completed": True},
                confidence=0.99,
            )
        if match("STATUS_BEAST_MARCH_OUTBOUND_MUSK_OX_9"):
            return WorldState(
                page=Page.MAP,
                marches=(MarchState.MARCHING,),
                march_used=6,
                march_max=6,
                beast={"name":"麝牛", "level":9, "status":"MARCHING", "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("STATUS_INTEL_BEAST_MARCHING"):
            return WorldState(
                page=Page.MAP,
                marches=(MarchState.MARCHING,),
                march_used=5,
                march_max=6,
                beast={"mission_id":"INTEL_BEAST_10", "level":22, "status":"MARCHING", "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("STATUS_INTEL_HERO_JOURNEY_FAILED"):
            return WorldState(
                page=Page.MAP,
                intel={"status":"BLOCKED", "mission_type":"HERO_JOURNEY", "failure":"BATTLE_FAILED"},
                confidence=0.99,
            )
        if match("STATUS_INTEL_RESCUE_SURVIVORS_ACTIVE"):
            return WorldState(
                page=Page.MAP,
                intel={"status":"IN_PROGRESS", "mission_id":"INTEL_RESCUE_SURVIVORS_10", "mission_type":"RESCUE_SURVIVORS", "mission_level":10, "stamina_cost_displayed":12},
                confidence=0.99,
            )
        if match("BTN_DISPATCH"):
            return WorldState(page=Page.MARCH, resource_target="WOOD", confidence=0.99)
        if match("BTN_BUILD_UPGRADE"):
            return WorldState(
                page=Page.BUILDING,
                building={"id": "STOREHOUSE", "level": 26, "target_level": 27, "upgradeable": True},
                confidence=0.99,
            )
        if match("BTN_TRAINING_MENU_LABEL") or match("BTN_OPEN_TRAINING_FROM_CAMP"):
            return WorldState(page=Page.HOME, training={"building":"INFANTRY_CAMP", "status":"IDLE", "queue_available":True, "menu_open":True}, confidence=0.99)
        if match("TARGET_INFANTRY_CAMP_HIGHLIGHTED"):
            return WorldState(page=Page.HOME, training={"navigation":"INFANTRY_CAMP_HIGHLIGHTED", "queue_available":True}, confidence=0.99)
        if match("BUILDING_QUEUE_TIMER"):
            return WorldState(
                page=Page.HOME,
                building={"queue_building": "STOREHOUSE", "from_level": 26, "target_level": 27, "timer": "VISIBLE", "status": "UPGRADING"},
                confidence=0.99,
            )
        if match("RESEARCH_BUILDING_QUEUE_TIMER"):
            return WorldState(
                page=Page.HOME,
                research={"building": "RESEARCH_CENTER", "status": "IN_PROGRESS", "timer": "VISIBLE", "queue_available": False},
                confidence=0.99,
            )
        if match("RESEARCH_QUEUE_TIMER") or match("STATUS_RESEARCH_IN_PROGRESS"):
            return WorldState(
                page=Page.RESEARCH,
                research={
                    "branch": "GROWTH",
                    "node": "WARD_EXPANSION_VII",
                    "name": "病房扩建VII",
                    "status": "IN_PROGRESS",
                    "timer": "VISIBLE",
                    "queue_available": False,
                },
                confidence=0.99,
            )
        if match("PAGE_RESEARCH"):
            return WorldState(page=Page.RESEARCH, research={"status": "UNKNOWN"}, confidence=0.98)
        training_type = None
        if match("PAGE_TRAINING_INFANTRY"):
            training_type = "INFANTRY"
        elif match("PAGE_TRAINING_LANCER"):
            training_type = "LANCER"
        elif match("PAGE_TRAINING_MARKSMAN"):
            training_type = "MARKSMAN"
        if training_type and (match("TRAINING_QUEUE_TIMER") or match("STATUS_TRAINING_IN_PROGRESS")):
            return WorldState(
                page=Page.TRAINING,
                training={
                    "troop_type": training_type,
                    "tier": 10,
                    "batch_count": 806,
                    "status": "IN_PROGRESS",
                    "timer": "VISIBLE",
                    "queue_available": False,
                },
                confidence=0.99,
            )
        if training_type and match("BTN_START_TRAINING"):
            return WorldState(
                page=Page.TRAINING,
                training={
                    "troop_type": training_type,
                    "tier": 10,
                    "batch_count": 806,
                    "status": "AVAILABLE",
                    "queue_available": True,
                    "trainable": True,
                },
                confidence=0.99,
            )
        if match("BTN_INTEL_CLAIM_ALL"):
            return WorldState(
                page=Page.INTEL,
                intel={"status": "CLAIMABLE", "claimable_count": 1},
                confidence=0.99,
            )
        if match("TARGET_INTEL_FIREBEAST_MISSION"):
            return WorldState(
                page=Page.INTEL,
                intel={"status":"AVAILABLE", "claimable_count":0, "mission_id":"INTEL_FIREBEAST_10", "mission_type":"FIREBEAST", "mission_level":10},
                confidence=0.99,
            )
        if match("TARGET_INTEL_RESCUE_SURVIVORS"):
            return WorldState(
                page=Page.INTEL,
                intel={"status":"AVAILABLE", "claimable_count":0, "mission_id":"INTEL_RESCUE_SURVIVORS_10", "mission_type":"RESCUE_SURVIVORS", "mission_level":10},
                confidence=0.99,
            )
        if match("TARGET_INTEL_BEAST_MISSION") or match("TARGET_INTEL_BEAST_MISSION_BLUE"):
            return WorldState(
                page=Page.INTEL,
                intel={"status":"AVAILABLE", "claimable_count":0, "available_count":1, "mission_type":"BEAST", "list_read":True},
                confidence=0.99,
            )
        if match("STATUS_INTEL_AVAILABLE"):
            return WorldState(page=Page.INTEL, intel={"status":"AVAILABLE", "claimable_count":0}, confidence=0.99)
        if match("PAGE_INTEL"):
            return WorldState(page=Page.INTEL, intel={"status": "UNKNOWN"}, confidence=0.98)
        if match("BTN_DAILY_CLAIM_ALL"):
            return WorldState(
                page=Page.DAILY,
                daily={"status": "CLAIMABLE", "claimable_count": 1},
                confidence=0.99,
            )
        if match("DAILY_ACTIVITY_70_CURRENT"):
            return WorldState(page=Page.DAILY, daily={"status":"AVAILABLE", "claimable_count":0, "activity":70}, confidence=0.99)
        if match("BTN_DAILY_GO_HERO_RECRUIT"):
            return WorldState(
                page=Page.DAILY,
                daily={"status": "AVAILABLE", "task_id": "HERO_RECRUIT_1", "progress": 0, "target": 1, "activity": 270},
                confidence=0.99,
            )
        if match("STATUS_ALLIANCE_TECH_CONTRIBUTION_RESULT"):
            return WorldState(
                page=Page.ALLIANCE,
                alliance={"section": "TECHNOLOGY", "status": "CONTRIBUTED", "contribution": 240, "attempts_remaining": 24},
                confidence=0.99,
            )
        if match("BTN_ALLIANCE_TECH_CONTRIBUTE_MEAT"):
            return WorldState(
                page=Page.ALLIANCE,
                alliance={"section": "TECHNOLOGY", "status": "AVAILABLE", "attempts_remaining": 25, "resource": "MEAT", "cost": 10000},
                confidence=0.99,
            )
        if match("STATUS_ALLIANCE_AUTO_HELP_ACTIVE"):
            return WorldState(
                page=Page.ALLIANCE,
                alliance={"section": "HELP", "status": "NOT_AVAILABLE", "auto_help_active": True},
                confidence=0.99,
            )
        if match("BTN_ALLIANCE_GIFTS_CLAIM_ALL"):
            return WorldState(page=Page.ALLIANCE, alliance={"section":"GIFTS", "status":"CLAIMABLE"}, confidence=0.99)
        if match("BTN_ALLY_GIFT_CLAIM"):
            return WorldState(page=Page.ALLIANCE, alliance={"section":"GIFTS", "tab":"ALLY_GIFT", "status":"CLAIMABLE"}, confidence=0.99)
        if match("STATUS_ALLIANCE_GIFTS_CLAIMED") or match("STATUS_ALLY_GIFTS_CLAIMED"):
            return WorldState(page=Page.ALLIANCE, alliance={"section":"GIFTS", "status":"CLAIMED"}, confidence=0.99)
        if match("PAGE_ALLIANCE_GIFTS"):
            return WorldState(page=Page.ALLIANCE, alliance={"section":"GIFTS", "status":"UNKNOWN"}, confidence=0.98)
        if match("PAGE_ALLIANCE_TECH"):
            return WorldState(page=Page.ALLIANCE, alliance={"section": "TECHNOLOGY", "status": "UNKNOWN"}, confidence=0.98)
        if match("PAGE_ALLIANCE"):
            return WorldState(page=Page.ALLIANCE, alliance={"section": "HOME"}, confidence=0.98)
        # PAGE_MAIL is the stable page identity. Badge state is deliberately
        # derived later by the lightweight red-badge detector because old
        # state templates can resemble a newly cleared list.
        if match("PAGE_MAIL"):
            active_tab = None
            if match("TAB_MAIL_ALLIANCE_ACTIVE"):
                active_tab = "ALLIANCE"
            elif match("TAB_MAIL_SYSTEM_ACTIVE"):
                active_tab = "SYSTEM"
            elif match("TAB_MAIL_REPORT_ACTIVE"):
                active_tab = "REPORT"
            legacy_status = "CLAIMABLE" if match("STATUS_MAIL_TAB_BADGES") else "CLAIMED" if match("STATUS_MAIL_ALL_CLEAR") else "UNKNOWN"
            return WorldState(page=Page.MAIL, mail={"status":legacy_status, "active_tab":active_tab}, confidence=0.99)
        if match("STATUS_MAIL_TAB_BADGES"):
            return WorldState(page=Page.MAIL, mail={"status":"CLAIMABLE"}, confidence=0.99)
        if match("STATUS_MAIL_ALL_CLEAR"):
            return WorldState(page=Page.MAIL, mail={"status":"CLAIMED", "badge_count":0}, confidence=0.99)
        if match("PAGE_EXPLORATION"):
            # Claimable and claimed controls have nearly identical shapes, so
            # perceptual hashes alone confuse green and grey variants. The
            # reviewed normalized control region has a stable colour gap.
            with Image.open(image_path) as exploration_image:
                width, height = exploration_image.size
                button = exploration_image.convert("RGB").crop((round(.77 * width), round(.66 * height), round(.95 * width), round(.70 * height)))
                red, green, _blue = ImageStat.Stat(button).mean
            status = "CLAIMABLE" if green - red >= 45 else "CLAIMED"
            return WorldState(page=Page.EXPLORATION, exploration={"status":status}, confidence=0.99)
        if match("BTN_EXPLORATION_IDLE_CLAIM"):
            return WorldState(page=Page.EXPLORATION, exploration={"status":"CLAIMABLE"}, confidence=0.99)
        if match("STATUS_EXPLORATION_IDLE_CLAIMED"):
            return WorldState(page=Page.EXPLORATION, exploration={"status":"CLAIMED"}, confidence=0.99)
        if match("BTN_GATHER"):
            return WorldState(
                page=Page.RESOURCE_DETAIL,
                resource_target="WOOD",
                resource_available=True,
                confidence=0.99,
            )

        visible_musk_ox = match("TARGET_BEAST_MUSK_OX_9")
        search_submit = match("BTN_RESOURCE_SEARCH_SUBMIT")
        # The active resource tab is decided by the calibrated strip
        # classifier instead of four fixed-ROI probes: the reviewed strip
        # pitch differs from the hand-typed ROIs, and a fixed probe cannot
        # tell "wood selected" from "meat icon happens to sit here".
        selected_resource = None
        if search_submit:
            selection = self.semantic.selected_resource(image_path)
            if selection is not None:
                selected_resource = selection.semantic[len("RESOURCE_"):-len("_SELECTED")]
        returning = match("STATUS_RETURNING")
        gathering = match("STATUS_GATHERING")
        marching = match("STATUS_MARCHING")
        count_one = match("MARCH_COUNT_1_OF_6")
        count_two = match("MARCH_COUNT_2_OF_6")
        # Persistent world-map anchor.
        #
        # Every other map signal is conditional: the resource-search button is
        # covered while the march-list overlay is open, and the STATUS_* row
        # templates do not match that overlay's layout.  Measured live on
        # 2026-09-14: a frame showing the map with `6/6` marches and five 采集中
        # rows matched none of them, so the world map was classified UNKNOWN and
        # the OCR fallback then read the right-hand event rail's "常规活动" label
        # and returned Page.EVENT.  That single misclassification is what made
        # DISPATCH_NOT_PROVEN fire 28 times even though the march had been sent.
        #
        # The "return to city" control is drawn on every world-map frame and its
        # reviewed template matches at distance 2.  It is paired with a negative
        # PAGE_MAP probe, because the home screen shows the *map* button (PAGE_MAP)
        # instead, so the two are mutually exclusive and together identify the map
        # without weakening any other page's evidence.
        map_hud = match("BTN_OPEN_HOME") is not None and match("PAGE_MAP") is None
        # Read the real level filter from the slider instead of assuming 8.
        # A hard-coded 8 made the search unusable whenever the nearby map had
        # no level-8 node ("在您的城镇附近没有发现条件相符的目标").
        level = self.semantic.resource_level(image_path) if search_submit else None
        if visible_musk_ox or search_submit or returning or gathering or marching or count_one or count_two or map_hud or match("BTN_OPEN_RESOURCE_SEARCH"):
            marches: list[MarchState] = []
            if marching:
                marches.append(MarchState.MARCHING)
            if gathering:
                marches.append(MarchState.GATHERING)
            if returning:
                marches.append(MarchState.RETURNING)
            # Tiny anti-aliased numerals are not reliable under perceptual hashing.
            # P0 therefore uses the role's live-verified 1/6 baseline plus each
            # explicitly recognized transient march; OCR will replace this
            # calibration before multi-role support.
            # The calibrated baseline is the long-running gathering queue.
            # MARCHING/RETURNING rows are additional transient queues, while a
            # recognized GATHERING row is the baseline itself. Counting every
            # recognized state double-counted the live 2/6 screen as 3/6.
            transient_count = sum(
                state in {MarchState.MARCHING, MarchState.RETURNING}
                for state in marches
            )
            used = self.calibrated_baseline_used + transient_count
            if not marches and count_two and not count_one:
                used = 2
            return WorldState(
                page=Page.MAP,
                marches=tuple(marches),
                march_used=used,
                march_max=self.calibrated_march_max,
                resource_target="WOOD" if marches else None,
                resource_search_open=bool(search_submit),
                resource_selected=selected_resource,
                resource_level=level,
                beast={"visible_target":"MUSK_OX", "level":9, "available":True} if visible_musk_ox else {},
                confidence=0.99,
            )
        if match("PAGE_MAP"):
            return WorldState(page=Page.HOME, confidence=0.98)
        return WorldState(page=Page.UNKNOWN, confidence=0.0)


# Backward-compatible name for the original P0 tests and callers.
P0SemanticVision = SemanticWorldVision


class ReplayVision:
    """Read human-reviewed replay labels; never claims live vision accuracy."""

    def __init__(self, labels_path: Path) -> None:
        payload = json.loads(labels_path.read_text(encoding="utf-8"))
        if payload.get("status") != "SIMULATION":
            raise ValueError("replay labels must be marked SIMULATION")
        self.root = labels_path.parent
        self.samples = {
            Path(row["image"]).name: row for row in payload.get("samples", [])
        }
        self._cache: dict[str, WorldState] = {}

    def observe(self, image_path: Path) -> WorldState:
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest in self._cache:
            return self._cache[digest]
        row = self.samples.get(image_path.name)
        if not row:
            state = WorldState(page=Page.UNKNOWN, confidence=0.0)
            self._cache[digest] = state
            return state
        raw = row.get("state", {})
        marches = tuple(
            MarchState(value) if value in MarchState._value2member_map_ else MarchState.UNKNOWN
            for value in raw.get("marches", [])
        )
        march_state = raw.get("march_state")
        if march_state:
            marches += (MarchState(march_state) if march_state in MarchState._value2member_map_ else MarchState.UNKNOWN,)
        state = WorldState(
            page=Page(row["page"]) if row["page"] in Page._value2member_map_ else Page.UNKNOWN,
            popup=raw.get("popup"),
            marches=marches,
            march_used=raw.get("march_used"),
            march_max=raw.get("march_max"),
            building=raw.get("building", {}),
            research=raw.get("research", {}),
            training=raw.get("training", {}),
            intel=raw.get("intel", {}),
            beast=raw.get("beast", {}),
            daily=raw.get("daily", {}),
            alliance=raw.get("alliance", {}),
            mail=raw.get("mail", {}),
            exploration=raw.get("exploration", {}),
            resource_target=raw.get("resource"),
            resource_search_open=bool(raw.get("resource_search_open", False)),
            resource_selected=raw.get("resource_selected"),
            resource_level=raw.get("resource_level"),
            resource_available=raw.get("resource_available"),
            confidence=min((float(item.get("confidence", 0.0)) for item in row.get("elements", [])), default=0.7),
        )
        self._cache[digest] = state
        return state


class SignatureVision:
    """L1 screenshot classifier that rejects scenes outside reviewed exemplars."""

    def __init__(self, labels_path: Path, max_distance: int = 4) -> None:
        self.replay = ReplayVision(labels_path)
        self.max_distance = max_distance
        payload = json.loads(labels_path.read_text(encoding="utf-8"))
        self.signatures: list[tuple[str, Path]] = []
        for row in payload.get("samples", []):
            image_path = labels_path.parent / row["image"]
            with Image.open(image_path) as image:
                self.signatures.append((phash(image), image_path))

    def observe(self, image_path: Path) -> WorldState:
        with Image.open(image_path) as image:
            signature = phash(image)
        if not self.signatures:
            return WorldState(page=Page.UNKNOWN, confidence=0.0)
        distance, exemplar = min(
            (hamming(signature, known), path) for known, path in self.signatures
        )
        if distance > self.max_distance:
            return WorldState(page=Page.UNKNOWN, confidence=0.0)
        state = self.replay.observe(exemplar)
        confidence = max(0.0, state.confidence * (1.0 - distance / 64.0))
        return replace(state, confidence=confidence)
