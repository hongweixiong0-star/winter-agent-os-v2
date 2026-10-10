from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from winter_agent_v2 import event_calendar, event_schedule
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import OCRResult
from winter_agent_v2.runtime import LiveRuntime


EVENT = "ICEBOUND_TREASURE_TRAINING"
ROLE = "role-A"


@pytest.fixture
def observe_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    frame = tmp_path / "detail.png"
    Image.new("RGB", (720, 1280), "white").save(frame)
    monkeypatch.setattr(event_calendar, "read_event_calendar", lambda *args, **kwargs: {
        "recognized": True, "details_visible": True, "entries": [],
    })
    monkeypatch.setattr(event_calendar, "read_event_detail", lambda *args, **kwargs: {
        "kind": "EVENT_DETAIL", "recognized": True, "event_id": EVENT,
    })
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = ROLE
    runtime.role_scope = "LIVE_OBSERVED"
    runtime.vision = SimpleNamespace(ocr=SimpleNamespace(
        recognize=lambda frame: OCRResult((), "fixture"),
    ))
    runtime._regular_event_hub_on_frame = lambda *args, **kwargs: {}
    return lambda: runtime._read_due_calendar_entry(WorldState(page=Page.EVENT), frame).events["calendar_detail"]


def row(key, days):
    return {"event_id": EVENT, "occurrence_key": key,
            "calendar_dates_raw": days, "tap_norm": [0.4, 0.5]}


def grid(rows, stamp):
    event_schedule.record_calendar_snapshot(
        role_id=ROLE, observation={"recognized": True, "entries": rows}, observed_at=stamp,
    )


def detail(stamp, key=None):
    observation = {"recognized": True, "event_id": EVENT, "calendar_origin": "GRID_ENTRY"}
    if key:
        observation["matched_occurrence_key"] = key
    event_schedule.record_calendar_detail(role_id=ROLE, observation=observation, observed_at=stamp)


def test_changed_calendar_window_does_not_reuse_old_detail_identity(observe_detail):
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    old = row(f"{EVENT}|10/04|10/04", ["10/04"])
    current = row(f"{EVENT}|10/02|10/06", ["10/02", "10/03", "10/04", "10/05", "10/06"])
    grid([old], stamp)
    detail(stamp + timedelta(seconds=1), old["occurrence_key"])
    grid([current], stamp + timedelta(seconds=2))

    observed = observe_detail()
    assert observed["matched_occurrence_key"] == current["occurrence_key"]
    event_schedule.record_calendar_detail(role_id=ROLE, observation=observed)
    assert not event_schedule.calendar_scan_pending(ROLE)
    assert event_schedule.calendar_next_entry(ROLE, [current]) is None


def test_returned_detail_does_not_steal_next_same_named_occurrence(observe_detail):
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    first = row(f"{EVENT}|10/02", ["10/02"])
    second = row(f"{EVENT}|10/06", ["10/06"])
    grid([first, second], stamp)
    detail(stamp + timedelta(seconds=1), first["occurrence_key"])
    grid([first, second], stamp + timedelta(seconds=2))

    observed = observe_detail()
    assert observed["matched_occurrence_key"] == second["occurrence_key"]
    event_schedule.record_calendar_detail(role_id=ROLE, observation=observed)
    assert not event_schedule.calendar_scan_pending(ROLE)


def test_pending_bad_record_is_rebound_to_current_calendar_window(observe_detail):
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    current = row(f"{EVENT}|10/02|10/06", ["10/02", "10/03", "10/04", "10/05", "10/06"])
    grid([current], stamp)
    detail(stamp + timedelta(seconds=1), f"{EVENT}|10/04|10/04")
    assert event_schedule.calendar_detail_return_pending(ROLE)
    # Corrected 2026-10-02, after the store learned to read the dates the detail carries: a key
    # that matches no row no longer means "credit nothing".  The detail's own 10/04 falls inside
    # exactly one uninspected row, so that row is credited when the detail is recorded and the
    # scan stops being pending at that moment.  Measured live over 4.4 unattended hours: while
    # this assertion held the other way, the credit never landed and AUTO re-opened the same six
    # entries 668 times (84% of every run).  What the rebind below still has to prove is that the
    # stored attribution names the *current* window, which is the thing this file exists for.
    assert not event_schedule.calendar_scan_pending(ROLE)

    observed = observe_detail()
    assert observed["matched_occurrence_key"] == current["occurrence_key"]
    event_schedule.record_calendar_detail(role_id=ROLE, observation=observed)
    assert not event_schedule.calendar_scan_pending(ROLE)


