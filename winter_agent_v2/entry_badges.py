"""Entry badges: which entry is showing a notification, read from that entry's own corner.

The operator's rule for this layer is one sentence -- a red dot must be bound to a concrete entry or
task row -- and the first measurement campaign showed why it matters.  Counting red pixels in a box
around an entry attributed the 英雄 tab's dot to 探险 (the window reached into the next tab), reported
"no badge" for the mail entry on a frame whose badge is plainly drawn (the window was written
``(x0, y0, x1, y1)`` and unpacked ``(x0, x1, y0, y1)``, so it scanned an empty range), and produced a
wrong inference from a right number (the 联盟 count badge is present in 26 of 26 sampled frames, which
looks constant but is simply never zero).

So this module reads the table at ``knowledge/ui/entry_badges.json`` -- measured, per entry, with the
frames it was measured on -- and refuses to answer for any entry that is not in it.  Three states,
because two cannot express the truth:

    PRESENT   a red blob of badge size sits at this entry's own corner
    ABSENT    the entry is on screen, its corner is visible, and no such blob is there
    UNKNOWN   the entry is not on this page, its frame was not given, or its badge is still only
              suspected of being artwork -- never "no red dot"

The last one is the operator's own requirement (§一: a row the panel has not scrolled to is UNKNOWN,
not ABSENT; §五: UNKNOWN must be observed again, never treated as "nothing there").
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TABLE_PATH = ROOT / "knowledge/ui/entry_badges.json"

PRESENT = "PRESENT"
ABSENT = "ABSENT"
UNKNOWN = "UNKNOWN"

#: The red family the 快捷面板 row reader already uses (``ocr.QUICK_PANEL_BADGE_RED_MIN`` is its
#: brightness floor).  Shared on purpose: two different definitions of "red" in one project is how
#: two layers start disagreeing about the same frame.
RED_MIN = 150
RED_EXCESS = 50
#: A badge is a drawn circle, so a handful of anti-aliased pixels is not one.  Measured: the smallest
#: real badge in the campaign (英雄 tab) is 195 px, and the mail badge 276-302 px, so 40 leaves a wide
#: margin on both sides of the boundary without ever being the deciding factor.
MIN_BLOB_PX = 40

_state_cache: dict[str, Any] = {}


def table() -> dict[str, Any]:
    """The measured table, read once per process."""
    if "table" not in _state_cache:
        _state_cache["table"] = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    return _state_cache["table"]


def entries() -> dict[str, dict[str, Any]]:
    return {str(row["entry"]): row for row in table()["entries"]}


@dataclass(frozen=True)
class EntryBadge:
    """One entry's notification state, with the evidence that produced it."""

    entry: str
    page: str
    state: str
    observed_at: str = ""
    goal: str | None = None
    task_state: str = ""
    pixels: int = 0
    box_norm: tuple[float, float, float, float] | None = None
    reason: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "page": self.page,
            "state": self.state,
            "observed_at": self.observed_at,
            "goal": self.goal,
            "task_state": self.task_state,
            "pixels": self.pixels,
            "box_norm": self.box_norm,
            "reason": self.reason,
        }


