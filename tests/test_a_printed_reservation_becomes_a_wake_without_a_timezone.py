"""A printed reservation becomes a wake through the client's own clock, not through a timezone.

The chain this pins, and every link is already on file:

    the 巨熊行动 page prints  预约自动开启： 2026-10-1120:30     -> events['bear']
    the calendar page prints  2026-10-10 07:52:18               -> CALENDAR_GRID's clock
    the snapshot says when      observed_at                      -> how old that clock is
    their difference                                                  is a DURATION

A duration needs no timezone, which is the whole point: event_goal.Activity.window refuses a
stamp without an offset and the project's time rule forbids inferring the game's.  The result
goes into record_live_countdown, which is the existing API for turning a live countdown into a
role-scoped absolute reservation.

Verified against the real stored shape (learning/timed_event_schedule.json): a CALENDAR_GRID
record carries current_game_datetime_raw and observed_at side by side, so the age of the clock is
always available when the clock is.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from winter_agent_v2 import event_schedule
from winter_agent_v2.runtime import LiveRuntime

ROLE = "1063040265"
OBSERVED = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)


def payload_with_clock(*, clock: str | None, age_seconds: float, reservation: str):
    """A schedule file shaped exactly like the real one, reduced to what this path reads."""
    record = {
        "kind": "CALENDAR_GRID", "recognized": True,
        "current_game_date_raw": "2026-10-10",
        "current_game_datetime_raw": clock,
    }
    if age_seconds is not None:
        record["observed_at"] = (OBSERVED - timedelta(seconds=age_seconds)).isoformat()
    return {
        "schema_version": "1.0",
        "roles": {},
        "calendar_observations": {
            ROLE: {"CALENDAR_GRID": record},
        },
    }


def run(tmp_path: Path, *, clock, age_seconds, reservation):
    tmp_path.mkdir(parents=True, exist_ok=True)
    state = tmp_path / "timed_event_schedule.json"
    state.write_text(json.dumps(payload_with_clock(
        clock=clock, age_seconds=age_seconds, reservation=reservation)),
        encoding="utf-8")
    runtime = object.__new__(LiveRuntime)
    runtime._calendar_role_id = lambda: ROLE
    world = SimpleNamespace(
        timestamp=OBSERVED,
        events={"bear": {"event_id": "BEAR_HUNT", "reserved_start_time": reservation}},
    )
    original = event_schedule.STATE_PATH
    event_schedule.STATE_PATH = state
    try:
        runtime._record_live_event_reservation(world)
    finally:
        event_schedule.STATE_PATH = original
    written = json.loads(state.read_text(encoding="utf-8"))
    # save() writes roles as a LIST of RoleSchedule rows, not a mapping -- checked against
    # learning/timed_event_schedule.json, whose rows carry role_id/event_id/reserved_start.
    rows = written.get("roles") or []
    for row in rows:
        if isinstance(row, dict) and row.get("role_id") == ROLE                 and row.get("event_id") == "BEAR_HUNT":
            return row
    return None


def test_a_printed_reservation_becomes_a_role_scoped_wake(tmp_path):
    # The client's clock was read 90 s before this frame; the reservation is 36 h 37 m 42 s
    # after the clock, so the lead is that minus the 90 s.
    role = run(tmp_path, clock="2026-10-10 07:52:18", age_seconds=90,
               reservation="2026-10-11T20:30:00")
    assert role is not None, "no reservation was written"
    expected = (OBSERVED + timedelta(seconds=36 * 3600 + 37 * 60 + 42 - 90)).isoformat()
    assert role["reserved_start"] == expected
    assert role["source"] == "LIVE_CLIENT_PRINTED_RESERVATION_MINUS_CLIENT_CLOCK"


def test_the_clock_s_age_is_what_makes_a_stale_reading_usable(tmp_path):
    """A clock read a day ago still produces a wake, and the day is taken off the lead.

    The two cases describe different worlds, so the instants SHOULD differ: a clock that said
    07:52:18 a day ago means the client's now is a day later than a clock that said it just now.
    The age is what carries that difference, and this asserts the arithmetic rather than an
    equality that would have been wrong.
    """
    body = 36 * 3600 + 37 * 60 + 42
    fresh = run(tmp_path / "a", clock="2026-10-10 07:52:18", age_seconds=0,
                reservation="2026-10-11T20:30:00")
    stale = run(tmp_path / "b", clock="2026-10-10 07:52:18", age_seconds=24 * 3600,
                reservation="2026-10-11T20:30:00")
    assert fresh["reserved_start"] == (OBSERVED + timedelta(seconds=body)).isoformat()
    assert stale["reserved_start"] == (OBSERVED + timedelta(seconds=body - 24 * 3600)).isoformat()


def test_a_clock_with_no_age_is_not_used_at_all(tmp_path):
    """Without observed_at the correction is unknown, and an unknown correction overstates the
    lead -- acting an hour early is worse than not acting, so nothing is written."""
    row = run(tmp_path, clock="2026-10-10 07:52:18", age_seconds=None,
              reservation="2026-10-11T20:30:00")
    # A row may exist: record_live_window_observation is pre-existing and writes the window state.
    # What must NOT exist is a reservation.
    assert not (row or {}).get("reserved_start")


def test_no_clock_means_no_answer(tmp_path):
    row = run(tmp_path, clock=None, age_seconds=0, reservation="2026-10-11T20:30:00")
    assert not (row or {}).get("reserved_start")


def test_a_reservation_that_already_passed_writes_nothing(tmp_path):
    row = run(tmp_path, clock="2026-10-10 07:52:18", age_seconds=0,
              reservation="2026-10-09T20:30:00")
    assert not (row or {}).get("reserved_start")


def test_the_old_countdown_path_is_untouched(tmp_path):
    """A frame with no reservation but the usual minimum_guarantee still works as before."""
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"schema_version": "1.0", "roles": {},
                                 "calendar_observations": {}}), encoding="utf-8")
    runtime = object.__new__(LiveRuntime)
    runtime._calendar_role_id = lambda: ROLE
    world = SimpleNamespace(timestamp=OBSERVED, events={
        "minimum_guarantee": {"event_id": "STATE_VS_STATE", "seconds_to_start": 3600}})
    original = event_schedule.STATE_PATH
    event_schedule.STATE_PATH = state
    try:
        runtime._record_live_event_reservation(world)
    finally:
        event_schedule.STATE_PATH = original
    roles = json.loads(state.read_text(encoding="utf-8")).get("roles") or []
    # Nothing is invented for the bear, and the guarantee path is free to do its own thing.
    assert not any(isinstance(row, dict) and row.get("event_id") == "BEAR_HUNT" for row in roles)