@pytest.mark.parametrize("explicit_key", [False, True])
def test_pending_overlay_keeps_its_verified_occurrence(observe_detail, explicit_key):
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    first = row(f"{EVENT}|10/02", ["10/02"])
    second = row(f"{EVENT}|10/06", ["10/06"])
    grid([first, second], stamp)
    detail(stamp + timedelta(seconds=1), first["occurrence_key"] if explicit_key else None)

    observed = observe_detail()
    assert observed["matched_occurrence_key"] == first["occurrence_key"]
    event_schedule.record_calendar_detail(role_id=ROLE, observation=observed)
    assert event_schedule.calendar_next_entry(ROLE, [first, second])["occurrence_key"] == second["occurrence_key"]


# ---------------------------------------------------------------------------------------------
# A card whose own heading mints a DIFFERENT id for the same activity.
#
# Measured 2026-10-10 on the live client: tapping the 除雪 grid row opens a preview card
# headed 除雪小分队 over that same grid.  ``_event_id`` hashes the OCR label, so the card's
# reading carries DISCOVERED_EVENT_1C9F9BD8F5 while the row that was tapped carries
# DISCOVERED_EVENT_DC53E03FB8.  Every id-based path then finds nothing, the row is never
# credited, the debt cannot fall, and DISCOVER_EVENT_CALENDAR is re-selected every few
# minutes -- 47% of the run's failures.  ``_prior_calendar_row`` states the rule this
# applies: "Date evidence is required when OCR changes an identifier."
# ---------------------------------------------------------------------------------------------

CARD_ID = "DISCOVERED_EVENT_1C9F9BD8F5"          # sha1("除雪小分队")
ROW_ID = "DISCOVERED_EVENT_DC53E03FB8"           # sha1("除雪")


def _card(**overrides):
    """The detail reading a preview card would produce: its own id, its own printed window."""
    observation = {
        "kind": "EVENT_DETAIL",
        "recognized": True,
        "event_id": CARD_ID,
        "display_name": "除雪小分队",
        "calendar_origin": "GRID_ENTRY",
        "preview_start_raw": "2026-10-13 00:00",
        "preview_end_raw": "2026-10-15 24:00",
        "source": "LIVE_CLIENT_OCR",
    }
    observation.update(overrides)
    return observation


