"""Tests for the alliance day-event reader -- strings from the live alliance page.

Measured 2026-10-16 on the [DIW] alliance landing (r203/r226); the two index styles and the
mixed dot forms appear verbatim in that capture.
"""

from winter_agent_v2.alliance_event_reader import (
    read_alliance_day,
    read_day_events,
    read_day_header,
)


SAMPLE = (
    "大王来修车\n实力：\n11,222,646,195\n排名：\n成员：\n96/100\n11\n已满级\n"
    "10月16日·周五\n"
    "1．【联盟大作战】&【军备竞演】\n"
    "2.【联盟争霸赛】\n"
    "+66\n联盟战争\n联盟宝箱\n"
)


def test_both_index_styles_are_read_as_one_list():
    rows = read_day_events(SAMPLE)
    assert [r["index"] for r in rows] == [1, 2]


def test_names_inside_brackets_are_extracted_verbatim():
    rows = read_day_events(SAMPLE)
    assert rows[0]["names"] == ["联盟大作战", "军备竞演"]
    assert rows[1]["names"] == ["联盟争霸赛"]


def test_raw_line_is_kept_even_without_brackets():
    rows = read_day_events("3. 领地建设活动\n")
    assert rows[0]["names"] == []
    assert rows[0]["raw"] == "领地建设活动"


def test_date_header_reads_day_and_weekday():
    assert read_day_header(SAMPLE) == {"date": "10月16日", "weekday": "周五"}


def test_header_absent_is_none_not_guessed():
    assert read_day_header("联盟战争 集结 单人 活动") is None


def test_full_block_combines_what_the_text_supports():
    block = read_alliance_day(SAMPLE)
    assert block["header"]["date"] == "10月16日"
    assert len(block["events"]) == 2


def test_empty_text_yields_empty_dict():
    assert read_alliance_day("") == {}


def test_fullwidth_digits_in_index_are_normalised():
    rows = read_day_events("１２．【测试活动】\n")
    assert rows and rows[0]["index"] == 12
