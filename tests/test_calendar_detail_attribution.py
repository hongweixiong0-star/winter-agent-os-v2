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
    assert event_schedule.calendar_scan_pending(ROLE)

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
