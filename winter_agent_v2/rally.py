from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, Iterable, Mapping

from .models import WorldState


class RallyTarget(str, Enum):
    BEAR = "BEAR"
    POLAR_TERROR = "POLAR_TERROR"
    FORTRESS = "FORTRESS"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class RallyRowState(str, Enum):
    JOINABLE = "JOINABLE"
    FULL = "FULL"
    EXPIRED = "EXPIRED"
    JOINED = "JOINED"
    UNKNOWN = "UNKNOWN"


class BearRole(str, Enum):
    LEADER = "LEADER"
    JOINER = "JOINER"
    AUTO = "AUTO"


class BearPhase(str, Enum):
    DISCOVERED = "DISCOVERED"
    SCHEDULED = "SCHEDULED"
    PREPARING = "PREPARING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class RallyRow:
    target_type: RallyTarget
    leader: str | None
    state: RallyRowState
    remaining_seconds: int | None = None
    capacity_used: int | None = None
    capacity_max: int | None = None
    required_queue_type: str = "NORMAL"
    join_point: tuple[int, int] | None = None

    @property
    def joinable(self) -> bool:
        capacity = self.capacity_used is None or self.capacity_max is None or self.capacity_used < self.capacity_max
        return self.target_type is RallyTarget.BEAR and self.state is RallyRowState.JOINABLE and capacity


# ---------------------------------------------------------------------------
# Reading the rally list off the current frame
# ---------------------------------------------------------------------------
#
# Why this exists (task book §一 / §二)
# ------------------------------------
# ``BTN_JOIN_ROW`` registers *a* green +.  That is a template for one control, not a model of
# the list, and treating it as "the rally to join" is precisely the confusion the task book
# names -- "不得把 BTN_JOIN_ROW 的绿色 + 模板直接当成当前应该加入的集结".  What was missing was
# the **object relationship**: which rally does a given + belong to?
#
# This reads that relationship off the frame:
#
#     巨熊集结列表
#       └─ 集结项 (one per 集结中 row)
#            ├─ 目标身份      等级1变异巨熊
#            ├─ 发起者        [iio]葬爱·超人强
#            ├─ 集结倒计时     00:00:45
#            ├─ 人数及容量     8/15
#            └─ 该集结自己的加入按钮   ← located inside THIS row's band
#
# Everything below is frame-derived.  There is no row index, no fixed pitch, no fixed button
# column and no fixed container rectangle: the rows come from the client's own 集结中 headers,
# each band is bounded by the **next header the client drew**, and a row's button is a green
# affordance found **inside that band**.  If the list scrolls, every one of those inputs
# changes with it.
#
# Measured on the four archived frames (2026-09-24, 720x1280):
#
#   join_list_now.png          3 rows, 2 green buttons (rows 1-2). Row 3 draws none.
#   join_list_after_detail.png 3 rows, 1 green button (row 2). Row 1's + is the grey one.
#   bear_rally_panel.png       3 rows.
#   joined_with_jesse.png      the same list after joining.
#
# The row headers sit at y 202 / 609 / 1020 -- a pitch of ~407 px -- but this module does not
# use that number.  It is recorded here only so a reader can tell a drifting pitch from a
# broken reader, and the code recomputes the band from the actual headers every time.

#: The client's own word on a row that has not left yet.  Its presence is what makes a row a
#: row: everything else is a field *within* one.
RALLY_ROW_HEADER_WORD = "集结中"

#: Words the client prints for the bear as a rally target.  等级1变异巨熊 is the measured one;
#: 冰原巨兽 is the name the auto-join dialog uses for the same activity (see
#: ``knowledge/ui/en_zh_semantic_map.json``).  A row matching none of these is NOT a bear row
#: and must never be joined on the strength of a green + alone.
BEAR_TARGET_WORDS: tuple[str, ...] = ("变异巨熊", "冰原巨兽", "巨熊")

#: ``8/15`` -- the row's own member count and capacity.
_CAPACITY_RE = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")

#: ``00:00:45``, and the client's occasional full-width colon ``00：01:50`` (measured on row 3
#: of join_list_now.png, where the colon is U+FF1A).  A reader that only accepted ':' silently
#: read no countdown for the last row.
_CLOCK_RE = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})\s*[:：]\s*(\d{2})")

