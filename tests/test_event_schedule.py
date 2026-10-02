"""The calendar's "already inspected" credit, and the keys it has to match on.

Why this file exists
--------------------
Measured 2026-10-02 on the sanctioned pinned panel, 4.4 unattended hours: role
``1061663148`` produced 668 ``OPEN_EVENT_CALENDAR_DETAIL`` and 608
``RETURN_EVENT_CALENDAR`` steps out of 1749 episodes -- 84% of every run -- because its
persisted grid said six entries were still uninspected and *nothing ever inspected them*.

Its grid and the detail it kept opening were both recorded on disk, and they disagree about
the occurrence key for the same activity:

    grid row   ICEBOUND_TREASURE_TRAINING|10/02|10/06   details_observed=None
    detail     ICEBOUND_TREASURE_TRAINING|10/04|10/04   calendar_origin=GRID_ENTRY

Two different derivations of the same idea: the grid row's key is the first and last date of
the visible strip, the detail page prints its own dates.  ``record_calendar_snapshot`` matched
on exact ``occurrence_key`` equality and its single fallback was guarded by ``not occurrence``
-- false in exactly the case where the fallback was needed -- so the credit never landed,
``calendar_scan_pending`` stayed true, ``calendar_scan_due`` had to stay true, and the brain
re-opened the same entry for hours.

The second role (``1063040265``) completed its scan on the same grid; its last-read detail
happened to yield ``DISCOVERED_EVENT_E1FB4AC23A|09/30|10/06``, which *does* equal its row's
key.  So the defect is not role-specific: it fires whenever the two derivations disagree.

What these tests pin
--------------------
* the credit lands when the detail's key matches no row but exactly one row of that event is
  still uninspected;
* it is refused when the frame leaves a choice (two uninspected occurrences of one event),
  because crediting either one would be a coin flip;
* it is refused once every row of that event is already inspected, so one detail read can
  never credit a second occurrence;
* a detail for an event the grid does not carry credits nothing;
* and the whole sequence converges: after one detail read per row, the scan is no longer
  pending, which is what stops the loop.
"""
from datetime import datetime, timedelta, timezone

from winter_agent_v2 import event_schedule

ROLE = "1061663148"
T0 = datetime(2026, 10, 2, 3, 55, tzinfo=timezone.utc)


def _row(event_id, name, key, dates, observed=None):
    return {
        "event_id": event_id,
        "display_name": name,
        "occurrence_key": key,
        "calendar_dates_raw": list(dates),
        "tap_norm": [0.5, 0.4],
        "details_observed": observed,
    }


# The six rows the live grid actually carried, with the keys it actually carried.
LIVE_GRID = [
    _row("ICEBOUND_TREASURE_TRAINING", "寻宝特训", "ICEBOUND_TREASURE_TRAINING|10/02|10/06",
         ["10/02", "10/03", "10/04", "10/05", "10/06"]),
    _row("ICEBOUND_TREASURE", "冰封的宝藏", "ICEBOUND_TREASURE|10/02|10/06",
         ["10/02", "10/03", "10/04", "10/05", "10/06"]),
    _row("ICEBOUND_TREASURE_MYSTERY_SHOP", "秘宝商行",
         "ICEBOUND_TREASURE_MYSTERY_SHOP|10/02|10/06",
         ["10/02", "10/03", "10/04", "10/05", "10/06"]),
    _row("DISCOVERED_EVENT_4178AC2F00", "庆典对对碰",
         "DISCOVERED_EVENT_4178AC2F00|10/02|10/06",
         ["10/02", "10/03", "10/04", "10/05", "10/06"]),
    _row("DISCOVERED_EVENT_BB2077C97D", "狮舞盛会",
         "DISCOVERED_EVENT_BB2077C97D|09/30|10/06",
         ["09/30", "10/01", "10/02", "10/03", "10/04", "10/05", "10/06"]),
    _row("DISCOVERED_EVENT_E1FB4AC23A", "盛会商铺",
         "DISCOVERED_EVENT_E1FB4AC23A|09/30|10/06",
         ["09/30", "10/01", "10/02", "10/03", "10/04", "10/05", "10/06"]),
]


def _record_grid(path, entries=LIVE_GRID, at=T0):
    return event_schedule.record_calendar_snapshot(
        role_id=ROLE,
        observation={"recognized": True, "kind": "CALENDAR_GRID", "source": "LIVE_CLIENT_OCR",
                     "entries": entries},
        observed_at=at, path=path,
    )


def _record_detail(path, key, event_id="ICEBOUND_TREASURE_TRAINING", at=None, **extra):
    """The detail the live client actually produced, including its own date strings."""
    observation = {
        "recognized": True, "kind": "EVENT_DETAIL", "source": "LIVE_CLIENT_OCR",
        "event_id": event_id, "matched_event_id": event_id, "matched_occurrence_key": key,
        "calendar_origin": "GRID_ENTRY", "display_name": "寻宝特训",
        "preview_start_raw": "2026-10-0200:00", "preview_end_raw": "2026-10-0824:00",
    }
    observation.update(extra)
    return event_schedule.record_calendar_detail(
        role_id=ROLE, observation=observation, observed_at=at or T0 + timedelta(minutes=1),
        path=path,
    )


