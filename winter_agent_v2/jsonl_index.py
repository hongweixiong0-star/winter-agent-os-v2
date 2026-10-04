"""A byte-offset index over an append-only JSONL log.

Why this exists
---------------
``learning/episodes.jsonl`` passed 158 MB at ~15 KB per row, because each row carries the
run's own step trace.  Three readers on the panel's refresh path parsed that file from byte
0 to answer questions about rows recorded in the last few hours, and two of them are called
*per record*, so the cost was paid several times per tick:

    new_live_episodes(...)        1836 ms      0 rows matched
    failures_since(...)           1566 ms     83 rows matched
    unattended_closure.rows(...)    72 ms

A tail read is the obvious answer and it is not a safe one.  Nothing enforces that the log
is sorted by ``recorded_at``.  Measured 2026-10-04: 10,137 stamped rows, 0 inversions -- so
it *is* sorted today, but a row appended out of order (imported history, a clock step) would
be skipped by a tail read, and on this log that means the gate that grants ``LIVE_VERIFIED``
quietly stops counting proofs.  A silent under-count in that gate is the one failure this
project cannot absorb, so an empirical "it looks sorted" is not good enough.

Nothing here is skipped.  Every line is still parsed and still offered to the caller's own
projection, so the caller's predicate sees exactly the rows it sees today.  What is cached is
the *parse*: one pass over the bytes, then on each later call only the bytes appended since
the last one.  Per line the index keeps its byte range plus whatever small projection the
caller asked for; the full dict is rebuilt only for the rows that pass, by reading back
exactly those bytes.

Division of labour (operator's rule, 2026-10-04) is untouched: this is not a background
thread and not a cache of an answer.  It removes I/O rather than moving it, and the caller
still decides what a row means.

Identity, and the four ways a JSONL file changes
------------------------------------------------
A cached parse is only valid while the bytes it was made from are unchanged, so every call
compares a fresh ``stat`` against the identity the entries were built under.

============== =============================================================
append         ``size > offset``: the only growth this design reads, and the
               only change an append-only log makes.  Read ``[offset, size)``.
in-place       same length, head or consumed-tail fingerprint moved, or the
               mtime moved with the length unchanged.  Rebuilt from zero.
rotation       ``os.replace`` swaps the inode: ``st_ino`` moved.  Rebuilt.
truncation     ``size < offset``.  Rebuilt.
============== =============================================================

The fingerprint is the file's first :data:`FINGERPRINT_BYTES` plus the last
:data:`FINGERPRINT_BYTES` of the region already consumed -- the head is the oldest row, which
an append-only log never rewrites, and the consumed tail catches a rewrite in place that
leaves the head alone.  A rewrite confined to the middle, with both fingerprints intact, is
the one blind spot; the mtime fallback above is what keeps it from being silent for the
shapes tests actually produce.

The offset never advances past a byte that is not a newline, so it is always a valid
``seek`` target and can never split a multi-byte character.  Nothing about the trailing
partial line is stored: every call re-reads from the offset, so a line whose newline has not
landed yet is parsed as it stands, then re-derived once the write completes.  That is the
answer ``read_text(...).splitlines()`` would give, without the read -- and it is why this
class cannot double-count a row that was already consumed.

One deliberate difference from the readers this replaces: they decoded with
``errors="replace"`` (``unattended_closure``) or strictly (``new_live_episodes``, where a bad
byte raised ``UnicodeDecodeError`` out of the caller).  This decodes with
``errors="replace"`` always: a malformed byte costs one row instead of taking down a refresh.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

__all__ = ["Row", "JsonlIndex", "index_for", "forget", "FINGERPRINT_BYTES"]

#: How much of the head, and how much of the consumed tail, take part in the identity check.
FINGERPRINT_BYTES = 64

_INDEX_LOCK = threading.Lock()
_INDEX_CACHE_LIMIT = 8
#: (normalised path, tag) -> index.  The tag is the caller's, and it exists because two
#: readers of one file may want different projections: a single entry per path would make
#: them rebuild each other's index on every call, which is the cost this module removes.
_INDEX_CACHE: dict[tuple[str, str], "JsonlIndex"] = {}


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


@dataclass(frozen=True)
class Row:
    """One line of the log: where its bytes are, and the caller's projection of it.

    ``fields`` is kept exactly as the projection returned it, so a projection that returns a
    ``NamedTuple`` stays readable at the use site instead of becoming a positional tuple.
    """

    start: int
    end: int
    fields: Any

    @property
    def span(self) -> int:
        return self.end - self.start


@dataclass
class _State:
    """Everything the index remembers about one file, under one lock."""

    st_dev: int = -1
    st_ino: int = -1
    head: bytes = b""
    consumed_tail: bytes = b""
    mtime_ns: int = 0
    #: Absolute byte offset consumed so far.  Always just past a ``b"\\n"``.
    offset: int = 0
    #: Entries derived from complete lines.  A trailing line without a newline gets a
    #: provisional entry that is *not* stored here, so it can be re-derived every call.
    entries: list[Row] = field(default_factory=list)

    def identity(self) -> tuple[int, int, bytes, bytes]:
        return (self.st_dev, self.st_ino, self.head, self.consumed_tail)

    def reset(self) -> None:
        self.st_dev = -1
        self.st_ino = -1
        self.head = b""
        self.consumed_tail = b""
        self.mtime_ns = 0
        self.offset = 0
        self.entries = []


def _tail_of(handle: Any, offset: int) -> bytes:
    """The last :data:`FINGERPRINT_BYTES` bytes of ``[0, offset)``; ``b""`` when empty."""
    back = min(FINGERPRINT_BYTES, offset)
    if not back:
        return b""
    handle.seek(offset - back)
    return handle.read(back)


class JsonlIndex:
    """Parse-once, grow-incrementally view of one append-only JSONL file.

    ``project`` is called once per parsed line and returns whatever small tuple the caller
    needs to test that row.  Returning ``None`` skips the line entirely (a JSON scalar, or a
    key the caller never wants).  Rows that pass are turned back into dicts with
    :meth:`load_all`, which reads only their own bytes.
    """

    def __init__(
        self,
        path: Path | str,
        project: Callable[[Mapping[str, Any]], Any],
        *,
        tag: str = "",
        encoding: str = "utf-8",
        errors: str = "replace",
    ) -> None:
        self.path = Path(path)
        self.project = project
        self.tag = tag
        self.encoding = encoding
        self.errors = errors
        self._state = _State()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ reading

    def rows(self) -> tuple[Row, ...]:
        """Every line's byte range and projection, reading only what is new.

        No line is skipped and no field is guessed, so this is the whole file as far as the
        caller is concerned -- for the cost of the bytes appended since the last call.
        """
        path = self.path
        try:
            info = path.stat()
        except OSError:
            with self._lock:
                self._state.reset()
            return ()

        leftover_at = 0
        leftover = b""
        with self._lock, path.open("rb") as handle:
            state = self._state
            head = handle.read(FINGERPRINT_BYTES)
            seen_tail = _tail_of(handle, state.offset)

            stale = (
                state.identity() != (info.st_dev, info.st_ino, head, seen_tail)
                or info.st_size < state.offset
                or (info.st_size == state.offset and state.mtime_ns != info.st_mtime_ns)
            )
            if stale:
                state.reset()

            if state.offset < info.st_size:
                handle.seek(state.offset)
                leftover_at, leftover = self._consume(state, handle.read(), state.offset)

            state.st_dev = info.st_dev
            state.st_ino = info.st_ino
            state.head = head
            state.consumed_tail = _tail_of(handle, state.offset)
            state.mtime_ns = info.st_mtime_ns
            settled = tuple(state.entries)

        provisional = self._provisional(leftover_at, leftover)
        return settled + (provisional,) if provisional is not None else settled

    def load(self, row: Row) -> dict[str, Any] | None:
        """The full row ``row`` describes, read back from its own bytes."""
        loaded = self.load_all((row,))
        return loaded[0] if loaded else None

    def load_all(self, rows: Iterable[Row]) -> list[dict[str, Any]]:
        """The full rows, in order, for the byte ranges given.  Opens the file once."""
        wanted = list(rows)
        if not wanted:
            return []
        out: list[dict[str, Any]] = []
        try:
            with self.path.open("rb") as handle:
                for row in wanted:
                    handle.seek(row.start)
                    parsed = self._parse(handle.read(row.end - row.start))
                    if parsed is not None:
                        out.append(parsed)
        except OSError:
            return out
        return out

    def identity(self) -> tuple[int, int]:
        """``(st_dev, st_ino)`` as of the last call, for a caller that wants to notice a
        rotation itself.  ``(-1, -1)`` before the first :meth:`rows`."""
        with self._lock:
            return (self._state.st_dev, self._state.st_ino)

    # ------------------------------------------------------------------ internals

    def _parse(self, blob: bytes) -> dict[str, Any] | None:
        """One line's bytes as a dict, or ``None`` when it is not one.

        ``b"\\n"`` is the only separator, and it is the right one for JSONL: unlike
        ``str.splitlines()`` it cannot break a row on U+0085 or U+2028.  Checked on the live
        log on 2026-10-04 -- ``b"\\n"`` and ``splitlines()`` agreed exactly, 10,147 lines
        each -- so this is a latent-difference fix, not a change in what the readers see.
        """
        line = blob.strip()
        if not line.startswith(b"{"):
            return None
        try:
            payload = json.loads(line.decode(self.encoding, errors=self.errors))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _consume(self, state: _State, blob: bytes, offset: int) -> tuple[int, bytes]:
        """Index every complete line in ``blob``; return ``(offset_after, leftover)``.

        ``leftover`` is the tail after the last newline.  It is returned rather than stored,
        and ``offset`` is not advanced past it, so the next call re-reads those bytes -- which
        is what makes an in-flight write converge instead of being consumed twice.
        """
        cut = blob.rfind(b"\n")
        if cut < 0:
            return offset, blob

        consumed = offset
        for line in blob[: cut + 1].split(b"\n")[:-1]:
            start = consumed
            consumed += len(line) + 1
            parsed = self._parse(line)
            if parsed is None:
                continue
            fields = self.project(parsed)
            if fields is None:
                continue
            state.entries.append(Row(start, consumed, fields))
        state.offset = consumed
        return consumed, blob[cut + 1 :]

    def _provisional(self, start: int, blob: bytes) -> Row | None:
        """The entry for a trailing line with no newline yet, if it is already one.

        ``read_text(...).splitlines()`` would have parsed it, so not parsing it would be a row
        silently missing.  It lives outside the state, so the moment the newline lands the
        real entry replaces it rather than joining it.
        """
        if not blob.strip():
            return None
        parsed = self._parse(blob)
        if parsed is None:
            return None
        fields = self.project(parsed)
        if fields is None:
            return None
        return Row(start, start + len(blob), fields)


def index_for(
    path: Path | str,
    project: Callable[[Mapping[str, Any]], Any],
    *,
    tag: str = "",
) -> JsonlIndex:
    """The shared index for ``(path, tag)``, creating it on first use.

    Shared rather than per-caller because the whole point is to parse the file once: a second
    instance would re-read every byte the first one already has.  Callers that want a
    different projection must pass a different ``tag``, which is also what keeps two readers
    of one file from rebuilding each other's index on every call.
    """
    key = (_norm(path), tag)
    with _INDEX_LOCK:
        found = _INDEX_CACHE.get(key)
        if found is None:
            # Oldest out rather than everything out: clearing the whole cache would make a
            # caller that reads a different path each time (a test suite) rebuild the log it
            # just indexed.  Insertion order is the eviction order.
            while len(_INDEX_CACHE) >= _INDEX_CACHE_LIMIT:
                _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
            found = JsonlIndex(path, project, tag=tag)
            _INDEX_CACHE[key] = found
        return found


def forget(path: Path | str | None = None) -> None:
    """Drop cached indexes.  ``None`` drops every one.  For tests, and for a caller that knows
    the file was replaced rather than appended to."""
    with _INDEX_LOCK:
        if path is None:
            _INDEX_CACHE.clear()
            return
        target = _norm(path)
        for key in [k for k in _INDEX_CACHE if k[0] == target]:
            _INDEX_CACHE.pop(key, None)
