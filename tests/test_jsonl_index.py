from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from winter_agent_v2.jsonl_index import JsonlIndex, forget, index_for


def _row(i: int, **extra) -> dict:
    return {"i": i, "skill": f"S{i % 3}", "recorded_at": f"2026-10-04T00:00:{i:02d}+00:00", **extra}


def _write(path: Path, rows) -> bytes:
    blob = b"".join(
        (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8") for row in rows
    )
    path.write_bytes(blob)
    return blob


def _project(row) -> tuple:
    return (row.get("i"), row.get("skill"))


@pytest.fixture(autouse=True)
def _isolate_cache():
    forget()
    yield
    forget()


# --------------------------------------------------------------- equivalence


def test_the_index_says_what_a_whole_file_read_says(tmp_path: Path):
    """The whole contract: every line, in order, same dicts.  Nothing is skipped."""
    path = tmp_path / "episodes.jsonl"
    _write(path, [{"i": i, "pad": "x" * (7 * i)} for i in range(120)])

    reference = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    index = JsonlIndex(path, _project)

    assert index.load_all(index.rows()) == reference


def test_load_reads_the_matching_bytes_and_nothing_else(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    _write(path, [{"i": i, "pad": "y" * 200} for i in range(50)])
    index = JsonlIndex(path, _project)
    rows = index.rows()

    wanted = [row for row in rows if row.fields[0] in {3, 17, 49}]
    assert [row["i"] for row in index.load_all(wanted)] == [3, 17, 49]

    total = sum(row.span for row in wanted)
    assert total < path.stat().st_size // 4, "three rows must not cost a whole-file read"


def test_the_projection_decides_what_is_indexed(tmp_path: Path):
    path = tmp_path / "x.jsonl"
    _write(path, [{"keep": True, "i": 1}, {"keep": False, "i": 2}, "not an object", {"keep": True, "i": 3}])

    index = JsonlIndex(path, lambda row: (row.get("i"),) if row.get("keep") else None)
    assert [row.fields[0] for row in index.rows()] == [1, 3]


# ------------------------------------------------------ growth and the cache


def test_a_second_call_reads_no_bytes(tmp_path: Path):
    """The point of the module: once the file is indexed, asking again is a stat plus a
    couple of fingerprint reads -- no line is re-parsed."""
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(200)])
    index = JsonlIndex(path, _project)

    first = index.rows()
    with patch.object(JsonlIndex, "_consume", side_effect=AssertionError("re-read the file")):
        second = index.rows()

    assert first == second


def test_an_appended_row_appears_without_re_reading_the_rest(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(200)])
    index = JsonlIndex(path, _project)
    before = index.rows()

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_row(900)) + "\n")
    after = index.rows()

    assert len(after) == len(before) + 1
    assert after[: len(before)] == before
    assert after[-1].fields[0] == 900


def test_the_bytes_consumed_after_an_append_are_the_bytes_appended(tmp_path: Path):
    """Measured on the index's own input, not on the process's I/O: the whole file is consumed
    once, and after that a call consumes only what was appended."""
    path = tmp_path / "episodes.jsonl"
    _write(path, [{"i": i, "pad": "z" * 400} for i in range(500)])
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 500

    blob = (json.dumps({"i": 10_000, "pad": "z" * 400}) + "\n").encode("utf-8")
    with path.open("ab") as handle:
        handle.write(blob)

    consumed: list[int] = []
    real_consume = JsonlIndex._consume

    def spy(self, state, other, offset):
        consumed.append(len(other))
        return real_consume(self, state, other, offset)

    with patch.object(JsonlIndex, "_consume", spy):
        rows = index.rows()

    assert len(rows) == 501
    assert consumed == [len(blob)], f"consumed {consumed} for a {len(blob)}-byte append"


# ------------------------------------------------------- the four changes


def test_a_rewrite_in_place_that_moves_the_head_is_caught(tmp_path: Path):
    """Only the first row changes, so both files have the same length and the same last 64
    bytes; the head is the only fingerprint that moves."""
    path = tmp_path / "episodes.jsonl"
    rest = [{"i": i, "v": "ccc"} for i in range(1, 40)]
    _write(path, [{"i": 0, "v": "aaa"}, *rest])
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 40

    _write(path, [{"i": 0, "v": "bbb"}, *rest])
    rows = index.rows()

    assert len(rows) == 40, "a rebuilt index must not append to the old entries"
    assert index.load_all(rows)[0]["v"] == "bbb"


def test_a_rewrite_in_place_that_moves_only_the_consumed_tail_is_caught(tmp_path: Path):
    """The head is the oldest row and an append-only log never rewrites it, so the head alone
    would miss a rewrite confined to the end.  The consumed-tail fingerprint is what catches it."""
    path = tmp_path / "episodes.jsonl"
    head_rows = [{"i": 0, "v": "same"}, *[{"i": i, "v": "ccc"} for i in range(1, 39)]]
    _write(path, [*head_rows, {"i": 39, "v": "aaa"}])
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 40

    _write(path, [*head_rows, {"i": 39, "v": "zzz"}])
    rows = index.rows()

    assert len(rows) == 40, "a rebuilt index must not append to the old entries"
    assert index.load_all(rows)[-1]["v"] == "zzz"