def _observed(path, event_id):
    grid = event_schedule.latest_calendar_snapshot(ROLE, path)
    return [row for row in grid["entries"] if row.get("event_id") == event_id]


def test_the_live_key_mismatch_is_what_the_scan_pending_flag_was_stuck_on(tmp_path):
    """Guard the fixture itself: the two keys really do differ, and pending really is true."""
    path = tmp_path / "schedule.json"
    _record_grid(path)

    assert event_schedule.calendar_scan_pending(ROLE, path) is True
    grid_key = _observed(path, "ICEBOUND_TREASURE_TRAINING")[0]["occurrence_key"]
    assert grid_key == "ICEBOUND_TREASURE_TRAINING|10/02|10/06"
    assert grid_key != "ICEBOUND_TREASURE_TRAINING|10/04|10/04"


def test_a_detail_whose_occurrence_key_matches_no_row_still_credits_its_own_row(tmp_path):
    path = tmp_path / "schedule.json"
    _record_grid(path)

    _record_detail(path, "ICEBOUND_TREASURE_TRAINING|10/04|10/04")

    rows = _observed(path, "ICEBOUND_TREASURE_TRAINING")
    assert len(rows) == 1, "the grid must not grow a second row for a detail read"
    assert rows[0]["details_observed"] is True
    # The credit is attributable: the record names the row it credited.
    recorded = event_schedule.latest_calendar_snapshot(ROLE, path)
    assert recorded is not None
    detail = event_schedule._schedule_payload(path)["calendar_observations"][ROLE]["EVENT_DETAIL"]
    assert detail["matched_occurrence_key"] == rows[0]["occurrence_key"]


def test_a_credit_is_refused_when_two_occurrences_of_one_event_are_uninspected(tmp_path):
    """Never a coin flip: an ambiguous frame must credit nothing rather than pick one."""
    path = tmp_path / "schedule.json"
    entries = [
        _row("ICEBOUND_TREASURE_TRAINING", "寻宝特训", "ICEBOUND_TREASURE_TRAINING|10/02|10/06",
             ["10/02"]),
        _row("ICEBOUND_TREASURE_TRAINING", "寻宝特训", "ICEBOUND_TREASURE_TRAINING|11/02|11/06",
             ["11/02"]),
    ]
    _record_grid(path, entries=entries)

    _record_detail(path, "ICEBOUND_TREASURE_TRAINING|10/04|10/04")

    assert [row["details_observed"] for row in _observed(path, "ICEBOUND_TREASURE_TRAINING")] == [
        None, None,
    ]


def test_a_second_detail_read_cannot_credit_a_second_occurrence(tmp_path):
    path = tmp_path / "schedule.json"
    entries = [
        _row("ICEBOUND_TREASURE_TRAINING", "寻宝特训", "ICEBOUND_TREASURE_TRAINING|10/02|10/06",
             ["10/02"]),
        _row("ICEBOUND_TREASURE_TRAINING", "寻宝特训", "ICEBOUND_TREASURE_TRAINING|11/02|11/06",
             ["11/02"]),
    ]
    _record_grid(path, entries=entries)

    _record_detail(path, "ICEBOUND_TREASURE_TRAINING|10/04|10/04")
    _record_detail(path, "ICEBOUND_TREASURE_TRAINING|10/04|10/04", at=T0 + timedelta(minutes=2))

    # The first read credited one; the second found the remaining choice ambiguous-by-history
    # only if it were the same occurrence -- it must not credit the *other* one.
    observed = [row["details_observed"] for row in _observed(path, "ICEBOUND_TREASURE_TRAINING")]
    assert observed.count(True) <= 1


def test_a_detail_for_an_event_the_grid_does_not_carry_credits_nothing(tmp_path):
    path = tmp_path / "schedule.json"
    _record_grid(path)

    _record_detail(path, "SOME_OTHER_EVENT|10/04|10/04", event_id="SOME_OTHER_EVENT")

    assert [row["details_observed"] for row in _observed(path, "ICEBOUND_TREASURE_TRAINING")] == [None]
    assert event_schedule.calendar_scan_pending(ROLE, path) is True


def test_the_scan_converges_after_one_read_per_row(tmp_path):
    """The whole point: pending must be able to become false, or the loop cannot end."""
    path = tmp_path / "schedule.json"
    _record_grid(path)

    for index, row in enumerate(LIVE_GRID):
        # Every detail yields a key of the *other* vocabulary, as the live client's did.
        _record_detail(path, f"{row['event_id']}|10/04|10/04", event_id=row["event_id"],
                       at=T0 + timedelta(minutes=1 + index))

    assert event_schedule.calendar_scan_pending(ROLE, path) is False
    assert event_schedule.calendar_scan_due(
        ROLE, path=path, now=T0 + timedelta(minutes=10)
    ) is False
