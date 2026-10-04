"""Truth Source Audit — every displayed state names its source, or says it does not know.

Why this exists
---------------
The operator reported a GUI cell that read ``current_role = xhw`` while the real client
was logged in as a different role.  The cause was not a stale cache: the panel printed a
**string literal** (``tools/control_panel.py``: ``text="xhw"``), next to another literal
(``● 在线``) that claimed the device was online no matter what it was doing.  A constant
that looks like an observation is worse than no value at all, because it cannot be told
apart from a measured one.

So the rule this module enforces is the operator's own ladder, and it is enforced by
`TruthAudit` refusing to return a value without a provenance record:

```
LIVE OBSERVED
  > fresh verified runtime state
  > persisted last-known state
  > expected / requested state
```

A cached or persisted value is allowed to *help recovery*.  It is not allowed to
impersonate a currently-observed one.  Anything past its freshness budget must read
``STALE`` / ``UNKNOWN`` / ``CONFLICT`` — never a confident-looking old number.

Deliberately **not** a second WorldState.  This is a read-only projection over artifacts
that already exist (runtime snapshot, episode stream, executor ledger, escalation ledger,
device lease, role probe, capability catalog).  It stores nothing; delete it and every
question is answerable again from the same files.  Same shape as ``capability_gate``.

The five questions each state must answer (operator, 2026-09-18):

1. what is the truth source?
2. when was it last confirmed?
3. what is the evidence?
4. which role / session / episode / version does it belong to?
5. is it expired right now?
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------- provenance status

LIVE_OBSERVED = "LIVE_OBSERVED"        # read off the device, with a frame behind it
FRESH_RUNTIME = "FRESH_RUNTIME"        # the running process wrote it just now
PERSISTED = "PERSISTED"                # last known value, older than its budget
REQUESTED = "REQUESTED"                # what we asked for -- not evidence it happened
EXPECTED = "EXPECTED"                  # a window we expect, with evidence of the window only
CATALOG_DERIVED = "CATALOG_DERIVED"    # derived from a maintained artifact, not a fresh read
ASSUMED = "ASSUMED"                    # a literal or a default: must be eliminated
HISTORY = "HISTORY"                    # known to be *past* -- not "was current once, unknown now"
UNKNOWN = "UNKNOWN"
STALE = "STALE"
CONFLICT = "CONFLICT"

# The operator's eight words, mapped from the precise internal statuses.  One mapping,
# in one place, so two panels cannot label the same reading differently -- and so the
# window never has to invent a word (operator §十六, 2026-09-18).
#
# ``CONFLICT`` is deliberately outside the eight: it is not a degree of belief about a
# value, it is the statement that two sources disagree, and it layers on top of whichever
# status the reading would otherwise have.
CATEGORY_OF: dict[str, str] = {
    LIVE_OBSERVED: "LIVE_OBSERVED",
    FRESH_RUNTIME: "FRESH_LAST_KNOWN",
    CATALOG_DERIVED: "FRESH_LAST_KNOWN",
    PERSISTED: "STALE",        # last known, past its freshness budget -- the operator's STALE
    STALE: "STALE",
    HISTORY: "HISTORY",
    REQUESTED: "REQUESTED",
    EXPECTED: "EXPECTED",
    ASSUMED: "EXPECTED",
    UNKNOWN: "UNKNOWN",
    CONFLICT: "CONFLICT",
}

def health_of(value: TruthValue) -> tuple[str, str]:
    """One of the operator's six words, plus the colour class it implies.

    The window's top bar must not invent its own vocabulary per cell: the operator asked
    for exactly 正常 / 工作中 / 等待 / 降级 / 未确认 / 异常, so they are derived here from the
    provenance status rather than re-guessed at each call site.
    """
    text = f"{value.value} {value.note}"
    if value.status == CONFLICT:
        return ("异常", "bad")
    if value.status in (UNKNOWN, ASSUMED):
        return ("未确认", "unknown")
    if value.status == STALE:
        return ("降级", "warn")
    if "降级" in text or "fallback" in text:
        return ("降级", "warn")
    if "等待" in text or "轮次之间" in text or "DEFER" in text:
        return ("等待", "idle")
    if any(word in text for word in ("研发中", "运行中", "真实执行", "已提交", "学习中")):
        return ("工作中", "work")
    return ("正常", "good")


# Worst-last, so a sort or a max() reads as "how much can this be trusted".
# ``ASSUMED`` sits below ``PERSISTED`` on purpose: an old measurement is a fact about the
# past, a literal is a claim about nothing.
STATUS_RANK: dict[str, int] = {
    CONFLICT: -1,      # not a low score -- an unresolved question, like TRUST_RANK[CONFLICT]
    UNKNOWN: 0,
    ASSUMED: 1,
    EXPECTED: 2,
    REQUESTED: 3,
    CATALOG_DERIVED: 4,
    # Below STALE on purpose: a stale value may still be true, a history record is known
    # to describe a past that has ended.  Neither may be printed as "current".
    HISTORY: 5,
    STALE: 6,
    PERSISTED: 7,
    FRESH_RUNTIME: 8,
    LIVE_OBSERVED: 9,
}

STATUS_ZH: dict[str, str] = {
    LIVE_OBSERVED: "真机观测",
    FRESH_RUNTIME: "运行时新鲜",
    PERSISTED: "持久化（上次已知）",
    REQUESTED: "已请求（未证实）",
    CATALOG_DERIVED: "总表推导（非真机）",
    ASSUMED: "假定值（必须消除）",
    HISTORY: "历史（已过去）",
    UNKNOWN: "未知",
    STALE: "已过期",
    CONFLICT: "冲突",
}

# A value that needs a frame behind it goes stale faster than one the runtime republishes.
FRESH_RUNTIME_SECONDS = 120.0
LIVE_OBSERVED_SECONDS = 6 * 3600.0
PERSISTED_SECONDS = 7 * 24 * 3600.0
# How long an activity record may describe "now".  Its own countdown overrides this: a
# record with 28 795 s left was already describing a closed window nine days later.  This
# is also the record's **TTL** -- the ceiling that expires it on its own -- because nothing
# in the tree ever rewrites ``learning/event_goal_state.json`` (measured 2026-10-04: the
# file was 595 h old and had no writer anywhere in ``winter_agent_v2/`` or ``tools/``).
EVENT_CURRENT_SECONDS = 6 * 3600.0


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _probe_stamp(text: str) -> str:
    """``20260916_184004`` -> an ISO stamp.  Shaped by the probe that writes it.

    The underscore matters: an earlier version tested ``isdigit()`` over the whole
    string and therefore silently produced no timestamp at all, which read as "this
    observation has no date" instead of "this observation is two days old".
    """
    digits = re.sub(r"\D", "", text or "")
    if len(digits) != 14:
        return ""
    return (f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}T"
            f"{digits[8:10]}:{digits[10:12]}:{digits[12:14]}+00:00")


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


# --------------------------------------------------- bounded tail reads and caches
#
# ``episodes.jsonl`` passed 162 MB while ``TruthAudit.__init__`` asks this module for its
# last *three* rows.  Reading the whole file to keep three measured 1.6 s of I/O plus
# 162 MB of JSON parsing, every 20 s (``TRUTH_EVERY`` 4 x ``GATEWAY_INTERVAL`` 5.0): the
# panel's own ``_poll_truth`` was the largest consumer in a py-spy profile of the live
# window -- 42 % of samples, against 57 % for the whole GUI main loop.
#
# Two things were wrong and both are fixed here:
#
# * the read was unbounded.  A tail is read as a tail: the window starts at
#   ``_TAIL_FIRST_WINDOW`` and is grown only until it holds ``count + 1`` line breaks, so a
#   3-row tail of a 162 MB file costs 256 KB and 15 ms cold / 10 us warm (measured).
# * the cache could not survive.  It was an instance attribute and the poll builds a
#   *fresh* ``TruthAudit`` every 20 s, so it was cold forever.  It is module level now,
#   keyed by ``(path, count)``, and a call that finds only appended bytes parses those
#   bytes and nothing else.
#
# The wide window (``_all_episodes``) is the one case where the rows wanted genuinely cost
# 85 MB, so it is built by ``_episode_rows`` below rather than held here: measured 1.03 s
# cold and 12 MB retained, against 19 us per call once built.

_TAIL_LOCK = threading.Lock()
_TAIL_CACHE: dict[tuple[str, int], "_TailState"] = {}

#: First window tried.  Grown on demand -- see the module comment above.
_TAIL_FIRST_WINDOW = 256 * 1024
#: Smallest growth step, and the unit the density estimate is trusted against.  One
#: megabyte of the current stream is ~70 rows, which is a stable sample: measured
#: 13 107 / 14 170 / 13 797 / 14 463 / 13 707 / 15 746 bytes per row for windows of
#: 0.25 / 0.5 / 1 / 4 / 16 / 64 MB.
_TAIL_SAMPLE_BYTES = 1024 * 1024
#: Margin on the estimate.  The estimate is a sample, so it is allowed to overshoot a
#: little; what it must not do is come up short, because the shortfall is then filled by
#: another read.
_TAIL_ESTIMATE_MARGIN = 1.15
#: Largest window kept resident.  A 5000-row window of the current episode stream is
#: ~75 MB of text and ~206 MB of parsed mappings (measured), which is not something to
#: hold for the whole soak, so wide windows are not cached here; the one caller that
#: needs a wide view goes through ``_episode_rows`` below, which keeps only the fields
#: that caller reads.
_TAIL_CACHE_MAX_COUNT = 1024
#: Bytes kept from the *head* of the file, plus its inode, as a rewrite detector.  Size
#: alone cannot tell an append from a rewrite that happens to grow: rewriting one of these
#: logs in place (which is what a retention pass does) leaves the size *larger*, and an
#: incremental read from the old offset then parses a mid-row slice of unrelated content
#: and reports it as if it were a row.  An append never changes the first bytes, a rewrite
#: does, and a rotation changes the inode as well -- so the incremental path is taken only
#: while both are unchanged.  Measured on NTFS: ``st_ino`` is populated and differs across
#: a replacement, stays equal across a truncate-and-rewrite.
_TAIL_HEAD_BYTES = 64


def _prefix(path: Path, size: int) -> tuple[int, bytes]:
    """Identity of the file's beginning: ``(st_ino, first bytes)``. ``(0, b"")`` if unreadable."""
    try:
        stat = path.stat()
        with path.open("rb") as handle:
            head = handle.read(min(_TAIL_HEAD_BYTES, size))
    except OSError:
        return 0, b""
    return stat.st_ino, head


class _TailState:
    """A cached tail: the rows, and the file position they were read up to."""

    __slots__ = ("size", "mtime_ns", "offset", "limit", "rows", "carry", "ino", "head")

    def __init__(self, size: int, mtime_ns: int, limit: int,
                 rows: list[Mapping[str, Any]], carry: str,
                 ino: int, head: bytes) -> None:
        self.size = size
        self.mtime_ns = mtime_ns
        self.offset = size
        self.limit = limit
        self.rows = rows
        self.carry = carry
        self.ino = ino
        self.head = head


def _split_rows(text: str) -> tuple[list[Mapping[str, Any]], str]:
    """Rows in file order, plus an unterminated trailing line that is not yet a row.

    The trailing-line rule is the original behaviour and it matters: the writer appends a
    line at a time, so the last line can be caught mid-write and must not be parsed.
    """
    carry = ""
    if text and not text.endswith("\n"):
        cut = text.rfind("\n")
        carry = text[cut + 1:] if cut != -1 else text
        text = text[:cut + 1] if cut != -1 else ""
    rows: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(payload)
    return rows, carry