def test_a_truncation_is_caught(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(80)])
    index = JsonlIndex(path, _project)
    index.rows()

    _write(path, [_row(1)])
    rows = index.rows()

    assert len(rows) == 1
    assert rows[0].fields[0] == 1


def test_a_rotation_is_caught(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(80)])
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 80

    replacement = tmp_path / "next.jsonl"
    _write(replacement, [_row(1), _row(2)])
    replacement.replace(path)

    rows = index.rows()
    assert len(rows) == 2
    assert [row.fields[0] for row in rows] == [1, 2]


def test_a_same_length_rewrite_is_caught_by_the_mtime(tmp_path: Path):
    """Both fingerprints can survive a rewrite that changes neither the first nor the last 64
    bytes.  That is the one blind spot, and the mtime is the fallback that keeps it bounded.

    The mtime is moved explicitly rather than by writing twice, so the test measures the
    fallback instead of the filesystem's timestamp granularity.
    """
    path = tmp_path / "episodes.jsonl"
    blob = _write(path, [{"i": i, "pad": "0123456789"} for i in range(8)])
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 8

    with path.open("wb") as handle:  # identical bytes, same length
        handle.write(blob)
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))

    rebuilt: list[int] = []
    real_consume = JsonlIndex._consume

    def spy(self, state, other, offset):
        rebuilt.append(len(other))
        return real_consume(self, state, other, offset)

    with patch.object(JsonlIndex, "_consume", spy):
        rows = index.rows()

    assert rebuilt == [len(blob)], "a moved mtime with an unchanged length must re-read"
    assert len(rows) == 8


# --------------------------------------------------- the trailing partial line


def test_a_trailing_line_without_a_newline_is_still_a_row(tmp_path: Path):
    """``read_text(...).splitlines()`` parses it, so not parsing it would be a row silently
    missing -- the failure mode this whole module exists to avoid."""
    path = tmp_path / "episodes.jsonl"
    path.write_bytes(
        (json.dumps(_row(1)) + "\n").encode()
        + json.dumps(_row(2)).encode()  # no trailing newline
        + b"\n"
        + json.dumps(_row(3)).encode()
    )

    index = JsonlIndex(path, _project)
    assert [row.fields[0] for row in index.rows()] == [1, 2, 3]