#: The green join affordance.  The threshold family is the project's own -- the one the quick
#: panel's done-tick scan uses (``QUICK_PANEL_DONE_GREEN_MIN`` and friends) -- so this reader
#: sees green where the rest of the project sees green.
GREEN_MIN = 150
GREEN_OVER_RED = 50
GREEN_OVER_BLUE = 50

#: A join button is ~59x54 px and ~2050 px of green.  A hero portrait's green fringe measured
#: 108-134 px in a 23x10 / 34x14 box.  These two size floors are what keep a portrait from
#: being read as a button, and they are shapes rather than positions, so they survive a re-layout.
GREEN_MIN_PIXELS = 400
GREEN_MIN_WIDTH = 40
GREEN_MIN_HEIGHT = 40


@dataclass(frozen=True)
class RallyRowReading:
    """One visible rally row, with its own fields and its own button.

    ``join_norm`` is the point of **this row's** join affordance, read off the frame it was
    found in.  It is a recognition result, not an operation rule: the caller must not store it
    and reuse it, because the next frame's list may be scrolled or reordered (constitution
    §三 坐标用完即弃).  When this row draws no green affordance the field is ``None`` -- the
    honest answer, and the one that stops a full rally from being joined.
    """

    row_index: int
    header_y_norm: float
    band_norm: tuple[float, float]
    target_text: str
    target_type: RallyTarget
    leader: str | None
    remaining_seconds: int | None
    capacity_used: int | None
    capacity_max: int | None
    join_norm: tuple[float, float] | None
    join_box_norm: tuple[float, float, float, float] | None
    state: RallyRowState

    @property
    def joinable(self) -> bool:
        capacity = (
            self.capacity_used is None
            or self.capacity_max is None
            or self.capacity_used < self.capacity_max
        )
        return (
            self.target_type is RallyTarget.BEAR
            and self.state is RallyRowState.JOINABLE
            and capacity
            and self.join_norm is not None
        )

    def to_row(self, *, width: int, height: int) -> RallyRow:
        """The scheduler-facing row.  ``join_point`` is in pixels **for this frame only**."""
        point = None
        if self.join_norm is not None:
            point = (round(self.join_norm[0] * width), round(self.join_norm[1] * height))
        return RallyRow(
            target_type=self.target_type,
            leader=self.leader,
            state=self.state,
            remaining_seconds=self.remaining_seconds,
            capacity_used=self.capacity_used,
            capacity_max=self.capacity_max,
            join_point=point,
        )


@dataclass(frozen=True)
class RallyListReading:
    """The whole visible list: its rows, and the container they live in."""

    rows: tuple[RallyRowReading, ...]
    #: The scroll container, normalized, derived from the rows the client drew.  ``None`` when
    #: no row was readable -- and then there is nothing to scroll *within*, so the caller must
    #: not invent a swipe (task book §二: 不得使用固定屏幕高度或固定起终点).
    container_norm: tuple[float, float, float, float] | None
    frame_size: tuple[int, int]
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_rows(self) -> bool:
        return bool(self.rows)

    def joinable_bears(self) -> tuple[RallyRowReading, ...]:
        return tuple(row for row in self.rows if row.joinable)

    def best_joinable(self) -> RallyRowReading | None:
        """The joinable bear with the least time left -- detect-to-join time is the scarce thing.

        Ties keep reading order, which is the order the client drew them in.  ``None`` means
        this frame offers nothing to join, which is an answer and not a failure.
        """
        eligible = self.joinable_bears()
        if not eligible:
            return None
        return min(
            eligible,
            key=lambda row: (
                row.remaining_seconds if row.remaining_seconds is not None else 10**9,
                row.row_index,
            ),
        )