def _tail_window(path: Path, count: int) -> tuple[str, int, int]:
    """Decoded text of a window holding at least ``count`` whole rows at the end of *path*.

    Returns ``(text, size, mtime_ns)``, where ``text`` starts on a line boundary unless
    the whole file is inside it.  The window is grown from ``_TAIL_FIRST_WINDOW`` with the
    remaining need *estimated from the density of the bytes already read*: growing by x4
    from 64 MB would overshoot a 74 MB need straight into the whole 162 MB file, which is
    the cost this function exists to avoid.

    There is deliberately no byte ceiling.  There was one (64 MB) and it was a defect: for
    ``count=5000`` -- whose rows average 15.5 KB, so 5000 of them need ~75 MB -- the window
    stopped at the ceiling and the caller silently received the last **4254** rows.  The
    panel prints that length as a denominator (``f"{len(scoped)}/{total}"``), so a quiet
    shortfall is a wrong number on screen.  When the estimate cannot be met the window
    becomes the whole file, which is the honest answer: refusing to read further does not
    make the tail shorter, it makes it wrong.
    """
    stat = path.stat()
    size = stat.st_size
    sample = min(_TAIL_SAMPLE_BYTES, size)
    window = min(_TAIL_FIRST_WINDOW, size)
    start = 0
    blob = b""
    while True:
        start = max(0, size - window)
        with path.open("rb") as handle:
            handle.seek(start)
            blob = handle.read(size - start)
        # ``count + 1``: the window may end mid-line, so one spare break proves ``count``
        # whole rows are inside even after that partial is dropped.
        breaks = blob.count(b"\n")
        if breaks >= count + 1 or start == 0:
            break
        # Grow by the estimate, never by a fixed multiple of the current window.  A
        # multiple is what made this read the whole file: at 64 MB the window held 4262 of
        # the 5001 rows wanted, and ``x4`` turned a 79 MB shortfall into 256 MB, clamped to
        # 162 MB -- the entire stream.  ``window + sample`` is the floor so the loop always
        # advances even when the estimate comes back low.
        density = (size - start) / max(1, breaks)
        need = int((count + 1) * density * _TAIL_ESTIMATE_MARGIN)
        window = min(size, max(need, window + sample))
    text = blob.decode("utf-8", "replace")
    del blob  # the caller holds ``text``; the raw bytes are ~75 MB on a wide window
    if start > 0:
        # The window began mid-line: that partial line is not a row.
        cut = text.find("\n")
        text = text[cut + 1:] if cut != -1 else ""
    return text, size, stat.st_mtime_ns


def _cold_tail(path: Path, count: int) -> "_TailState":
    """Read a window off the end of *path* and keep its last ``count`` rows."""
    text, size, mtime_ns = _tail_window(path, count)
    rows, carry = _split_rows(text)
    if len(rows) > count:
        # The window grows in steps and may hold more rows than asked for.  Keeping only
        # the last ``count`` is the same invariant ``_grow_tail`` maintains.
        del rows[:len(rows) - count]
    ino, head = _prefix(path, size)
    return _TailState(size, mtime_ns, count, rows, carry, ino, head)


def _grow_tail(state: "_TailState", path: Path, count: int) -> bool:
    """Parse only the bytes appended since the previous call.

    Returns ``False`` -- having modified nothing -- when the file was not appended to: its
    inode or its first bytes changed, so this is a rewrite or a rotation and the caller has
    to rebuild from scratch.  ``state.carry`` is the half-written line left over from the
    previous read and is prepended so a row split across two reads is still parsed once.
    """
    stat = path.stat()
    size = stat.st_size
    with path.open("rb") as handle:
        head = handle.read(min(_TAIL_HEAD_BYTES, size))
        if head != state.head or stat.st_ino != state.ino:
            return False
        handle.seek(state.offset)
        blob = handle.read(size - state.offset)
    rows, carry = _split_rows(state.carry + blob.decode("utf-8", "replace"))
    state.rows.extend(rows)
    if len(state.rows) > count:
        del state.rows[:len(state.rows) - count]
    state.carry = carry
    state.offset = size
    state.size = size
    state.mtime_ns = stat.st_mtime_ns
    state.ino = stat.st_ino
    state.head = head
    return True


def _tail_jsonl(path: Path, count: int) -> tuple[Mapping[str, Any], ...]:
    """The last ``count`` well-formed rows.  Skips a half-written trailing line."""
    if count <= 0:
        return ()
    try:
        stat = path.stat()
    except OSError:
        return ()
    if count > _TAIL_CACHE_MAX_COUNT:
        # Not cached on purpose: keeping this many rows resident is the leak this limit
        # exists to prevent.  Correct, just not remembered.
        try:
            return tuple(_cold_tail(path, count).rows)
        except OSError:
            return ()
    key = (str(path), count)
    with _TAIL_LOCK:
        state = _TAIL_CACHE.get(key)
        try:
            if state is None or stat.st_size < state.size or (
                stat.st_size == state.size and stat.st_mtime_ns != state.mtime_ns
            ):
                # Cold, or rewritten in place: re-read the window.
                state = _cold_tail(path, count)
            elif stat.st_size > state.size and not _grow_tail(state, path, count):
                # It grew, but it is not the same file: a rewrite that happened to end up
                # larger, or a rotation.  The cached offset means nothing in the new bytes.
                state = _cold_tail(path, count)
            _TAIL_CACHE[key] = state
        except OSError:
            return ()
        rows = state.rows
        return tuple(rows[-count:]) if rows else ()


# ----------------------------------------------------- the wide episode window
#
# ``_all_episodes`` asks for the last ``_EPISODE_WINDOW_ROWS`` episode rows, and every
# consumer reads only three things out of it:
#
#   * ``len(...)``                     -- the denominator the panel prints
#   * ``row.get("role_id")``           -- over the whole window
#   * full payloads from ``[-200:]`` and shorter slices of it
#
# Parsing all 5000 and keeping them retains ~206 MB of mappings (measured) to answer that.
# So the rows are parsed once, the ``role_id`` of every row is kept as a plain string, and
# only the last ``_EPISODE_CONTENT_ROWS`` payloads stay in memory: ~10 MB retained instead
# of ~206 MB, with ``len()`` and every slice still exact.  Like the tails above, the
# projection is cached at module level by file identity and grows incrementally, so the
# 0.5 s cold parse is paid once and an append costs only the appended bytes.

#: How many recent episode rows the panel's ratios are computed over.
_EPISODE_WINDOW_ROWS = 5000
#: How much of that window keeps its payload.  The widest consumer is ``[-200:]``.
_EPISODE_CONTENT_ROWS = 256

_WINDOW_LOCK = threading.Lock()
#: str(path) -> _EpisodeWindowState
_WINDOW_CACHE: dict[str, "_EpisodeWindowState"] = {}
_WINDOW_CACHE_LIMIT = 16


class _EpisodeWindowState:
    """Cached projection: one ``role_id`` per row, plus the payloads of the tail."""

    __slots__ = ("size", "mtime_ns", "offset", "carry", "role_ids", "recent", "ino", "head")

    def __init__(self, size: int, mtime_ns: int, offset: int, carry: str,
                 role_ids: list[str], recent: deque, ino: int, head: bytes) -> None:
        self.size = size
        self.mtime_ns = mtime_ns
        self.offset = offset
        self.carry = carry
        self.role_ids = role_ids
        self.recent = recent
        self.ino = ino
        self.head = head


class _EpisodeRows(Sequence[Mapping[str, Any]]):
    """The last N episode rows, without keeping all N payloads in memory.

    A sequence rather than a tuple so the existing call sites -- ``len()``, iteration and
    ``[-200:]`` -- keep working unchanged.  Rows outside the retained tail are yielded as
    a one-field mapping, which is exactly what the wide consumers read: the only field
    taken from them is ``role_id``, and a row that never carried one reads as ``""``
    through ``row.get("role_id")`` either way.
    """

    __slots__ = ("_total", "_role_ids", "_recent")

    def __init__(self, total: int, role_ids: Sequence[str],
                 recent: Sequence[Mapping[str, Any]]) -> None:
        self._total = total
        self._role_ids = role_ids
        self._recent = recent

    def __len__(self) -> int:
        return self._total

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            return tuple(self[i] for i in range(*index.indices(self._total)))
        position = index
        if position < 0:
            position += self._total
        if position < 0 or position >= self._total:
            raise IndexError(index)
        content_from = self._total - len(self._recent)
        if position >= content_from:
            return self._recent[position - content_from]
        return {"role_id": self._role_ids[position]}

    def __iter__(self) -> Any:
        content_from = self._total - len(self._recent)
        for position in range(content_from):
            yield {"role_id": self._role_ids[position]}
        yield from self._recent


def _feed_episode_rows(text: str, role_ids: list[str], recent: deque) -> str:
    """Append the rows in *text*; return the unterminated trailing line (the carry)."""
    carry = ""
    if text and not text.endswith("\n"):
        cut = text.rfind("\n")
        carry = text[cut + 1:] if cut != -1 else text
        text = text[:cut + 1] if cut != -1 else ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        role_ids.append(str(payload.get("role_id") or ""))
        recent.append(payload)
    return carry


def _trim_episode_rows(role_ids: list[str]) -> None:
    if len(role_ids) > _EPISODE_WINDOW_ROWS:
        del role_ids[:len(role_ids) - _EPISODE_WINDOW_ROWS]


def _episode_rows(path: Path) -> "_EpisodeRows":
    """The last ``_EPISODE_WINDOW_ROWS`` rows of *path*, reduced to what is read.

    The parse runs *outside* the lock: a cold window is ~0.5 s of JSON work, and holding a
    lock across it would block whichever thread asked second for exactly that long.  Two
    builders racing is harmless -- the result is a pure function of the file bytes -- and
    the loser's copy is discarded.

    Never raises: an unreadable stream is an empty window, which the callers already
    handle as "no episodes".
    """
    empty = _EpisodeRows(0, (), ())
    if _EPISODE_WINDOW_ROWS <= 0:
        return empty
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return empty
    with _WINDOW_LOCK:
        cached = _WINDOW_CACHE.get(key)
    stale = cached is None or stat.st_size < cached.size or (
        stat.st_size == cached.size and stat.st_mtime_ns != cached.mtime_ns
    )
    append = False
    if not stale and stat.st_size > cached.size:
        # Cheap pre-check on the prefix before committing to the incremental path; the
        # authoritative check is repeated inside the same handle as the append read.
        ino, head = _prefix(path, stat.st_size)
        append = ino == cached.ino and head == cached.head
    if not stale and not append:
        if stat.st_size == cached.size:
            return _EpisodeRows(
                len(cached.role_ids), tuple(cached.role_ids), tuple(cached.recent)
            )
        # It grew, but it is not the same file any more.  Fall through to a cold rebuild.
    try:
        if not append:
            text, size, mtime_ns = _tail_window(path, _EPISODE_WINDOW_ROWS)
            role_ids: list[str] = []
            recent: deque = deque(maxlen=_EPISODE_CONTENT_ROWS)
            carry = _feed_episode_rows(text, role_ids, recent)
            _trim_episode_rows(role_ids)
            ino, head = _prefix(path, size)
            state = _EpisodeWindowState(
                size, mtime_ns, size, carry, role_ids, recent, ino, head
            )
        else:
            with path.open("rb") as handle:
                head = handle.read(min(_TAIL_HEAD_BYTES, stat.st_size))
                handle.seek(cached.offset)
                blob = handle.read(stat.st_size - cached.offset)
            # Copied rather than mutated in place: ``cached`` is still installed in the
            # cache and another thread may be reading its ``role_ids`` right now.  A 5000
            # element list of short strings costs ~40 us to copy, which buys the invariant
            # that a cached state is never modified after it is published.
            role_ids = list(cached.role_ids)
            recent: deque = deque(cached.recent, maxlen=_EPISODE_CONTENT_ROWS)
            carry = _feed_episode_rows(
                cached.carry + blob.decode("utf-8", "replace"), role_ids, recent
            )
            _trim_episode_rows(role_ids)
            state = _EpisodeWindowState(
                stat.st_size, stat.st_mtime_ns, stat.st_size, carry, role_ids, recent,
                stat.st_ino, head,
            )
    except OSError:
        return empty
    with _WINDOW_LOCK:
        if len(_WINDOW_CACHE) >= _WINDOW_CACHE_LIMIT and key not in _WINDOW_CACHE:
            _WINDOW_CACHE.clear()
        _WINDOW_CACHE[key] = state
    return _EpisodeRows(len(state.role_ids), tuple(state.role_ids), tuple(state.recent))