def test_a_row_is_not_counted_twice_when_its_newline_lands(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    path.write_bytes((json.dumps(_row(1)) + "\n").encode() + json.dumps(_row(2)).encode())
    index = JsonlIndex(path, _project)
    assert [row.fields[0] for row in index.rows()] == [1, 2]

    with path.open("ab") as handle:
        handle.write(b"\n")
    assert [row.fields[0] for row in index.rows()] == [1, 2], "the provisional row became a settled one"


def test_an_unfinished_row_is_not_a_row_until_it_is_one(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    path.write_bytes(b'{"i": 1, "skill": "S1", "recorded_at": "2026-10-04T00:00:01+00:00"}\n')
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 1

    with path.open("ab") as handle:  # half a row, still being written
        handle.write(b'{"i": 2, "skill": "S2", "recor')
    assert len(index.rows()) == 1

    with path.open("ab") as handle:
        handle.write(b'ded_at": "2026-10-04T00:00:02+00:00"}\n')
    assert [row.fields[0] for row in index.rows()] == [1, 2]


# --------------------------------------------------------------- robustness


def test_a_malformed_byte_costs_one_row_not_the_reader(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    path.write_bytes(
        (json.dumps(_row(1)) + "\n").encode()
        + b'{"i": 2, "broken": "\xff\xfe"}\n'
        + (json.dumps(_row(3)) + "\n").encode()
    )

    index = JsonlIndex(path, lambda row: (row.get("i"),))
    assert [row.fields[0] for row in index.rows()] == [1, 2, 3]


def test_a_line_that_is_not_an_object_is_skipped_not_fatal(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    path.write_bytes(
        b"\n"
        + b"[1, 2, 3]\n"
        + b"not json at all\n"
        + (json.dumps(_row(1)) + "\n").encode()
        + b"   \n"
    )

    index = JsonlIndex(path, lambda row: (row.get("i"),))
    assert [row.fields[0] for row in index.rows()] == [1]


def test_a_row_containing_u0085_is_one_row(tmp_path: Path):
    """``b"\\n"`` is the only separator.  ``str.splitlines()`` also breaks on U+0085, which would
    cut this row into two pieces that both fail to parse -- a silent drop.  Checked against the
    live log on 2026-10-04: both readings agreed on all 10,147 lines, so nothing changes today;
    this pins the separator so it cannot start mattering by accident."""
    path = tmp_path / "episodes.jsonl"
    row = {"i": 1, "text": "a\u0085b"}
    _write(path, [row])

    index = JsonlIndex(path, lambda r: (r.get("i"),))
    loaded = index.load_all(index.rows())
    assert loaded == [row]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2, (
        "splitlines still splits it; that is the reading this module does not use"
    )


def test_a_multibyte_row_never_lands_on_a_split_boundary(tmp_path: Path):
    """The offset only ever advances past a newline, so a 3-byte character can never be cut."""
    path = tmp_path / "episodes.jsonl"
    _write(path, [{"i": i, "text": "中文测试" * (i + 1)} for i in range(60)])
    index = JsonlIndex(path, lambda row: (row.get("i"),))

    for _ in range(60):  # every call re-reads the offset region; none may mis-decode
        rows = index.rows()
        assert [row.fields[0] for row in rows] == list(range(60))
        assert index.load_all(rows)[-1]["text"] == "中文测试" * 60


def test_a_missing_file_is_empty_not_an_error(tmp_path: Path):
    index = JsonlIndex(tmp_path / "nope.jsonl", _project)
    assert index.rows() == ()
    assert index.load_all(()) == []


def test_a_stat_failure_is_empty_and_does_not_poison_the_next_call(tmp_path: Path):
    """A file that cannot be stat-ed is answered as empty, and the state is reset rather than
    kept -- so the moment it is readable again the index rebuilds instead of continuing from an
    offset that no longer describes anything.

    Simulated by failing ``stat`` rather than by unlinking: the point is the reader's behaviour
    when the file cannot be measured, and a test that deletes files is a test the host's
    safe-delete guard can interrupt for reasons that have nothing to do with this module.
    """
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(10)])
    index = JsonlIndex(path, _project)
    assert len(index.rows()) == 10

    with patch.object(Path, "stat", side_effect=OSError("the file went away")):
        assert index.rows() == ()

    assert len(index.rows()) == 10, "the index must rebuild once the file can be read again"


# ------------------------------------------------------------- the registry


def test_index_for_returns_one_index_per_path_and_tag(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(10)])

    first = index_for(path, _project, tag="a")
    assert index_for(path, _project, tag="a") is first
    assert index_for(path, _project, tag="b") is not first, "a second projection needs its own index"


def test_two_tags_do_not_rebuild_each_other(tmp_path: Path):
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(50)])

    one = index_for(path, lambda row: (row.get("i"),), tag="i")
    two = index_for(path, lambda row: (row.get("skill"),), tag="skill")
    one.rows()
    two.rows()  # both indexed once; from here on neither may re-read a line

    with patch.object(JsonlIndex, "_consume", side_effect=AssertionError("re-read the file")):
        assert len(two.rows()) == 50
        assert len(one.rows()) == 50


def test_forget_drops_a_single_path(tmp_path: Path):
    keep = tmp_path / "keep.jsonl"
    drop = tmp_path / "drop.jsonl"
    _write(keep, [_row(1)])
    _write(drop, [_row(1)])
    kept = index_for(keep, _project, tag="t")
    index_for(drop, _project, tag="t")

    forget(drop)
    assert index_for(drop, _project, tag="t") is not kept
    assert index_for(keep, _project, tag="t") is kept


# ------------------------------------------------------------ concurrency


def test_readers_can_ask_while_another_appends(tmp_path: Path):
    """One tick, one pump and the panel's own page all read the same log."""
    path = tmp_path / "episodes.jsonl"
    _write(path, [_row(i) for i in range(400)])
    index = JsonlIndex(path, _project)
    index.rows()

    stop = threading.Event()
    seen: list[list[int]] = [[] for _ in range(3)]
    errors: list[BaseException] = []

    def reader(slot: int):
        try:
            while not stop.is_set():
                seen[slot].append(len(index.rows()))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def writer():
        try:
            for i in range(400, 800):
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(_row(i)) + "\n")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            stop.set()

    threads = [threading.Thread(target=reader, args=(slot,)) for slot in range(3)]
    threads.append(threading.Thread(target=writer))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    # Each reader's own sequence must never go backwards: a reader that saw 700 rows and then
    # 650 would mean the index dropped what it had already answered with.
    for slot, counts in enumerate(seen):
        assert counts, f"reader {slot} never ran"
        assert counts[0] >= 400
        assert all(a <= b for a, b in zip(counts, counts[1:])), f"reader {slot} went backwards"
    # And the writer's last row is there once everything has stopped -- asserted from a fresh
    # call rather than from a reader's last sample, which can legitimately predate the last
    # append (the writer sets the stop flag immediately after writing it).
    assert len(index.rows()) == 800
    assert [row.fields[0] for row in index.rows()][-1] == 799