def _green_boxes(
    image_path: Path,
    *,
    min_pixels: int = GREEN_MIN_PIXELS,
    min_width: int = GREEN_MIN_WIDTH,
    min_height: int = GREEN_MIN_HEIGHT,
) -> list[tuple[int, int, int, int, int]]:
    """Every green affordance big enough to be a button, as (x0, y0, x1, y1, pixels).

    Uses numpy when it is importable (it is, and the project already depends on it) and falls
    back to the same connected-component walk in pure Python otherwise.  Both paths apply the
    identical threshold, so a machine without numpy reads the same list, slower.
    """
    from PIL import Image

    with Image.open(image_path) as opened:
        rgb = opened.convert("RGB")
    width, height = rgb.size

    try:
        import numpy as np

        arr = np.asarray(rgb, dtype=np.int16)
        red, green, blue = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        mask = (green >= GREEN_MIN) & (green - red >= GREEN_OVER_RED) & (green - blue >= GREEN_OVER_BLUE)
        boxes: list[tuple[int, int, int, int, int]] = []
        # Connected components without scipy: label by flood fill over the mask's True cells.
        seen = np.zeros_like(mask, dtype=bool)
        ys, xs = np.nonzero(mask)
        for y0, x0 in zip(ys.tolist(), xs.tolist()):
            if seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            xmin = xmax = x0
            ymin = ymax = y0
            count = 0
            while stack:
                cy, cx = stack.pop()
                count += 1
                if cx < xmin:
                    xmin = cx
                elif cx > xmax:
                    xmax = cx
                if cy < ymin:
                    ymin = cy
                elif cy > ymax:
                    ymax = cy
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if count >= min_pixels and (xmax - xmin + 1) >= min_width and (ymax - ymin + 1) >= min_height:
                boxes.append((xmin, ymin, xmax, ymax, count))
        return sorted(boxes, key=lambda b: (b[1], b[0]))
    except ImportError:
        pixels = rgb.load()
        seen = set()
        boxes = []
        for y in range(height):
            for x in range(width):
                if (x, y) in seen:
                    continue
                r, g, b = pixels[x, y]
                if not (g >= GREEN_MIN and g - r >= GREEN_OVER_RED and g - b >= GREEN_OVER_BLUE):
                    continue
                stack = [(x, y)]
                seen.add((x, y))
                xmin = xmax = x
                ymin = ymax = y
                count = 0
                while stack:
                    cx, cy = stack.pop()
                    count += 1
                    xmin = min(xmin, cx)
                    xmax = max(xmax, cx)
                    ymin = min(ymin, cy)
                    ymax = max(ymax, cy)
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = cx + dx, cy + dy
                        if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in seen:
                            continue
                        nr, ng, nb = pixels[nx, ny]
                        if ng >= GREEN_MIN and ng - nr >= GREEN_OVER_RED and ng - nb >= GREEN_OVER_BLUE:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
                if count >= min_pixels and (xmax - xmin + 1) >= min_width and (ymax - ymin + 1) >= min_height:
                    boxes.append((xmin, ymin, xmax, ymax, count))
        return sorted(boxes, key=lambda b: (b[1], b[0]))


def _clock_seconds(text: str) -> int | None:
    match = _CLOCK_RE.search(text)
    if not match:
        return None
    hours, minutes, seconds = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _bear_target_in(text: str) -> str | None:
    for word in BEAR_TARGET_WORDS:
        if word in text:
            return word
    return None