# ------------------------------------------------------------------ the value object


@dataclass
class TruthValue:
    """One state, with everything needed to judge whether to believe it."""

    name: str
    value: str = ""
    status: str = UNKNOWN
    source: str = ""
    observed_at: str = ""
    age_seconds: float | None = None
    role_id: str = ""
    episode: str = ""
    version: str = ""
    evidence: tuple[str, ...] = ()
    verification: str = ""      # "", PASS, FAIL, UNVERIFIED
    note: str = ""
    # Where the same fact was also seen, so a disagreement is visible instead of resolved
    # by whoever read last.
    seen: tuple[tuple[str, str], ...] = ()
    # A structured payload for states that are a *list* (events, anomalies).  Kept out of
    # ``value`` on purpose: a list rendered into one string cannot be re-checked field by
    # field by the wiring verifier.
    items: tuple[Mapping[str, Any], ...] = ()

    @property
    def category(self) -> str:
        """One of the operator's eight words, from the one mapping in ``CATEGORY_OF``."""
        return CATEGORY_OF.get(self.status, UNKNOWN)

    @property
    def current(self) -> bool:
        """Is this value a claim about *now*?"""
        return self.status in (LIVE_OBSERVED, FRESH_RUNTIME, CATALOG_DERIVED)

    @property
    def headline(self) -> str:
        """What a window may print beside a heading that says "当前…".

        A persisted value is not a current one, and printing one under a *current*
        heading is exactly how a 46-hour-old role read came to be shown as the logged-in
        character (operator P0-2, 2026-09-18).  When the value is not current the
        headline refuses to carry it; ``last_known`` carries it instead, with its age.
        """
        return self.value or UNKNOWN if self.current else UNKNOWN

    @property
    def last_known(self) -> str:
        """The old value, offered as history -- empty when there is nothing old to offer."""
        return "" if self.current else (self.value or "")

    @property
    def stale(self) -> bool:
        return self.status in (STALE, UNKNOWN, CONFLICT, ASSUMED)

    @property
    def display(self) -> str:
        """What a window may print.  A value never travels without its qualifier."""
        if self.status in (UNKNOWN, ASSUMED):
            return f"{UNKNOWN}（{STATUS_ZH.get(self.status, self.status)}）"
        if self.status == STALE:
            return f"{self.value or UNKNOWN} · 已过期"
        if self.status == CONFLICT:
            return f"{self.value or UNKNOWN} · 冲突"
        return self.value or UNKNOWN

    def as_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "status_zh": STATUS_ZH.get(self.status, self.status),
            "source": self.source,
            "observed_at": self.observed_at,
            "age_seconds": None if self.age_seconds is None else round(self.age_seconds, 1),
            "role_id": self.role_id,
            "episode": self.episode,
            "version": self.version,
            "evidence": list(self.evidence),
            "verification": self.verification,
            "note": self.note,
            "seen_elsewhere": [f"{where}={what}" for where, what in self.seen],
            "current": self.current,
            "headline": self.headline,
            "last_known": self.last_known,
            "items": [dict(item) for item in self.items],
        }


@dataclass
class Conflict:
    """Two artifacts disagree about the same fact, and nobody may silently pick one."""

    name: str
    readings: tuple[tuple[str, str], ...]
    note: str = ""

    def describe(self) -> str:
        joined = " vs ".join(f"{where}={what}" for where, what in self.readings)
        return f"STATE_CONFLICT {self.name}: {joined}" + (f" ({self.note})" if self.note else "")


