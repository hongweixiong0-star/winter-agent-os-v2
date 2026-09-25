from winter_agent_v2.models import Page
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken


def classify(*texts, boxes=None, frame_size=None):
    boxes = boxes or [() for _ in texts]
    result = OCRResult(tuple(OCRToken(text, 0.99, box) for text, box in zip(texts, boxes)), "test")
    return OCRPageClassifier().classify(result, frame_size=frame_size)


def test_armament_explicit_start_countdown_is_not_confused_with_stage_remaining():
    world = classify("军备竞赛", "距开始 02:00:00", "我的积分：0")
    assert world.page is Page.EVENT
    minimum = world.events["minimum_guarantee"]
    assert minimum["event_id"] == "ARMAMENT_COMPETITION"
    assert minimum["seconds_to_start"] == 7200
    assert minimum["remaining_seconds"] is None


def test_state_of_power_stage_timer_stays_an_end_deadline_not_a_start_time():
    world = classify("最强王国", "击败野兽 12:03:29", "我的积分：0")
    minimum = world.events["minimum_guarantee"]
    assert minimum["event_id"] == "STATE_VS_STATE"
    assert minimum["seconds_to_start"] is None
    assert minimum["remaining_seconds"] == 12 * 3600 + 3 * 60 + 29


def test_discovered_event_alias_uses_registry_identity_and_explicit_start_timer():
    heading = ((102.0, 214.0), (219.0, 214.0), (219.0, 258.0), (102.0, 258.0))
    world = classify("常规活动", "联盟总动员", "距开始 02:00:00",
                     boxes=[(), heading, ()], frame_size=(720, 1280))
    assert world.page is Page.EVENT
    minimum = world.events["minimum_guarantee"]
    assert minimum["event_id"] == "ALLIANCE_MOBILIZATION"
    assert minimum["seconds_to_start"] == 7200
    assert minimum["remaining_seconds"] is None


def test_rotating_event_names_are_resolved_only_by_exact_registered_aliases():
    heading = ((41.0, 214.0), (208.0, 214.0), (208.0, 258.0), (41.0, 258.0))
    for title, event_id in (
        ("Officer Project", "OFFICER_PROJECT"),
        ("Defeat Nearby Beasts", "DEFEAT_NEARBY_BEASTS"),
        ("Brothers in Arms", "BROTHERS_IN_ARMS"),
    ):
        world = classify("常规活动", title, boxes=[(), heading], frame_size=(720, 1280))
        assert world.events["minimum_guarantee"]["event_id"] == event_id


def test_small_event_tab_does_not_override_the_active_event_heading():
    tab = ((102.0, 156.0), (219.0, 156.0), (219.0, 185.0), (102.0, 185.0))
    heading = ((41.0, 214.0), (208.0, 214.0), (208.0, 258.0), (41.0, 258.0))
    world = classify("常规活动", "联盟总动员", "军备竞演", "00:38:40",
                     boxes=[(), tab, heading, ()], frame_size=(720, 1280))
    assert world.page is Page.EVENT
    assert world.events["minimum_guarantee"]["event_id"] == "ARMAMENT_COMPETITION"
    assert world.events["minimum_guarantee"]["remaining_seconds"] == 2320


def test_bear_trap_start_countdown_is_role_ready_input():
    world = classify("狩猎陷阱", "距开始", "00:08:00", "前往")
    assert world.page is Page.ALLIANCE
    assert world.events["bear"]["event_id"] == "BEAR_HUNT"
    assert world.events["bear"]["seconds_to_start"] == 480


def test_bear_trap_cooldown_text_does_not_become_a_start_reservation():
    world = classify("狩猎陷阱", "剩余时间 00:15:39", "前往")
    assert world.page is Page.ALLIANCE
    assert world.events["bear"]["seconds_to_start"] is None


def test_runtime_keeps_reservation_clock_when_open_window_is_observed(monkeypatch, tmp_path):
    from winter_agent_v2 import event_schedule
    from winter_agent_v2.models import WorldState
    from winter_agent_v2.runtime import LiveRuntime

    path = tmp_path / "timed_event_schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", path)
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = "role-A"

    runtime._record_live_event_reservation(WorldState(
        timestamp="2026-09-25T12:00:00+08:00",
        events={"minimum_guarantee": {
            "event_id": "ARMAMENT_COMPETITION", "seconds_to_start": 90,
        }},
    ))
    schedule = event_schedule.load(path)["role-A|ARMAMENT_COMPETITION"]
    assert schedule.role_id == "role-A"
    assert schedule.start_datetime().isoformat() == "2026-09-25T12:01:30+08:00"
    assert schedule.live_window_state == "SCHEDULED_NOT_OPEN"
    assert schedule.time_zone == "UTC+08:00"

    runtime._record_live_event_reservation(WorldState(
        timestamp="2026-09-25T12:01:31+08:00",
        events={"minimum_guarantee": {
            "event_id": "ARMAMENT_COMPETITION", "remaining_seconds": 500,
        }},
    ))
    opened = event_schedule.load(path)["role-A|ARMAMENT_COMPETITION"]
    assert opened.reserved_start == "2026-09-25T12:01:30+08:00"
    assert opened.live_window_state == "OPEN"
    assert opened.live_window_source == "LIVE_CLIENT_EVENT_WINDOW_OBSERVATION"


def test_runtime_preserves_reservation_when_live_event_page_has_no_readable_timer(
    monkeypatch, tmp_path,
):
    from winter_agent_v2 import event_schedule
    from winter_agent_v2.models import WorldState
    from winter_agent_v2.runtime import LiveRuntime

    path = tmp_path / "timed_event_schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", path)
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = "role-A"
    runtime._record_live_event_reservation(WorldState(
        timestamp="2026-09-25T12:00:00+08:00",
        events={"minimum_guarantee": {
            "event_id": "ARMAMENT_COMPETITION", "seconds_to_start": 90,
        }},
    ))
    runtime._record_live_event_reservation(WorldState(
        timestamp="2026-09-25T12:00:30+08:00",
        events={"minimum_guarantee": {
            "event_id": "ARMAMENT_COMPETITION",
            "seconds_to_start": None,
            "remaining_seconds": None,
        }},
    ))

    observed = event_schedule.load(path)["role-A|ARMAMENT_COMPETITION"]
    assert observed.reserved_start == "2026-09-25T12:01:30+08:00"
    assert observed.live_window_state == "UNKNOWN"
    assert observed.live_window_observed_at == "2026-09-25T12:00:30+08:00"


def test_runtime_does_not_schedule_a_countdown_without_a_registered_event_identity(monkeypatch, tmp_path):
    from winter_agent_v2 import event_schedule
    from winter_agent_v2.models import WorldState
    from winter_agent_v2.runtime import LiveRuntime

    path = tmp_path / "timed_event_schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", path)
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = "role-A"
    runtime._record_live_event_reservation(WorldState(
        timestamp="2026-09-25T12:00:00+08:00",
        events={"minimum_guarantee": {
            "event_id": "CURRENT_EVENT", "seconds_to_start": 90,
        }},
    ))
    assert event_schedule.load(path) == {}
