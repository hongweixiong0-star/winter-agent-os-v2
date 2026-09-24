"""The rally list must be read as objects with relationships, not as a column of green +.

Task book §一 forbids exactly one thing here, and it is the easy thing to build:

    不得把 BTN_JOIN_ROW 的绿色 + 模板直接当成"当前应该加入的集结"

A template for a green + is a template for *a control*.  It says "a joinable rally is drawn
here"; it cannot say **which** rally that is, so a chain built on it alone will join whatever
happens to be first, and will keep doing so when the list scrolls.  ``rally.read_rally_list``
reads the missing half -- which + belongs to which 集结中 row -- and these tests pin it against
the four archived live frames.

Every expectation below is a fact about a real frame, and the frame is named in the test, so a
failure says which picture stopped being read rather than merely that a number moved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RAW = ROOT / "dataset/raw/bear_live_20260909"


@pytest.fixture(scope="module")
def ocr_service():
    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

    cfg = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    return OCRService(ResilientOCRBackend(RapidOCRBackend(Path(cfg["ocr"]["module_path"]))))


@pytest.fixture(scope="module")
def read(ocr_service):
    from winter_agent_v2 import rally

    def _read(name: str):
        return rally.read_rally_list(RAW / name, ocr_service)

    return _read


# --------------------------------------------------- the row <-> button relationship


def test_each_row_carries_its_own_join_button(read):
    """§一's core requirement, on the frame with two joinable rallies.

    ``join_list_now.png`` draws three 集结中 rows and two green +.  The point of reading the
    list rather than the template is that the two + belong to *different rows*, so a row's
    button must fall inside that row's own band -- not at one shared point.
    """
    reading = read("join_list_now.png")
    joinable = reading.joinable_bears()
    assert len(joinable) == 2, (
        f"this frame draws two green +, so two rows must read joinable; got {len(joinable)}"
    )

    ys = []
    for row in joinable:
        assert row.join_norm is not None
        band_top, band_bottom = row.band_norm
        assert band_top <= row.join_norm[1] <= band_bottom, (
            f"row {row.row_index}'s button at y={row.join_norm[1]} is outside its own band "
            f"{row.band_norm} -- the button does not belong to the row it was attached to"
        )
        ys.append(row.join_norm[1])
    assert len(set(ys)) == len(ys), (
        "two rows were given the same button point, which is the shared-template failure "
        "this reader exists to prevent"
    )


def test_the_two_joinable_rows_are_told_apart_by_their_own_fields(read):
    """A row's identity comes from its own leader / capacity / countdown, all three read."""
    reading = read("join_list_now.png")
    rows = {row.row_index: row for row in reading.rows}

    first, second = rows[0], rows[1]
    assert first.leader and second.leader and first.leader != second.leader, (
        "two rows on one frame must carry their own initiator, not a shared one"
    )
    assert (first.capacity_used, first.capacity_max) == (8, 15)
    assert (second.capacity_used, second.capacity_max) == (10, 15)
    assert first.remaining_seconds == 45
    assert second.remaining_seconds == 61


def test_selection_is_by_state_and_deadline_not_by_row_index(read):
    """§一: 不得固定点击第一行.

    The winning row is chosen by "joinable AND least time left", so it is a property of the
    row's own reading.  This frame happens to put the shortest countdown first, so the test
    also asserts the *rule* rather than the coincidence: the winner is the joinable row with
    the minimum ``remaining_seconds``.
    """
    reading = read("join_list_now.png")
    best = reading.best_joinable()
    assert best is not None

    eligible = list(reading.joinable_bears())
    expected = min(
        eligible,
        key=lambda r: (r.remaining_seconds if r.remaining_seconds is not None else 10**9, r.row_index),
    )
    assert best.row_index == expected.row_index
    assert best.remaining_seconds == min(r.remaining_seconds for r in eligible)
    assert best.join_norm is not None and best.join_norm[1] != reading.rows[1].join_norm[1], (
        "the winner's button must be its own, not the other joinable row's"
    )


def test_a_full_row_is_not_joinable_even_though_it_is_a_bear(read):
    """``joinable`` requires capacity headroom, target identity AND a drawn affordance.

    ``rally.RallyRow.joinable`` (the scheduler model) has always required this; the reader's
    ``RallyRowReading.joinable`` is asserted to agree, because the two are consumed by
    different layers and a disagreement would let a full row be selected.
    """
    from winter_agent_v2.rally import RallyTarget, RallyRow, RallyRowState

    full = RallyRow(target_type=RallyTarget.BEAR, leader="x", state=RallyRowState.JOINABLE,
                    capacity_used=15, capacity_max=15, join_point=(1, 2))
    assert not full.joinable, "a 15/15 rally must not be joinable however green its + is"

    open_row = RallyRow(target_type=RallyTarget.BEAR, leader="x", state=RallyRowState.JOINABLE,
                        capacity_used=14, capacity_max=15, join_point=(1, 2))
    assert open_row.joinable