def _grid(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    event_schedule.record_calendar_snapshot(
        role_id=ROLE, observation={"recognized": True, "entries": rows},
        observed_at=datetime.now(timezone.utc),
    )


def _target_row():
    return {"event_id": ROW_ID, "display_name": "除雪", "occurrence_key": f"{ROW_ID}|10/13|10/14",
            "calendar_dates_raw": ["10/13", "10/14"], "tap_norm": [0.875, 0.38047]}


def _other_row():
    return {"event_id": "DISCOVERED_EVENT_6F33C054CA", "display_name": "英雄集结",
            "occurrence_key": "DISCOVERED_EVENT_6F33C054CA|10/08|10/11",
            "calendar_dates_raw": ["10/08", "10/09", "10/10", "10/11"], "tap_norm": [0.33, 0.68]}


def test_a_card_whose_id_differs_credits_the_row_its_own_dates_cover(tmp_path, monkeypatch):
    """The measured case: the card's window overlaps exactly one uninspected row."""
    _grid(tmp_path, monkeypatch, [_target_row(), _other_row()])
    assert set(event_schedule.advertised_but_unread_activities(ROLE)) == {
        ROW_ID, "DISCOVERED_EVENT_6F33C054CA"}

    event_schedule.record_calendar_detail(role_id=ROLE, observation=_card())

    after = event_schedule.advertised_but_unread_activities(ROLE)
    assert ROW_ID not in after, "the tapped row must be credited by its dates"
    assert after == ("DISCOVERED_EVENT_6F33C054CA",)


def test_the_credit_names_the_row_so_the_verifier_can_see_it(tmp_path, monkeypatch):
    _grid(tmp_path, monkeypatch, [_target_row(), _other_row()])
    credited = event_schedule.record_calendar_detail(role_id=ROLE, observation=_card())
    assert credited["matched_occurrence_key"] == f"{ROW_ID}|10/13|10/14"


def test_two_rows_that_both_fit_credit_nothing(tmp_path, monkeypatch):
    """A coin flip credits nothing -- the same rule its neighbouring matcher holds."""
    twin = {**_other_row(), "event_id": "DISCOVERED_EVENT_TWIN",
            "calendar_dates_raw": ["10/14", "10/15"], "tap_norm": [0.55, 0.68]}
    _grid(tmp_path, monkeypatch, [_target_row(), twin])
    event_schedule.record_calendar_detail(role_id=ROLE, observation=_card())
    still = event_schedule.advertised_but_unread_activities(ROLE)
    assert ROW_ID in still and "DISCOVERED_EVENT_TWIN" in still


def test_a_card_that_prints_no_dates_credits_nothing(tmp_path, monkeypatch):
    _grid(tmp_path, monkeypatch, [_target_row(), _other_row()])
    event_schedule.record_calendar_detail(
        role_id=ROLE, observation=_card(preview_start_raw=None, preview_end_raw=None))
    assert ROW_ID in event_schedule.advertised_but_unread_activities(ROLE)


def test_an_already_observed_row_is_not_a_candidate(tmp_path, monkeypatch):
    """Re-reading the same card must not credit a second row through the same window."""
    _grid(tmp_path, monkeypatch, [_target_row(), _other_row()])
    credited = event_schedule.record_calendar_detail(role_id=ROLE, observation=_card())
    assert credited["matched_occurrence_key"] == f"{ROW_ID}|10/13|10/14"

    # The row now carries details_observed, so the same window has no candidate left and the
    # card cannot credit anything a second time.
    already = dict(_target_row(), details_observed=True)
    assert event_schedule.row_covering_the_details_window(_card(), [already]) is None


def test_the_helper_refuses_without_a_tap_point(tmp_path, monkeypatch):
    """A row the client drew without a clickable position is not something this run read."""
    row_without_tap = {**_target_row(), "tap_norm": None}
    assert event_schedule.row_covering_the_details_window(_card(), [row_without_tap]) is None


def test_the_real_raw_format_parses(tmp_path, monkeypatch):
    """The live client runs the date and the clock together: ``2026-09-2800:00``."""
    assert event_schedule._detail_window_days(
        {"preview_start_raw": "2026-09-2800:00", "preview_end_raw": "2026-10-1124:00"}
    ) == {(9, 28), (10, 11)}


def test_the_window_fallback_never_runs_when_the_id_already_matches_a_row(
        tmp_path, monkeypatch):
    """The guard an earlier draft of this fallback was missing.

    ``test_event_schedule.test_a_credit_is_refused_when_two_occurrences_of_one_event_are_uninspected``
    pinned that two uninspected occurrences of ONE event must credit nothing, and the first
    version of the date-window fallback broke it: a detail's printed window spans its whole
    preview run, which is coarse enough to overlap the wrong occurrence of the same event.
    The fallback exists for "OCR changed the identifier", so it applies only when the
    detail's id matches no row at all.
    """
    first = {**_target_row(), "event_id": "ICEBOUND_TREASURE_TRAINING",
             "occurrence_key": "ICEBOUND_TREASURE_TRAINING|10/02|10/06",
             "calendar_dates_raw": ["10/02"]}
    second = {**first, "occurrence_key": "ICEBOUND_TREASURE_TRAINING|11/02|11/06",
              "calendar_dates_raw": ["11/02"]}
    _grid(tmp_path, monkeypatch, [first, second])

    # A key that matches no row, which is what keeps the pre-existing event_id path from
    # firing -- otherwise this would test that path instead of the window fallback.
    event_schedule.record_calendar_detail(
        role_id=ROLE,
        observation=_card(event_id="ICEBOUND_TREASURE_TRAINING",
                          matched_occurrence_key="ICEBOUND_TREASURE_TRAINING|10/04|10/04"))

    observed = [row.get("details_observed") for row in
                (event_schedule.latest_calendar_snapshot(ROLE) or {}).get("entries") or ()]
    assert observed == [None, None], "an ambiguous frame must still credit nothing"


# ---------------------------------------------------------------------------------------------
# Attribution when the card's own window cannot discriminate.
#
# Measured 2026-10-10 in production: the 除雪 card prints 2026-10-13 00:00 - 2026-10-15 24:00,
# which overlaps THREE uninspected rows (除雪 10/13-14, 专属装备铸炼 10/08-14, the second
# 英雄集结 10/12-14), so a window-only rule correctly refuses and credits nothing.  The
# discriminator is the row the run actually aimed at -- already on hand in the resolver, and the
# same row ``verify_event_calendar_detail_open`` treats as ``expected_event_id``.
# ---------------------------------------------------------------------------------------------

FORGE_ID = "DISCOVERED_EVENT_FORGE"
HERO_ID = "DISCOVERED_EVENT_HERO"


def _overlapping_rows():
    """Three uninspected rows the card's window touches, so no window rule can pick one.

    The card's own raws are ``2026-10-13`` and ``2026-10-15``, so the day set it yields is
    ``{(10, 13), (10, 15)}`` -- not the whole run.  The rows below are chosen to overlap BOTH of
    those days across three rows, which is what makes the window rule refuse.  An earlier draft
    of this fixture gave the other rows 10/14, which the window does not contain, so only one
    row matched and the window fallback credited it -- the test passed without ever reaching the
    aimed-row path it was written for.
    """
    return [
        {**_target_row(), "event_id": ROW_ID, "occurrence_key": f"{ROW_ID}|10/13|10/14",
         "calendar_dates_raw": ["10/13", "10/14"]},
        {"event_id": FORGE_ID, "display_name": "专属装备铸炼",
         "occurrence_key": f"{FORGE_ID}|10/08|10/13",
         "calendar_dates_raw": ["10/08", "10/13"], "tap_norm": [0.55, 0.59]},
        {"event_id": HERO_ID, "display_name": "英雄集结",
         "occurrence_key": f"{HERO_ID}|10/14|10/15",
         "calendar_dates_raw": ["10/14", "10/15"], "tap_norm": [0.34, 0.86]},
    ]


def _observed_detail(tmp_path, monkeypatch, *, tap_row, detail):
    """Run the real ``_read_due_calendar_entry`` over a fixture with only the readers patched."""
    monkeypatch.setattr(event_calendar, "read_event_calendar", lambda *a, **k: {
        "recognized": True, "details_visible": True, "entries": [],
    })
    monkeypatch.setattr(event_calendar, "read_event_detail", lambda *a, **k: dict(detail))
    frame = tmp_path / "card.png"
    Image.new("RGB", (720, 1280), "white").save(frame)
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = ROLE
    runtime.role_scope = "LIVE_OBSERVED"
    runtime.vision = SimpleNamespace(ocr=SimpleNamespace(
        recognize=lambda _frame: OCRResult((), "fixture")))
    runtime._regular_event_hub_on_frame = lambda *a, **k: {}
    runtime._calendar_detail_tap_row = tap_row
    return runtime._read_due_calendar_entry(WorldState(page=Page.EVENT), frame).events["calendar_detail"]


def test_the_card_is_attributed_to_the_row_the_run_aimed_at(tmp_path, monkeypatch):
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    rows = _overlapping_rows()
    event_schedule.record_calendar_snapshot(
        role_id=ROLE, observation={"recognized": True, "entries": rows},
        observed_at=datetime.now(timezone.utc))

    # Guard against a test that passes for the wrong reason: the window rule ALONE must refuse
    # here, so anything that credits a row did it from the aimed row.
    assert event_schedule.row_covering_the_details_window(_card(), rows) is None

    observed = _observed_detail(
        tmp_path, monkeypatch,
        tap_row={"occurrence_key": f"{ROW_ID}|10/13|10/14", "event_id": ROW_ID},
        detail=_card())

    assert observed["matched_occurrence_key"] == f"{ROW_ID}|10/13|10/14"
    assert observed["matched_event_id"] == ROW_ID


def test_a_card_that_does_not_touch_the_row_it_aimed_at_is_not_attributed(tmp_path, monkeypatch):
    """A tap that landed on something else must not be credited to what it aimed at."""
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    rows = _overlapping_rows()
    # Aim at a row whose dates the card's window (10/13-10/15) does not touch.
    rows.append({"event_id": "DISCOVERED_EVENT_EARLY", "display_name": "早期活动",
                 "occurrence_key": "DISCOVERED_EVENT_EARLY|10/01|10/02",
                 "calendar_dates_raw": ["10/01", "10/02"], "tap_norm": [0.9, 0.2]})
    event_schedule.record_calendar_snapshot(
        role_id=ROLE, observation={"recognized": True, "entries": rows},
        observed_at=datetime.now(timezone.utc))

    observed = _observed_detail(
        tmp_path, monkeypatch,
        tap_row={"occurrence_key": "DISCOVERED_EVENT_EARLY|10/01|10/02",
                 "event_id": "DISCOVERED_EVENT_EARLY"},
        detail=_card())

    assert not observed.get("matched_occurrence_key")
    assert not observed.get("matched_event_id")