@dataclass
class TruthReport:
    values: tuple[TruthValue, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    role_id: str = ""
    role_status: str = UNKNOWN
    head: str = ""
    generated_at: str = ""
    anomalies: tuple[Mapping[str, Any], ...] = ()
    consistency: tuple[Mapping[str, str], ...] = ()

    def needs_attention(self) -> tuple[Mapping[str, Any], ...]:
        """Anomalies that have not healed.  A recovered one is history, not a red light."""
        return tuple(a for a in self.anomalies if not a.get("auto_recovered"))

    def by_name(self, name: str) -> TruthValue | None:
        for value in self.values:
            if value.name == name:
                return value
        return None

    def conflicts_for(self, name: str) -> tuple[Conflict, ...]:
        return tuple(c for c in self.conflicts if c.name == name)

    def worst(self) -> tuple[TruthValue, ...]:
        """Everything that must not be shown as if it were a current fact."""
        return tuple(v for v in self.values if v.stale)

    def line(self) -> str:
        stale = len(self.worst())
        return (
            f"[truth] {len(self.values)} states · {stale} not current"
            f" · {len(self.conflicts)} conflict(s)"
            f" · role {self.role_id or UNKNOWN} ({STATUS_ZH.get(self.role_status, self.role_status)})"
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "head": self.head,
            "role_id": self.role_id,
            "role_status": self.role_status,
            "states": [v.as_row() for v in self.values],
            "conflicts": [
                {"name": c.name, "readings": [f"{w}={v}" for w, v in c.readings], "note": c.note}
                for c in self.conflicts
            ],
            "anomalies": [dict(a) for a in self.anomalies],
            "consistency": [dict(row) for row in self.consistency],
        }


# ------------------------------------------------------------------------ the audit


ROLE_PROBE_DIR = "dataset/truth_audit/role_identity_20260916"
ROLE_ARTIFACT = "learning/role_identity.json"
SNAPSHOT = "learning/runtime_snapshot.json"
EPISODES = "learning/episodes.jsonl"
EXECUTOR_LEDGER = "learning/executor_backend.jsonl"
ESCALATIONS = "learning/workbuddy_escalations.jsonl"
DEVICE_LEASE = "learning/DEVICE_LEASE.json"
BACKEND_ROUTING = "knowledge/execution/backend_routing.json"
TOOL_REGISTRY = "knowledge/tooling/tool_registry.json"
GATEWAY_PROBE = "learning/control_panel/gateway.json"
EVENT_STATE = "learning/event_goal_state.json"
PUMP = "learning/control_panel/pump.json"
STATE_PATH_BOOTSTRAP = "learning/knowledge_bootstrap/STATE.json"
PANEL_STATE = "config/control_panel_state.json"

# The scheduler's own gap between cycles.  A stopped worker inside this window is the
# design working, not a fault: the worker is a fresh process per round.
ROUND_GAP_SECONDS = 1200.0
# How recently AUTO must have *produced* something to be called running from work alone.
AUTO_WORKING_SECONDS = 600.0


class TruthAudit:
    """Read-only projection: every key state, with provenance and a freshness verdict."""

    def __init__(self, root: Path | str, *, now: datetime | None = None) -> None:
        self.root = Path(root)
        self.now = now or datetime.now(timezone.utc)
        self._snapshot = _read_json(self.root / SNAPSHOT)
        self._episodes = _tail_jsonl(self.root / EPISODES, 3)
        self._all_episodes_cache: "_EpisodeRows | None" = None
        # ``git rev-parse`` is answered once per audit: the commit cannot change under a
        # running process, and a fresh subprocess per window refresh is what flashed a
        # console window every few seconds (operator P0, 2026-09-18).
        self._head_cache: str | None = None
        self._all_executor_cache: tuple[Mapping[str, Any], ...] | None = None
        self._executor = _tail_jsonl(self.root / EXECUTOR_LEDGER, 2)
        self._pump = _read_json(self.root / PUMP)
        self._conflicts: list[Conflict] = []

    @property
    def _all_episodes(self) -> "_EpisodeRows":
        """The recent episode window, reduced to the fields this audit reads.

        Lazy because most states do not need it: the panel asks this question on a slower
        cadence than it asks for the page.  The old comment here said "it is four
        megabytes" and read the last 5000 rows as a tuple -- that window is now ~74 MB of
        text and ~206 MB of parsed mappings, which is why ``_episode_rows`` keeps only
        ``role_id`` for the wide part and full payloads for the last 256 rows.  ``len()``
        and every slice are unchanged, so the ``N/5000`` ratio on the panel is unchanged.
        """
        if self._all_episodes_cache is None:
            self._all_episodes_cache = _episode_rows(self.root / EPISODES)
        return self._all_episodes_cache

    @property
    def _all_executor(self) -> tuple[Mapping[str, Any], ...]:
        """The recent executor ledger rows, read at most once per audit.

        ``100`` rather than ``5000``: both consumers of this property read ``[-100:]`` and
        nothing else (``maa_state`` and ``executor_mix``), so a hundred rows is the whole
        requirement -- and it is exactly equivalent even on a ledger shorter than 100
        rows, where the slice is the entire file either way.  The old ``5000`` parsed
        10.7 MB to fill a tuple the callers then sliced back down to 100.
        """
        if self._all_executor_cache is None:
            self._all_executor_cache = _tail_jsonl(self.root / EXECUTOR_LEDGER, 100)
        return self._all_executor_cache

    # -- primitives --------------------------------------------------------

    def _age(self, stamp: str) -> float | None:
        moment = _moment(stamp)
        if moment is None:
            return None
        return (self.now - moment).total_seconds()

    def _grade(self, *, live: bool, age: float | None) -> str:
        if age is None:
            return PERSISTED
        if live and age <= LIVE_OBSERVED_SECONDS:
            return LIVE_OBSERVED
        if age <= FRESH_RUNTIME_SECONDS:
            return FRESH_RUNTIME
        if age <= PERSISTED_SECONDS:
            return PERSISTED
        return STALE

    def _stamp(self, source: str, stamp: str, *, live: bool = False) -> tuple[str, float | None]:
        """A provenance stamp plus the status its age earns.  Never a bare value."""
        age = self._age(stamp)
        return self._grade(live=live, age=age), age

    def _episode_stamp(self, episode_id: str, recorded_at: str) -> tuple[str, float | None]:
        return self._stamp(f"episode {episode_id}", recorded_at, live=True)

    def _snapshot_stamp(self) -> tuple[str, float | None]:
        return self._stamp(SNAPSHOT, str(self._snapshot.get("updated_at") or ""))

    def _head(self) -> str:
        """The commit the tree is on, read once per audit and never through a console window.

        Two defects measured here on 2026-09-18.  The first: this ran ``git rev-parse`` on
        every call with no creation flags, and ``report()`` calls it on every window
        refresh -- so the panel flashed a black console window every few seconds, which is
        the operator's P0.  The second: a fresh ``git`` process per refresh is work the
        answer cannot change under, since a running process is on the commit it loaded.
        Both are fixed by reading it once per audit, through ``winproc``.
        """
        if self._head_cache is not None:
            return self._head_cache
        from . import winproc

        result = winproc.run(["git", "rev-parse", "HEAD"], cwd=self.root, timeout=15.0)
        self._head_cache = (result.stdout or "").strip()
        return self._head_cache

    # -- the role, which everything else must be scoped by ----------------

    def role(self) -> TruthValue:
        """Which role the client is logged in as -- or an honest admission that we do not know.

        The operator's product definition makes this a *precondition* for every other
        metric, because the corpus was already built from two accounts with different
        power and different march slots.  So it gets the strictest treatment here: the
        only acceptable sources are a vision read of the 领主档案 panel (``LIVE_OBSERVED``,
        with the frame on disk) or a persisted copy of one (``PERSISTED``/``STALE``).
        A configured name, a panel literal or a default are all ``ASSUMED``, and the
        display must say so.
        """
        artifact = _read_json(self.root / ROLE_ARTIFACT)
        probe = _read_json(self.root / ROLE_PROBE_DIR / "probe.json")
        frame = self.root / ROLE_PROBE_DIR / "profile_panel_live_20260916T184004.png"

        evidence: list[str] = []
        source = ""
        observed_at = ""
        role_id = ""
        role_name = ""
        verification = ""

        if artifact.get("role_id"):
            source = ROLE_ARTIFACT
            observed_at = str(artifact.get("observed_at") or "")
            role_id = str(artifact.get("role_id") or "")
            role_name = str(artifact.get("role_name") or "")
            verification = str(artifact.get("verification") or "VISION_READ")
            evidence = [str(p) for p in (artifact.get("evidence") or ())][:3]
        elif probe:
            # The archived probe is a real observation with a real frame; it is simply old.
            source = f"{ROLE_PROBE_DIR}/probe.json"
            observed_at = _probe_stamp(str(probe.get("stamp") or ""))
            for token in probe.get("candidate_identity_tokens") or ():
                text = str((token or {}).get("text") or "")
                if text.startswith("账号："):
                    role_id = text.split("：", 1)[1].strip()
                elif text.startswith("[") and "]" in text:
                    role_name = text.split("]", 1)[1].strip()
                elif text and not role_name and "领主档案" not in text and "：" not in text:
                    role_name = text
            verification = "VISION_READ"
            if frame.exists():
                evidence = [frame.as_posix()]

        if not role_id and not role_name:
            return TruthValue(
                name="current_role", value="", status=UNKNOWN,
                source="(no observation on file)",
                note=("没有任何角色观测记录；GUI 不得用配置名或默认值代替 —— "
                      "这正是「界面显示 xhw、真机不是 xhw」那类缺陷的来源"),
                verification="",
            )

        status, age = self._stamp(source, observed_at, live=bool(artifact.get("observed_at")))
        if artifact.get("observed_at") and status != LIVE_OBSERVED:
            status = STALE if age is not None and age > PERSISTED_SECONDS else PERSISTED
        note = ""
        if status in (PERSISTED, STALE):
            note = (
                "这是**上一次已知**的角色，不是当前真机确认值；"
                "任何 role-scoped 状态都必须按此标注，不得当作当前事实。"
            )
        return TruthValue(
            name="current_role",
            value=f"{role_name}（账号 {role_id}）" if role_name else f"账号 {role_id}",
            status=status, source=source, observed_at=observed_at, age_seconds=age,
            role_id=role_id, evidence=tuple(evidence), verification=verification, note=note,
        )

    # -- runtime states ----------------------------------------------------

    def current_page(self) -> TruthValue:
        page = str(self._snapshot.get("page") or "")
        status, age = self._snapshot_stamp()
        seen: list[tuple[str, str]] = []
        for episode in reversed(self._episodes):
            after = (episode.get("state_after") or {})
            if isinstance(after, Mapping) and after.get("page"):
                seen.append((f"episode {episode.get('episode_id')}", str(after["page"])))
                if page and str(after["page"]) != page:
                    self._conflicts.append(Conflict(
                        "current_page",
                        ((SNAPSHOT, page), (f"episode {episode.get('episode_id')}", str(after["page"]))),
                        "运行时快照与最近一条生产 episode 的 state_after 不一致",
                    ))
                break
        return TruthValue(
            name="current_page", value=page, status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            episode=str((self._episodes[-1] or {}).get("episode_id") or "") if self._episodes else "",
            evidence=(), verification="", seen=tuple(seen),
        )

    def current_goal(self) -> TruthValue:
        goal = str(self._snapshot.get("current_goal") or "")
        status, age = self._snapshot_stamp()
        seen: list[tuple[str, str]] = []
        for episode in reversed(self._episodes):
            if episode.get("goal_id"):
                seen.append((f"episode {episode.get('episode_id')}", str(episode["goal_id"])))
                if goal and str(episode["goal_id"]) != goal:
                    self._conflicts.append(Conflict(
                        "current_goal",
                        ((SNAPSHOT, goal), (f"episode {episode.get('episode_id')}", str(episode["goal_id"]))),
                        "快照与最近 episode 的 goal_id 不一致",
                    ))
                break
        return TruthValue(
            name="current_goal", value=goal, status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            seen=tuple(seen),
        )

    def current_skill(self) -> TruthValue:
        skill = str(self._snapshot.get("current_skill") or "")
        status, age = self._snapshot_stamp()
        seen: list[tuple[str, str]] = []
        for episode in reversed(self._episodes):
            if episode.get("skill"):
                seen.append((f"episode {episode.get('episode_id')}", str(episode["skill"])))
                break
        return TruthValue(
            name="current_skill", value=skill, status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            episode=str((self._episodes[-1] or {}).get("episode_id") or "") if self._episodes else "",
            seen=tuple(seen),
        )

    def auto_state(self) -> TruthValue:
        """Is AUTO actually running?  Graded from *work*, not from a flag.

        The operator's P0-4: the top bar said ``AUTO ● 正常`` while the system page said
        ``Runtime Thread 未运行 / Scheduler Loop 未运行``.  Both were reading a snapshot
        whose own fields disagree with the architecture: this project's AUTO is a
        ``run_live.py`` subprocess per round, so the two in-process flags are written
        False by the panel itself and are structurally incapable of ever saying
        "running".  A flag that cannot be true is not evidence.

        So the grade comes from what AUTO *produced*: a fresh episode, plus the panel's
        own heartbeat (the panel is what runs it), plus the operator's recorded intent.
        ``IDLE`` between rounds with a named ``stop_reason`` is the design working, and
        is reported as 等待 with that reason -- not as 正常.
        """
        intent = str(_read_json(self.root / PANEL_STATE).get("operator_intent") or "")
        beat = self.panel_heartbeat()
        snapshot_state = str(self._snapshot.get("agent_state") or "")
        stop_reason = str(self._snapshot.get("stop_reason") or "")
        exits = self._snapshot.get("unexpected_worker_exits")

        work_age: float | None = None
        if self._episodes:
            stamp = _moment(str(self._episodes[-1].get("recorded_at") or ""))
            if stamp is not None:
                work_age = (self.now - stamp).total_seconds()

        def age_text(seconds: float | None) -> str:
            if seconds is None:
                return "无记录"
            if seconds < 90:
                return f"{int(seconds)} 秒前"
            if seconds < 5400:
                return f"{seconds / 60:.0f} 分钟前"
            return f"{seconds / 3600:.1f} 小时前"

        counter = f"（累计异常退出 {exits}）" if exits else ""
        if intent == "STOPPED":
            status = FRESH_RUNTIME if beat.current else PERSISTED
            value = "已停止（操作者意图）"
            note = f"操作者停止的优先级最高，任何自动机制都不得重启它。最近动作 {age_text(work_age)}。{counter}"
        elif work_age is not None and work_age <= AUTO_WORKING_SECONDS:
            status = LIVE_OBSERVED
            value = f"运行中 · 最近动作 {age_text(work_age)}"
            note = f"有真实产出（最新 episode）{counter}"
        elif beat.current:
            status = FRESH_RUNTIME
            value = f"运行中 · 本轮之间（最近动作 {age_text(work_age)}）"
            note = (f"面板时钟新鲜，运行主体没有产出是轮次间隔"
                    f"{f'，原因 {stop_reason}' if stop_reason else ''}。{counter}")
        else:
            status = STALE
            value = "未确认"
            note = ("面板时钟不新鲜，没有任何证据说明 AUTO 在运行"
                    f"（快照状态 {snapshot_state or '-'}、最近动作 {age_text(work_age)}）。{counter}")
        return TruthValue(
            name="auto_state", value=value, status=status,
            source=f"{PANEL_STATE} + {EPISODES} + {PUMP}",
            observed_at=str(self._episodes[-1].get("recorded_at") or "") if self._episodes else "",
            age_seconds=work_age,
            episode=str(self._episodes[-1].get("episode_id") or "") if self._episodes else "",
            note=note + "；runtime_thread_alive / scheduler_loop_alive 属于**上一代**"
                        "进程内架构，本轮不是它们的证据来源（见 system 页的说明）",
        )

    def panel_heartbeat(self) -> TruthValue:
        stamp = str(self._pump.get("written_at") or "")
        status, age = self._stamp(PUMP, stamp)
        alive = status in (FRESH_RUNTIME, LIVE_OBSERVED)
        return TruthValue(
            name="panel_heartbeat",
            value=f"pid {self._pump.get('process') or '?'}",
            status=status if alive else STALE, source=PUMP, observed_at=stamp, age_seconds=age,
            note="看门狗据此判断面板是否真的在运行",
        )

    def march_capacity(self) -> TruthValue:
        used = self._snapshot.get("march_used")
        maximum = self._snapshot.get("march_max")
        status, age = self._snapshot_stamp()
        if used is None and maximum is None:
            return TruthValue(
                name="march_capacity", value="", status=UNKNOWN, source=SNAPSHOT,
                observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
                note="快照里没有行军占用/容量",
            )
        role = self.role()
        note = ""
        if role.status != LIVE_OBSERVED:
            # The marching capacity is a property of the *account*: the audited corpus
            # already contains 6 slots for one account and 2 for another.  A number whose
            # role is only "last known" is therefore not scoped to the current role, and
            # saying so is the whole point -- the operator's case was exactly a value that
            # belonged to one account being shown while another was logged in.
            note = (
                f"未按当前角色确认：角色状态为「{STATUS_ZH.get(role.status, role.status)}」；"
                f"容量可能属于另一个账号（上次已知 {role.value or '未知'}）"
            )
        # A number that cannot be true is a conflict, not a reading.  Found live: the
        # snapshot reported ``march_used=21`` against ``march_max=3`` and the window drew
        # it without complaint, which is exactly "displayed state disconnected from the
        # client" -- the failure mode this audit exists to surface.
        try:
            used_int, max_int = int(used), int(maximum)
        except (TypeError, ValueError):
            used_int = max_int = None
        if used_int is not None and max_int is not None and max_int > 0 and used_int > max_int:
            self._conflicts.append(Conflict(
                "march_capacity",
                ((SNAPSHOT, f"{used_int}/{max_int}"),
                 ("invariant", f"行军占用不可能超过容量 {max_int}")),
                "占用大于容量：这两个数不是同一时刻/同一角色的读数",
            ))
            return TruthValue(
                name="march_capacity", value=f"{used_int}/{max_int}", status=CONFLICT,
                source=SNAPSHOT, observed_at=str(self._snapshot.get("updated_at") or ""),
                age_seconds=age, role_id=role.role_id,
                note=(note + "；" if note else "")
                     + f"占用 {used_int} 超过容量 {max_int}，不是可信读数",
            )
        return TruthValue(
            name="march_capacity", value=f"{used}/{maximum}" if maximum is not None else str(used),
            status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
            role_id=role.role_id, note=note,
        )

    def resources(self) -> TruthValue:
        for episode in reversed(self._episodes):
            after = episode.get("state_after") or {}
            if isinstance(after, Mapping) and after.get("resources"):
                status, age = self._episode_stamp(
                    str(episode.get("episode_id") or ""), str(episode.get("recorded_at") or "")
                )
                resources = after["resources"]
                return TruthValue(
                    name="resources",
                    value=", ".join(f"{k}={v}" for k, v in list(resources.items())[:5]),
                    status=status, source=f"episode {episode.get('episode_id')} state_after",
                    observed_at=str(episode.get("recorded_at") or ""), age_seconds=age,
                    episode=str(episode.get("episode_id") or ""),
                    role_id=self.role().role_id,
                    evidence=tuple(
                        p for p in (episode.get("after_screenshot"),) if isinstance(p, str)
                    ),
                )
        return TruthValue(
            name="resources", value="", status=UNKNOWN, source=EPISODES,
            note=("最近 3 条 episode 的 state_after 里没有资源读数 —— "
                  "「没读到」不是「没有资源」，不得显示为 0"),
        )

    def queues(self) -> TruthValue:
        queues = self._snapshot.get("queues") or {}
        status, age = self._snapshot_stamp()
        if not isinstance(queues, Mapping) or not any(queues.values()):
            return TruthValue(
                name="queues", value="", status=UNKNOWN, source=SNAPSHOT,
                observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
                note=("快照里建筑/科研/训练/情报/联盟/活动队列都是空的 —— "
                      "空是「没读到」，不是「没有任务」"),
            )
        filled = {k: v for k, v in queues.items() if v}
        return TruthValue(
            name="queues", value=", ".join(f"{k}={v}" for k, v in list(filled.items())[:4]),
            status=status, source=SNAPSHOT,
            observed_at=str(self._snapshot.get("updated_at") or ""), age_seconds=age,
        )

    def feature_unlock(self) -> TruthValue:
        catalog = self.root / "knowledge/game/capability_catalog.json"
        payload = _read_json(catalog)
        capabilities = payload.get("capabilities") or ()
        if not capabilities:
            return TruthValue(name="feature_unlock", value="", status=UNKNOWN, source=str(catalog))
        observed = sum(
            1 for row in capabilities
            if str((row or {}).get("current_role_available")) == "OBSERVED_AVAILABLE"
        )
        return TruthValue(
            name="feature_unlock",
            value=f"{observed}/{len(capabilities)} 项标记为当前角色可用",
            status=CATALOG_DERIVED, source="knowledge/game/capability_catalog.json",
            observed_at=str(payload.get("generated_at") or ""),
            age_seconds=self._age(str(payload.get("generated_at") or "")),
            note=("总表推导，不是真机解锁检查；且未绑定角色 —— 换角色后必须重新推导"),
        )

    def event_state(self) -> TruthValue:
        payload = _read_json(self.root / EVENT_STATE)
        if not payload:
            return TruthValue(
                name="event_state", value="", status=UNKNOWN, source=EVENT_STATE,
                note="没有活动状态文件；「没有活动」与「没读到活动」必须区分",
            )
        # One classification, two readers: ``legacy_event_row`` owns the rule (the record's
        # own countdown first, then the TTL).  This method used to carry a **second copy**
        # of it that read ``updated_at``/``recorded_at`` while the record actually writes
        # ``verified_at`` -- so the stamp was empty, ``_age`` returned None, and ``_grade``
        # turned "no date at all" into **PERSISTED**, which reads as "saved, fine".
        #
        # Measured 2026-10-04: the 运行状态 table showed ``event_state = PERSISTED,
        # age=None`` for a record that was **599 h old**.  A missing field must never become
        # a benign status -- that is the same defect as the panel printing a stale activity
        # as today's plan, one layer down.
        row = legacy_event_row(payload, now=self.now)
        stamp = str(row.get("observed_at") or payload.get("verified_at") or "")
        return TruthValue(
            name="event_state",
            value=", ".join(f"{k}={v}" for k, v in list(payload.items())[:4]),
            status=STALE if row.get("expired") else LIVE_OBSERVED,
            source=EVENT_STATE,
            observed_at=stamp,
            age_seconds=row.get("age_seconds"),
            note=str(row.get("note") or ""),
        )

    def events(self) -> TruthValue:
        """Every activity the project knows about, each graded by how it was observed.

        The operator's rule (2026-09-18): **HISTORY must never stand in for a current
        event.**  Measured before this: the window's 运行活动 showed
        ``最强王国·击败野兽`` from a record whose own fields said
        ``数据来源 HISTORY · 最后验证 待验证 · 置信度 0%``, verified 2026-09-09 -- nine days
        earlier, with the event's own countdown (28795 s) long since elapsed -- and its
        当前积分 11250 / 目标 80000 / 缺口 68750 line still on screen as today's plan.

        The model is a list, not a single ``current_event``: activities overlap, and a
        window that can only show one hides the other.  Each row carries the fields the
        operator listed, and ``planner_usable`` is the gate: only a row that is current
        (or an EXPLICIT future window) may feed a plan.  Nothing here *reads* the device;
        a live row appears only when real evidence does, and until then the honest answer
        is "当前活动尚未实时确认" -- not an old name filling the space.

        Only two readers may consume this: this projection and the window.  Asserted by
        ``tests/test_state_truth.py`` precisely because the planner *ought* to be a third
        and must not become one through a history record.
        """
        moment = self.now
        rows: list[dict[str, Any]] = []

        # 1. The live-client record, if it is one.  Its own window decides: a record kept
        #    past the countdown it recorded describes an activity that has ended, whatever
        #    its ``source`` says.
        legacy = _read_json(self.root / EVENT_STATE)
        if legacy.get("name") or legacy.get("event_id"):
            row = legacy_event_row(legacy, now=moment, role_id=self.role().role_id)
            row.pop("raw", None)
            rows.append(row)

        # 2. The event knowledge base: candidates and priors, never current.  A file in
        #    ``knowledge/events`` is a description of an event, not an observation of it.
        for path in sorted((self.root / "knowledge/events").glob("*.json")):
            if path.name == EVENT_STATE.split("/")[-1] or path.name == "event_registry.json":
                continue
            payload = _read_json(path)
            name = str(payload.get("name") or payload.get("event_name") or "")
            if not name:
                continue
            rows.append({
                "event_id": str(payload.get("event_id") or path.stem),
                "event_name": name,
                "status": HISTORY,
                "source": f"knowledge/events/{path.name}",
                "observed_at": str(payload.get("retrieved_at") or payload.get("last_verified") or ""),
                "age_seconds": None,
                "freshness": "知识库（不是观测）",
                "confidence": None,
                "started_at": str(payload.get("start") or ""),
                "ends_at": str(payload.get("end") or ""),
                "progress": {},
                "claimable": False,
                "role_id": "",
                "evidence": (path.as_posix(),),
                "planner_usable": False,
                "note": "知识库条目：只能作为先验，不能当作当前活动",
            })

        active = [r for r in rows if r["status"] in (LIVE_OBSERVED, FRESH_RUNTIME)]
        claimable = [r for r in rows if r["claimable"]]
        upcoming = [r for r in rows if r["status"] in (EXPECTED, REQUESTED) and r["ends_at"]]
        history = [r for r in rows if r["status"] == HISTORY]
        value = (
            " · ".join(r["event_name"] for r in active)
            if active
            else ("当前活动尚未实时确认" if rows else "")
        )
        return TruthValue(
            name="events", value=value,
            status=LIVE_OBSERVED if active else (UNKNOWN if not rows else HISTORY),
            source=EVENT_STATE if rows else "(no event source)",
            observed_at=max((str(r.get("observed_at") or "") for r in active), default=""),
            note=(
                f"当前 {len(active)} · 可领取 {len(claimable)} · 即将开始 {len(upcoming)}"
                f" · 历史/知识 {len(history)}"
                + ("" if active else
                   "；没有实时确认的活动，不得用历史记录填空（操作者 P0-1）")
            ),
            items=tuple(rows),
        )

    def gateway_health(self) -> TruthValue:
        """Is the WorkBuddy gateway answering?  A separate question from "what is the job doing".

        The operator's P0-3: the top bar said ``WorkBuddy ● 正常`` while the development
        page said ``GatewayUnavailable /api/v1/jobs/d8ea0e44 timed out after 15s`` and the
        log kept timing out.  The word "正常" was derived from the *ledger* -- a job whose
        last known state is WORKING -- and a job's last known state is not evidence that
        anything is reachable.  Two facts, two cells.

        Read from the panel's own probe record, which is the only artifact that knows the
        answer; the panel writes it so this projection can grade it rather than guess.
        """
        payload = _read_json(self.root / GATEWAY_PROBE)
        if not payload:
            return TruthValue(
                name="gateway_health", value="", status=UNKNOWN, source=GATEWAY_PROBE,
                note=("面板还没有写过探针结果。**不能**从 Job 状态反推网关健康 —— "
                      "那正是「Job=WORKING 就显示正常」这个错误的来源"),
            )
        available = payload.get("available")
        stamp = str(payload.get("checked_at_utc") or "")
        status, age = self._stamp(GATEWAY_PROBE, stamp, live=True)
        consecutive = int(payload.get("consecutive_failures") or 0)
        last_ok = str(payload.get("last_ok_at") or "")
        backoff = payload.get("backoff_seconds")
        if available is True:
            value = "正常"
            if consecutive == 0:
                # An answer is not proof that work flows: the top bar must not claim more
                # than the probe measured, and the probe measures reachability.
                pass
        elif available is False:
            value = "异常"
            status = CONFLICT
        else:
            value = UNKNOWN
        note = str(payload.get("reason") or "")
        if consecutive >= 2:
            note += (f"；连续 {consecutive} 次失败"
                     + (f"，已退避 {backoff} 秒" if backoff else ""))
        if last_ok:
            ok_age = self._age(last_ok)
            note += f"；最近一次成功通信 {'' if ok_age is None else f'{ok_age / 60:.0f} 分钟前'}"
        else:
            note += "；没有成功通信记录"
        return TruthValue(
            name="gateway_health", value=value, status=status, source=GATEWAY_PROBE,
            observed_at=stamp, age_seconds=age, note=note,
        )

    # -- execution, evidence and version ----------------------------------

    def executor_backend(self) -> TruthValue:
        if not self._executor:
            return TruthValue(
                name="executor_backend", value="", status=UNKNOWN, source=EXECUTOR_LEDGER,
                note="没有执行器台账行",
            )
        row = self._executor[-1]
        stamp = str(row.get("recorded_at") or row.get("at") or "")
        status, age = self._stamp(EXECUTOR_LEDGER, stamp, live=True)
        used = row.get("used_backend") or row.get("backend") or row.get("executor_backend") or ""
        capture = row.get("capture_backend") or ""
        return TruthValue(
            name="executor_backend",
            value=f"{used}" + (f" / 截图 {capture}" if capture else ""),
            status=status, source=EXECUTOR_LEDGER, observed_at=stamp, age_seconds=age,
            note="这是**实际用过**的后端，不是配置里写的偏好",
        )

    def version_active(self) -> TruthValue:
        head = self._head()
        for episode in reversed(self._episodes):
            revision = str(episode.get("repo_revision") or "")
            if not revision:
                continue
            status, age = self._episode_stamp(
                str(episode.get("episode_id") or ""), str(episode.get("recorded_at") or "")
            )
            running = revision.split("+")[0]
            conflict = bool(head) and not (head.startswith(running) or running.startswith(head[:7]))
            if conflict:
                # Not a defect by itself -- it is exactly VERSION_ACTIVATION_PENDING -- but
                # it must be *visible*, because a live episode produced by the old tree
                # must never be credited to the new one.
                self._conflicts.append(Conflict(
                    "version_active",
                    (("git HEAD", head[:7]), (f"episode {episode.get('episode_id')}", running[:7])),
                    "生产仍在跑旧树；新版本的 episode 尚未产生",
                ))
            return TruthValue(
                name="version_active", value=running[:7] or revision,
                status=CONFLICT if conflict else status,
                source=f"episode {episode.get('episode_id')} repo_revision",
                observed_at=str(episode.get("recorded_at") or ""), age_seconds=age,
                version=revision, episode=str(episode.get("episode_id") or ""),
                note=f"HEAD={head[:7]}" if head else "",
            )
        return TruthValue(
            name="version_active", value=head[:7], status=REQUESTED, source="git HEAD",
            version=head, note="没有带 repo_revision 的 episode：新版本是否已生效无法证明",
        )

    def verifier(self) -> TruthValue:
        for episode in reversed(self._episodes):
            if "verifier_ok" not in episode:
                continue
            ok = episode.get("verifier_ok")
            status, age = self._episode_stamp(
                str(episode.get("episode_id") or ""), str(episode.get("recorded_at") or "")
            )
            return TruthValue(
                name="verifier",
                value=f"{'PASS' if ok else 'FAIL'} · skill={episode.get('skill')}"
                      f" · goal={episode.get('goal_id')}",
                status=status, source=f"episode {episode.get('episode_id')} verifier_ok",
                observed_at=str(episode.get("recorded_at") or ""), age_seconds=age,
                episode=str(episode.get("episode_id") or ""),
                verification="PASS" if ok else "FAIL",
                note=("单条 episode 的 verifier 结果；只有它属于**当前生效版本**时才可用来判定能力"),
            )
        return TruthValue(
            name="verifier", value="", status=UNKNOWN, source=EPISODES,
            note="没有带 verifier_ok 的 episode",
        )

    def workbuddy_jobs(self) -> TruthValue:
        from .escalation_queue import EscalationLedger, fold

        try:
            snapshot = fold(EscalationLedger(self.root / ESCALATIONS).events())
        except Exception as exc:  # noqa: BLE001
            return TruthValue(
                name="workbuddy_jobs", value="", status=UNKNOWN, source=ESCALATIONS,
                note=f"台账不可读：{type(exc).__name__}",
            )
        records = list(snapshot.records.values())
        if not records:
            # An empty ledger and a missing ledger are the same thing here: nothing has
            # been filed, which is a fact about the queue but not a freshness claim.
            return TruthValue(
                name="workbuddy_jobs", value="", status=UNKNOWN, source=ESCALATIONS,
                note="台账为空：还没有任何升级记录，不得显示成「队列正常」",
            )
        counts: dict[str, int] = {}
        for record in records:
            counts[record.state] = counts.get(record.state, 0) + 1
        new = counts.get("NEW", 0) + counts.get("QUEUED", 0)
        working = [r for r in records if r.state in ("WORKING", "SUBMITTED")]
        value = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        note = ""
        if new and not working:
            # The exact GUI lie the operator caught once before: "排队中" over an empty
            # pipeline, or worse, a queue that says nothing while records sit unconsumed.
            note = f"{new} 条仍未被消费（NEW/QUEUED）——不得显示成「开发中」"
        stamp = datetime.fromtimestamp(
            (self.root / ESCALATIONS).stat().st_mtime, tz=timezone.utc
        ).isoformat()
        return TruthValue(
            name="workbuddy_jobs", value=value, status=FRESH_RUNTIME, source=ESCALATIONS,
            observed_at=stamp, age_seconds=self._age(stamp), note=note,
        )

    def device_lease(self) -> TruthValue:
        payload = _read_json(self.root / DEVICE_LEASE)
        if not payload:
            return TruthValue(
                name="device_lease", value="idle", status=CATALOG_DERIVED, source=DEVICE_LEASE,
                note=("没有租约文件 = 游戏端持有设备（在唯一那把锁上定义），这是正常情况；"
                      "但它是一个由文件存在性推出的读数，不是新鲜观测"),
            )
        released = bool(payload.get("released_at"))
        return TruthValue(
            name="device_lease",
            value=f"{payload.get('owner')}" + ("（已归还）" if released else "（持有中）"),
            status=FRESH_RUNTIME if released else LIVE_OBSERVED, source=DEVICE_LEASE,
            observed_at=str(payload.get("released_at") or payload.get("acquired_at") or ""),
            age_seconds=self._age(str(payload.get("released_at") or payload.get("acquired_at") or "")),
            note=f"trace={payload.get('trace_id') or '-'} job={payload.get('job_id') or '-'}",
        )

    def episode_role_scope(self) -> TruthValue:
        """Are episode rows attributable to a role in the shared multi-role ledger?

        The global scheduler writes both roles to one episode stream. Their presence together
        is expected when every row carries a role_id; role-specific metrics must group by that
        field. Recent rows without a role_id cannot safely be attributed and remain a conflict.
        """
        role = self.role()
        total = len(self._all_episodes)
        scoped = [e for e in self._all_episodes if str(e.get("role_id") or "").strip()]
        role_ids = sorted({str(e.get("role_id")).strip() for e in scoped})
        mine = [e for e in scoped if role.role_id and str(e.get("role_id")).strip() == role.role_id]
        note = (f"{len(scoped)}/{total} 条 episode 带角色；"
                f"{len(mine)} 条属于上次已知角色 {role.value or '未知'}")

        if not scoped:
            return TruthValue(
                name="episode_role_scope", value=f"0/{total}", status=UNKNOWN,
                source=EPISODES, role_id=role.role_id,
                note=note + "；**全部未按角色限定** —— 跨 episode 统计不得当作单角色结论",
            )

        unscoped_recent = [
            e for e in self._all_episodes[-200:] if not str(e.get("role_id") or "").strip()
        ]
        if unscoped_recent:
            self._conflicts.append(Conflict(
                "episode_role_scope",
                (("current_role", role.role_id or "UNKNOWN"),
                 ("recent unscoped episodes", str(len(unscoped_recent)))),
                "最近 episode 缺少 role_id，无法归属到角色；不得用于角色状态或跨角色统计",
            ))
            return TruthValue(
                name="episode_role_scope", value=f"{len(scoped)}/{total}",
                status=CONFLICT, source=EPISODES, role_id=role.role_id,
                note=note + f"；最近 200 条中有 {len(unscoped_recent)} 条未标角色",
            )

        if not role.role_id:
            return TruthValue(
                name="episode_role_scope", value=f"{len(scoped)}/{total}", status=UNKNOWN,
                source=EPISODES, role_id="",
                note=note + "；当前角色身份未知，不能把记录归并到当前角色",
            )
        if not mine:
            return TruthValue(
                name="episode_role_scope", value=f"{len(scoped)}/{total}", status=UNKNOWN,
                source=EPISODES, role_id=role.role_id,
                note=note + "；共享日志中暂无当前角色的 episode",
            )

        latest_mine = mine[-1]
        status, age = self._episode_stamp(
            str(latest_mine.get("episode_id") or ""), str(latest_mine.get("recorded_at") or "")
        )
        if len(role_ids) > 1:
            note += (f"；共享日志含 {len(role_ids)} 个带标角色，已按 role_id 区分；"
                     "跨角色指标需分组计算（这是多角色历史，不是实时冲突）")
        return TruthValue(
            name="episode_role_scope", value=f"{len(scoped)}/{total}", status=status,
            source=EPISODES, observed_at=str(latest_mine.get("recorded_at") or ""),
            age_seconds=age, role_id=role.role_id, note=note,
        )

    def capability_lifecycle(self) -> TruthValue:
        catalog = _read_json(self.root / "knowledge/game/capability_catalog.json")
        rows = catalog.get("capabilities") or ()
        if not rows:
            return TruthValue(
                name="capability_lifecycle", value="", status=UNKNOWN,
                source="knowledge/game/capability_catalog.json",
                note="能力总表不可读：生命周期状态未知",
            )
        counts: dict[str, int] = {}
        verified_with_episode = 0
        for row in rows:
            lifecycle = str((row or {}).get("lifecycle") or "?")
            counts[lifecycle] = counts.get(lifecycle, 0) + 1
            if lifecycle == "LIVE_VERIFIED" and int((row or {}).get("live_attempts") or 0) > 0:
                verified_with_episode += 1
        return TruthValue(
            name="capability_lifecycle",
            value=" · ".join(f"{k} {v}" for k, v in sorted(counts.items())),
            status=CATALOG_DERIVED, source="knowledge/game/capability_catalog.json",
            note=(f"LIVE_VERIFIED {counts.get('LIVE_VERIFIED', 0)} 项中 "
                  f"{verified_with_episode} 项带有真机尝试记录；其余是总表状态，不是本轮证据"),
        )

    # -- the states the control centre needs, derived from the ones above ------

    def maa_state(self) -> TruthValue:
        """Is MAA *working*, or merely installed?

        The operator's rule: "不能仅因为MAA进程存在就显示正常".  So this is graded on what
        the executor ledger says actually ran, not on the config flag -- a configured MAA
        that has never issued an input is not healthy, it is unused.
        """
        config = _read_json(self.root / "config/v2.json")
        enabled = bool(((config.get("executor") or {}).get("maa") or {}).get("enabled"))
        rows = self._all_executor
        recent = rows[-100:]
        maa_rows = [r for r in recent if str(r.get("used_backend") or "") == "MAA"]
        fallbacks = [r for r in recent if r.get("fallback_used")]
        last = self._executor[-1] if self._executor else {}
        last_stamp = str(last.get("recorded_at") or "")
        age = self._age(last_stamp)

        if not enabled:
            return TruthValue(
                name="maa_state", value="已关闭（config executor.maa.enabled=false）",
                status=CATALOG_DERIVED, source="config/v2.json",
                note="配置里关掉了 MAA —— 这是策略，不是故障",
            )
        if not rows:
            return TruthValue(
                name="maa_state", value="未初始化（无执行记录）", status=UNKNOWN,
                source=EXECUTOR_LEDGER, note="MAA 已启用但从未发过任何输入",
            )
        if not maa_rows:
            return TruthValue(
                name="maa_state", value=f"最近 {len(recent)} 步全部 ADB",
                status=STALE if recent else UNKNOWN, source=EXECUTOR_LEDGER,
                observed_at=last_stamp, age_seconds=age,
                note="MAA 已启用但最近没有真实执行 —— 只显示「可用」会掩盖这件事",
            )
        if fallbacks and len(fallbacks) >= max(3, len(recent) // 4):
            return TruthValue(
                name="maa_state",
                value=f"降级到 ADB（{len(fallbacks)}/{len(recent)} 步走了 fallback）",
                status=CONFLICT, source=EXECUTOR_LEDGER, observed_at=last_stamp, age_seconds=age,
                note="MAA 名义可用但大量走 fallback，等于生产在用 ADB",
            )
        status = LIVE_OBSERVED if age is not None and age <= LIVE_OBSERVED_SECONDS else STALE
        return TruthValue(
            name="maa_state", value=f"正常且最近真实执行（{len(maa_rows)}/{len(recent)} 步）",
            status=status, source=EXECUTOR_LEDGER, observed_at=last_stamp, age_seconds=age,
            verification="LEDGER",
        )

    def executor_mix(self) -> TruthValue:
        """What production has *actually* been using, and why the rest went to ADB.

        The operator's use case: "快速发现「MAA明明正常，但生产实际上一直ADB」".  The reason
        comes from the ledger's own fields, so it is a measurement rather than a guess:
        a skill with no routing entry keeps its historical ADB path, and that is a fact
        about the migration, not a fault.
        """
        recent = self._all_executor[-100:]
        if not recent:
            return TruthValue(
                name="executor_mix", value="", status=UNKNOWN, source=EXECUTOR_LEDGER,
                note="没有执行记录",
            )
        counts: dict[str, int] = {}
        for row in recent:
            key = str(row.get("used_backend") or "?")
            counts[key] = counts.get(key, 0) + 1
        adb = [r for r in recent if str(r.get("used_backend")) == "ADB"]
        not_migrated = sum(1 for r in adb if not r.get("skill_known"))
        fallback = sum(1 for r in adb if r.get("fallback_used"))
        other = max(0, len(adb) - not_migrated - fallback)
        stamp = str(recent[-1].get("recorded_at") or "")
        age = self._age(stamp)
        share = " · ".join(f"{k} {round(v / len(recent) * 100)}%" for k, v in sorted(counts.items()))
        reasons = []
        if not_migrated:
            reasons.append(f"技能未迁移 MAA {not_migrated} 步")
        if fallback:
            reasons.append(f"fallback {fallback} 步")
        if other:
            reasons.append(f"显式策略/其它 {other} 步")
        return TruthValue(
            name="executor_mix", value=share,
            status=LIVE_OBSERVED if age is not None and age <= LIVE_OBSERVED_SECONDS else STALE,
            source=EXECUTOR_LEDGER, observed_at=stamp, age_seconds=age,
            note=("ADB 原因：" + "、".join(reasons)) if reasons else "全部 MAA",
        )

    def watchdog(self) -> TruthValue:
        """Current health, which is not the same number as the historical total.

        The operator's point: a cumulative counter that only ever grows makes the window
        look permanently broken ("历史累计15会让GUI永久看起来异常").  So health is reported
        from the live flags and the operator's own intent, and the counters are labelled as
        cumulative.  The 1h/24h windows are ``UNKNOWN`` rather than inferred, because
        nothing on disk records *when* a restart happened -- a guessed window would be
        worse than an honest gap.

        A stopped runtime thread is **not** an anomaly by itself.  The worker is a fresh
        process per cycle and exits cleanly between rounds; the first version flagged that
        as "runtime 线程与 scheduler 循环都已停止" while episodes were still being produced,
        which is exactly how a monitor teaches people to ignore it.  A dead thread only
        matters when the operator asked for RUNNING *and* the snapshot has gone stale
        beyond the scheduler's own round gap.
        """
        alive = bool(self._snapshot.get("runtime_thread_alive"))
        scheduler = bool(self._snapshot.get("scheduler_loop_alive"))
        state = str(self._snapshot.get("agent_state") or "")
        stop_reason = str(self._snapshot.get("stop_reason") or "")
        stamp = str(self._snapshot.get("updated_at") or "")
        age = self._age(stamp)
        intent = str(_read_json(self.root / PANEL_STATE).get("operator_intent") or "")

        heartbeat = self.panel_heartbeat()
        healthy = True
        note = ""
        if intent and intent != "RUNNING":
            healthy = True
            note = f"操作者意图 {intent} —— 停在这里是意图，不是故障"
        elif heartbeat.status not in (FRESH_RUNTIME, LIVE_OBSERVED):
            healthy = False
            note = "面板心跳过期：没有时钟在驱动这一轮"
        elif state == "FATAL_STOPPED":
            healthy = False
            note = f"致命停止：{self._snapshot.get('last_fatal_error') or '-'}"
        elif alive and scheduler:
            note = "runtime 线程与 scheduler 循环都在"
        elif age is not None and age <= ROUND_GAP_SECONDS:
            note = (f"轮次之间（上一轮 {stop_reason or '已结束'}，"
                    f"{int(age)}s 前），scheduler 会在下一轮重新拉起")
        else:
            healthy = False
            note = (f"意图 RUNNING 但已经静默 "
                    f"{'-' if age is None else f'{int(age)}s'}，超过轮次间隔")

        return TruthValue(
            name="watchdog",
            value=(f"{'正常' if healthy else '异常'} · 状态 {state or '-'}"
                   f" · 历史累计重启 {self._snapshot.get('watchdog_restart_count') or 0}"
                   f" · 异常退出 {self._snapshot.get('unexpected_worker_exits') or 0}"),
            status=(self._snapshot_stamp()[0] if healthy else CONFLICT), source=SNAPSHOT,
            observed_at=stamp, age_seconds=age,
            note=note + "；最近1h/24h 重启：UNKNOWN（磁盘上没有重启时间序列）",
        )

    def why_idle(self) -> TruthValue:
        """If nothing is moving, say why -- or say that nobody knows.

        The operator asked for this by name: "不能让用户看到游戏不动以后还要自己猜".
        The reason is read from the runtime's own last decision, and a named reason is only
        accepted if the runtime actually recorded one.  Otherwise it is
        ``UNEXPLAINED_IDLE``, which is a finding, not a blank.
        """
        last_action = _moment(str(self._snapshot.get("last_action_time") or ""))
        idle_seconds = (self.now - last_action).total_seconds() if last_action else None
        reason = str(self._snapshot.get("reason") or "")
        next_action = str(self._snapshot.get("next_action") or "")
        stop_reason = str(self._snapshot.get("stop_reason") or "")
        deferrals = self._snapshot.get("deferred_goals") or ()
        state = str(self._snapshot.get("agent_state") or "")
        moment = str(self._snapshot.get("updated_at") or "")

        if state in ("PAUSED",):
            why, status = "用户暂停", FRESH_RUNTIME
        elif state in ("FATAL_STOPPED",):
            why, status = f"致命停止：{self._snapshot.get('last_fatal_error') or '-'}", CONFLICT
        elif self._device_is_leased_for_validation():
            why, status = "Device Lease 被 validation 占用（V2 让路中）", FRESH_RUNTIME
        elif self._reload_pending():
            why, status = "正在安全重载（新版本待生效）", FRESH_RUNTIME
        elif deferrals:
            caps = ", ".join(str((d or {}).get("capability") or (d or {}).get("goal_id") or "")
                             for d in deferrals[:3])
            why, status = f"当前目标已 DEFER（{caps}）", FRESH_RUNTIME
        elif stop_reason:
            why, status = f"轮次结束原因：{stop_reason}", FRESH_RUNTIME
        elif reason:
            why, status = reason, FRESH_RUNTIME
        elif idle_seconds is not None and idle_seconds > 900:
            why, status = "UNEXPLAINED_IDLE", CONFLICT
        elif idle_seconds is not None:
            why, status = f"等待下一 Scheduler Tick（已静默 {int(idle_seconds)}s）", FRESH_RUNTIME
        else:
            why, status = "runtime 尚未记录任何动作时间", UNKNOWN

        age = self._age(moment)
        note = f"下一步：{next_action}" if next_action else ""
        if status == CONFLICT and why == "UNEXPLAINED_IDLE":
            self._conflicts.append(Conflict(
                "why_idle", (("last_action", str(self._snapshot.get("last_action_time") or "-")),
                             ("reason", reason or "(空)")),
                "超时无动作且 runtime 没有给出原因 —— 需要诊断，不是等待",
            ))
        return TruthValue(
            name="why_idle", value=why, status=status, source=SNAPSHOT,
            observed_at=moment, age_seconds=age, note=note,
        )

    def _device_is_leased_for_validation(self) -> bool:
        payload = _read_json(self.root / DEVICE_LEASE)
        return bool(payload) and not payload.get("released_at")

    def _reload_pending(self) -> bool:
        try:
            from .runtime_reload import ReloadSignal, default_path

            return ReloadSignal(default_path(self.root)).pending() is not None
        except Exception:  # noqa: BLE001
            return False

    def workbuddy_job(self) -> TruthValue:
        """The job that is being worked on right now, with its stage."""
        try:
            from .escalation_queue import EscalationLedger, fold

            snapshot = fold(EscalationLedger(self.root / ESCALATIONS).events())
        except Exception as exc:  # noqa: BLE001
            return TruthValue(name="workbuddy_job", value="", status=UNKNOWN,
                              source=ESCALATIONS, note=f"台账不可读：{type(exc).__name__}")
        records = list(snapshot.records.values())
        active = [r for r in records
                  if r.state in ("WORKING", "SUBMITTED", "VERSION_ACTIVATION_PENDING",
                                 "LIVE_VERIFY_PENDING")]
        if not records:
            return TruthValue(
                name="workbuddy_job", value="", status=UNKNOWN, source=ESCALATIONS,
                note="台账为空：既没有在飞的任务，也没有任何历史 —— 不得显示成「空闲」",
            )
        if not active:
            return TruthValue(
                name="workbuddy_job", value="空闲（没有在飞的开发任务）", status=FRESH_RUNTIME,
                source=ESCALATIONS,
                observed_at=datetime.fromtimestamp(
                    (self.root / ESCALATIONS).stat().st_mtime, tz=timezone.utc
                ).isoformat() if (self.root / ESCALATIONS).exists() else "",
                note="新能力由 Bootstrap 准备，不依赖失败触发",
            )
        record = active[0]
        stage = {
            "WORKING": "研发中", "SUBMITTED": "已提交", "VERSION_ACTIVATION_PENDING": "待生效",
            "LIVE_VERIFY_PENDING": "等真机验证",
        }.get(record.state, record.state)
        return TruthValue(
            name="workbuddy_job",
            value=f"{record.capability or record.skill} · {stage} · job {record.job_id or '-'}",
            status=FRESH_RUNTIME, source=ESCALATIONS,
            episode=record.job_id, role_id=self.role().role_id,
            note=f"起源 {record.origin or 'failure'}",
        )

    def bootstrap(self) -> TruthValue:
        """What the knowledge bootstrap is doing, from its own heartbeat."""
        payload = _read_json(self.root / STATE_PATH_BOOTSTRAP)
        if not payload:
            return TruthValue(
                name="bootstrap", value="", status=UNKNOWN, source=STATE_PATH_BOOTSTRAP,
                note="没有控制器状态文件：预载还没有在任何进程里跑过一轮",
            )
        stamp = str(payload.get("written_at") or "")
        status, age = self._stamp(STATE_PATH_BOOTSTRAP, stamp)
        state = str(payload.get("status") or "")
        from .capability_bootstrap import BOOTSTRAP_STATE_ZH, HEARTBEAT_BUDGET_SECONDS

        label = BOOTSTRAP_STATE_ZH.get(state, state or "?")
        # The budget comes from the module that owns the heartbeat rather than from the literal
        # ``3 * 600`` that used to stand here: that literal, the same rule spelled out on the
        # panel's 系统 page, and ``source_freshness``'s table disagreed by a factor of twelve, so
        # for five and a half hours the top bar could read 预载降级 while the 需要关注 card, built
        # from this very value's *file*, read 没有问题.
        if age is not None and age > HEARTBEAT_BUDGET_SECONDS:
            status = STALE
        return TruthValue(
            name="bootstrap",
            value=(f"{label} · 学习 {payload.get('learning') or '-'}"
                   f" · 预装 {payload.get('preloading') or '-'}"
                   f" · 等待验证 {payload.get('waiting_live_verify_count') or 0}"
                   f" · 下一个 {payload.get('next_capability') or '-'}"),
            status=status, source=STATE_PATH_BOOTSTRAP, observed_at=stamp, age_seconds=age,
            note=str(payload.get("decision") or ""),
        )

    def coverage(self) -> TruthValue:
        """The growth KPI, with the 24h delta taken from real per-capability timestamps."""
        catalog = _read_json(self.root / "knowledge/game/capability_catalog.json")
        rows = catalog.get("capabilities") or ()
        if not rows:
            return TruthValue(name="coverage", value="", status=UNKNOWN,
                              source="knowledge/game/capability_catalog.json")
        counts: dict[str, int] = {}
        recent_verified = 0
        for row in rows:
            life = str((row or {}).get("lifecycle") or "?")
            counts[life] = counts.get(life, 0) + 1
            stamp = _moment(str((row or {}).get("last_live_verified") or ""))
            if stamp is not None and (self.now - stamp).total_seconds() <= 24 * 3600:
                recent_verified += 1
        total = len(rows)
        verified = counts.get("LIVE_VERIFIED", 0)
        value = " · ".join(
            f"{k} {counts.get(k, 0)}" for k in
            ("OBSERVED", "CANDIDATE", "LIVE_TRIED", "LIVE_VERIFIED", "STABLE")
        )
        return TruthValue(
            name="coverage", value=value, status=CATALOG_DERIVED,
            source="knowledge/game/capability_catalog.json",
            observed_at=str(catalog.get("generated_at_utc") or catalog.get("generated_at") or ""),
            note=(f"全表 {total} 项中 LIVE_VERIFIED {verified}"
                  f"（{round(verified / total * 100, 1) if total else 0}%）"
                  f" · 最近24h 新增 {recent_verified}"),
        )

    # -- the attention centre -------------------------------------------------

    def anomalies(self) -> tuple[dict[str, Any], ...]:
        """Everything genuinely worth a human look, and nothing else.

        Built from the same projection as the rest, so a finding here is a fact with a
        source rather than a heuristic with a mood.  ``auto_recovered`` separates "this
        happened and healed" from "this is happening", because a list that stays red
        forever stops being read.
        """
        found: list[dict[str, Any]] = []

        def add(kind: str, at: str, detail: str, *, capability: str = "",
                auto_recovered: bool = False, status: str = "NEEDS_ATTENTION") -> None:
            found.append({
                "kind": kind, "at": at, "detail": detail, "capability": capability,
                "status": status, "auto_recovered": auto_recovered,
            })

        for conflict in self._conflicts:
            add("STATE_CONFLICT", self.now.isoformat(), conflict.describe())

        role = self.role()
        if role.status in (UNKNOWN, STALE):
            add("ROLE_IDENTITY_UNKNOWN", role.observed_at or self.now.isoformat(),
                f"角色身份 {STATUS_ZH.get(role.status, role.status)}；"
                f"role-scoped 结论在此期间不可信",
                auto_recovered=role.status == STALE)

        watchdog = self.watchdog()
        if watchdog.status == CONFLICT:
            add("RUNTIME_NOT_RUNNING", self.now.isoformat(), watchdog.note)

        jobs = self.workbuddy_jobs()
        if jobs.note and "未被消费" in jobs.note:
            add("WORKBUDDY_QUEUE_STUCK", jobs.observed_at or self.now.isoformat(), jobs.note)

        idle = self.why_idle()
        if idle.value == "UNEXPLAINED_IDLE":
            add("UNEXPLAINED_IDLE", idle.observed_at or self.now.isoformat(), idle.note or
                "超过静默阈值且 runtime 没有记录原因")

        boot = self.bootstrap()
        if boot.status == STALE:
            add("BOOTSTRAP_DEAD", boot.observed_at, "预载控制器心跳过期",
                auto_recovered=True)
        elif boot.status == UNKNOWN:
            add("BOOTSTRAP_NOT_STARTED", self.now.isoformat(), boot.note)

        mix = self.executor_mix()
        if mix.note.startswith("ADB 原因：fallback"):
            add("MAA_FALLBACK_SURGE", mix.observed_at, mix.note)

        # The two evidence-integrity findings, read off the production stream itself.
        recent = self._all_episodes[-40:]
        streak = 0
        for row in reversed(recent):
            if row.get("goal_progress") is False:
                streak += 1
            else:
                break
        if streak >= 10:
            add("REPEATED_NO_GOAL_PROGRESS", str(recent[-1].get("recorded_at") or ""),
                f"连续 {streak} 步 verifier 通过但目标无进展",
                capability=str(recent[-1].get("skill") or ""))

        for row in recent[-8:]:
            if row.get("verifier_ok") is True and str(row.get("result")) == "FAILURE":
                add("VERIFIER_CONFLICT", str(row.get("recorded_at") or ""),
                    f"verifier PASS 但 result FAILURE（{row.get('skill')}）",
                    capability=str(row.get("skill") or ""))
                break

        for row in reversed(self._all_episodes[-5:]):
            path = str(row.get("after_screenshot") or "")
            if path and not Path(path).exists():
                add("EVIDENCE_MISSING", str(row.get("recorded_at") or ""),
                    f"episode {row.get('episode_id')} 的 after 帧不在磁盘上",
                    capability=str(row.get("skill") or ""))
                break

        if self._reload_pending():
            add("RELOAD_PENDING", self.now.isoformat(), "有重载请求尚未生效")

        # The validation lease, which the operator saw buried in prose: "lease expired
        # without being released / process gone or hung".  Two different things were
        # being printed as one, and the first of them was not a fault at all: a lease
        # that was *released* still reported the orphan sentence because expiry was
        # checked before released_at (fixed in device_lease).  What remains here is the
        # real case -- held, window passed, nobody handed it back.
        lease_payload = _read_json(self.root / DEVICE_LEASE)
        if lease_payload and not lease_payload.get("released_at"):
            expires = _moment(str(lease_payload.get("expires_at") or ""))
            if expires is not None and expires < self.now:
                # auto_recovered: the expired lease is already not a holder, so gameplay
                # has the device back.  Reported so it is traceable, not so it alarms.
                add("VALIDATION_LEASE_ORPHANED", str(lease_payload.get("acquired_at") or ""),
                    f"校验租约（{lease_payload.get('owner')} / "
                    f"{lease_payload.get('capability_id') or '(未命名)'}）在 "
                    f"{expires.isoformat()} 过期且未被归还；TTL 已自动回收，"
                    f"当前租约：{self.device_lease().value}",
                    capability=str(lease_payload.get("capability_id") or ""),
                    auto_recovered=True, status="AUTO_RECOVERED")

        return tuple(found)

    def consistency(self) -> tuple[dict[str, str], ...]:
        """GUI field ↔ production source, compared field by field.

        Every row is ``displayed`` vs the source the window claims to read.  A mismatch is
        a ``STATE_CONFLICT`` -- never resolved here, because resolving it is exactly how
        the window and the runtime drifted apart in the first place.
        """
        rows: list[dict[str, str]] = []
        page = self.current_page()
        goal = self.current_goal()
        skill = self.current_skill()
        for name, value in (("current_page", page), ("current_goal", goal),
                            ("current_skill", skill), ("version_active", self.version_active()),
                            ("march_capacity", self.march_capacity())):
            rows.append({
                "field": name, "source": value.source, "source_value": value.value,
                "status": value.status,
                "agree": "yes" if not value.seen or
                         all(what == value.value for _, what in value.seen) else "no",
            })
        return tuple(rows)

    # -- the report --------------------------------------------------------

    def report(self) -> TruthReport:
        role = self.role()
        values = (
            role,
            self.current_page(), self.current_goal(), self.current_skill(),
            self.auto_state(), self.panel_heartbeat(),
            self.march_capacity(), self.resources(), self.queues(),
            self.feature_unlock(), self.event_state(), self.events(), self.gateway_health(),
            self.executor_backend(), self.version_active(), self.verifier(),
            self.workbuddy_jobs(), self.device_lease(), self.capability_lifecycle(),
            self.episode_role_scope(),
            # The control centre's own questions, derived from the same reading so the
            # window cannot hold a second opinion about any of them.
            self.maa_state(), self.executor_mix(), self.watchdog(), self.why_idle(),
            self.workbuddy_job(), self.bootstrap(), self.coverage(),
        )
        return TruthReport(
            values=values, conflicts=tuple(self._conflicts), role_id=role.role_id,
            role_status=role.status, head=self._head(),
            generated_at=self.now.isoformat(),
            anomalies=self.anomalies(), consistency=self.consistency(),
        )


def record_role(
    root: Path | str,
    identity: Any,
    *,
    evidence: Sequence[str] = (),
    observed_at: datetime | None = None,
    verification: str = "VISION_READ",
) -> Path:
    """Persist one read of the 领主档案 panel.

    The other half of the role chain.  The vision reader existed and was verified against
    an archived frame (``tools/cq_role_identity_verify.py``), but nothing ever wrote its
    answer anywhere -- so the window had no choice but to print a literal.  This is the
    only function that writes the artifact, and it refuses to write a read with no frame
    behind it: an identity without evidence is the thing that caused the original defect.

    ``observed_at`` is when the **frame** was captured, not when this ran.  A replay of an
    old frame stamped with ``now()`` would make an old observation look current -- the same
    error in the opposite direction, and the reason ``verification`` distinguishes a live
    read from a replay.
    """
    if not getattr(identity, "role_id", ""):
        raise ValueError("refusing to persist a role identity with no role_id")
    if not evidence:
        raise ValueError(
            "refusing to persist a role identity with no evidence frame: an identity "
            "without a frame is indistinguishable from a hardcoded one"
        )
    moment = observed_at or datetime.now(timezone.utc)
    path = Path(root) / ROLE_ARTIFACT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(identity.to_dict() if hasattr(identity, "to_dict") else identity)
    payload.update({
        "observed_at": moment.isoformat(),
        "evidence": list(evidence),
        "verification": verification,
        "written_by": "state_truth.record_role",
    })
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def legacy_event_row(
    legacy: Mapping[str, Any],
    *,
    now: datetime | None = None,
    role_id: str = "",
) -> dict[str, Any]:
    """Grade the single ``event_goal_state.json`` record: current, or history?

    Its own countdown decides.  A record that says ``remaining_seconds_at_verification``
    is an assertion about a window, and once more time has passed than that window held,
    the record describes an activity that has *ended* -- whatever its ``source`` field
    claims.  Measured 2026-09-18: ``最强王国·击败野兽`` with 28 795 s left, verified nine
    days earlier (781 965 s), still on screen as the running activity.

    Extracted from ``TruthAudit.events`` so the window classifies the record the same way
    the audit does.  One implementation, two callers -- a second copy in the panel is how
    the window and the audit end up disagreeing about the same file.
    """
    moment = now or datetime.now(timezone.utc)
    verified = _moment(str(legacy.get("verified_at") or ""))
    age = (moment - verified).total_seconds() if verified else None
    try:
        remaining = legacy.get("remaining_seconds_at_verification")
        remaining = float(remaining) if remaining is not None else None
    except (TypeError, ValueError):
        remaining = None
    window_closed = age is not None and remaining is not None and age > remaining
    # Two independent expiry rules, and the first one to fire wins.  The record's *own*
    # countdown is the sharp one; the age ceiling is the only rule available to a record
    # that saved no countdown, and it is what makes a record expire on its own.
    #
    # Why an explicit ceiling exists at all, measured 2026-10-04: ``event_goal_state.json``
    # was 595 h old and **no process had ever refreshed it** -- it is a hand-recorded live
    # observation (``source`` LIVE_CLIENT, its ``resource_spent`` is Chinese prose), and a
    # tree-wide search finds no writer for the path anywhere in ``winter_agent_v2/`` or
    # ``tools/``.  Waiting for a refresh that does not exist is not a plan, so the record
    # has to expire by itself.
    past_ttl = age is not None and age > EVENT_CURRENT_SECONDS
    expired = bool(window_closed or past_ttl or age is None)
    if window_closed:
        status, why = HISTORY, (
            f"记录的活动窗口早已结束：记录时剩余 {int(remaining)} 秒，"
            f"而这条记录已过去 {age / 3600:.0f} 小时"
        )
    elif past_ttl:
        status, why = HISTORY, (
            f"记录已过期（TTL {EVENT_CURRENT_SECONDS / 3600:.0f} 小时）："
            f"这条记录已过去 {age / 3600:.0f} 小时，且没有任何进程刷新过它"
        )
    elif age is not None:
        status, why = LIVE_OBSERVED, "记录的验证时间在本活动的新鲜度预算内"
    else:
        status, why = UNKNOWN, "没有验证时间"
    return {
        "event_id": str(legacy.get("event_id") or ""),
        "event_name": str(legacy.get("name") or ""),
        "status": status,
        "source": f"{EVENT_STATE}（记录时来源 {legacy.get('source') or '?'}）",
        "observed_at": str(legacy.get("verified_at") or ""),
        "age_seconds": None if age is None else round(age, 1),
        "freshness": STATUS_ZH.get(status, status),
        "confidence": 0.0 if status != LIVE_OBSERVED else 0.99,
        "started_at": "",
        "ends_at": "",
        "remaining_seconds_at_verification": remaining,
        # The expiry verdict travels with the row so that no reader has to re-derive it --
        # which is how the window and the audit come to disagree about the same file.  The
        # window renders ``待重新观测`` straight off ``expired``.
        "expired": expired,
        "ttl_seconds": EVENT_CURRENT_SECONDS,
        "progress": {
            "current": legacy.get("current_points"),
            "target": legacy.get("target_points"),
            "missing": legacy.get("points_missing"),
        },
        "claimable": bool(
            legacy.get("minimum_guarantee_complete") is False and status == LIVE_OBSERVED
        ),
        "role_id": role_id,
        "evidence": (),
        "planner_usable": status in (LIVE_OBSERVED, FRESH_RUNTIME),
        "note": why,
        "raw": dict(legacy),
    }


def legacy_event_row_for(root: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    """Convenience for the window: classify the saved record, or ``{}`` when there is none."""
    payload = _read_json(Path(root) / EVENT_STATE)
    if not (payload.get("name") or payload.get("event_id")):
        return {}
    return legacy_event_row(payload, now=now)


def audited_names() -> tuple[str, ...]:
    """The state names this projection answers for.  One list, so a test can hold it."""
    return (
        "current_role", "current_page", "current_goal", "current_skill",
        "auto_state", "panel_heartbeat", "march_capacity", "resources", "queues",
        "feature_unlock", "event_state", "events", "gateway_health",
        "executor_backend", "version_active",
        "verifier", "workbuddy_jobs", "device_lease", "capability_lifecycle",
        "episode_role_scope",
        # the control centre's own questions
        "maa_state", "executor_mix", "watchdog", "why_idle", "workbuddy_job",
        "bootstrap", "coverage",
    )


def scannable_state_names(source: str) -> tuple[str, ...]:
    """State names a *source file* may be allowed to carry as a literal.

    Used by the invariant test: a GUI that hard-codes a ``name="value"`` cell for one of
    these is claiming an observation it never made.  Kept here rather than in the test so
    the list cannot drift away from :func:`audited_names`.
    """
    return tuple(name for name in audited_names() if name in source)