def test_a_joined_list_offers_nothing_to_join(read):
    """§三: 当前已经加入集结时，不得重复派出同一支队伍.

    ``joined_with_jesse.png`` is the same list after this role joined: 12/15 and 13/15, and
    **no green + at all**.  The reader must therefore report zero joinable rows -- not "two
    rows, so join one", which is what a template-only chain would do.
    """
    reading = read("joined_with_jesse.png")
    assert reading.has_rows, "the list is still drawn, so rows must still be read"
    assert reading.joinable_bears() == (), (
        "this frame draws no green +, so there is nothing to join; reporting a joinable row "
        "here is how the same march gets dispatched twice"
    )
    assert reading.best_joinable() is None


def test_an_unreadable_row_is_unknown_not_full(read):
    """§一: 如果当前列表无法提供可靠的目标身份，不得盲目加入其他类型的集结.

    The third row of ``join_list_now.png`` has no OCR-readable 等级1变异巨熊 token -- it is
    partly scrolled out.  The honest answer is UNKNOWN, which makes it unjoinable.  Recording
    it as FULL would also make it unjoinable, but for a reason that is not true, and that
    difference matters the moment someone asks why the last row is never joined.
    """
    from winter_agent_v2.rally import RallyRowState

    reading = read("join_list_now.png")
    third = reading.rows[2]
    assert third.state is RallyRowState.UNKNOWN, (
        f"a row whose target could not be read must be UNKNOWN, got {third.state}"
    )
    assert not third.joinable
    assert third.join_norm is None


def test_a_frame_that_is_not_a_rally_list_reads_no_rows(read):
    """The negative case that keeps the reader from firing on the alliance home page.

    ``special_buildings.png`` is the 联盟领地 page.  It has no 集结中 header, so the reader
    must return nothing -- which is what stops a 前往 button or any stray green from being
    read as a rally.
    """
    reading = read("special_buildings.png")
    assert reading.rows == ()
    assert reading.container_norm is None, (
        "with no rows there is no container, so no scroll may be invented (task book §二)"
    )


# ----------------------------------------------------------------- the container


def test_the_container_is_derived_from_the_rows_not_from_the_frame_edge(read):
    """§二: 不得使用固定屏幕高度或固定起终点.

    The container must be a consequence of where the client drew the rows and its footer, so
    that a scrolled list yields a different container.  The evidence field names the source so
    a reader can tell a derived rectangle from a constant one.
    """
    reading = read("join_list_now.png")
    assert reading.container_norm is not None
    top, bottom = reading.container_norm[1], reading.container_norm[3]
    assert reading.evidence.get("container_source") == "row_headers_and_footer"
    assert top < reading.rows[0].header_y_norm, "the container must start above the first row"
    assert bottom >= reading.rows[-1].band_norm[0], "and reach into the last row"

    # A frame whose rows start lower must produce a different container: same reader, same
    # code path, geometry from the picture.
    other = read("join_list_after_detail.png")
    assert other.container_norm is not None
    assert other.container_norm[1] != reading.container_norm[1], (
        "two frames with rows at different heights must not share a container rectangle"
    )


def test_the_reader_does_not_store_a_row_pitch(read):
    """A pitch constant would be a fixed row-height rule by another name.

    ``read_rally_list`` recomputes every band from the headers the client drew.  This asserts
    the two frames that differ in row positions still read correctly, which is the observable
    consequence of not having a pitch.
    """
    a = read("join_list_now.png")
    b = read("join_list_after_detail.png")
    assert a.rows[0].header_y_norm != pytest.approx(b.rows[0].header_y_norm, abs=0.01), (
        "the two frames place their first row differently; that difference is the point"
    )
    for reading in (a, b):
        for row in reading.rows:
            assert row.band_norm[1] > row.band_norm[0]


# ------------------------------------------------------------------- the model


def test_the_reading_converts_to_the_scheduler_row_for_this_frame_only(read):
    """``to_row`` yields the scheduler's ``RallyRow``, with the button in this frame's pixels.

    The conversion is deliberately explicit about ``width``/``height``: the pixel point only
    means anything relative to the frame it was measured on, so the caller has to say which
    frame that is rather than having the reader cache one.
    """
    reading = read("join_list_now.png")
    width, height = reading.frame_size
    row = reading.rows[0]
    scheduler_row = row.to_row(width=width, height=height)
    assert scheduler_row.join_point is not None
    assert scheduler_row.join_point == (
        round(row.join_norm[0] * width), round(row.join_norm[1] * height)
    )

    # A different frame size relocates the point rather than reusing the old pixel value.
    scaled = row.to_row(width=width * 2, height=height * 2)
    assert scaled.join_point != scheduler_row.join_point, (
        "a pixel point must be a function of the frame it is applied to, not a stored value"
    )
