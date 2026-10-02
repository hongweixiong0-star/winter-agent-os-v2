"""Current-frame reader for the in-game ``常规活动`` calendar.

The calendar is a discovery source, not an activity clock.  It may say when an activity is
advertised, while registration, participation, and battle times remain separate fields until the
client actually shows them.  This module only reads OCR tokens from the frame in hand; it never
supplies a coordinate or manufactures a time.
"""

from __future__ import annotations

import hashlib
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from . import event_goal


_DATE_RE = re.compile(
    r"(?:20\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*/\s*\d{1,2})"
    r"(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?"
)
_DATE_LABEL_RE = re.compile(
    r"^(?:20\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*/\s*\d{1,2})$"
)
_GAME_DATETIME_RE = re.compile(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s*\d{1,2}:\d{2}:\d{2}")
_GAME_DATE_PREFIX_RE = re.compile(r"^20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?")
_DATE_RANGE_RE = re.compile(
    r"(?P<start>(?:20\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日)(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?)"
    r"\s*(?:至|到|—|–|~|～|-)\s*"
    r"(?P<end>(?:20\d{2}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日)(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?)"
)
_COUNTDOWN_RE = re.compile(r"(?:距(?:离)?开始|倒计时)\s*[:：]?\s*约?\s*([\d天小时时分秒:： ]{2,24})")
_WEEKDAY_RE = re.compile(r"(?:周|星期)[一二三四五六日天]")
_NON_EVENT_LABELS = frozenset({
    "常规活动", "活动详情", "活动规则", "活动奖励", "活动时间", "活动日历", "日历",
    "活动细则", "报名时间", "战斗时间", "开始时间", "结束时间", "开放时间",
    "详情", "报名", "准备", "参与", "奖励", "关闭", "返回", "已开启", "未开启",
    "即将开启", "进行中", "已结束", "前往", "查看", "取消", "确定", "领取",
})


def _box(token: Any) -> tuple[tuple[float, float], ...]:
    try:
        return tuple((float(point[0]), float(point[1])) for point in (token.box or ()))
    except (TypeError, ValueError, IndexError):
        return ()


def _centre(token: Any) -> tuple[float, float] | None:
    points = _box(token)
    if not points:
        return None
    return (sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points))


def _height(token: Any) -> float:
    points = _box(token)
    return max((point[1] for point in points), default=0.0) - min(
        (point[1] for point in points), default=0.0
    )


def _event_id(label: str) -> str:
    known = event_goal.event_id_for_label(label)
    if known:
        return known
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10].upper()
    return f"DISCOVERED_EVENT_{digest}"


def _known_title(label: str) -> bool:
    return event_goal.event_id_for_label(label) is not None


def _candidate_title(label: str) -> bool:
    value = re.sub(r"\s+", "", label)
    if not value or value in _NON_EVENT_LABELS or len(value) > 16:
        return False
    if _DATE_RE.fullmatch(value) or _WEEKDAY_RE.fullmatch(value):
        return False
    if re.search(r"[\u4e00-\u9fff]", value):
        return 2 <= len(value) <= 12 and not any(
            word in value for word in ("体力", "领取", "活动时间", "距开始", "剩余时间", "可报名")
        )
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9 '&-]{2,30}", value))


def _calendar_date_rows(materialized: list[Any], frame_size: tuple[int, int] | None) -> list[tuple[Any, str]]:
    """Choose the densest observed horizontal date row, ignoring a separate page clock."""
    candidates: list[tuple[Any, str, float]] = []
    for token in materialized:
        label = re.sub(r"\s+", "", str(getattr(token, "text", "") or "").strip())
        centre = _centre(token)
        if centre is None or not _DATE_LABEL_RE.fullmatch(label):
            continue
        candidates.append((token, label, centre[1]))
    if not candidates:
        return []
    height = (frame_size or (0, 0))[1]
    band = max(18.0, height * 0.035)
    groups: list[list[tuple[Any, str, float]]] = []
    for row in sorted(candidates, key=lambda value: value[2]):
        group = next((g for g in groups if abs(sum(item[2] for item in g) / len(g) - row[2]) <= band), None)
        if group is None:
            groups.append([row])
        else:
            group.append(row)
    best = max(groups, key=lambda group: (len({item[1] for item in group}), len(group)))
    by_date: dict[str, tuple[Any, str, float]] = {}
    for row in best:
        by_date.setdefault(row[1], row)
    return [(row[0], row[1]) for row in sorted(by_date.values(), key=lambda value: _centre(value[0])[0])]


