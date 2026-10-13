"""The client's own 预约自动开启 line, read where the client prints it.

Measured 2026-10-10 on
dataset/evidence/bear_baseline_newaccount_20260927T100038Z/p11_bear_page.png: OCR returns
the label and the clock as TWO tokens (y=1083 and y=1113) and glues the clock to the date
with no space -- '2026-09-2720:30'.  Joined in the reader's own order they reproduce
exactly the client_raw the CONFIRMED record holds:

    knowledge/events/bear_hunt_time_20260927_newaccount.json
      client_raw       "预约自动开启： 2026-09-2720:30"
      scheduled_start  "2026-09-27T20:30:00+08:00"

These tests pin the reading. They deliberately do NOT pin an offset: the client prints
none, and the project's time rule forbids inferring the game's timezone from this machine's.
"""

from winter_agent_v2.event_calendar import read_printed_reservation
from winter_agent_v2.ocr import OCRToken


def token(text, x=0, y=0, w=100, h=26, confidence=0.99):
    return OCRToken(text, confidence, ((x, y), (x + w, y), (x + w, y + h), (x, y + h)))


#: The frame's strip and body, in the order the reader hands them over. The two lines that
#: matter are adjacent in that order even though 等级5 is drawn between them on screen.
REAL_FRAME_ORDER = [
    token("常规活动", 96, 22, 134, 38),
    token("巨熊行动", 284, 799, 157, 43),
    token("陷阱可持续30分钟，盟友协力造成的总伤害越高，", 78, 945, 536, 29),
    token("预约自动开启：", 273, 1083, 157, 26, 0.994),
    token("2026-09-2720:30", 253, 1113, 215, 26, 0.99),
    token("等级5", 578, 1112, 64, 28),
]


def test_the_two_printed_lines_are_read_as_one_reservation():
    got = read_printed_reservation(REAL_FRAME_ORDER)
    assert got is not None
    assert got["reserved_start_time"] == "2026-09-27T20:30:00"
    assert got["reserved_start_raw"] == "预约自动开启： 2026-09-2720:30"
    assert got["reserved_start_source"] == "LIVE_CLIENT_PRINTED_RESERVATION"


def test_the_answer_carries_no_offset_because_the_client_prints_none():
    got = read_printed_reservation(REAL_FRAME_ORDER)
    assert got["reserved_start_offset"] is None
    # A naive stamp is the honest answer: event_goal.Activity.window refuses one for a wake.
    assert "+" not in got["reserved_start_time"] and "Z" not in got["reserved_start_time"]


def test_a_space_ocr_kept_between_the_date_and_the_clock_still_reads():
    got = read_printed_reservation([token("预约自动开启： 2026-09-28 20:00")])
    assert got["reserved_start_time"] == "2026-09-28T20:00:00"


def test_the_line_is_read_when_the_frame_prints_it_as_a_single_token():
    got = read_printed_reservation([token("预约自动开启：2026-09-27 20:30")])
    assert got["reserved_start_time"] == "2026-09-27T20:30:00"


def test_a_frame_without_the_line_answers_nothing():
    for frame in ([], [token("常规活动"), token("小游戏"), token("决战王城")]):
        assert read_printed_reservation(frame) is None


def test_a_printed_clock_that_is_not_a_time_is_a_misread_not_a_reservation():
    """2026-13-45 is the reader being wrong, not the client scheduling something."""
    assert read_printed_reservation([token("预约自动开启： 2026-13-45 99:99")]) is None
    assert read_printed_reservation([token("预约自动开启： 2026-09-27 25:30")]) is None


def test_a_second_event_s_line_does_not_borrow_the_first_one_s_answer():
    """One reservation per frame: the field is a scalar, so the reading must be too."""
    got = read_printed_reservation([
        token("预约自动开启： 2026-09-27 20:30"),
        token("预约自动开启： 2026-09-28 21:00"),
    ])
    assert got is not None and got["reserved_start_time"].startswith("2026-09-")
