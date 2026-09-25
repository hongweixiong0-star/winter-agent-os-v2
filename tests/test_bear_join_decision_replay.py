"""Offline replay: the JOIN decision chain against the real 09-09 rally-list frames.

``read_rally_list`` parses each visible row (target / leader / countdown / capacity /
**that row's own** join affordance) and ``choose_bear_operation`` answers WHAT. The
frames live in ``dataset/raw/bear_live_20260909/`` and are LOCAL_ONLY -- they are raw
screenshots of the test account's client and are not committed, so the suite skips
when they are absent rather than pretending to have run.

What this locks in, from evidence rather than from hope:

* a row is joined only when the client itself drew a green affordance **on that row**
  and the capacity reading allows it -- a full rally reports joinable=False;
* a row whose target the parser could not read is refused (UNKNOWN never joins);
* a frame without any 集结中 header yields zero rows and no decision, instead of
  guessing a position.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from winter_agent_v2.models import WorldState
from winter_agent_v2.ocr import OCRService, RapidOCRBackend
from winter_agent_v2.rally import BearRole, choose_bear_operation, read_rally_list

FRAMES = Path(__file__).resolve().parents[1] / "dataset" / "raw" / "bear_live_20260909"
LIST_FRAMES = [
    "join_list_now.png",
    "join_list_after_detail.png",
    "join_more_list.png",
    "bear_rally_panel.png",
]

pytestmark = pytest.mark.skipif(
    not all((FRAMES / name).is_file() for name in LIST_FRAMES),
    reason="LOCAL_ONLY frames dataset/raw/bear_live_20260909/ are not in this clone",
)


def _world(idle_marches: int = 2) -> WorldState:
    return WorldState(normal_idle_slots=idle_marches, bear_rally_special_available=False)


def test_joinable_rows_produce_a_join_decision_and_full_rows_do_not() -> None:
    ocr = OCRService(RapidOCRBackend())

    reading = read_rally_list(FRAMES / "join_list_now.png", ocr)
    assert len(reading.rows) == 3
    first = reading.rows[0]
    assert first.target_type.value == "BEAR"
    assert first.joinable is True
    # The affordance belongs to this row, read off this frame -- not a stored point.
    assert first.join_norm is not None
    assert choose_bear_operation(_world(), BearRole.JOINER, reading.rows) == "JOIN_RALLY"

    # A list where every visible rally is full must honestly refuse.
    full = read_rally_list(FRAMES / "join_more_list.png", ocr)
    assert choose_bear_operation(_world(), BearRole.JOINER, full.rows) is None
    assert choose_bear_operation(_world(), BearRole.LEADER, full.rows) is None


def test_rows_without_a_readable_target_are_never_joined() -> None:
    ocr = OCRService(RapidOCRBackend())
    reading = read_rally_list(FRAMES / "join_more_list.png", ocr)
    unknowns = [row for row in reading.rows if row.target_type.value == "UNKNOWN"]
    assert unknowns, "this frame is expected to carry at least one unreadable row"
    for row in unknowns:
        assert row.joinable is False


def test_a_frame_without_rally_headers_yields_no_rows_and_no_decision() -> None:
    ocr = OCRService(RapidOCRBackend())
    reading = read_rally_list(FRAMES / "bear_rally_next.png", ocr)
    assert reading.rows == ()
    assert choose_bear_operation(_world(), BearRole.JOINER, reading.rows) is None