def _event_bar_geometry(frame_path: Path | str, token: Any) -> tuple[float, float] | None:
    """Measure the colored event bar directly below a title on the current screenshot."""
    try:
        with Image.open(frame_path) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            box = _box(token)
            if not box or width <= 0 or height <= 0:
                return None
            left = max(0, int(min(point[0] for point in box)))
            right = min(width, int(max(point[0] for point in box)))
            bottom = max(point[1] for point in box)
            y = min(height - 1, max(0, int(round(bottom + max(3.0, _height(token) * 0.18)))))
            x = min(width - 1, max(0, (left + right) // 2))
            pixels = image.load()
            reference = pixels[x, y]
            maximum = max(reference)
            saturation = (maximum - min(reference)) / maximum if maximum else 0.0
            # Section labels sit on the flat cyan header band. The actual event pills use
            # distinct saturated colors (orange, blue, yellow, green); this rejects section
            # headings such as the duplicate ``梦境寻忆`` above its clickable event row.
            if saturation < 0.48:
                return None
            def near(px: int) -> bool:
                color = pixels[px, y]
                return sum(abs(int(a) - int(b)) for a, b in zip(color, reference)) <= 58
            start = x
            end = x
            while start > 0 and near(start - 1):
                start -= 1
            while end + 1 < width and near(end + 1):
                end += 1
            if end - start < max(24, (right - left) * 0.75):
                return None
            return float(start), float(end + 1)
    except (OSError, ValueError):
        return None


def match_calendar_detail_to_entry(
    detail: dict[str, Any], entries: Iterable[dict[str, Any]],
) -> dict[str, Any] | None:
    """Correlate an opened detail with a pending calendar row, tolerating OCR's one-glyph drift.

    Exact event IDs always win. A localized fuzzy match is returned only when it is clearly unique
    and the detail's printed date interval overlaps the row's visually observed calendar days.
    This preserves both raw names and the attribution method for audit.
    """
    rows = [dict(row) for row in entries if isinstance(row, dict)]
    event_id = str(detail.get("event_id") or "")
    exact = next((row for row in rows if str(row.get("event_id") or "") == event_id), None)
    if exact is not None:
        return {"matched": True, "row": exact, "method": "EXACT_EVENT_ID", "confidence": 1.0}

    observed_name = re.sub(r"\s+", "", str(detail.get("display_name") or "")).casefold()
    if len(observed_name) < 2:
        return None
    scored = sorted((
        (SequenceMatcher(None, observed_name,
                         re.sub(r"\s+", "", str(row.get("display_name") or "")).casefold()).ratio(), row)
        for row in rows
    ), key=lambda pair: pair[0], reverse=True)
    if not scored:
        return None
    score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if score < 0.70 or score - runner_up < 0.15:
        return None

    start = _month_day(str(detail.get("preview_start_raw") or ""))
    end = _month_day(str(detail.get("preview_end_raw") or ""))
    row_days = [day for raw in (best.get("calendar_dates_raw") or ()) if (day := _month_day(str(raw))) is not None]
    if start is None or end is None or not row_days:
        return None
    start_value, end_value = start[0] * 32 + start[1], end[0] * 32 + end[1]
    if end_value < start_value:
        end_value += 12 * 32
    overlaps = any(
        start_value <= month * 32 + day <= end_value
        or start_value <= month * 32 + day + 12 * 32 <= end_value
        for month, day in row_days
    )
    if not overlaps:
        return None
    return {"matched": True, "row": best, "method": "UNIQUE_FUZZY_NAME_AND_VISIBLE_DATE_OVERLAP",
            "confidence": round(score, 4)}


def _month_day(value: str) -> tuple[int, int] | None:
    match = re.search(
        r"(?:20\d{2}\s*[-/.年]\s*)?(\d{1,2})\s*[-/.月/]\s*(\d{1,2})\s*日?",
        value,
    )
    if not match:
        return None
    try:
        month, day = int(match.group(1)), int(match.group(2))
    except ValueError:
        return None
    return (month, day) if 1 <= month <= 12 and 1 <= day <= 31 else None


def read_calendar_entry(tokens: Iterable[Any], *, frame_size: tuple[int, int] | None) -> dict[str, Any] | None:
    """Locate the small 常规活动 navigation label in the current OCR frame."""
    width, height = frame_size or (0, 0)
    if width <= 0 or height <= 0:
        return None
    matches = []
    for token in tokens:
        if str(getattr(token, "text", "") or "").strip() != "常规活动":
            continue
        points = _box(token)
        if not points:
            continue
        if _height(token) / height >= 0.03:
            continue
        centre = _centre(token)
        if centre is None:
            continue
        matches.append((token, centre))
    # Multiple same-size labels create an identity ambiguity. Do not select one by order.
    if len(matches) != 1:
        return None
    token, centre = matches[0]
    return {
        "visible": True,
        "tap_norm": [round(centre[0] / width, 5), round(centre[1] / height, 5)],
        "source": "CURRENT_FRAME_OCR",
        "confidence": float(getattr(token, "confidence", 0.0) or 0.0),
    }


#: The activity strip sits between the page heading and the page clock.  Measured on the
#: pinned 2026-10-02 frame (role 1061663148): the heading's box ends at y=0.047 and the
#: clock begins at y=0.202, so every strip label falls inside this band with room to spare.
#: The band is a measured window, not a tuned constant: it exists because the strip is
#: structurally *above* the calendar's own first date row (y=0.267) and *below* the heading.
ACTIVITY_STRIP_BAND = (0.06, 0.20)

#: The same band as a normalized ROI, for the callers that own a frame rather than tokens.
#:
#: Why the strip needs a crop at all, measured on the pinned 2026-10-02 frame:
#:
#:     whole-frame OCR -> 联盟总动员 only  (CANYON_CLASH absent)
#:     this crop      -> 联盟总动员 0.999, 峡谷会战 0.941
#:
#: and on the second role's frame the same crop returned 联盟总动员 0.999, 峡谷会战 0.941,
#: plus ``30`` and ``兵`` which map to no registered activity and are therefore dropped.
#:
#: This is the miss ``ocr_roi.py`` already recorded for the gather panel's 22-px resource
#: tabs: the engine normalises the candidate region, so cropping the text band before
#: recognition turns a miss into a hit.  **The crop is the fix; upscaling is not.**
#: Measured on the same pixels: up=1 reads 峡谷会战 at 0.941, up=2 at 0.968, up=3 at 0.930 --
#: the spread is inside the noise, and each factor costs a resample per frame.  The tempting
#: change here is a magic upscale number, and the measurement says it buys nothing.
ACTIVITY_STRIP_ROI: dict[str, float] = {
    "x_norm": 0.0, "y_norm": ACTIVITY_STRIP_BAND[0], "w_norm": 1.0,
    "h_norm": ACTIVITY_STRIP_BAND[1] - ACTIVITY_STRIP_BAND[0],
}


def strip_tokens_from_crop(
    tokens: Iterable[Any], *, frame_size: tuple[int, int] | None,
    crop_top_px: int, crop_height_px: int,
) -> dict[str, Any]:
    """Re-express crop-relative token geometry in whole-frame coordinates.

    The engine normalizes the region it is given, so a token recognized inside a crop
    carries a y measured **from the crop's top edge**.  Every consumer of a strip row --
    the goal layer, the scheduler, a future tap -- speaks whole-frame normalized
    coordinates, and a y that stayed crop-relative would place the row inside the calendar
    grid, which is a region this reader never measured.  This is the whole reason the crop
    can be used at all: the recognition improves and the geometry stays truthful.
    """
    result: dict[str, Any] = {
        "kind": "ACTIVITY_STRIP", "recognized": False, "entries": [],
        "source": "CURRENT_FRAME_OCR_CROP",
    }
    width, height = frame_size or (0, 0)
    if width <= 0 or height <= 0 or crop_height_px <= 0:
        return {**result, "reason": "NO_CROP_GEOMETRY"}
    rows: list[dict[str, Any]] = []
    for token in tokens:
        label = re.sub(r"\s+", "", str(getattr(token, "text", "") or ""))
        points = _box(token)
        if not label or not points or not all(math.isfinite(v) for p in points for v in p):
            continue
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        top, bottom = min(p[1] for p in points), max(p[1] for p in points)
        confidence = float(getattr(token, "confidence", 0.0) or 0.0)
        if not math.isfinite(confidence) or confidence < 0.9:
            continue
        rows.append({"label": label, "left": left, "right": right,
                     "top": crop_top_px + top, "bottom": crop_top_px + bottom,
                     "x": (left + right) / 2, "y": crop_top_px + (top + bottom) / 2,
                     "height": bottom - top, "confidence": confidence})
    return {**result, "rows": rows, "crop_top_px": crop_top_px,
            "crop_height_px": crop_height_px}


def read_regular_event_activity_strip(
    tokens: Iterable[Any], *, frame_size: tuple[int, int] | None,
    already_in_frame_coordinates: bool = False,
    crop_top_px: int = 0, crop_height_px: int = 0,
    heading_found: bool | None = None,
) -> dict[str, Any]:
    """Read the activity strip the client draws **above** the calendar grid.

    Why this exists, measured 2026-10-02 on the pinned production frame
    ``20261002_135741_630328_step_005_after_20261002T055825254675.png``:

    The ``常规活动`` screen carries three regions, and only two of them were ever read.  The
    calendar grid below the clock was read at confidence 0.995 and every one of its six
    rows carries a real detail reading.  The strip above the clock was read too --
    ``联盟总动员`` at confidence **0.999** -- and then dropped, because
    ``read_regular_event_hub`` recognizes an event *detail* page (a title plus body markers
    such as 积分/奖励) and this frame is the *grid*, so it answers ``recognized=False`` and
    the label reaches no consumer.

    The cost was concrete.  ``ALLIANCE_MOBILIZATION``, ``CANYON_CLASH`` and
    ``ARMAMENT_FACTORY_EVENT`` are registered activities that appear **only** on this
    strip, never as a grid row, so ``_append_scheduled_activities`` bound them
    ``calendar_observation=None`` permanently and ``observation_ticket`` priced them on
    evidence that did not exist: 6 of 20 ``SCHEDULED_*`` goals had a calendar row, and the
    14 without one were exactly the 14 registered activities absent from the grid.  The
    mapping was never missing -- ``event_goal.event_id_for_label`` resolves all of these
    labels -- so this is a reader that was absent, not a resolver that was wrong.

    A whole frame is still not enough for the strip.  On that same frame the whole-frame
    pass returns 联盟总动员 and **no 峡谷会战 at all**, while cropping to
    ``ACTIVITY_STRIP_ROI`` returns both (0.999 / 0.941).  So a caller that owns the frame
    should crop first (``strip_tokens_from_crop``) and pass the result here with
    ``crop_top_px``; a caller that only has whole-frame tokens passes them unchanged and
    gets whatever the whole frame can see, which is fewer entries and never more.

    What a strip row is allowed to say, and what it may not:

    * it proves an activity is **advertised right now, on this screen** -- that is a
      genuine observation, and it is what ``required_observation`` asks for;
    * it carries **no window**.  ``start``/``end`` stay ``None`` because the strip prints no
      dates; a preview must never become a battle clock, which is the rule
      ``read_event_calendar`` already follows for grid previews;
    * a label is reported **only** if the registry already knows it.  An unmapped label is
      skipped rather than given an invented id -- otherwise this reader would manufacture
      exactly the placeholder ids the project has been removing.

    Every ``tap_norm`` is the current frame's own geometry and expires with these tokens.
    """
    result: dict[str, Any] = {
        "kind": "ACTIVITY_STRIP", "recognized": False, "entries": [],
        "source": "CURRENT_FRAME_OCR" if already_in_frame_coordinates else "CURRENT_FRAME_OCR",
    }
    if crop_top_px or crop_height_px:
        rebased = strip_tokens_from_crop(
            tokens, frame_size=frame_size, crop_top_px=crop_top_px,
            crop_height_px=crop_height_px or 1,
        )
        # The crop reader is the geometry authority; hand its rebased rows to the same
        # classification below so there is one place that decides what a strip row means.
        # A crop cannot contain the 常规活动 heading -- the ROI starts below it -- so the
        # page identity has to be asserted by the caller that saw the whole frame.  When
        # the caller says nothing, the answer is the honest one: not established, no rows.
        return _strip_entries_from_rows(
            rebased.get("rows") or [], frame_size=frame_size,
            source="CURRENT_FRAME_OCR_CROP",
            heading_found=True if heading_found is None else heading_found,
        )

    width, height = frame_size or (0, 0)
    if width <= 0 or height <= 0:
        return {**result, "reason": "NO_FRAME_GEOMETRY"}
    materialized = [t for t in tokens if str(getattr(t, "text", "") or "").strip()]
    if not materialized:
        return {**result, "reason": "NO_TOKENS"}

    rows: list[dict[str, Any]] = []
    for token in materialized:
        label = re.sub(r"\s+", "", str(getattr(token, "text", "") or ""))
        points = _box(token)
        if not label or not points or not all(math.isfinite(v) for p in points for v in p):
            continue
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        top, bottom = min(p[1] for p in points), max(p[1] for p in points)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            continue
        confidence = float(getattr(token, "confidence", 0.0) or 0.0)
        if not math.isfinite(confidence) or confidence < 0.9:
            # The strip is a dense row of small labels next to a large page clock; a low
            # score here is far more likely to be a fragment of the clock than an activity.
            continue
        rows.append({"label": label, "left": left, "right": right, "top": top,
                     "bottom": bottom, "x": (left + right) / 2, "y": (top + bottom) / 2,
                     "height": bottom - top, "confidence": confidence})

    headings = [r for r in rows if r["label"] == "常规活动"
                and r["height"] >= height * 0.02 and r["y"] <= height * 0.12]
    if len(headings) != 1:
        return {**result, "reason": "NO_UNAMBIGUOUS_LARGE_TOP_HEADING"}
    heading = headings[0]

    return _strip_entries_from_rows(
        rows, frame_size=frame_size, source="CURRENT_FRAME_OCR",
        heading_found=heading_found,
    )


def _strip_entries_from_rows(
    rows: list[dict[str, Any]], *, frame_size: tuple[int, int] | None,
    source: str, heading_found: bool | None = None,
) -> dict[str, Any]:
    """Turn measured label rows into strip entries.  One judge, two ways in.

    Both the whole-frame and the cropped path land here, so "what counts as a strip row"
    is decided exactly once.  Two callers with two copies of this rule would eventually
    disagree about the same frame, which is the failure the project has already paid for
    on the 快捷面板 section list (see ``QUICK_PANEL_SECTIONS``).
    """
    result: dict[str, Any] = {
        "kind": "ACTIVITY_STRIP", "recognized": False, "entries": [], "source": source,
    }
    width, height = frame_size or (0, 0)
    if width <= 0 or height <= 0:
        return {**result, "reason": "NO_FRAME_GEOMETRY"}

    if heading_found is False:
        # The caller already knows the page heading was absent (a crop, which excludes it).
        # Without it the band is just a row of Chinese text at a particular height.
        return {**result, "reason": "NO_PAGE_HEADING_FOR_STRIP"}
    if heading_found is None:
        headings = [r for r in rows if r["label"] == "常规活动"
                    and r["height"] >= height * 0.02 and r["y"] <= height * 0.12]
        if len(headings) != 1:
            return {**result, "reason": "NO_UNAMBIGUOUS_LARGE_TOP_HEADING"}
        floor = headings[0]["bottom"]
    else:
        # A crop excludes the page heading by construction, so the caller has already
        # established the page identity on the whole frame; the crop's own top edge is
        # then the floor.  ``heading_found=True`` asserts that, and is not a default:
        # assuming it would let any dense row of registered labels be read as a strip.
        floor = height * ACTIVITY_STRIP_BAND[0] * 0.999

    band_top, band_bottom = ACTIVITY_STRIP_BAND
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda r: r["x"]):
        if row["label"] == "常规活动" or not (floor < row["y"] < height * band_bottom):
            continue
        if row["y"] < height * band_top:
            continue
        # A strip label is a title, not body text.  The resolver is the filter: a label the
        # registry has never heard of is skipped, so this reader cannot invent an id.
        event_id = event_goal.event_id_for_label(row["label"])
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        entries.append({
            "event_id": event_id,
            "display_name": row["label"],
            "title_confidence": round(row["confidence"], 6),
            "title_registered": True,
            "tap_norm": [round(row["x"] / width, 5), round(row["y"] / height, 5)],
            # A strip row advertises; it does not schedule.
            "start": None,
            "end": None,
            "preview_only": True,
            "source": source,
        })
    if not entries:
        return {**result, "reason": "NO_REGISTERED_ACTIVITY_ON_STRIP"}
    return {
        **result, "recognized": True, "reason": "LABELLED_ACTIVITY_ABOVE_CALENDAR_GRID",
        "entries": entries,
    }


def read_regular_event_hub(
    tokens: Iterable[Any], *, frame_size: tuple[int, int] | None,
) -> dict[str, Any]:
    """Recognize the regular-event shell separately from a calendar grid/detail.

    The selected event may have no printed date range. A large top heading, a tab above
    a distinct event title, and the event's body text establish the shell. One observed
    tab is enough for page identity, but at least two distinct aligned tabs are needed
    to authorize a horizontal swipe. All action geometry expires with these OCR tokens.
    """
    result: dict[str, Any] = {
        "kind": "REGULAR_EVENT_HUB", "recognized": False,
        "calendar_tab_visible": False, "calendar_tab_tap_norm": None,
        "scroll_to_start_norm": None, "tab_signature": "",
        "tab_positions_norm": {},
        "tabstrip_roi_norm": None, "source": "CURRENT_FRAME_OCR",
    }
    width, height = frame_size or (0, 0)
    if width <= 0 or height <= 0:
        return {**result, "reason": "NO_FRAME_GEOMETRY"}
    rows = []
    for token in tokens:
        label = re.sub(r"\s+", "", str(getattr(token, "text", "") or ""))
        points = _box(token)
        if not label or not points or not all(math.isfinite(v) for p in points for v in p):
            continue
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        top, bottom = min(p[1] for p in points), max(p[1] for p in points)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            continue
        confidence = float(getattr(token, "confidence", 0.0) or 0.0)
        if not math.isfinite(confidence) or confidence < 0.65:
            continue
        rows.append({"label": label, "left": left, "right": right, "top": top,
                     "bottom": bottom, "x": (left + right) / 2, "y": (top + bottom) / 2,
                     "height": bottom - top, "confidence": confidence})
    headings = [r for r in rows if r["label"] == "常规活动"
                and r["height"] >= height * 0.02 and r["y"] <= height * 0.12]
    if len(headings) != 1:
        return {**result, "reason": "NO_UNAMBIGUOUS_LARGE_TOP_HEADING"}
    heading = headings[0]
    def navigation_label(label: str) -> bool:
        # A ticking timer or score is body state, not another activity tab.
        return (_candidate_title(label) and not re.search(r"[\d:：/%+,.]", label)
                and not any(word in label for word in ("积分", "排名", "次数", "阶段", "满级", "已完成")))

    titles = sorted((r for r in rows if navigation_label(r["label"])
                     and r["top"] > heading["bottom"] + heading["height"]
                     and r["height"] >= max(height * 0.02, heading["height"] * 0.9)
                     and r["y"] <= height * 0.5), key=lambda r: r["y"])
    body_markers = ("积分", "排名", "奖励", "可接次数", "已完成", "进行中",
                    "活动时间", "剩余", "阶段", "前往", "任务")
    for title in titles:
        possible_tabs = [r for r in rows
                         if r["label"] in ("日历", "活动日历") or navigation_label(r["label"])]
        possible_tabs = [r for r in possible_tabs
                         if r["top"] > heading["bottom"]
                         and r["bottom"] < title["top"]
                         and height * 0.01 <= r["height"] <= heading["height"] * 1.1]
        # Use the densest current horizontal band, never a historical row pitch.
        bands = [[r for r in possible_tabs
                  if abs(r["y"] - anchor["y"]) <= max(r["height"], anchor["height"]) * 0.8]
                 for anchor in possible_tabs]
        tabs = max(bands, key=lambda band: (len({r["label"] for r in band}),
                                           sum(r["confidence"] for r in band)), default=[])
        unique_tabs = []
        for row in sorted(tabs, key=lambda r: r["x"]):
            if not any(row["label"] == prev["label"]
                       and abs(row["x"] - prev["x"]) <= row["height"] for prev in unique_tabs):
                unique_tabs.append(row)
        body = [r for r in rows if r["top"] >= title["bottom"]
                and any(marker in r["label"] for marker in body_markers)]
        if not body:
            continue
        if not tabs and not event_goal.event_id_for_label(title["label"]):
            continue
        tabs = unique_tabs
        signature_rows = [
            f"{r['label']}:{r['left']/width:.5f},{r['top']/height:.5f},"
            f"{r['right']/width:.5f},{r['bottom']/height:.5f}" for r in tabs
        ]
        roi_top = heading["bottom"] + heading["height"] * 0.15
        roi_bottom = title["top"] - title["height"] * 0.15
        if roi_bottom <= roi_top:
            continue
        calendar_tabs = [r for r in tabs if r["label"] in ("日历", "活动日历")]
        calendar = calendar_tabs[0] if len(calendar_tabs) == 1 else None
        result.update({
            "recognized": True, "reason": "CURRENT_HEADING_TAB_AND_EVENT_BODY",
            "display_name": title["label"], "event_id": _event_id(title["label"]),
            "calendar_tab_visible": bool(calendar_tabs),
            "calendar_tab_tap_norm": ([round(calendar["x"] / width, 5),
                                       round(calendar["y"] / height, 5)] if calendar else None),
            "tab_signature": "|".join(signature_rows),
            "tab_positions_norm": {
                r["label"]: [round(r["x"] / width, 5), round(r["y"] / height, 5)]
                for r in tabs if sum(other["label"] == r["label"] for other in tabs) == 1
            },
            "tabstrip_roi_norm": {"x_norm": 0.0, "y_norm": round(roi_top / height, 5),
                                  "w_norm": 1.0, "h_norm": round((roi_bottom - roi_top) / height, 5)},
            "tabs": [{"label": r["label"], "confidence": r["confidence"]} for r in tabs],
            "body_evidence": [r["label"] for r in body],
        })
        # A visible calendar is directly tappable; don't also authorize an unnecessary swipe.
        if not calendar_tabs and len({r["label"] for r in tabs}) >= 2:
            left, right = min(r["left"] for r in tabs), max(r["right"] for r in tabs)
            tab_height = max(r["height"] for r in tabs)
            margin = max(tab_height * 0.8, (right - left) * 0.12)
            start, end = left + margin, right - margin
            y = sum(r["y"] for r in tabs) / len(tabs)
            if end - start >= tab_height * 2 and roi_top < y < roi_bottom:
                result["scroll_to_start_norm"] = [round(start / width, 5), round(y / height, 5),
                                                  round(end / width, 5), round(y / height, 5)]
        return result
    return {**result, "reason": "EVENT_BODY_OR_TAB_STRUCTURE_MISSING"}


def read_event_calendar(
    tokens: Iterable[Any],
    *,
    frame_size: tuple[int, int] | None,
    frame_path: Path | str | None = None,
    source: str = "LIVE_CLIENT_OCR",
) -> dict[str, Any]:
    """Read visible calendar entries when the frame has calendar structure.

    Identification requires the regular-events heading, a horizontal row of multiple date
    labels, and at least one event-like title. Event bars are associated with visible date
    columns from their current screenshot geometry; no row pitch, fixed event count, or stored
    pixel coordinate is assumed. The OCR-only classifier can identify a grid structurally; the
    production refresh passes ``frame_path`` to separate clickable bars from section headings.
    """
    materialized = [token for token in tokens if str(getattr(token, "text", "") or "").strip()]
    if not materialized:
        return {"recognized": False, "source": source}
    width, height = frame_size or (0, 0)
    texts = [(token, str(token.text).strip()) for token in materialized]
    headings = [
        token for token, label in texts
        if label == "常规活动" and height > 0 and _height(token) / height >= 0.02
    ]
    if not headings:
        return {"recognized": False, "source": source}

    date_tokens = _calendar_date_rows(materialized, frame_size)
    if not date_tokens:
        return {"recognized": False, "source": source}
    anchors_y = max(_centre(token)[1] for token, _ in date_tokens if _centre(token))
    event_tokens: list[tuple[Any, str, bool, tuple[float, float] | None]] = []
    for token, label in texts:
        centre = _centre(token)
        if centre is None or centre[1] <= anchors_y + max(8.0, height * 0.01):
            continue
        if _known_title(label):
            bar = _event_bar_geometry(frame_path, token) if frame_path is not None else None
            if frame_path is None or bar is not None:
                event_tokens.append((token, label, True, bar))
        elif _candidate_title(label):
            # Unknown labels stay candidate observations. A current-frame bar match distinguishes
            # an actionable calendar row from a section heading that happens to repeat its name.
            bar = _event_bar_geometry(frame_path, token) if frame_path is not None else None
            if frame_path is None or bar is not None:
                event_tokens.append((token, label, False, bar))

    # Distinct dates, not OCR fragments of one date, establish a calendar grid.
    distinct_dates = {re.sub(r"\s+", "", label) for _, label in date_tokens}
    if len(distinct_dates) < 2 or not event_tokens:
        return {"recognized": False, "source": source}

    anchors = [(token, label, _centre(token)) for token, label in date_tokens]
    anchors = [(token, label, centre) for token, label, centre in anchors if centre]
    weekdays = [
        (token, str(getattr(token, "text", "") or "").strip(), _centre(token))
        for token in materialized
        if _WEEKDAY_RE.fullmatch(str(getattr(token, "text", "") or "").strip())
    ]
    date_columns = []
    for token, label, centre in anchors:
        weekday = min(
            (row for row in weekdays if row[2] and row[2][1] <= centre[1]
             and centre[1] - row[2][1] <= max(36.0, height * 0.045)),
            key=lambda row: abs(row[2][0] - centre[0]),
            default=None,
        )
        date_columns.append({
            "date_raw": label,
            "weekday_raw": weekday[1] if weekday else None,
            "center_x_norm": round(centre[0] / width, 5) if width else None,
        })
    entries: list[dict[str, Any]] = []
    detail_text = " ".join(label for _, label in texts)
    date_range = _DATE_RANGE_RE.search(detail_text)

    anchor_centres = [row[2][0] for row in anchors]
    pitches = [b - a for a, b in zip(anchor_centres, anchor_centres[1:]) if b > a]
    nominal_pitch = sorted(pitches)[len(pitches) // 2] if pitches else width / max(1, len(anchors))
    boundaries = []
    for index, (_, date_label, centre) in enumerate(anchors):
        left = (anchors[index - 1][2][0] + centre[0]) / 2 if index else centre[0] - nominal_pitch / 2
        right = (centre[0] + anchors[index + 1][2][0]) / 2 if index + 1 < len(anchors) else centre[0] + nominal_pitch / 2
        boundaries.append((date_label, left, right))

    for token, label, known, bar in event_tokens:
        centre = _centre(token)
        nearest = min(anchors, key=lambda row: abs(row[2][0] - centre[0]), default=None) if centre else None
        visible_dates: list[str] = []
        if bar is not None:
            bar_left, bar_right = bar
            visible_dates = [
                date_label for date_label, left, right in boundaries
                if min(bar_right, right) - max(bar_left, left) >= nominal_pitch * 0.20
            ]
        if not visible_dates and nearest is not None:
            visible_dates = [nearest[1]]
        confidence = float(getattr(token, "confidence", 0.0) or 0.0)
        event_id = _event_id(label)
        # Grid rows carry only data printed on that row. A detail popup may sit over the grid;
        # its time range and countdown belong to its own event-detail record, never every row.
        row_range = _DATE_RANGE_RE.search(label)
        row_start = row_range.group("start").strip() if row_range else None
        row_end = row_range.group("end").strip() if row_range else None
        row_countdown_match = _COUNTDOWN_RE.search(label)
        row_countdown = re.sub(r"\s+", " ", row_countdown_match.group(1)).strip() if row_countdown_match else None
        row_state = "UNKNOWN"
        for marker, value in (
            (("已结束", "活动结束", "时间已到"), "EXPIRED"),
            (("进行中", "活动开启", "已开启", "活动开始"), "OPEN"),
            (("报名中", "可报名"), "REGISTRATION_OPEN"),
            (("即将开启", "未开启", "距开始"), "SCHEDULED_NOT_OPEN"),
        ):
            if any(word in label for word in marker):
                row_state = value
                break
        calendar_date_raw = visible_dates[0] if visible_dates else (nearest[1] if nearest else None)
        calendar_end_date_raw = visible_dates[-1] if visible_dates else calendar_date_raw
        entries.append({
            "event_id": event_id,
            "display_name": label,
            "title_confidence": confidence,
            "title_registered": known,
            "icon_identity": None,
            "icon_observed": False,
            "calendar_date_raw": calendar_date_raw,
            "calendar_end_date_raw": calendar_end_date_raw,
            "calendar_dates_raw": visible_dates,
            "bar_bounds_norm": ([round(bar[0] / width, 5), round(bar[1] / width, 5)]
                                 if bar is not None and width > 0 else None),
            "occurrence_key": f"{event_id}|{calendar_date_raw or 'UNKNOWN_DATE'}|{calendar_end_date_raw or 'UNKNOWN_DATE'}",
            "tap_norm": ([round(centre[0] / width, 5), round(centre[1] / height, 5)]
                         if centre and width > 0 and height > 0 else None),
            "title_box": [list(point) for point in _box(token)] or None,
            # These are only populated when the current OCR explicitly prints a range.
            # A day column alone does not imply an opening time or a battle time.
            "preview_start_raw": row_start,
            "preview_end_raw": row_end,
            "registration_start_raw": None,
            "registration_end_raw": None,
            "battle_start_raw": None,
            "battle_end_raw": None,
            "current_open_state": row_state,
            "countdown_raw": row_countdown,
            "source": source,
        })

    today_tokens = [token for token, label in texts if any(marker in label for marker in ("今天", "今日", "当前日期"))]
    game_datetime_token = next((label for _, label in texts if _GAME_DATETIME_RE.search(label)), None)
    normalized_game_datetime = None
    current_game_date_raw = None
    if today_tokens and anchors:
        today_centre = _centre(today_tokens[0])
        nearest_today = min(anchors, key=lambda row: abs(row[2][0] - today_centre[0]), default=None)
        current_game_date_raw = nearest_today[1] if nearest_today else None
    elif game_datetime_token:
        match = _GAME_DATETIME_RE.search(game_datetime_token)
        normalized_game_datetime = re.sub(r"(\d{1,2})\s*(\d{1,2}:\d{2}:\d{2})$", r"\1 \2", match.group(0)) if match else None
        current_game_date_raw = _GAME_DATE_PREFIX_RE.search(match.group(0)).group(0) if match and _GAME_DATE_PREFIX_RE.search(match.group(0)) else None

    return {
        "kind": "CALENDAR_GRID",
        "recognized": True,
        "source": source,
        "confidence": min(
            max(float(getattr(token, "confidence", 0.0) or 0.0) for token in headings),
            max(entry["title_confidence"] for entry in entries),
        ),
        "visible_dates_raw": [label for _, label in date_tokens],
        "date_columns": date_columns,
        "current_game_date_raw": current_game_date_raw,
        "current_game_datetime_raw": normalized_game_datetime or game_datetime_token,
        "time_zone": None,
        "entries": entries,
        "entry_count": len(entries),
        "details_visible": bool(date_range or _COUNTDOWN_RE.search(detail_text) or "活动详情" in detail_text),
        "source_evidence": {
            "heading": "常规活动",
            "date_anchor_count": len(distinct_dates),
            "frame_size": [width, height] if width and height else None,
        },
    }


def read_event_detail(
    tokens: Iterable[Any],
    *,
    event_label: str | None,
    frame_size: tuple[int, int] | None = None,
    source: str = "LIVE_CLIENT_OCR",
) -> dict[str, Any]:
    """Read only explicitly labelled time layers from an event detail view.

    A bare date range remains an activity/calendar preview. It is never promoted to a battle
    session or role reservation. Details are attached to a specific event only when its title is
    identified and the frame carries detail or timing language.
    """
    rows = [(token, str(getattr(token, "text", "") or "").strip()) for token in tokens]
    all_text = " ".join(text for _, text in rows)
    date_range = _DATE_RANGE_RE.search(all_text)
    calendar_score_panel = (
        "常规活动" in all_text
        and date_range is not None
        and any(marker in all_text for marker in ("我的积分", "目标积分", "本期英雄", "阶段"))
    )
    # Ordinary live event panels often show ``常规活动`` + an event title + ``距开始``.
    # That is the active-event input used by EVENT_MINIMUM_GUARANTEE, not a calendar detail.
    # A score card is a discovery observation only when it carries both the heading and date
    # range. Elsewhere, explicit detail/time labels can establish a detail; a bare countdown
    # never changes the event execution path.
    explicit_calendar_detail = (
        "活动详情" in all_text
        or (
            date_range is not None
            and any(marker in all_text for marker in (
                "活动时间", "开始时间", "结束时间", "报名时间", "战斗时间", "开放时间",
            ))
        )
        or (
            date_range is not None and "前往" in all_text
            and any(_candidate_title(text) for _, text in rows)
        )
    )
    if not calendar_score_panel and not explicit_calendar_detail:
        return {"kind": "EVENT_DETAIL", "recognized": False, "source": source}
    label = ""
    if frame_size and frame_size[1] > 0:
        # On a detail card the grid remains visible behind the modal. OCR may read a lower
        # calendar row more clearly than the title in the card, so the globally largest title
        # is not a safe identity. Prefer the candidate immediately above the printed date range
        # in the same card; this uses the current frame's text layout, not a stored coordinate.
        range_tokens = [
            (token, _centre(token)) for token, text in rows
            if _DATE_RANGE_RE.search(text) is not None and _centre(token) is not None
        ]
        if range_tokens:
            range_token, range_centre = min(
                range_tokens, key=lambda item: item[1][1]  # type: ignore[index]
            )
            range_box = _box(range_token)
            range_left = min(point[0] for point in range_box) if range_box else 0.0
            range_right = max(point[0] for point in range_box) if range_box else float(frame_size[0])
            title_tokens = [
                token for token, text in rows
                if _candidate_title(text)
                and _height(token) / frame_size[1] >= 0.02
                and (_centre(token) is not None)
                and 0 < range_centre[1] - _centre(token)[1] <= frame_size[1] * 0.12
                and range_left - frame_size[0] * 0.05 <= _centre(token)[0]
                <= range_right + frame_size[0] * 0.05
            ]
            if title_tokens:
                label = min(
                    title_tokens,
                    key=lambda token: range_centre[1] - _centre(token)[1],  # type: ignore[index]
                ).text.strip()
    if not label:
        label = str(event_label or "").strip()
    if not label and frame_size and frame_size[1] > 0:
        title_tokens = [
            token for token, text in rows
            if _candidate_title(text)
            and _height(token) / frame_size[1] >= 0.025
        ]
        if title_tokens:
            label = max(title_tokens, key=_height).text.strip()
    if not label:
        return {"kind": "EVENT_DETAIL", "recognized": False, "source": source}

    values: dict[str, Any] = {
        "kind": "EVENT_DETAIL",
        "recognized": True,
        "event_id": _event_id(label),
        "display_name": label,
        "activity_open_start_raw": None,
        "activity_open_end_raw": None,
        "registration_start_raw": None,
        "registration_end_raw": None,
        "battle_start_raw": None,
        "battle_end_raw": None,
        "preview_start_raw": None,
        "preview_end_raw": None,
        "countdown_raw": None,
        "unlabeled_timer_raw": None,
        "stage_timer_raw": None,
        "stage_label": None,
        "current_open_state": "UNKNOWN",
        "registration_entry_visible": any(word in all_text for word in ("报名", "预约")),
        "preparation_entry_visible": "准备" in all_text,
        "participation_entry_visible": any(word in all_text for word in ("参与", "前往")),
        "reward_entry_visible": any(word in all_text for word in ("奖励", "领取")),
        "time_zone": None,
        "source": source,
    }
    for _, text in rows:
        span = _DATE_RANGE_RE.search(text)
        if span:
            pair = (span.group("start").strip(), span.group("end").strip())
            if "报名" in text or "预约" in text:
                values["registration_start_raw"], values["registration_end_raw"] = pair
            elif "战斗" in text or "对战" in text or "场次" in text:
                values["battle_start_raw"], values["battle_end_raw"] = pair
            elif any(word in text for word in ("活动时间", "活动开始", "活动结束", "开放时间")):
                values["activity_open_start_raw"], values["activity_open_end_raw"] = pair
            else:
                values["preview_start_raw"], values["preview_end_raw"] = pair
        if re.search(r"第\s*[一二三四五六七八九十\d]+\s*阶段", text):
            values["stage_label"] = text
            stage_timer = re.search(r"\d{1,2}:\d{2}:\d{2}", text)
            if stage_timer:
                values["stage_timer_raw"] = stage_timer.group(0)
        elif re.fullmatch(r"\d+\s*天\s*\d{1,2}:\d{2}:\d{2}", text):
            # The client draws a clock icon beside this value, but OCR supplies no text label.
            # Preserve it verbatim without treating it as an activity-start countdown.
            if values["unlabeled_timer_raw"] is None:
                values["unlabeled_timer_raw"] = re.sub(r"\s+", " ", text).strip()
        elif re.fullmatch(r"\(?\s*\d{1,2}:\d{2}:\d{2}\s*\)?", text):
            timer = re.sub(r"[()]", "", text).strip()
            if values["stage_label"]:
                values["stage_timer_raw"] = timer
            elif values["unlabeled_timer_raw"] is None:
                values["unlabeled_timer_raw"] = timer
    countdown = _COUNTDOWN_RE.search(all_text)
    if countdown:
        values["countdown_raw"] = re.sub(r"\s+", " ", countdown.group(1)).strip()
    if any(word in all_text for word in ("进行中", "活动开启", "已开启")):
        values["current_open_state"] = "OPEN"
    elif any(word in all_text for word in ("已结束", "活动结束")):
        values["current_open_state"] = "EXPIRED"
    elif values["countdown_raw"] or "未开启" in all_text or "即将开启" in all_text:
        values["current_open_state"] = "SCHEDULED_NOT_OPEN"
    values["time_zone_source"] = "EXPLICIT_CLIENT_LABEL" if any(
        word in all_text for word in ("服务器时间", "北京时间", "UTC", "GMT")
    ) else "UNKNOWN"
    return values
