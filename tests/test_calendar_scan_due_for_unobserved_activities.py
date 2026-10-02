"""An activity the screen advertised and nobody opened keeps the calendar due.

Measured 2026-10-02 on the pinned production tree, and this is the defect that made the
strip reader (9f468b3) and its crop (2ee4908) inert on the real device.

The state as it stood at 13:52 local, both roles:

    timed_event_schedule.json updated_at 2026-10-02T05:58:27Z
    grid entries                6, every one details_observed=True
    calendar_scan_pending(...)  False
    calendar_scan_due(1061663148)  False        <-- 24 h TTL, read at 05:35-05:58
    DISCOVER_EVENT_CALENDAR last selected  05:57Z, then never again for 8 hours
    episodes on the new revisions whose state_before.page == EVENT   0

So the loop closed on itself:

    the strip shows an activity the grid does not list
      -> the scan gate only inspects grid rows, and all 6 are read
      -> scan_due is False for 24 h
      -> AUTO never opens the 常规活动 screen again
      -> the strip reader never runs
      -> the activity is never observed

**A reader that is correct and never called is not a reader.** The strip fix was wired,
tested against the real frame, and still produced nothing on the device, because the one
gate that decides whether to go and look had no idea the strip exists.

The predicate is about **what the client drew and can actually open**, never about what the
registry contains, and it uses the same "has a tap point" test ``calendar_scan_pending``
already uses.  Both halves were forced by evidence, and both are pinned below so the wrong
versions cannot come back:

* a registry-based version ("which registered activity is unread") was written first and
  four existing tests rejected it within minutes --
  ``test_the_scan_converges_after_one_read_per_row`` among them, whose docstring is
  "pending must be able to become false, or the loop cannot end".  The registry holds 17
  activities and the grid read 6, so a registry predicate is permanently true and turns a
  23-hour convergence into an infinite one;
* "listed but no tap point" was rejected by
  ``test_calendar_storage_is_role_scoped_due_after_a_day_and_does_not_set_reserved_time``,
  whose row carries neither ``tap_norm`` nor ``details_observed``: a row the client drew
  without a clickable position is not something this run *could* have opened, so calling it
  an unpaid debt would re-open the calendar forever over a row nobody can read.

Those tests were right both times and this predicate was wrong both times.  The live state
agrees with them: all six real grid rows carry ``tap_norm=True`` and
``details_observed=True``, so the strip is the only thing left owing anything.
"""

import json
from datetime import datetime, timedelta, timezone

from winter_agent_v2.event_schedule import (
    advertised_but_unread_activities,
    calendar_scan_due,
    calendar_scan_pending,
    record_calendar_snapshot,
    strip_read_stale_against_grid,
)

NOW = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)
ROLE = "1061663148"
DAY_AGO = (NOW - timedelta(hours=8, minutes=30)).isoformat()

#: The six activities the real grid did read on 2026-10-02, by their own ids.  Taken from
#: the production ``timed_event_schedule.json`` rather than invented, because the control
#: group only means something if the "everything drawn has been opened" state is one the
#: device has actually been in.
READ_EVENTS = (
    "ICEBOUND_TREASURE", "ICEBOUND_TREASURE_TRAINING", "ICEBOUND_TREASURE_MYSTERY_SHOP",
    "DISCOVERED_EVENT_4178AC2F00", "DISCOVERED_EVENT_BB2077C97D", "DISCOVERED_EVENT_E1FB4AC23A",
)


def _row(event_id, *, observed=True, tap=True):
    return {
        "event_id": event_id, "display_name": event_id,
        "tap_norm": [0.5, 0.4] if tap else None,
        "details_observed": observed, "occurrence_key": f"{event_id}|10/02|10/06",
    }


def _state(tmp_path, *, grid_entries, strip_entries=None, observed_at=DAY_AGO):
    path = tmp_path / "timed_event_schedule.json"
    record_calendar_snapshot(
        role_id=ROLE, path=path, observed_at=observed_at,
        observation={"recognized": True, "kind": "CALENDAR_GRID", "source": "LIVE_CLIENT_OCR",
                     "entries": grid_entries},
    )
    if strip_entries is not None:
        record_calendar_snapshot(
            role_id=ROLE, path=path, observed_at=observed_at,
            observation={"recognized": True, "kind": "ACTIVITY_STRIP",
                         "source": "CURRENT_FRAME_OCR_CROP", "entries": strip_entries},
        )
    return path


def _strip_row(event_id="CANYON_CLASH"):
    """The row the real crop produced on 2026-10-02: CANYON_CLASH at confidence 0.941."""
    return {"event_id": event_id, "display_name": "峡谷会战",
            "tap_norm": [0.465, 0.134], "start": None, "end": None, "preview_only": True}


def test_a_fully_read_grid_converges(tmp_path):
    """The control group four existing tests protect, kept explicit here.

    Everything the screen drew has been opened, so ``pending`` is false, nothing is
    advertised-but-unread, and the 24 h interval governs.  If this ever fails, the new
    predicate has started manufacturing obligations out of thin air.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS])
    assert calendar_scan_pending(ROLE, path) is False
    assert advertised_but_unread_activities(ROLE, path) == ()
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_a_grid_row_nobody_opened_is_still_pending(tmp_path):
    """The original rule, unchanged: a listed row with a tap point and no detail reading."""
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS[:5]]
                  + [_row(READ_EVENTS[5], observed=False)])
    assert calendar_scan_pending(ROLE, path) is True
    assert calendar_scan_due(ROLE, now=NOW, path=path) is True


def test_a_strip_activity_nobody_opened_keeps_the_scan_due(tmp_path):
    """The fix.  峡谷会战 is advertised on the strip above the grid and has no reading.

    This is CANYON_CLASH, so the goal it backs (SCHEDULED_CANYON_CLASH) can be priced on a
    real observation instead of a floor value that exists only because the screen was
    never opened again.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS],
                  strip_entries=[_strip_row()])
    assert calendar_scan_pending(ROLE, path) is False, "the grid itself is complete"
    assert advertised_but_unread_activities(ROLE, path) == ("CANYON_CLASH",)
    assert calendar_scan_due(ROLE, now=NOW, path=path) is True


