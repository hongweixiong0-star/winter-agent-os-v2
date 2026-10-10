"""How long until a reservation, using only what the client printed.

Both stamps come off the client and carry no offset, so their difference is a duration and needs
no timezone.  That is the whole point: the client prints 预约自动开启 as a naive local time, the
project's time rule forbids inferring the game's zone from this machine's, and
event_goal.Activity.window refuses a stamp without an offset -- so a naive reservation cannot
become a wake on its own, while its difference from the client's own clock can.

The two stamps are measured, 2026-10-10:
    calendar view   2026-10-10 07:52:18      <- the client's clock, from read_event_calendar
    巨熊行动 page   预约自动开启： 2026-10-1120:30   <- the reservation, from read_printed_reservation
Those two lines are what the first test feeds in.
"""

from winter_agent_v2.event_schedule import seconds_until_a_printed_reservation as until

#: The real pair, and the answer is a duration rather than an instant.
RESERVED = "2026-10-11T20:30:00"
CLIENT_NOW = "2026-10-10 07:52:18"


def test_the_two_real_readings_give_the_lead_in_seconds():
    # 2026-10-11 20:30 minus 2026-10-10 07:52:18 = 36 h 37 m 42 s
    assert until(RESERVED, CLIENT_NOW) == 36 * 3600 + 37 * 60 + 42


def test_the_age_of_the_clock_comes_off_the_difference():
    """The clock and the reservation are printed on different pages, so the clock has an age."""
    fresh = until(RESERVED, CLIENT_NOW)
    stale = until(RESERVED, CLIENT_NOW, client_now_age_seconds=600)
    assert fresh - stale == 600


def test_a_reservation_that_has_already_passed_is_not_a_countdown():
    assert until("2026-10-09T20:30:00", CLIENT_NOW) is None


def test_a_missing_clock_answers_nothing():
    """The bear page prints no clock at all -- that is a fact about the page, not a zero."""
    assert until(RESERVED, None) is None
    assert until(RESERVED, "") is None


def test_a_clock_without_a_year_is_not_guessed_at():
    """The map popup's clock reads 09-09 21:16:07. Inventing 2026 would be the guess."""
    assert until(RESERVED, "09-09 21:16:07") is None


def test_a_missing_or_unreadable_reservation_answers_nothing():
    assert until(None, CLIENT_NOW) is None
    assert until("", CLIENT_NOW) is None
    assert until("预约自动开启： 2026-10-1120:30", CLIENT_NOW) is None


def test_slash_separated_dates_parse_too():
    assert until("2026/10/11 20:30:00", CLIENT_NOW) == until(RESERVED, CLIENT_NOW)


def test_a_negative_age_is_treated_as_no_age():
    """A clock stamped in the future is a clock arithmetic error, not extra lead."""
    assert until(RESERVED, CLIENT_NOW, client_now_age_seconds=-99) == until(RESERVED, CLIENT_NOW)