def _is_red(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return r >= RED_MIN and r - g >= RED_EXCESS and r - b >= RED_EXCESS


def _largest_blob(image, box: tuple[int, int, int, int]) -> tuple[int, tuple[int, int, int, int]]:
    """The biggest red blob in ``box`` and its pixel count, or ``(0, (0, 0, 0, 0))``."""
    x0, y0, x1, y1 = box
    seen: set[tuple[int, int]] = set()
    best = (0, (0, 0, 0, 0))
    for cy in range(y0, y1):
        for cx in range(x0, x1):
            if (cx, cy) in seen or not _is_red(image.getpixel((cx, cy))):
                continue
            queue = deque([(cx, cy)])
            seen.add((cx, cy))
            comp: list[tuple[int, int]] = []
            while queue:
                px, py = queue.popleft()
                comp.append((px, py))
                for nx, ny in ((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)):
                    if x0 <= nx < x1 and y0 <= ny < y1 and (nx, ny) not in seen and _is_red(image.getpixel((nx, ny))):
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(comp) > best[0]:
                xs = [q[0] for q in comp]
                ys = [q[1] for q in comp]
                best = (len(comp), (min(xs), min(ys), max(xs), max(ys)))
    return best


def read_entry_badges(
    frame: Path | None,
    page: str,
    *,
    observed_at: str = "",
    task_states: dict[str, str] | None = None,
) -> dict[str, EntryBadge]:
    """Every entry in the measured table, each with PRESENT / ABSENT / UNKNOWN and its reason.

    ``page`` is the page the reading belongs to, as the vision layer resolved it.  An entry whose
    page does not match is UNKNOWN -- it is simply not on this screen, and saying ABSENT would turn
    "I cannot see it" into "there is nothing there", which is the whole failure this layer exists to
    avoid.
    """
    states = task_states or {}
    answer: dict[str, EntryBadge] = {}
    image = None
    for entry, row in entries().items():
        goal = row.get("goal")
        task_state = states.get(entry, "")
        entry_page = str(row.get("page", ""))
        if entry_page and entry_page != page:
            answer[entry] = EntryBadge(
                entry, page, UNKNOWN, observed_at, goal, task_state,
                reason=f"entry_is_on_{entry_page}_not_{page}",
            )
            continue
        if row.get("status") == "SUSPECT_ARTWORK":
            answer[entry] = EntryBadge(
                entry, page, UNKNOWN, observed_at, goal, task_state,
                reason="badge_geometry_never_varies_so_it_may_be_artwork",
            )
            continue
        if frame is None:
            answer[entry] = EntryBadge(entry, page, UNKNOWN, observed_at, goal, task_state, reason="no_frame_given")
            continue
        if image is None:
            from PIL import Image  # imported here: this module is also used by replay tests

            image = Image.open(frame).convert("RGB")
        width, height = image.size
        wx0, wy0, wx1, wy1 = (float(v) for v in row["search_window_norm"])
        box = (
            int(max(0.0, wx0) * width),
            int(max(0.0, wy0) * height),
            int(min(1.0, wx1) * width),
            int(min(1.0, wy1) * height),
        )
        pixels, blob = _largest_blob(image, box)
        answer[entry] = EntryBadge(
            entry,
            page,
            PRESENT if pixels >= MIN_BLOB_PX else ABSENT,
            observed_at,
            goal,
            task_state,
            pixels=pixels,
            box_norm=(
                (blob[0] / width, blob[1] / height, blob[2] / width, blob[3] / height) if pixels else None
            ),
            reason="" if pixels >= MIN_BLOB_PX else (
                f"no_red_blob_of_badge_size_in_x{row['search_window_norm'][0]:.3f}-"
                f"{row['search_window_norm'][2]:.3f}_y{row['search_window_norm'][1]:.3f}-"
                f"{row['search_window_norm'][3]:.3f}" + (f"_largest_was_{pixels}px" if pixels else "")
            ),
        )
    return answer


#: The 快捷面板's own rows, which already carry a badge reading from ``read_quick_panel``.  Kept as
#: a mapping so a row's entry name and its goal are stated once, here, rather than inferred.
#:
#: Every value is a **goal id the goal layer uses**, not a route domain and not a label.  Measured
#: 2026-09-23 over the 12 panel-open frames whose ledger carries these rows
#: (``tools/measure_panel_row_badges.py``): the 科技研究 row is the single most common dotted row
#: (PRESENT in 9 of those 12, and the only row that ever discriminates -- ``>=1 PRESENT`` while
#: another row reads ABSENT in 9 frames), and its binding used to be the string ``"RESEARCH"``,
#: which is the *route domain* ``run_live.py --goal`` accepts, not a goal id.  ``GOAL_ROUTES``
#: maps the goal to that domain (``KEEP_RESEARCH_PRODUCTIVE -> RESEARCH``), so a consumer asking
#: the goal layer "which goal is the client pointing at" could never match it: the majority of the
#: panel's dot signal was silently unattributable.  The same trap is why the vocabulary here is
#: asserted against ``goal_library`` in ``tests/test_red_dot_priority.py`` rather than eyeballed.
QUICK_PANEL_ROW_GOALS = {
    "SHIELD_CAMP": "SHIELD_CAMP_TRAINING",
    "LANCER_CAMP": "LANCER_CAMP_TRAINING",
    "MARKSMAN_CAMP": "MARKSMAN_CAMP_TRAINING",
    "RESEARCH": "KEEP_RESEARCH_PRODUCTIVE",
    "ALLIANCE_DONATION": "ALLIANCE_ROUTINE",
    # 英雄招募 names a goal the board does not have: there is no route domain for it, the goal
    # layer cannot emit it, and ``DAILY_HERO_RECRUIT`` is documented as having no live-loop
    # verifier (open issue #100).  Stated rather than invented -- and ``dots_pointing_at`` drops
    # it, so the row's dot points at nothing until that goal exists.
    "HERO_RECRUIT": "HERO_RECRUIT",
    "MY_REWARDS": "DAILY_ACTIVITY_TARGET",
}


def dot_varies(entry: str) -> bool:
    """Whether this entry's badge was *measured to come and go* -- the licence to rank with it.

    Read from the table's ``dot_variability`` section, which carries the counts and the two tools
    that reproduce them from ``learning/episodes.jsonl``.  The rule is the operator's §二② read
    strictly: ``P(work) != P(work|dot)`` is what makes a dot a signal, so a badge observed only
    ever present (the 每日/联盟 count badges, measured 26 of 26) cannot decide an order -- a signal
    that is always on is a constant, and ranking on it is ranking on nothing.  One observed only
    ever absent is not a signal either; it simply never fires.

    An entry with **no** variability record answers False, which is the same direction as
    ``read_entry_badges`` refusing to read an entry that is not in the table: a new row does not
    become a priority signal by being added to a mapping.

    Never raises.  This answer is consulted on the ranking path, where an unreadable table must
    cost a priority hint and not a step of the run -- ``read_entry_badges`` may raise, because
    there the caller is already an observation that can be left empty, and this is not.
    """
    try:
        record = (table().get("dot_variability") or {}).get("entries") or {}
        row = record.get(str(entry))
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not isinstance(row, dict):
        return False
    return bool(row.get("varies"))


#: The goals whose **existence** is decided by their own entry's badge, and the entries that decide
#: it.  Operator directive 2026-09-23 ("红点对邮件和联盟宝箱不是加分项，而是有没有任务的准入信号"):
#: for these two, ABSENT means the goal does not exist this cycle -- it is not ranked lower, it is
#: not on the board -- and UNKNOWN is not permission to go and look (§四: 不能为了消除 UNKNOWN
#: 每轮打开页面).
#:
#: Why an entry and not a page reading: both entries are drawn on screens the loop already stands
#: on (邮件的 in HOME, 联盟宝箱 on the alliance page's own tile grid), so the signal costs no step.
#: ``BTN_OPEN_MAIL`` and ``TILE_ALLIANCE_GIFTS`` are both measured in the table; a goal whose entry
#: is not in the table cannot be gated by it, which is the honest direction -- see :func:`entry_gate`.
#:
#: The 联盟 one is the **tile's own** badge, not the alliance entry's.  That distinction is the
#: operator's §三 and it is not cosmetic: the alliance page's badges sit on individual tiles
#: (联盟战争 / 联盟宝箱 / 联盟领地 / 联盟商店 ...), so "the alliance entry has a dot" says nothing
#: about the gift box.  Measured over the 97 production steps that entered the gifts page: the tile's
#: own badge was **ABSENT in 93 of them**, and the alliance page had reported no readable state at all
#: in 96 of them.
ENTRY_GATED_GOALS: dict[str, tuple[str, ...]] = {
    "MAIL_ROUTINE": ("BTN_OPEN_MAIL",),
    # The gifts goal is the 联盟宝箱 tile; ``ALLIANCE_ROUTINE`` is the goal id the goal layer emits
    # for the alliance page (``goal_library.PANEL_ROUTINES`` / ``GOAL_ROUTES``), which is why the
    # binding is on the routine rather than on a goal named after the tile.
    "ALLIANCE_ROUTINE": ("TILE_ALLIANCE_GIFTS",),
}


def entry_gate(goal_id: str, red_dots: Any) -> tuple[str, tuple[str, ...]]:
    """``(verdict, entries)`` -- may a goal that lives behind an entry exist on this frame?

    Three answers, and each is a different decision rather than a different score:

    * ``PRESENT`` -- the client drew a dot on this goal's own entry, so there is something behind it.
      The caller may emit the goal and open the page.
    * ``ABSENT`` -- the entry was **read on this screen** and carries no dot.  For a gated goal that
      is a refusal: 无红点，就没有这个 Goal.  Note what makes this safe: ``read_entry_badges`` answers
      UNKNOWN, never ABSENT, when the entry belongs to another page or when there is no frame, so an
      ABSENT here means the entry really was looked at.
    * ``UNKNOWN`` -- nothing readable.  Not permission: §四 says the answer is to re-observe, not to
      open the page in order to find out.  The caller emits nothing; HOME frames are frequent, so the
      entry is re-read for free on the next step that stands there.

    A goal with no declared entry answers UNKNOWN, which is the same direction as
    ``dots_pointing_at`` dropping an unbound entry: a goal does not become gated by being added to a
    mapping, and an ungated goal keeps whatever behaviour it had.
    """
    wanted = ENTRY_GATED_GOALS.get(str(goal_id) or "")
    if not wanted or not isinstance(red_dots, dict):
        return UNKNOWN, ()
    seen: list[str] = []
    readable = False
    for name in wanted:
        record = red_dots.get(name)
        if not isinstance(record, dict):
            continue
        state = str(record.get("state") or "")
        if state == PRESENT:
            seen.append(name)
            readable = True
        elif state == ABSENT:
            readable = True
    if seen:
        return PRESENT, tuple(seen)
    return (ABSENT if readable else UNKNOWN), ()


def dots_pointing_at(red_dots: Any) -> dict[str, tuple[str, ...]]:
    """Which goals the client is currently pointing at, by drawing a dot on their entry.

    ``{goal_id: (entry, ...)}`` -- only PRESENT dots, only entries whose badge was measured to
    vary, and only when the entry names a goal.  ABSENT contributes nothing (the client saying
    "nothing here" is not a reason to rank a goal up), UNKNOWN contributes nothing (§一: a reading
    that was never made is not evidence in either direction), and a dot that never goes away is
    not a signal at all (see ``dot_varies``).

    A binding that names no goal the board has (英雄招募 today) is dropped here rather than
    mistranslated: the whole point of the three-state layer is that a dot is bound to a concrete
    entry, and an entry bound to no goal is a gap to record, not a dot to act on.

    Never raises and never reads the frame: the input is the ledger production already wrote onto
    ``WorldState.red_dots``, so a caller in the ranking path pays nothing for it.
    """
    answer: dict[str, list[str]] = {}
    if not isinstance(red_dots, dict):
        return {}
    for entry, record in sorted(red_dots.items()):
        if not isinstance(record, dict):
            continue
        if str(record.get("state") or "") != PRESENT:
            continue
        goal = str(record.get("goal") or "")
        if not goal or not dot_varies(str(entry)):
            continue
        answer.setdefault(goal, []).append(str(entry))
    return {goal: tuple(entries) for goal, entries in answer.items()}


def quick_panel_badges(state: Any) -> dict[str, EntryBadge]:
    """The panel's rows, with UNKNOWN for every row that was not read (scrolled out, or panel shut).

    ``read_quick_panel`` returns only the rows it could read, so a row missing from that reading is
    exactly the "not scrolled to" case the operator calls out.  Reporting ABSENT for it would claim
    the client drew no dot on a row nobody looked at.
    """
    panel = getattr(state, "quick_panel", None) or {}
    open_ = bool(panel.get("open"))
    rows = {str(r.get("key")): r for r in (panel.get("rows") or [])}
    answer: dict[str, EntryBadge] = {}
    for key, goal in QUICK_PANEL_ROW_GOALS.items():
        row = rows.get(key)
        entry = f"QUICK_PANEL_ROW_{key}"
        if not open_:
            answer[entry] = EntryBadge(entry, "HOME", UNKNOWN, goal=goal, reason="quick_panel_is_closed")
            continue
        if row is None:
            answer[entry] = EntryBadge(entry, "HOME", UNKNOWN, goal=goal, reason="row_not_read_this_frame")
            continue
        badge = str(row.get("badge") or UNKNOWN)
        if badge not in (PRESENT, ABSENT):
            badge = UNKNOWN
        answer[entry] = EntryBadge(
            entry,
            "HOME",
            badge,
            goal=goal,
            task_state=str(row.get("status") or ""),
            reason="" if badge != UNKNOWN else "panel_read_did_not_settle_this_row",
        )
    return answer


def read_all(state: Any, frame: Path | None = None, *, observed_at: str = "") -> dict[str, EntryBadge]:
    """The whole ledger for one observation: measured entries plus the panel's own rows."""
    page = getattr(getattr(state, "page", None), "value", str(getattr(state, "page", "")))
    ledger = read_entry_badges(frame, page, observed_at=observed_at)
    ledger.update(quick_panel_badges(state))
    return ledger


def transitions(previous: dict[str, EntryBadge], current: dict[str, EntryBadge]) -> list[dict[str, Any]]:
    """What changed, in the terms the goal layer triggers on.

    Only real changes are reported.  An entry that stays PRESENT across frames is *not* a change, so
    it cannot be turned into a new goal every round (operator §二: the same dot seen again in
    consecutive screenshots must not re-create the same goal), and an UNKNOWN on either side is not a
    change either -- there is nothing to compare a reading that was never made against.
    """
    events = []
    for entry, now in sorted(current.items()):
        before = previous.get(entry)
        if before is None:
            continue
        if before.state == UNKNOWN or now.state == UNKNOWN:
            continue
        if before.state != now.state:
            events.append(
                {
                    "entry": entry,
                    "from": before.state,
                    "to": now.state,
                    "goal": now.goal,
                    "observed_at": now.observed_at,
                }
            )
    return events