def test_a_strip_row_that_was_opened_closes_the_scan(tmp_path):
    """The fix must converge too, or it is the infinite loop the registry version was.

    Opening the advertised activity is what discharges the debt; nothing else does.  This is
    the direction that makes the change safe to ship: a goal that re-reads the same screen
    forever is worse than one that never goes.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS],
                  strip_entries=[_strip_row()])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["calendar_observations"][ROLE]["ACTIVITY_STRIP"]["read_entries"] = [
        {"event_id": "CANYON_CLASH"}
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert advertised_but_unread_activities(ROLE, path) == ()
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_a_registry_activity_the_client_is_not_showing_creates_no_debt(tmp_path):
    """The defect of the first version, pinned so it cannot return.

    The registry holds 17 activities; this screen drew 6.  The eleven it did not draw are
    not obligations -- they may be next week's events, or events for another client state --
    and treating them as debt is what made the scan unable to converge.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS])
    assert advertised_but_unread_activities(ROLE, path) == ()
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_the_strip_region_itself_is_not_a_debt_before_the_first_look(tmp_path):
    """The third rejected version, and the subtlest of the three.

    "``ACTIVITY_STRIP`` is absent, therefore the region is owed" reads like the obvious
    fix for the loop below, and it is what a reader naturally reaches for.  It was rejected
    because it makes every grid-only role permanently due, which is exactly what four
    existing tests assert against.  The reason it cannot work is worth stating plainly:

        the strip is read only while the calendar is open
        -> the calendar opens only when the scan is due
        -> so "was the strip ever read" can only be answered after the action it gates

    **A reader cannot discover that it has never been called by asking whether it has been
    called.**  The absence of a record is not evidence about the screen, so it is not
    evidence of a debt.  What does open the gate, once the reader exists, is
    ``advertised_but_unread_activities`` below -- the strip is read on the first ordinary
    interval, and from then on the debt it found keeps it due.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS])
    assert "ACTIVITY_STRIP" not in json.loads(
        path.read_text(encoding="utf-8"))["calendar_observations"][ROLE]
    assert strip_read_stale_against_grid(ROLE, path) is False
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_a_grid_read_after_the_strip_leaves_the_strip_stale(tmp_path):
    """What the strip predicate is actually for, and the direction that matters.

    ``_record_calendar_observation`` writes the grid and the strip from one call with one
    ``stamp``, so equal timestamps are the proof that they came from the same frame.  A
    strictly newer grid therefore means the last look at that screen left the strip out, and
    this fires from the first honest look onwards -- which is what makes it a real gate
    rather than a first-run bootstrap that then forgets.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS], strip_entries=[])
    assert strip_read_stale_against_grid(ROLE, path) is False
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False
    # The client re-renders the grid; the strip reading is now the older of the two.
    record_calendar_snapshot(
        role_id=ROLE, path=path, observed_at=NOW.isoformat(),
        observation={"recognized": True, "kind": "CALENDAR_GRID", "source": "LIVE_CLIENT_OCR",
                     "entries": [_row(e) for e in READ_EVENTS]},
    )
    assert strip_read_stale_against_grid(ROLE, path) is True
    assert calendar_scan_due(ROLE, now=NOW, path=path) is True


def test_looking_at_the_strip_once_closes_the_region_debt(tmp_path):
    """And it must close, or the fix is the infinite loop the registry version was.

    An empty reading is still a reading: this frame drew no registered activity on the
    strip, so there is nothing left to open there and the 24-hour interval governs again.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS],
                  strip_entries=[])
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_a_fully_read_grid_with_a_looked_at_strip_converges(tmp_path):
    """The convergence the four existing tests protect, now including the strip.

    Same terminal state they describe, reached with both regions observed.  If the strip
    requirement ever leaks into a permanent debt this is the test that will say so first.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS], strip_entries=[])
    assert calendar_scan_pending(ROLE, path) is False
    assert advertised_but_unread_activities(ROLE, path) == ()
    assert strip_read_stale_against_grid(ROLE, path) is False
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_a_row_the_client_could_not_make_clickable_is_not_a_debt(tmp_path):
    """The second rejected version, pinned too.

    ``test_calendar_storage_is_role_scoped_due_after_a_day_and_does_not_set_reserved_time``
    records a row with no ``tap_norm`` and expects the scan to converge.  A row without a
    clickable position is not something the run *could* have opened, so demanding it be
    opened is a debt that can never be paid.
    """
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS]
                  + [_row("CANYON_CLASH", observed=False, tap=False)],
                  strip_entries=[])
    assert advertised_but_unread_activities(ROLE, path) == ()
    assert calendar_scan_due(ROLE, now=NOW, path=path) is False


def test_a_stale_grid_still_reopens_on_the_interval(tmp_path):
    """The reason ``calendar_scan_due`` exists at all, unchanged by any of this."""
    path = _state(tmp_path, grid_entries=[_row(e) for e in READ_EVENTS],
                  observed_at=(NOW - timedelta(days=2)).isoformat())
    assert calendar_scan_due(ROLE, now=NOW, path=path) is True
