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
        # Cell templates are the *whole* cell (bracket included) as captured when
        # that resource was selected, so a template always carries a bracket.  The
        # probe is a PREDICTED position, which is only the selected cell when the
        # anchor happens to be that tab -- so the distances here are not the
        # "active <= 1.2 / non-active >= 13.0" pair the older comment claimed; that
        # pair described comparing a probe crop taken FROM the bracket.  Measured
        # again on 2026-09-16 over 10 frames with verified anchors (27 correct and
        # 37 wrong observations):
        #
        #     correct  (predicted position vs its own template)  0.00 .. 6.49
        #     wrong    (same cell, another template)            10.65 .. 16.17
        #     wrong    (non-gatherable tab vs any template)     14.74 .. 25.09
        #
        # The ceiling has to sit inside 6.49 < gate < 10.65.  It was 6.0, i.e.
        # BELOW the largest value its own calibration frames produce -- the two
        # frames that measure 6.45 and 6.49 were rejected by it.  That is the
        # defect behind the live SELECT_RESOURCE failures: on the 2026-09-15T23:37
        # frames the geometry is right (bracket on tab index 1 at x=172, which
        # predicts 生肉 at x=486, and 生肉 is visibly there) and the only reason
        # nothing was accepted is that the crop scored 6.49 against a limit of 6.0.
        # 8.0 keeps 1.51 of headroom above the worst correct observation and 2.65
        # below the best wrong one, and stays clear of the identity margin gate,
        # which is unchanged at 4.0 and was never the binding constraint (the
        # live frames' correct reading has a margin of 8.00).
        self.resource_tab_max_distance = 8.0
        self.resource_tab_min_margin = 4.0
        # Cell templates are the *whole* cell (bracket included) as captured when
        # that resource was selected, so a template always carries a bracket.
        self.resource_tab_cell_templates: dict[str, list[str]] = {}
        for row in payload.get("records", []):
            semantic = str(row.get("semantic", ""))
            if semantic.startswith("RESOURCE_TAB_") and semantic.endswith("_SELECTED"):
                resource = semantic[len("RESOURCE_TAB_"):-len("_SELECTED")]
                if resource in self.resource_tab_order:
                    self.resource_tab_cell_templates.setdefault(resource, []).append(str(row["template_path"]))
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
        # March list: measured live on the 2026-09-14 map (720x1280) with
        # ``tools/probe_march_recall_ui.py``, which printed both the row tokens
        # and the dialog the tap produced.  Rows start under the HUD and repeat
        # at a fixed pitch; row 1's tappable centre opens the 召回 confirmation.
        # Only row 1 is targeted: it is the oldest march and therefore the
        # cheapest one to release.
        self.march_row_1_center = (0.28, 0.2234)
        self.march_row_pitch = 0.0474
        # The 领主体力 gauge is drawn on every world-map frame under the avatar.
        # Measured live on 2026-09-14 (720x1280): the number sits at px
        # 30-68 x 101-119, i.e. centre (49,110).  Tapping it opens the
        # 获取更多 stamina-source panel -- verified live, one tap, no other
        # control touched.
        self.stamina_gauge_center = (49.0 / 720.0, 110.0 / 1280.0)
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

    def candidate_tab_lefts(self, image_path: Path) -> list[float]:
        """``candidate_tab_lefts_from`` for a path on disk."""
        with Image.open(image_path) as opened:
            return self.candidate_tab_lefts_from(opened.convert("RGB"))

    def _supported_offsets(self, image: Image.Image, width: int, height: int) -> list[tuple[int, float, float, str]]:
        """Score every ``(anchor, anchored tab)`` pair by reviewed-template support.

        An offset is a prediction about where all seven tabs sit.  The four
        reviewed templates therefore *judge* it independently of the frame being
        explained: for the true pair the predicted MEAT/WOOD/COAL/IRON cells
        match their own template and no other's, and for a wrong pair they land on
        neighbouring tabs and match nothing.

        Returns ``(support, margin, left_px, anchored_tab)``, best first.
        """
        y0, y1 = self._tab_band_rows(height)
        cell_px = round(self.resource_tab_cell * width)
        signatures = {
            resource: [s for s in (_cell_template_signature(Path(p)) for p in paths) if s is not None]
            for resource, paths in self.resource_tab_cell_templates.items()
        }
        results: list[tuple[int, float, float, str]] = []
        for left_px in self.candidate_tab_lefts_from(image):
            for anchored in self.resource_tab_order:
                offset = self.resource_tab_offset_from(left_px, anchored, width)
                support = 0
                best_margin = -999.0
                for resource, own_signatures in signatures.items():
                    if not own_signatures:
                        continue
                    predicted_left = (
                        self.resource_tab_first_left
                        + self.resource_tab_order.index(resource) * self.resource_tab_pitch
                    ) * width + offset
                    x0 = round(predicted_left)
                    if x0 < 0 or x0 + cell_px > width:
                        continue
                    probe_signature = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
                    own = min(_signature_distance(probe_signature, s) for s in own_signatures)
                    others = [
                        _signature_distance(probe_signature, s)
                        for other, other_signatures in signatures.items()
                        if other != resource
                        for s in other_signatures
                    ]
                    runner_up = min(others) if others else own + 999.0
                    if own <= self.resource_tab_max_distance and runner_up - own >= self.resource_tab_min_margin:
                        support += 1
                        best_margin = max(best_margin, runner_up - own)
                if support:
                    results.append((support, best_margin, left_px, anchored))
        results.sort(key=lambda item: (-item[0], -item[1]))
        return results

    def candidate_tab_lefts_from(self, image: Image.Image) -> list[float]:
        """Every stroke-pair left edge that could be the active tab.

        ``selected_tab_left`` returns the FIRST accepted pair, which is correct
        only while the bracket is the only thing producing one.  Measured
        2026-09-16 on the production frame that failed SELECT_RESOURCE: nine
        strokes yielded four accepted pairs, and the first (x=2.0) was spurious
        while the real bracket sat on the third visible cell (x=282.5).  Taking
        the first one put the offset 280 px out -- harmless there only because the
        anchored cell happened not to match a template; had it matched, the
        executor would have been handed a wrong tap target.

        This reports what is geometrically possible and nothing more; the caller
        resolves the ambiguity with the reviewed templates.
        """
        strokes = self._bracket_strokes(image)
        lefts: list[float] = []
        for index, (first, _) in enumerate(strokes):
            for second, _ in strokes[index + 1:]:
                if 130 <= second - first <= 175 and first not in lefts:
                    lefts.append(first)
        return lefts

    def _offset_from_tab_contents(self, image_path: Path) -> tuple[float, int, float] | None:
        """Locate the strip from the reviewed cell templates alone.

        The bracket is an OPTIONAL anchor.  Measured 2026-09-16T04:09:31 on the live
        client: the search panel was open with 生肉, 木材 and 煤矿 all fully visible
        and no white bracket anywhere, because the client draws no bracket until a
        tab has been selected.  The stroke-pair detector therefore found nothing,
        ``resource_tab_offset`` stayed None, and the run could neither tap (the
        target's position was unknown) nor scroll (the scroll branch requires a known
        offset) -- so SELECT_RESOURCE failed against a target that was already on
        screen.  Confirmed by eye on the frame and by the offset scan, which finds a
        single position where three gatherable templates sit on their own cells.

        The reviewed templates have exactly known relative spacing, so an offset that
        simultaneously places several of them on their own cells IS the strip
        position.  Two conditions keep this from being a single coincidental match:

        * at least two template cells must be fully on screen and agree;
        * every cell that can be scored must match its OWN template with the best
          distance, and the best must be unique among the templates.

        Both are satisfied with a wide margin on the measured frames (a correct
        offset puts three or four cells within distance <= 6.5 while the nearest
        wrong reading is 10.65), and a wrong offset cannot satisfy them at all.

        Returns ``(offset_px, supporting_cells, worst_own_distance)`` or ``None``.
        """
        if not self.resource_tab_cell_templates:
            return None
        signatures = {
            resource: [s for s in (_cell_template_signature(Path(p)) for p in paths) if s is not None]
            for resource, paths in self.resource_tab_cell_templates.items()
        }
        if not signatures:
            return None
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            y0, y1 = self._tab_band_rows(height)
            cell_px = round(self.resource_tab_cell * width)

            def evaluate(offset: float) -> tuple[int, float] | None:
                supporting = 0
                worst = 0.0
                for resource, own_signatures in signatures.items():
                    if not own_signatures:
                        continue
                    left = (self.resource_tab_first_left
                            + self.resource_tab_order.index(resource) * self.resource_tab_pitch) * width
                    x0 = round(left + offset)
                    if x0 < 0 or x0 + cell_px > width:
                        continue
                    probe = _cell_signature(image.crop((x0, y0, x0 + cell_px, y1)))
                    own = min(_signature_distance(probe, s) for s in own_signatures)
                    others = [
                        _signature_distance(probe, s)
                        for other, other_signatures in signatures.items()
                        if other != resource
                        for s in other_signatures
                    ]
                    runner = min(others) if others else own + 999.0
                    if own > self.resource_tab_max_distance or own >= runner:
                        return None
                    supporting += 1
                    worst = max(worst, own)
                if supporting < 2:
                    return None
                return supporting, worst

            # Coarse pass then refine: a 1 px sweep over the whole range would be
            # thousands of crops, and the answer only needs to land on the right
            # pixel, not be searched for exhaustively.
            best: tuple[int, float, float] | None = None
            for offset in range(-450, 901, 6):
                verdict = evaluate(float(offset))
                if verdict is None:
                    continue
                supporting, worst = verdict
                if best is None or (supporting, -worst) > (best[0], -best[1]):
                    best = (supporting, worst, float(offset))
            if best is None:
                return None
            supporting, worst, coarse = best
            for offset in range(int(coarse) - 6, int(coarse) + 7):
                verdict = evaluate(float(offset))
                if verdict is None:
                    continue
                got_support, got_worst = verdict
                if (got_support, -got_worst) > (supporting, -worst):
                    supporting, worst, coarse = got_support, got_worst, float(offset)
            return coarse, supporting, worst

    def selected_resource(self, image_path: Path) -> SemanticMatch | None:
        """Identify the active resource tab from the bracket anchor + cell icon.

        Priority used here, in the project's Vision order: page context is the
        caller's gate, the white bracket is the semantic anchor, the strip pitch
        is the relative layout, and only then a template decides *which* resource
        the anchored cell holds.

        1. locate the bracket.  No bracket -> the identity is ``None``, because a
           screen without an active resource tab must never be reported as a
           selection (the old fixed-ROI version returned
           ``RESOURCE_COAL_SELECTED`` on the HOME screen).  The OFFSET, however, is
           still resolved when the tab contents pin it -- see step 5: the client
           draws no bracket at all until something is selected, and refusing to
           locate the strip then made the run unable to tap a target that was
           already on screen;
        2. crop the anchored cell and compare it against the reviewed cell
           templates, which all carry the same bracket, so identity comes from
           the icon and label;
        3. accept only when the best match is both close (``<= 8.0``, see the
           ceiling note in ``__init__``) and clearly better than the runner-up
           (``>= 4.0``);
        4. if (3) rejects, the anchored tab is one of the three tabs that carry no
           template -- measured 2026-09-16 on the production frame that failed
           `SELECT_RESOURCE`: bracket found at left_px=2.0, fully visible, and the
           four reviewed templates scored 33.75 / 34.63 / 35.98 / 36.48, i.e. the
           cell is none of them.  Declining to identify it left
           ``resource_tab_offset`` at ``None``, which stopped the executor from
           tapping *or* scrolling anything.  So the offset is instead resolved
           from the known strip order, and the resolution is validated by the
           reviewed templates themselves -- see
           ``_offset_supported_by_reviewed_tabs``.  This is the work order's
           "safe method that determines the offset from the known complete order
           alone"; it deliberately adds no template, because the only frame
           available for the missing tabs is the very frame being explained, and
           a template cropped from its own test frame proves nothing.
        5. if there is no bracket at all -- which is the normal state of a freshly
           opened search panel, measured live 2026-09-16T04:09:31, where the panel
           showed 生肉/木材/煤矿 fully visible and the stroke detector found nothing
           -- the offset is resolved from the tab CONTENTS instead, see
           ``_offset_from_tab_contents``.  The identity stays ``None`` because no
           tab is marked as selected, but ``resource_tab_offset`` is set, which is
           what the executor needs in order to tap or scroll at all.

        ``self.resource_tab_offset`` and ``self.resource_tab_visible_span`` are
        updated whenever the strip can be located, which is what lets the executor
        compute a correct tap target for any of the four resources.  The offset and
        the identity are therefore independent: a panel with no selection has a
        known geometry and an unknown selection.
        """
        self.resource_tab_offset = None
        self.resource_tab_visible_span = None
        if not self.resource_tab_cell_templates:
            return None

        def locate_from_contents() -> None:
            """Set the strip offset from cell contents when the bracket cannot.

            Called only on the paths where the bracket fails, because it is an
            order of magnitude more expensive than a single crop and the bracket,
            when it exists, is the better anchor: it names the selected tab.
            """
            located = self._offset_from_tab_contents(image_path)
            if located is not None:
                self.resource_tab_offset = located[0]
        left_px, fully_visible = self.selected_tab_left(image_path)
        if left_px < 0:
            # No bracket anywhere: a freshly opened panel, where the client marks no
            # tab until one is chosen.  The identity is honestly unknown, but the
            # strip position is not -- and without it the executor can neither tap
            # nor scroll, which is what stalled SELECT_RESOURCE.
            locate_from_contents()
            return None
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            y0, y1 = self._tab_band_rows(height)
            cell_px = round(self.resource_tab_cell * width)
            x0 = round(left_px)
            x1 = x0 + cell_px
            if x0 < 0 or x1 > width:
                locate_from_contents()
                return None
            probe = image.crop((x0, y0, x1, y1))
            self.resource_tab_visible_span = (x0, x1)
            if not fully_visible:
                # A clipped cell cannot be identified reliably; the strip must be
                # scrolled instead of guessed at -- and scrolling needs an offset,
                # so resolve it from the contents rather than leaving it at None.
                locate_from_contents()
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
            if scored:
                scored.sort()
                best_distance, best_resource = scored[0]
                runner_up = scored[1][0] if len(scored) > 1 else best_distance + 999.0
                if (
                    best_distance <= self.resource_tab_max_distance
                    and runner_up - best_distance >= self.resource_tab_min_margin
                ):
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
            # Neither the anchor nor the identity survived the direct test, so
            # search the possibilities the layout allows -- every stroke pair that
            # could be the bracket crossed with every tab it could be marking --
            # and let the reviewed templates pick.  A pair is only accepted when
            # it is the unique best: two equally-supported candidates stay
            # unresolved rather than being guessed between.
            supported = self._supported_offsets(image, width, height)
            if supported:
                support, margin, anchor_left, anchored = supported[0]
                if len(supported) == 1:
                    unique = True
                else:
                    runner_support, runner_margin = supported[1][0], supported[1][1]
                    unique = support > runner_support or margin > runner_margin + 1.0
                if unique:
                    self.resource_tab_offset = self.resource_tab_offset_from(anchor_left, anchored, width)
                    self.resource_tab_visible_span = (round(anchor_left), round(anchor_left) + cell_px)
                    return SemanticMatch(
                        f"RESOURCE_{anchored}_SELECTED",
                        float(support),
                        {
                            "x_norm": round(anchor_left / width, 4),
                            "y_norm": round(y0 / height, 4),
                            "w_norm": round(cell_px / width, 4),
                            "h_norm": round((y1 - y0) / height, 4),
                            "offset_source": "ANCHOR_AND_IDENTITY_RESOLVED_BY_REVIEWED_TABS",
                            "supporting_reviewed_tabs": support,
                            "support_margin": round(margin, 2),
                        },
                    )
        # Neither path resolved an identity.  Before giving up on the geometry too,
        # let the cell contents place the strip: the executor can act on a known
        # offset even when no tab is marked as selected.
        locate_from_contents()
        return None

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
                if row.get("matcher") == "ccoeff":
                    # Opt-in search-based matcher (tools/ab_matcher.py measures
                    # its separation against the phash path).  Score 1.0 -> 0,
                    # 0.75 -> 16, keeping the SemanticMatch distance contract.
                    #
                    # ``search_band`` is the window, and the registration ROI is
                    # only the fallback.  A record needs the two separated when
                    # the control moves: measured 2026-09-16 on the world-map HUD,
                    # the same button sat at y_norm 0.6727 in one HUD layout and
                    # 0.7453 in another (93 px apart) because the right-hand stack
                    # is bottom-anchored and its contents vary.  A ROI that is
                    # both "where it is" and "where to look" cannot express that,
                    # and a window only 40 px wide around the registration missed
                    # the real control entirely (ccoeff 0.107 there versus 0.945
                    # found 93 px lower).
                    #
                    # The match reports the bounds it FOUND rather than the
                    # registration ROI, because the executor taps
                    # ``match.center_norm``: reporting the registration would send
                    # the tap to where the control used to be.  ``_find_anywhere``
                    # already reports found bounds for the same reason.
                    from .matchers import match_ccoeff

                    band = row.get("search_band")
                    found = match_ccoeff(
                        image_path,
                        Path(row["template_path"]),
                        band or row["roi_norm"],
                        margin=0 if band else 40,
                    )
                    if found is not None:
                        distance = int(round((1.0 - found.score) * 64))
                        bx, by, bw, bh = found.bounds
                        matches.append(SemanticMatch(semantic, distance, {
                            "x_norm": round(bx / width, 4),
                            "y_norm": round(by / height, 4),
                            "w_norm": round(bw / width, 4),
                            "h_norm": round(bh / height, 4),
                        }))
                else:
                    with Image.open(row["template_path"]) as template:
                        distance = hamming(phash(image.crop(bounds)), phash(template))
                    matches.append(SemanticMatch(semantic, distance, roi))
        if not matches:
            # The ``ccoeff`` branch appends nothing when the matcher cannot be
            # evaluated -- every scale is skipped because the template is not
            # strictly smaller than the search window, which is what happens
            # when the frame's resolution differs from the one the ROI was
            # registered at (measured 2026-09-15: a 302x79 crop under
            # dataset/raw made every ROI fall outside the frame, and
            # ``POPUP_HERO_BATTLE_VICTORY`` -- a single-record, ccoeff-only
            # semantic -- left this list empty).  ``min`` on an empty list
            # raises, so ``find`` crashed the whole observation instead of
            # reporting "not found".
            #
            # ``find`` is called on every captured frame, including partial
            # ones and frames from a device whose resolution changed, so it must
            # be total: a template that cannot be evaluated is not a match.
            return None
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
        # No default.  This used to be 6, which is an assumption about ONE account
        # at ONE point in its progression presented as a property of the game: the
        # live client measured on 2026-09-16 runs at capacity 2 and at 6 at other
        # times, and capacity grows with progression.  Guessing high is the
        # dangerous direction -- 6 phantom slots authorize a dispatch into a full
        # queue, the same failure the baseline_used comment below describes.
        # ``None`` means "not read yet", which makes WorldState.idle_marches None and
        # sends the brain to CHECK_MARCH; the OCR layer replaces this with the real
        # count whenever the HUD counter can be read (see the MAP branch and
        # ocr.read_march_count), which is the observed-truth path.
        calibrated_march_max: int | None = None,
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
        # The recall confirmation is checked before the other confirmations so a
        # shared blue 确定 button can never be attributed to the wrong dialog.
        # The title 召回 is the identifying evidence, and it only appears in
        # this dialog (see tools/register_recall_templates.py, which also
        # asserts the negative control: neither template matches a map frame).
        if match("POPUP_HERO_BATTLE_VICTORY"):
            # The Hero Journey battle result (measured live 2026-09-14: 胜利
            # banner plus reward rows; dismissed by BACK - taps do not clear it).
            return WorldState(page=Page.POPUP, popup="HERO_BATTLE_VICTORY", confidence=0.99)
        if match("POPUP_TITLE_RECALL"):
            return WorldState(page=Page.POPUP, popup="MARCH_RECALL", confidence=0.99)
        # The stamina-source panel is reached by tapping the 领主体力 gauge.  It
        # mixes one free claim (「丰盛的招待」, a bare 领取 with no price) with
        # paid rows (「购买并使用 💎300」, store links), so it must be its own
        # popup identity: only the free control may ever be tapped.
        if match("POPUP_TITLE_GET_MORE_STAMINA"):
            return WorldState(page=Page.POPUP, popup="GET_MORE_STAMINA", confidence=0.99)
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
            # Only the fact this template evidences is asserted.  Until
            # 2026-09-15 this branch also claimed 雪豹 level 29, and the two
            # sibling branches below claimed 麝牛 level 9 and 大角鹿 level 22.
            # The formation page draws none of those values: its title bar is
            # the only place the target appears, and it reads 目标：<name> (no
            # level at all).  See the block comment further down for the
            # measured proof that the "identity" was duplicate templates.
            return WorldState(
                page=Page.MARCH,
                beast={"victory_assured":False},
                confidence=0.99,
            )
        if match("BTN_BEAST_DISPATCH_MUSK_OX_9") and match("STATUS_VICTORY_ASSURED_MUSK_OX_9"):
            return WorldState(
                page=Page.MARCH,
                beast={"victory_assured":True},
                confidence=0.99,
            )
        if match("DIALOG_BEAST_MUSK_OX_9") and match("BTN_BEAST_START_MARCH"):
            # This one is legitimate: the world-map target dialog prints the
            # string 等级9 麝牛, so name and level are both drawn on screen.
            return WorldState(
                page=Page.BEAST,
                beast={"name":"麝牛", "level":9, "available":True, "recommended_power":9000, "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("BTN_BEAST_DISPATCH"):
            return WorldState(
                page=Page.MARCH,
                beast={"victory_assured": True},
                confidence=0.99,
            )
        # Stable-anchor fallback identity for the same 出征 formation page.
        #
        # The dispatch button above is animated, and its template therefore
        # drifts.  Measured live 2026-09-15 on two frames of the identical
        # page: BTN_BEAST_DISPATCH sat at distance 0 on one and distance 26 on
        # the other (its threshold is the default 8).  On the frame where it
        # missed, the next branch that matched was the PAGE_ALLIANCE title
        # strip at distance 8, so the formation page was reported as
        # ALLIANCE/HOME with an empty beast.  That single misclassification is
        # what recorded INTEL_BEAST_MARCH_NOT_PROVEN for
        # intel_pins_20260915_000822_nav_01 even though the tap had opened
        # exactly the right page, and it also poisons every downstream
        # decision that branches on the page (brain, recovery, verifier).
        #
        # PAGE_BEAST_MARCH and STATUS_VICTORY_ASSURED are the reviewed anchors
        # of this page -- both were extracted from the same live frame
        # (dataset/raw/live_beast_march_selection.png) -- and both sit at
        # distance 0 on *both* frames above.  They were never referenced by
        # this classifier, which is why the unstable button decided the page.
        #
        # Negative evidence, measured over all 2716 frames in dataset/raw:
        # neither anchor matches any of the 89 alliance frames, so this cannot
        # steal a real alliance page.
        #
        # Two deliberate design choices:
        #   * placed AFTER BTN_BEAST_DISPATCH, so the already live-verified
        #     path stays byte-identical whenever the button does match and this
        #     only adds coverage when it does not;
        #   * no beast name/level is claimed.  The formation page does not
        #     display them, and inheriting the neighbour branch's hard-coded
        #     大角鹿/22 would be an invention whenever another beast is being
        #     marched.  Only the safety fact the page actually shows (the green
        #     本次出征胜券在握 line) is asserted, which is exactly what
        #     verify_intel_beast_march_open needs.
        #
        # 2026-09-15, second pass: the two sibling branches above were brought
        # in line with that rule.  They had kept their hard-coded identities,
        # and measurement showed those identities were not descriptions of the
        # beast at all but duplicate templates of the same two controls:
        #
        #     semantic                          parent frame
        #     BTN_BEAST_DISPATCH_MUSK_OX_9      beast9_round3_march
        #     BTN_BEAST_DISPATCH                live_beast_march_selection
        #     STATUS_VICTORY_ASSURED_MUSK_OX_9  beast9_round3_march
        #     STATUS_VICTORY_ASSURED            live_beast_march_selection
        #
        # All four match BOTH frames at distance 0
        # (tools/probe_beast_formation_identity.py); their ROIs differ by 0.002
        # in y_norm, which is under the hash resolution.  So the reported
        # identity was decided by branch order, and the consequence was
        # measurable: dataset/raw/stamina_emergency/beast6_march.png is a 北极狼
        # formation page and was reported as 麝牛 level 9, which is exactly the
        # name+level verify_beast_dispatch demanded -- a verifier passing on an
        # invented identity.
        #
        # The page does show the target, in its title bar, and the two
        # populations separate cleanly there:
        #     wilderness  目标：麝牛 / 目标：北极狼 / 目标：雪豹   (4/4 frames)
        #     intel       出征                                    (2/2 frames)
        # HybridVision.observe reads that strip and fills beast["name"] plus
        # beast["target_kind"], which is where the identity now comes from.
        if match("PAGE_BEAST_MARCH") and match("STATUS_VICTORY_ASSURED"):
            return WorldState(page=Page.MARCH, beast={"victory_assured": True}, confidence=0.99)
        if match("BTN_BEAST_START_MARCH"):
            # No march counts here.  This template proves the formation page is up
            # and which mission it holds; it says nothing about how many march slots
            # the account has or how many are in use.  The three numbers that used to
            # be written here (march_used=1/2/5/6 against a fixed march_max=6) were
            # invented, and inventing occupancy is the dangerous direction: it feeds
            # idle_marches, and the scheduler then plans against slots that may not
            # exist.  A count that was not read is `None`, which every consumer
            # already treats as "not proven" (WorldState.idle_marches, and the
            # CHECK_MARCH branch in RuleBrain).
            return WorldState(
                page=Page.BEAST,
                beast={"mission_id":"INTEL_BEAST_10", "name": "大角鹿", "level": 22, "available": True,
                       "recommended_power": 5107044, "stamina_cost_displayed": 10},
                confidence=0.99,
            )
        if match("STATUS_BEAST_RETURNING"):
            # A LOWER BOUND, not a reading.  The template proves a beast march is
            # returning, which implies at least one slot is in use -- that is the
            # whole of what is claimed.  The CAPACITY stays unknown, because a
            # phantom slot comes from an over-stated capacity and never from an
            # under-stated occupancy: with march_max unknown, idle_marches is None
            # either way and the brain goes to CHECK_MARCH to read the real pair.
            return WorldState(
                page=Page.MAP,
                marches=(MarchState.RETURNING,),
                march_used=1,
                beast={"name": "大角鹿", "level": 22, "battle_completed": True},
                confidence=0.99,
            )
        if match("STATUS_BEAST_MARCH_OUTBOUND_MUSK_OX_9"):
            # A LOWER BOUND, not a reading -- see STATUS_BEAST_RETURNING above.  The
            # template proves a musk ox march is outbound, so at least one slot is in
            # use.  The old pair (6 of 6) was the dangerous half: it claimed a
            # CAPACITY, which is what makes idle_marches compute to 0 and sends the
            # brain looking for a gathering march to recall -- on a number nobody
            # measured.  ``verify_beast_dispatch`` legitimately wants "at least one
            # march is now active" as its evidence, and a proven lower bound
            # satisfies that without inventing a capacity.
            return WorldState(
                page=Page.MAP,
                marches=(MarchState.MARCHING,),
                march_used=1,
                beast={"name":"麝牛", "level":9, "status":"MARCHING", "stamina_cost_displayed":10},
                confidence=0.99,
            )
        if match("STATUS_INTEL_BEAST_MARCHING"):
            # A LOWER BOUND, not a reading -- see STATUS_BEAST_RETURNING above.
            # The old "5 of 6" also claimed a capacity; only the lower bound remains.
            return WorldState(
                page=Page.MAP,
                marches=(MarchState.MARCHING,),
                march_used=1,
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
        # Stable-anchor identity for the Alliance HOME page, placed before the
        # two weak title strips below.
        #
        # The home page shows eight entry tiles (联盟战争 / 联盟宝箱 / 联盟领地 /
        # 据点争夺 / 联盟商店 / 联盟科技 / 实力排行 / 联盟互助).  PAGE_ALLIANCE is
        # its reviewed title strip and sits at distance 0 on every home frame
        # measured -- but it is a *weak* strip: over all 2757 frames in
        # dataset/raw it also matches 79 出征 (troop formation) frames at
        # distance 8, so it must never be trusted on its own.
        #
        # Until 2026-09-15 the home page therefore never reached the
        # PAGE_ALLIANCE branch further down: PAGE_ALLIANCE_GIFTS (distance 6 on
        # home, 0 on the real gifts page) and PAGE_ALLIANCE_TECH (distance 8 on
        # home, 2 on the real tech page) both matched first, so the live home
        # page was reported as section=GIFTS / status=UNKNOWN.  That single
        # misread broke two things at once, silently:
        #   * brain.py dispatches OPEN_ALLIANCE_GIFTS only when section == HOME,
        #     so that branch was unreachable and the loop always ended in
        #     SAFE_STOP alliance_state_unknown;
        #   * verify_open_alliance_gifts requires before.section == HOME, so the
        #     skill could not have passed even if it had been dispatched.
        # OPEN_ALLIANCE_GIFTS is consequently one of the registry's
        # never-executed skills, while the live Alliance page carries an
        # unclaimed-gift badge of 99+.
        #
        # The pair below is measured, not assumed.  Over the same 2757 frames,
        # BTN_OPEN_ALLIANCE_GIFTS (the 联盟宝箱 tile) and BTN_ALLIANCE_HELP (the
        # 联盟互助 tile) match 16 frames -- and *only* frames the production
        # classifier already calls Page.ALLIANCE, every one of them with
        # visible_claim_buttons == 0 (i.e. genuinely the home page, not the
        # gifts list).  On the real gifts / technology / help pages the same two
        # tiles sit at distance 24-34.  Requiring the title strip AND an entry
        # tile therefore changes no page identity at all (0 of 2757 frames) and
        # only corrects the section on the home page itself (16 of 2757).
        if match("PAGE_ALLIANCE") and (match("BTN_OPEN_ALLIANCE_GIFTS") or match("BTN_ALLIANCE_HELP")):
            return WorldState(page=Page.ALLIANCE, alliance={"section": "HOME"}, confidence=0.98)
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

        if match("BTN_HERO_FIGHT"):
            # The Hero Journey squad-setup page (小队设置, measured live
            # 2026-09-14): pre-filled heroes plus a 战斗 button. It is the
            # formation stage of the camp fight, so it maps to Page.MARCH
            # with empty beast fields - the brain's intel hero branch then
            # dispatches.
            return WorldState(page=Page.MARCH, beast={}, confidence=0.99)
        if match("BTN_HERO_CAMP_FIGHT"):
            # The Hero Journey camp panel on the world map (measured live
            # 2026-09-14): an 探险 ⚡10 fight button, no march stage. It is a
            # fight target like the beast card, so it maps to Page.BEAST with
            # empty beast fields - which is how the brain tells it apart from
            # an intel beast target. The check must precede the map branch:
            # the panel covers the map HUD and would otherwise be misread.
            return WorldState(page=Page.BEAST, beast={}, confidence=0.99)
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
            # The reviewed counter templates are the only authored evidence for
            # the count.  ``calibrated_baseline_used`` used to be added
            # unconditionally, which encoded "one march was running when the
            # template was captured" as a permanent property of the map:
            # measured live on 2026-09-14, a frame with six gathering marches
            # still reported 1/6 -- five phantom free slots, enough to authorize
            # a dispatch into a full queue.  With no counter template matched the
            # count is unknown, and the OCR layer fills it in; every verifier
            # already treats ``march_used is None`` as "not proven".
            if count_one and not count_two:
                used = 1 + transient_count
            elif count_two and not count_one:
                used = 2 + transient_count
            else:
                used = None
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