def read_rally_list(
    image_path: Path | str,
    ocr,
    *,
    result=None,
) -> RallyListReading:
    """Read the visible rally rows and the relationship between each row and its button.

    ``ocr`` is the OCR service (``ocr.OCRService``); it is taken as a parameter rather than
    imported so this module keeps depending on ``models`` alone and stays cheap to import
    from the goal layer.

    ``result`` lets a caller that has already OCR'd this frame hand the reading over instead of
    paying for a second pass -- ``OCRService`` caches by image digest anyway, so passing it is
    an optimisation and not a correctness requirement.

    Returns a reading whose ``rows`` are in the client's own drawing order.  Nothing here
    selects a rally; selection is a policy question and lives in ``choose_bear_operation`` /
    ``best_joinable``.
    """
    image_path = Path(image_path)
    if result is None:
        result = ocr.recognize(image_path)
    tokens = [t for t in getattr(result, "tokens", ()) if getattr(t, "text", "").strip()]

    from PIL import Image

    with Image.open(image_path) as opened:
        width, height = opened.size

    # ---- 1. row anchors: the client's own 集结中 headers ---------------------
    anchors: list[tuple[float, str]] = []
    for token in tokens:
        text = token.text.strip()
        if RALLY_ROW_HEADER_WORD not in text:
            continue
        y = token.centre[1]
        # The tab strip also prints 集结 (without 中) at y ~108 on this client; requiring the
        # header word, and a y below the tab strip, keeps the tab out of the row list.
        if y < height * 0.12:
            continue
        anchors.append((y, text))
    anchors.sort(key=lambda pair: pair[0])

    if not anchors:
        return RallyListReading(
            rows=(), container_norm=None, frame_size=(width, height),
            evidence={"reason": "no_rally_row_header_on_this_frame",
                      "tokens": len(tokens)},
        )

    # ---- 2. bands: bounded by the NEXT header the client drew ----------------
    # The last band has no successor, so it is closed by the footer when the client printed
    # one (开启后自动加入… / 自动加入) and by the frame edge otherwise.  Deriving the end from
    # the frame rather than from a pitch is what lets a scrolled list read correctly.
    footer_y = None
    for token in tokens:
        if token.text.strip().startswith(("开启后自动加入", "自动加入")):
            footer_y = min(footer_y, token.centre[1]) if footer_y else token.centre[1]

    green_boxes = _green_boxes(image_path)

    rows: list[RallyRowReading] = []
    for index, (header_y, header_text) in enumerate(anchors):
        if index + 1 < len(anchors):
            band_top = header_y - (header_y - (anchors[index - 1][0] if index else header_y - 40)) * 0.25
            band_bottom = anchors[index + 1][0] - (anchors[index + 1][0] - header_y) * 0.25
        else:
            band_top = header_y - 40
            band_bottom = footer_y - 10 if footer_y is not None else float(height)
        band_top = max(0.0, band_top)
        band_bottom = min(float(height), band_bottom)
        if band_bottom <= band_top:
            band_bottom = min(float(height), band_top + 40)

        in_band = [t for t in tokens if band_top <= t.centre[1] < band_bottom]

        capacity_used = capacity_max = None
        for token in in_band:
            match = _CAPACITY_RE.match(token.text.strip())
            if match:
                used, maximum = int(match.group(1)), int(match.group(2))
                # Keep the widest count on the row: 800,563/875,430 also matches nothing here
                # because of the comma, but a future client could print 8/15 twice.
                if capacity_used is None or used > capacity_used:
                    capacity_used, capacity_max = used, maximum

        target_text = ""
        target_type = RallyTarget.UNKNOWN
        for token in in_band:
            word = _bear_target_in(token.text)
            if word:
                target_text = token.text.strip()
                target_type = RallyTarget.BEAR
                break

        remaining = _clock_seconds(header_text)
        if remaining is None:
            for token in in_band:
                value = _clock_seconds(token.text)
                if value is not None:
                    remaining = value
                    break

        # The initiator is the row's own name line, just under the header.  Read as "the
        # topmost token below the header that is none of the header's own furniture", so it
        # needs no column constant: on this client the 目标 column label shares the line and is
        # excluded by name, and the header words are excluded by the same rule.
        #
        # Measured on join_list_now.png row 1: header centre y=207, initiator '[iio]葬爱·超人强'
        # centre y=279, 目标 centre y=288.  Picking the leftmost token on the header line -- the
        # first version -- returned '集结', the header word itself.
        leader = None
        leader_line = [
            t for t in in_band
            if header_y < t.centre[1] <= header_y + height * 0.06
            and RALLY_ROW_HEADER_WORD not in t.text
            and _CLOCK_RE.search(t.text) is None
            and _bear_target_in(t.text) is None
            and t.text.strip() not in {"目标", "集结", "发起者", "距离"}
        ]
        if leader_line:
            leader = min(leader_line, key=lambda t: (t.centre[1], t.centre[0])).text.strip()

        # ---- 3. THIS row's join button, found inside THIS row's band ---------
        join_norm = None
        join_box = None
        for x0, y0, x1, y1, pixels in green_boxes:
            centre_y = (y0 + y1) / 2.0
            if not (band_top <= centre_y < band_bottom):
                continue
            join_norm = (round(((x0 + x1) / 2.0) / width, 4), round(centre_y / height, 4))
            join_box = (round(x0 / width, 4), round(y0 / height, 4),
                        round((x1 - x0) / width, 4), round((y1 - y0) / height, 4))
            break

        if join_norm is not None:
            state = RallyRowState.JOINABLE
        elif capacity_used is not None and capacity_max is not None and capacity_used >= capacity_max:
            state = RallyRowState.FULL
        else:
            # A row with no green affordance and no readable full count is *unknown*, not full.
            # Collapsing the two would let "I could not read it" become "it is not available".
            state = RallyRowState.UNKNOWN

        rows.append(RallyRowReading(
            row_index=index,
            header_y_norm=round(header_y / height, 4),
            band_norm=(round(band_top / height, 4), round(band_bottom / height, 4)),
            target_text=target_text,
            target_type=target_type,
            leader=leader,
            remaining_seconds=remaining,
            capacity_used=capacity_used,
            capacity_max=capacity_max,
            join_norm=join_norm,
            join_box_norm=join_box,
            state=state,
        ))

    # ---- 4. the scroll container, derived from the rows themselves -----------
    # Top is where the first row starts; bottom is the footer if the client printed one,
    # else the last row's band end.  A caller that wants to scroll uses THIS rectangle, so a
    # scrolled list scrolls in the scrolled list's own geometry (task book §二).
    container_top = max(0.0, rows[0].header_y_norm * height - 30.0)
    container_bottom = footer_y - 10.0 if footer_y is not None else min(
        float(height), rows[-1].band_norm[1] * height)
    if container_bottom <= container_top:
        container_bottom = container_top + 40.0
    container_norm = (0.05, round(container_top / height, 4),
                      0.90, round(min(float(height), container_bottom) / height, 4))

    return RallyListReading(
        rows=tuple(rows),
        container_norm=container_norm,
        frame_size=(width, height),
        evidence={
            "anchors": len(anchors),
            "green_boxes": len(green_boxes),
            "footer_y_norm": round(footer_y / height, 4) if footer_y is not None else None,
            "container_source": "row_headers_and_footer",
        },
    )


@dataclass(frozen=True)
class BearGoalState:
    phase: BearPhase
    role: BearRole = BearRole.AUTO
    reserved_start_time: str | None = None
    remaining_seconds: int | None = None
    normal_idle_slots: int | None = None
    special_start_available: bool | None = None


def bear_phase(event_status: str | None, seconds_to_start: int | None, seconds_remaining: int | None) -> BearPhase:
    if event_status == "ACTIVE" or (seconds_remaining is not None and seconds_remaining > 0):
        return BearPhase.ACTIVE
    if event_status in {"FINISHED", "COOLDOWN"} or (seconds_remaining is not None and seconds_remaining <= 0):
        return BearPhase.FINISHED
    if seconds_to_start is None:
        return BearPhase.DISCOVERED
    if seconds_to_start <= 120:
        return BearPhase.READY
    if seconds_to_start <= 600:
        return BearPhase.PREPARING
    return BearPhase.SCHEDULED


def choose_bear_operation(world: WorldState, role: BearRole, rows: Iterable[RallyRow]) -> str | None:
    """Choose WHAT only; execution stays in generic START_RALLY/JOIN_RALLY skills."""
    joinable = any(row.joinable for row in rows)
    normal_idle = world.idle_marches
    can_join = joinable and normal_idle is not None and normal_idle > 0
    can_start = world.bear_rally_special_available is True
    if role is BearRole.JOINER:
        return "JOIN_RALLY" if can_join else None
    if role is BearRole.LEADER:
        if can_start:
            return "START_RALLY"
        return "JOIN_RALLY" if can_join else None
    if can_start:
        return "START_RALLY"
    return "JOIN_RALLY" if can_join else None


def fastest_joinable_bear(rows: Iterable[RallyRow]) -> RallyRow | None:
    eligible = [row for row in rows if row.joinable]
    return min(eligible, key=lambda row: row.remaining_seconds if row.remaining_seconds is not None else 10**9, default=None)


def body_hero_order(available: Iterable[str]) -> tuple[str, ...]:
    available_set = {str(name).upper() for name in available}
    preferred = ("JESSIE", "SEO_YOON", "JASSER")
    selected = tuple(name for name in preferred if name in available_set)
    return selected + ("NO_HERO",)


@dataclass
class RallyMetrics:
    join_attempts: int = 0
    join_success: int = 0
    rally_full: int = 0
    join_failure: int = 0
    last_detect_to_join_ms: int | None = None
    last_join_to_confirm_ms: int | None = None
    last_total_join_ms: int | None = None
    _detected_at: float | None = field(default=None, repr=False)
    _clicked_at: float | None = field(default=None, repr=False)

    def detected(self) -> None:
        self._detected_at = monotonic()

    def clicked(self) -> None:
        self.join_attempts += 1
        self._clicked_at = monotonic()
        if self._detected_at is not None:
            self.last_detect_to_join_ms = round((self._clicked_at - self._detected_at) * 1000)

    def confirmed(self) -> None:
        now = monotonic()
        self.join_success += 1
        if self._clicked_at is not None:
            self.last_join_to_confirm_ms = round((now - self._clicked_at) * 1000)
        if self._detected_at is not None:
            self.last_total_join_ms = round((now - self._detected_at) * 1000)

    def race_lost(self) -> None:
        self.rally_full += 1

