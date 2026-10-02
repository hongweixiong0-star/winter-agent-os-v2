from datetime import datetime, timedelta, timezone
from pathlib import Path
from winter_agent_v2 import event_calendar, event_schedule
from winter_agent_v2.goal_library import GoalLibrary, GoalStatus, route_for
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_event_calendar_open, verify_event_calendar_tab_open


def token(text, x, y, w=90, h=32, confidence=0.99):
    return OCRToken(text, confidence, ((x, y), (x + w, y), (x + w, y + h), (x, y + h)))


def test_calendar_reader_uses_visible_date_columns_and_never_infers_execution_times():
    tokens = (
        token("常规活动", 250, 10, 220, 50),
        token("9月25日", 35, 110),
        token("9月26日", 190, 110),
        token("9月27日", 345, 110),
        token("峡谷会战", 193, 180, 110, 36),
        token("堡垒争夺", 350, 180, 110, 36),
    )
    reading = event_calendar.read_event_calendar(tokens, frame_size=(720, 1280))

    assert reading["recognized"] is True
    assert reading["visible_dates_raw"] == ["9月25日", "9月26日", "9月27日"]
    by_name = {row["display_name"]: row for row in reading["entries"]}
    assert by_name["峡谷会战"]["event_id"] == "CANYON_CLASH"
    assert by_name["峡谷会战"]["calendar_date_raw"] == "9月26日"
    assert by_name["堡垒争夺"]["calendar_date_raw"] == "9月27日"
    assert by_name["峡谷会战"]["preview_start_raw"] is None
    assert by_name["峡谷会战"]["battle_start_raw"] is None
    assert reading["time_zone"] is None
    world = OCRPageClassifier().classify(
        OCRResult(tokens, "test"), frame_size=(720, 1280)
    )
    assert world.page is Page.EVENT
    assert world.events["calendar"]["recognized"] is True
    assert "minimum_guarantee" not in world.events


def test_small_home_or_map_rail_label_cannot_impersonate_calendar_page():
    tokens = (token("常规活动", 620, 420, 70, 24),)
    reading = event_calendar.read_event_calendar(tokens, frame_size=(720, 1280))
    world = OCRPageClassifier().classify(
        OCRResult(tokens, "test"), frame_size=(720, 1280)
    )
    assert reading["recognized"] is False
    assert world.page is Page.UNKNOWN
    assert world.events["calendar_entry"]["visible"] is True
    assert world.events["calendar_entry"]["tap_norm"] == [0.90972, 0.3375]


def test_regular_events_default_panel_is_a_separate_dated_detail_not_a_live_countdown():
    tokens = (
        token("常规活动", 96, 22, 134, 38),
        token("冻土之王", 40, 215, 168, 44),
        token("2026-09-21-2026-09-27", 39, 271, 289, 26),
        token("2天 08:01:48", 82, 310, 149, 27),
        token("本期英雄", 51, 416, 102, 28),
        token("第5阶段：基础能力提升", 45, 579, 335, 31),
        token("(08:01:48)", 393, 577, 118, 28),
        token("我的积分：0", 519, 622, 120, 26),
        token("目标积分：1500", 54, 714, 170, 28),
    )
    detail = event_calendar.read_event_detail(tokens, event_label=None, frame_size=(720, 1280))
    assert detail["recognized"] is True
    assert detail["display_name"] == "冻土之王"
    assert detail["preview_start_raw"] == "2026-09-21"
    assert detail["preview_end_raw"] == "2026-09-27"
    assert detail["activity_open_start_raw"] is None
    assert detail["battle_start_raw"] is None
    assert detail["countdown_raw"] is None
    assert detail["unlabeled_timer_raw"] == "2天 08:01:48"
    assert detail["stage_timer_raw"] == "08:01:48"
    assert detail["current_open_state"] == "UNKNOWN"

    world = OCRPageClassifier().classify(OCRResult(tokens, "fixture"), frame_size=(720, 1280))
    assert world.page is Page.EVENT
    assert world.events["calendar_detail"]["event_id"] == detail["event_id"]
    assert "minimum_guarantee" not in world.events


def test_live_date_strip_and_colored_event_bars_are_read_from_current_screenshot():
    frame = Path(
        "dataset/raw/event_calendar_live_20260925/tab_retry_2/"
        "tab_retry_2_step_001_after_refresh_2_20260925T081815044793.png"
    )
    assert frame.exists(), "the live calendar screen is the production-layout fixture"
    tokens = (
        token("常规活动", 95, 23, 135, 37),
        token("2026-09-2516:18:17", 231, 244, 260, 28),
        token("星期三", 27, 328, 73, 28), token("星期四", 127, 329, 73, 27),
        token("星期五", 226, 329, 70, 28), token("星期六", 324, 329, 72, 28),
        token("星期日", 423, 329, 70, 27), token("星期一", 520, 328, 69, 28),
        token("星期二", 618, 328, 68, 28),
        token("09/23", 29, 357, 71, 24), token("09/24", 127, 356, 74, 27),
        token("09/25", 226, 355, 72, 27), token("09/26", 323, 355, 73, 27),
        token("09/27", 424, 356, 70, 27), token("09/28", 521, 358, 71, 24),
        token("09/29", 618, 355, 72, 27),
        token("梦境寻忆", 18, 402, 114, 29),  # section heading, not a clickable event row
        token("梦境寻忆", 141, 472, 104, 30),
        token("明月的盛典", 25, 552, 160, 30),  # section heading, not an event row
        token("妙解干机", 240, 620, 105, 34), token("灯彩映月华", 230, 737, 127, 30),
        token("望月商铺", 289, 850, 105, 33), token("月光领主", 243, 965, 103, 33),
        token("壶纳千祥", 241, 1079, 105, 33),
    )
    reading = event_calendar.read_event_calendar(
        tokens, frame_size=(720, 1280), frame_path=frame,
    )
    assert reading["recognized"] is True
    assert reading["visible_dates_raw"] == ["09/23", "09/24", "09/25", "09/26", "09/27", "09/28", "09/29"]
    assert reading["current_game_date_raw"] == "2026-09-25"
    assert reading["current_game_datetime_raw"] == "2026-09-25 16:18:17"
    assert [(row["date_raw"], row["weekday_raw"]) for row in reading["date_columns"]][:3] == [
        ("09/23", "星期三"), ("09/24", "星期四"), ("09/25", "星期五"),
    ]
    names = [row["display_name"] for row in reading["entries"]]
    assert names == ["梦境寻忆", "妙解干机", "灯彩映月华", "望月商铺", "月光领主", "壶纳千祥"]
    assert reading["entries"][0]["calendar_dates_raw"] == ["09/23", "09/24", "09/25"]
    assert all(row["battle_start_raw"] is None for row in reading["entries"])


def test_opening_regular_events_accepts_default_detail_panel_and_calendar_tab_verifies_grid():
    before = WorldState(page=Page.HOME)
    detail = {"recognized": True, "event_id": "DISCOVERED_EVENT_1"}
    opened = WorldState(page=Page.EVENT, events={"calendar_detail": detail})
    assert verify_event_calendar_open(before, opened).ok is True

    tabbed = WorldState(page=Page.EVENT, events={"calendar": {
        "recognized": True,
        "visible_dates_raw": ["9月25日", "9月26日"],
        "entries": [{"event_id": "CANYON_CLASH"}],
    }})
    result = verify_event_calendar_tab_open(opened, tabbed)
    assert result.ok is True


def test_calendar_entry_detail_overlay_is_read_even_while_calendar_grid_remains_behind_it():
    tokens = (
        token("常规活动", 95, 23, 135, 37),
        token("星期三", 27, 328, 73, 28), token("星期四", 127, 329, 73, 27),
        token("09/23", 29, 357, 71, 24), token("09/24", 127, 356, 74, 27),
        token("梦境寻忆", 141, 472, 104, 30),
        token("梦境寻忆", 151, 602, 382, 46),
        token("2026-09-23 00:00 - 2026-09-25 24:00", 46, 668, 623, 28),
        token("去境里寻那些无价的点滴吧！", 47, 724, 406, 28),
        token("奖励", 316, 772, 94, 30),
        token("前往", 138, 954, 220, 68),
    )
    world = OCRPageClassifier().classify(OCRResult(tokens, "fixture"), frame_size=(720, 1280))
    assert world.page is Page.EVENT
    assert world.events["calendar"]["recognized"] is True
    detail = world.events["calendar_detail"]
    assert detail["recognized"] is True
    assert detail["display_name"] == "梦境寻忆"
    assert detail["preview_start_raw"] == "2026-09-23 00:00"
    assert detail["preview_end_raw"] == "2026-09-25 24:00"
    assert detail["battle_start_raw"] is None
    assert all(row["preview_start_raw"] is None for row in world.events["calendar"]["entries"])
    assert "minimum_guarantee" not in world.events


def test_calendar_tab_target_uses_current_candidate_template_match_not_old_pixels(tmp_path):
    from types import SimpleNamespace

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.semantic_vision = SimpleNamespace(find=lambda _path, name: SimpleNamespace(
        center_norm=(0.1819, 0.1047) if name == "EVENT_CALENDAR_TAB" else None
    ))
    detail = {"recognized": True}
    world = WorldState(page=Page.EVENT, events={"calendar_detail": detail})
    target = runtime._resolve_semantic_target("EVENT_CALENDAR_TAB", world, frame_path=tmp_path / "frame.png")
    assert target == (0.1819, 0.1047)
    assert runtime._resolve_semantic_target(
        "EVENT_CALENDAR_TAB", WorldState(page=Page.HOME, events=world.events),
        frame_path=tmp_path / "frame.png",
    ) is None


def test_calendar_storage_is_role_scoped_due_after_a_day_and_does_not_set_reserved_time(tmp_path):
    path = tmp_path / "timed_event_schedule.json"
    observed = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    schedule = event_schedule.RoleSchedule(
        role_id="role-A", event_id="BEAR_HUNT", reserved_start="2026-09-28T10:00:00+08:00",
        source="ROLE_CONFIG",
    )
    event_schedule.save({"role-A|BEAR_HUNT": schedule}, path)
    snapshot = event_schedule.record_calendar_snapshot(
        role_id="role-A",
        observation={
            "recognized": True, "source": "LIVE_CLIENT_OCR", "visible_dates_raw": ["9月25日", "9月26日"],
            "entries": [{"event_id": "CANYON_CLASH", "display_name": "峡谷会战",
                         "preview_start_raw": "9月28日", "battle_start_raw": None}],
        },
        observed_at=observed,
        evidence_ref="frame.png",
        path=path,
    )
    assert snapshot is not None
    assert event_schedule.latest_calendar_snapshot("role-A", path)["role_id"] == "role-A"
    assert event_schedule.latest_calendar_snapshot("role-B", path) is None
    assert event_schedule.calendar_scan_due("role-B", now=observed, path=path) is True
    assert event_schedule.calendar_scan_due("role-A", now=observed + timedelta(hours=23), path=path) is False
    assert event_schedule.calendar_scan_due("role-A", now=observed + timedelta(hours=24), path=path) is True
    saved = event_schedule.load(path)
    assert saved["role-A|BEAR_HUNT"].reserved_start == "2026-09-28T10:00:00+08:00"


def test_unconfirmed_role_uses_an_explicit_unscoped_calendar_bucket(tmp_path):
    path = tmp_path / "timed_event_schedule.json"
    observed = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    snapshot = event_schedule.record_calendar_snapshot(
        role_id="",
        observation={"recognized": True, "visible_dates_raw": ["9月25日"], "entries": []},
        observed_at=observed,
        path=path,
    )
    assert snapshot["scope"] == "UNSCOPED_CLIENT"
    assert snapshot["role_id"] is None
    assert event_schedule.latest_calendar_snapshot("", path)["scope_key"] == event_schedule.GLOBAL_CALENDAR_SCOPE
    assert event_schedule.latest_calendar_snapshot("role-A", path) is None
    assert event_schedule.calendar_scan_due("", now=observed + timedelta(hours=23), path=path) is False
    assert event_schedule.calendar_scan_due("role-A", now=observed, path=path) is True


def test_detail_keeps_preview_registration_and_battle_times_separate(tmp_path):
    tokens = (
        OCRToken("峡谷会战", 0.99),
        OCRToken("活动详情", 0.99),
        OCRToken("活动时间：2026-09-28 00:00 至 2026-10-03 24:00", 0.99),
        OCRToken("距开始 约2天13小时", 0.99),
        OCRToken("报名时间：2026-09-27 10:00 至 2026-09-27 22:00", 0.99),
    )
    detail = event_calendar.read_event_detail(tokens, event_label="峡谷会战")
    assert detail["recognized"] is True
    assert detail["activity_open_start_raw"] == "2026-09-28 00:00"
    assert detail["activity_open_end_raw"] == "2026-10-03 24:00"
    assert detail["registration_start_raw"] == "2026-09-27 10:00"
    assert detail["battle_start_raw"] is None
    assert detail["countdown_raw"] == "2天13小时"

    path = tmp_path / "timed_event_schedule.json"
    stamp = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    event_schedule.record_calendar_snapshot(
        role_id="role-A",
        observation={"kind": "CALENDAR_GRID", "recognized": True,
                     "visible_dates_raw": ["9月25日", "9月26日"], "entries": []},
        observed_at=stamp, path=path,
    )
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation=detail, observed_at=stamp + timedelta(minutes=1), path=path,
    )
    assert event_schedule.latest_calendar_snapshot("role-A", path)["kind"] == "CALENDAR_GRID"
    assert event_schedule.latest_calendar_snapshot("role-A", path, kind="EVENT_DETAIL")["observation"]["battle_start_raw"] is None


def test_detail_title_comes_from_modal_header_not_visible_calendar_row():
    tokens = (
        token("常规活动", 95, 22, 135, 38),
        token("灯彩映月华", 152, 242, 148, 33),
        token("2026-09-21 00:00 至 2026-09-27 24:00", 48, 314, 374, 23),
        token("活动详情", 48, 280, 100, 24),
        token("前往", 212, 614, 76, 45),
        token("梦境寻忆", 17, 401, 61, 31),
        token("望月商铺", 288, 849, 107, 35),
    )
    detail = event_calendar.read_event_detail(
        tokens, event_label="梦境寻忆", frame_size=(720, 1280)
    )
    assert detail["recognized"] is True
    assert detail["display_name"] == "灯彩映月华"
    assert detail["event_id"] == event_calendar._event_id("灯彩映月华")


def test_calendar_goal_is_scheduled_on_due_home_and_uses_existing_event_route(tmp_path, monkeypatch):
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    world = WorldState(
        page=Page.HOME,
        events={"calendar_entry": {"visible": True, "tap_norm": [0.9, 0.3]}},
    )
    goals = GoalLibrary().discover(world, role_id="role-A")
    calendar_goal = next(goal for goal in goals if goal.goal_id == "DISCOVER_EVENT_CALENDAR")
    assert calendar_goal.status is GoalStatus.READY
    assert calendar_goal.available_skills == ("OPEN_EVENT_CALENDAR_FROM_HOME",)
    assert route_for(calendar_goal.goal_id) == "EVENT"

    current = WorldState(page=Page.EVENT, events={"calendar": {
        "recognized": True, "source": "LIVE_CLIENT_OCR", "entries": [{"event_id": "CANYON_CLASH"}],
        "visible_dates_raw": ["9月25日", "9月26日"],
    }})
    complete = GoalLibrary().discover(current, role_id="role-A")
    observed = next(goal for goal in complete if goal.goal_id == "DISCOVER_EVENT_CALENDAR")
    assert observed.status is GoalStatus.COMPLETE
    assert observed.evidence["event_ids"] == ["CANYON_CLASH"]


def test_calendar_preview_and_live_event_page_share_one_activity_goal():
    """Calendar discovery and current UI state describe one event occurrence, not two tasks."""
    current = WorldState(page=Page.EVENT, events={
        "minimum_guarantee": {
            "event_id": "ARMAMENT_COMPETITION",
            "points_missing": 100,
            "remaining_seconds": 600,
        },
        "calendar": {
            "recognized": True,
            "entries": [{
                "event_id": "ARMAMENT_COMPETITION",
                "display_name": "军备竞赛",
                "occurrence_key": "ARMAMENT_COMPETITION|09/25|09/27",
                "details_observed": True,
            }],
            "visible_dates_raw": ["09/25", "09/26", "09/27"],
        },
    })

    goals = GoalLibrary().discover(current, role_id="role-A")
    event_goals = [goal for goal in goals if (goal.evidence or {}).get("event_id") == "ARMAMENT_COMPETITION"]

    assert len(event_goals) == 1
    assert event_goals[0].goal_id == "EVENT_MINIMUM_GUARANTEE"
    assert event_goals[0].status is GoalStatus.READY
    assert not any(goal.goal_id == "SCHEDULED_ARMAMENT_COMPETITION" for goal in goals)


def test_new_calendar_activity_keeps_the_existing_generic_event_route_registered():
    event_id = "DISCOVERED_EVENT_ABC123"
    current = WorldState(page=Page.EVENT, events={
        "calendar": {
            "recognized": True,
            "entries": [{
                "event_id": event_id,
                "display_name": "新活动候选",
                "occurrence_key": f"{event_id}|09/25|09/27",
                "details_observed": True,
            }],
            "visible_dates_raw": ["09/25", "09/26", "09/27"],
        },
    })

    snapshot = {
        "role_id": "role-A",
        "observed_at": "2026-09-25T12:00:00+00:00",
        "entries": current.events["calendar"]["entries"],
    }
    goals = GoalLibrary().discover(current, role_id="role-A", calendar_snapshot=snapshot)
    activity = next(goal for goal in goals if goal.goal_id == f"SCHEDULED_{event_id}")

    assert activity.evidence["flow_registration_state"] == "PARTIAL_GENERIC_FALLBACK_REGISTERED_WAITING_FOR_LIVE_CONDITIONS"
    assert "DISCOVER_EVENT_CALENDAR" in activity.evidence["registered_goal_ids"]
    assert "EVENT_MINIMUM_GUARANTEE" in activity.evidence["registered_goal_ids"]
    assert "TRY_ORDINARY_CONTROL" in activity.evidence["registered_skill_ids"]
    assert "CLAIM_EVENT_TIER" in activity.evidence["unregistered_skill_ids"]
    assert activity.available_skills == ()
    assert activity.status is GoalStatus.UNKNOWN


def test_due_calendar_from_map_returns_home_and_is_not_starved_by_background_stamina_work(tmp_path, monkeypatch):
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    world = WorldState(
        page=Page.MAP,
        stamina={"current": 201},
        events={"calendar_entry": {"visible": False}},
    )
    goals = GoalLibrary().discover(world, role_id="role-A")
    calendar_goal = next(goal for goal in goals if goal.goal_id == "DISCOVER_EVENT_CALENDAR")
    stamina_goal = next(goal for goal in goals if goal.goal_id == "AVOID_STAMINA_WASTE")
    assert calendar_goal.status is GoalStatus.READY
    assert calendar_goal.available_skills == ("OPEN_HOME",)
    assert calendar_goal.priority > stamina_goal.priority

    brain = RuleBrain(current_goal="EVENT")
    brain.goal_id = "DISCOVER_EVENT_CALENDAR"
    decision = brain.decide(world, v2_registry())
    assert decision.skill == "OPEN_HOME"
    assert decision.expected_result == "home_opened"


def test_visible_calendar_rows_open_details_one_at_a_time_and_persist_per_occurrence(tmp_path):
    path = tmp_path / "timed_event_schedule.json"
    stamp = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    grid = {
        "kind": "CALENDAR_GRID", "recognized": True,
        "visible_dates_raw": ["9月26日", "9月27日"],
        "entries": [
            {"event_id": "CANYON_CLASH", "display_name": "峡谷会战", "calendar_date_raw": "9月26日",
             "occurrence_key": "CANYON_CLASH|9月26日", "tap_norm": [0.4, 0.4]},
            {"event_id": "CANYON_CLASH", "display_name": "峡谷会战", "calendar_date_raw": "9月27日",
             "occurrence_key": "CANYON_CLASH|9月27日", "tap_norm": [0.4, 0.6]},
        ],
    }
    event_schedule.record_calendar_snapshot(role_id="role-A", observation=grid,
                                           observed_at=stamp, path=path)
    detail = {
        "kind": "EVENT_DETAIL", "recognized": True, "event_id": "CANYON_CLASH",
        "display_name": "峡谷会战", "activity_open_start_raw": "2026-09-28 00:00",
        "battle_start_raw": None,
    }
    event_schedule.record_calendar_snapshot(role_id="role-A", observation=detail,
                                           observed_at=stamp + timedelta(minutes=1), path=path)
    saved = event_schedule.latest_calendar_snapshot("role-A", path)
    assert saved["entries"][0]["details_observed"] is True
    assert saved["entries"][0]["detail_observation"]["battle_start_raw"] is None
    assert saved["entries"][1].get("details_observed") is not True

    current = WorldState(page=Page.EVENT, events={"calendar": {
        **grid, "entries": [dict(row) for row in grid["entries"]],
    }})
    goals = GoalLibrary().discover(current, role_id="role-A", calendar_snapshot=saved)
    goal = next(goal for goal in goals if goal.goal_id == "DISCOVER_EVENT_CALENDAR")
    assert goal.status is GoalStatus.READY
    assert goal.evidence["next_event_id"] == "CANYON_CLASH"
    assert goal.evidence["details_observed_count"] == 1


def test_calendar_goal_uses_live_label_box_and_verifies_calendar_page(tmp_path, monkeypatch):
    monkeypatch.setattr(event_schedule, "STATE_PATH", tmp_path / "schedule.json")
    world = WorldState(
        page=Page.HOME,
        events={"calendar_entry": {"visible": True, "tap_norm": [0.91, 0.34]}},
    )
    brain = RuleBrain(current_goal="EVENT")
    brain.goal_id = "DISCOVER_EVENT_CALENDAR"
    decision = brain.decide(world, v2_registry())
    assert decision.skill == "OPEN_EVENT_CALENDAR_FROM_HOME"

    runtime = LiveRuntime.__new__(LiveRuntime)
    # A detached WorldState point is not current-frame grounding. The production
    # resolver must receive/re-read a screenshot; live positive cases are covered
    # by test_runtime_current_task_targets.py.
    assert runtime._resolve_semantic_target("REGULAR_EVENT_ENTRY", world) is None
    on_other_page = WorldState(page=Page.TRAINING, events=world.events)
    assert runtime._resolve_semantic_target("REGULAR_EVENT_ENTRY", on_other_page) is None

    after = WorldState(page=Page.EVENT, events={"calendar": {
        "recognized": True, "visible_dates_raw": ["9月25日", "9月26日"],
        "entries": [{"event_id": "CANYON_CLASH"}],
    }})
    result = verify_event_calendar_open(world, after)
    assert result.ok is True
    assert result.evidence["entry_count"] == 1


def test_runtime_reads_known_city_calendar_entry_only_when_due_and_keeps_stale_role_unscoped(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from PIL import Image

    from winter_agent_v2.runtime import LiveRuntime

    schedule_path = tmp_path / "schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", schedule_path)
    frame = tmp_path / "home.png"
    Image.new("RGB", (720, 1280), "white").save(frame)

    class FakeOCR:
        calls = 0

        def recognize(self, _frame):
            self.calls += 1
            return OCRResult((token("常规活动", 620, 420, 70, 24),), "fixture")

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = "old-role"
    runtime.role_scope = "STALE"
    runtime.vision = SimpleNamespace(ocr=FakeOCR())
    home = WorldState(page=Page.HOME)
    observed = runtime._read_due_calendar_entry(home, frame)
    assert observed.events["calendar_entry"]["visible"] is True
    assert observed.events["calendar_entry"]["tap_norm"] == [0.90972, 0.3375]
    assert runtime.vision.ocr.calls == 1
    assert runtime._calendar_role_id() == ""

    # Keep the saved client observation inside the production freshness window.
    # A literal 2026-09-25 timestamp becomes stale as soon as this test runs on
    # 2026-09-26 or later, correctly triggering another OCR pass.
    calendar_world = WorldState(timestamp=datetime.now(timezone.utc).isoformat(), events={"calendar": {
        "recognized": True, "visible_dates_raw": ["9月25日"], "entries": [],
    }})
    runtime._record_calendar_observation(calendar_world, frame)
    saved = event_schedule.latest_calendar_snapshot("", schedule_path)
    assert saved["scope"] == "UNSCOPED_CLIENT"
    assert saved["role_id"] is None
    assert event_schedule.latest_calendar_snapshot("old-role", schedule_path) is None

    # The observation is fresh, so the known Home frame does not pay for OCR again.
    runtime._read_due_calendar_entry(home, frame)
    assert runtime.vision.ocr.calls == 1


def test_runtime_does_not_replace_full_grid_with_detail_overlay(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image

    schedule_path = tmp_path / "schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", schedule_path)
    frame = tmp_path / "detail.png"
    Image.new("RGB", (720, 1280), "white").save(frame)
    # This is a re-observation of an unreturned detail, inside its pending lifetime.
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    rows = [
        {"event_id": f"EVENT_{index}", "display_name": f"活动{index}",
         "occurrence_key": f"EVENT_{index}|09/25", "calendar_date_raw": "09/25",
         "tap_norm": [0.4, 0.3 + index * 0.1]}
        for index in range(6)
    ]
    event_schedule.record_calendar_snapshot(
        role_id="", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                  "visible_dates_raw": ["09/25", "09/26"], "entries": rows},
        observed_at=stamp, path=schedule_path,
    )
    partial_overlay = {
        "kind": "CALENDAR_GRID", "recognized": True, "details_visible": True,
        "visible_dates_raw": ["09/25", "09/26"], "entries": rows[:2], "entry_count": 2,
    }
    detail = {"kind": "EVENT_DETAIL", "recognized": True, "event_id": "EVENT_1",
              "display_name": "活动1", "preview_start_raw": "2026-09-25",
              "preview_end_raw": "2026-09-27"}
    event_schedule.record_calendar_snapshot(
        role_id="", observation={**detail, "matched_event_id": "EVENT_1",
                                  "matched_occurrence_key": rows[1]["occurrence_key"]},
        observed_at=stamp + timedelta(minutes=1), evidence_ref="prior-detail.png", path=schedule_path,
    )
    monkeypatch.setattr(event_calendar, "read_event_calendar", lambda *_args, **_kwargs: dict(partial_overlay))
    monkeypatch.setattr(event_calendar, "read_event_detail", lambda *_args, **_kwargs: dict(detail))

    class FakeOCR:
        def recognize(self, _frame):
            return OCRResult((), "fixture")

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = ""
    runtime.role_scope = "UNSCOPED_CLIENT"
    runtime.vision = SimpleNamespace(ocr=FakeOCR())
    observed = runtime._read_due_calendar_entry(WorldState(page=Page.EVENT), frame)
    assert "calendar" not in observed.events
    assert observed.events["calendar_overlay_detected"] is True
    assert observed.events["calendar_detail"]["matched_event_id"] == "EVENT_1"
    assert observed.events["calendar_detail"]["calendar_origin"] == "GRID_ENTRY"

    runtime._record_calendar_observation(observed, frame)
    saved = event_schedule.latest_calendar_snapshot("", schedule_path)
    assert len(saved["entries"]) == 6
    assert saved["entries"][1]["details_observed"] is True
    assert event_schedule.calendar_scan_pending("", schedule_path) is True


def test_schedule_records_partial_detail_overlay_without_replacing_last_full_grid(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    rows = [{"event_id": f"EVENT_{index}", "occurrence_key": f"EVENT_{index}|09/25",
             "tap_norm": [0.4, 0.3 + index * 0.1]} for index in range(6)]
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                        "visible_dates_raw": ["09/25", "09/26"], "entries": rows},
        observed_at=stamp, path=path,
    )
    result = event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                        "details_visible": True,
                                        "visible_dates_raw": ["09/25", "09/26"], "entries": rows[:2]},
        observed_at=stamp + timedelta(minutes=1), path=path,
    )
    assert result["kind"] == "CALENDAR_GRID_OVERLAY"
    assert len(event_schedule.latest_calendar_snapshot("role-A", path)["entries"]) == 6
    assert event_schedule.calendar_scan_pending("role-A", path) is True


def test_schedule_carries_detail_evidence_across_unique_one_glyph_ocr_drift(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    old_row = {"event_id": "DISCOVERED_OLD", "display_name": "妙解干机",
               "occurrence_key": "DISCOVERED_OLD|09/23|09/27",
               "calendar_dates_raw": ["09/23", "09/24", "09/25", "09/26", "09/27"],
               "tap_norm": [0.4, 0.5]}
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                        "visible_dates_raw": old_row["calendar_dates_raw"],
                                        "entries": [old_row]},
        observed_at=stamp, path=path,
    )
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "EVENT_DETAIL", "recognized": True,
                                        "event_id": "DISCOVERED_OLD", "display_name": "妙解千机",
                                        "matched_event_id": "DISCOVERED_OLD",
                                        "matched_occurrence_key": old_row["occurrence_key"]},
        observed_at=stamp + timedelta(minutes=1), path=path,
    )
    corrected_row = {**old_row, "event_id": "DISCOVERED_NEW", "display_name": "妙解千机",
                     "occurrence_key": "DISCOVERED_NEW|09/23|09/27"}
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                        "visible_dates_raw": old_row["calendar_dates_raw"],
                                        "entries": [corrected_row]},
        observed_at=stamp + timedelta(minutes=2), path=path,
    )
    saved_row = event_schedule.latest_calendar_snapshot("role-A", path)["entries"][0]
    assert saved_row["event_id"] == "DISCOVERED_NEW"
    assert saved_row["details_observed"] is True
    assert saved_row["detail_observation"]["display_name"] == "妙解千机"


def test_calendar_detail_keeps_goal_active_until_a_new_full_grid_is_seen(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    row = {"event_id": "CANYON_CLASH", "display_name": "峡谷会战",
           "occurrence_key": "CANYON_CLASH|09/25", "calendar_dates_raw": ["09/25"],
           "tap_norm": [0.4, 0.5]}
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                        "visible_dates_raw": ["09/25", "09/26"], "entries": [row]},
        observed_at=stamp, path=path,
    )
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "EVENT_DETAIL", "recognized": True,
                                        "event_id": "CANYON_CLASH", "display_name": "峡谷会战",
                                        "calendar_origin": "GRID_ENTRY",
                                        "matched_event_id": "CANYON_CLASH",
                                        "matched_occurrence_key": row["occurrence_key"]},
        observed_at=stamp + timedelta(minutes=1), path=path,
    )
    assert event_schedule.calendar_scan_pending("role-A", path) is False
    assert event_schedule.calendar_detail_return_pending(
        "role-A", path, now=stamp + timedelta(minutes=2)
    ) is True

    assert event_schedule.clear_calendar_detail_return_pending(
        "role-A", observed_at=stamp + timedelta(minutes=2),
        reason="fresh_known_page_MAP", evidence_ref="map.png", path=path,
    ) is True
    assert event_schedule.calendar_detail_return_pending(
        "role-A", path, now=stamp + timedelta(minutes=2)
    ) is False

    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                        "visible_dates_raw": ["09/25", "09/26"], "entries": [row]},
        observed_at=stamp + timedelta(minutes=3), path=path,
    )
    assert event_schedule.calendar_detail_return_pending(
        "role-A", path, now=stamp + timedelta(minutes=4)
    ) is False


def test_runtime_reobserves_last_detail_even_after_all_rows_are_marked_seen(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image

    schedule_path = tmp_path / "schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", schedule_path)
    frame = tmp_path / "last-detail.png"
    Image.new("RGB", (720, 1280), "white").save(frame)
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    row = {"event_id": "CANYON_CLASH", "display_name": "峡谷会战",
           "occurrence_key": "CANYON_CLASH|09/25", "calendar_dates_raw": ["09/25"],
           "tap_norm": [0.4, 0.5], "details_observed": True}
    event_schedule.record_calendar_snapshot(
        role_id="", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                  "visible_dates_raw": ["09/25", "09/26"], "entries": [row]},
        observed_at=stamp, path=schedule_path,
    )
    detail = {"kind": "EVENT_DETAIL", "recognized": True, "event_id": "CANYON_CLASH",
              "display_name": "峡谷会战", "preview_start_raw": "2026-09-25",
              "preview_end_raw": "2026-09-27", "calendar_origin": "GRID_ENTRY",
              "matched_event_id": "CANYON_CLASH", "matched_occurrence_key": row["occurrence_key"]}
    event_schedule.record_calendar_snapshot(
        role_id="", observation=detail, observed_at=stamp + timedelta(minutes=1),
        evidence_ref="last-detail.png", path=schedule_path,
    )
    assert event_schedule.calendar_scan_pending("", schedule_path) is False
    assert event_schedule.calendar_detail_return_pending("", schedule_path) is True
    monkeypatch.setattr(event_calendar, "read_event_calendar", lambda *_args, **_kwargs: {
        "kind": "CALENDAR_GRID", "recognized": True, "details_visible": True,
        "visible_dates_raw": ["09/25", "09/26"], "entries": [],
    })
    monkeypatch.setattr(event_calendar, "read_event_detail", lambda *_args, **_kwargs: dict(detail))

    class FakeOCR:
        def recognize(self, _frame):
            return OCRResult((), "fixture")

    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = ""
    runtime.role_scope = "UNSCOPED_CLIENT"
    runtime.vision = SimpleNamespace(ocr=FakeOCR())
    observed = runtime._read_due_calendar_entry(WorldState(page=Page.EVENT), frame)
    assert observed.events["calendar_detail"]["calendar_origin"] == "GRID_ENTRY"


def test_unknown_page_with_unreturned_detail_requeues_calendar_recovery(tmp_path, monkeypatch):
    from PIL import Image

    schedule_path = tmp_path / "schedule.json"
    monkeypatch.setattr(event_schedule, "STATE_PATH", schedule_path)
    frame = tmp_path / "unknown.png"
    Image.new("RGB", (720, 1280), "white").save(frame)
    stamp = datetime.now(timezone.utc) - timedelta(minutes=2)
    row = {"event_id": "CANYON_CLASH", "display_name": "峡谷会战",
           "occurrence_key": "CANYON_CLASH|09/25", "calendar_dates_raw": ["09/25"],
           "tap_norm": [0.4, 0.5], "details_observed": True}
    event_schedule.record_calendar_snapshot(
        role_id="", observation={"kind": "CALENDAR_GRID", "recognized": True,
                                  "visible_dates_raw": ["09/25", "09/26"], "entries": [row]},
        observed_at=stamp, path=schedule_path,
    )
    event_schedule.record_calendar_snapshot(
        role_id="", observation={"kind": "EVENT_DETAIL", "recognized": True,
                                  "event_id": "CANYON_CLASH", "display_name": "峡谷会战",
                                  "calendar_origin": "GRID_ENTRY",
                                  "matched_event_id": "CANYON_CLASH",
                                  "matched_occurrence_key": row["occurrence_key"]},
        observed_at=stamp + timedelta(minutes=1), path=schedule_path,
    )
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.role_id = ""
    runtime.role_scope = "UNSCOPED_CLIENT"
    unknown = runtime._read_due_calendar_entry(WorldState(page=Page.UNKNOWN), frame)
    assert unknown.events["calendar_detail_return_pending"] is True

    goal = next(item for item in GoalLibrary().discover(unknown, role_id="")
                if item.goal_id == "DISCOVER_EVENT_CALENDAR")
    assert goal.status is GoalStatus.READY
    assert goal.available_skills == ("BACK",)
    brain = RuleBrain(current_goal="EVENT")
    brain.goal_id = goal.goal_id
    decision = brain.decide(unknown, v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == "unknown_page"


def test_calendar_write_and_later_reservation_save_preserve_both_sources(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    reservation = event_schedule.RoleSchedule(
        role_id="role-A", event_id="BEAR_HUNT",
        reserved_start="2026-10-02T20:00:00+08:00", source="CLIENT_DIRECT_SCHEDULE",
    )
    event_schedule.save({"role-A|BEAR_HUNT": reservation}, path)
    event_schedule.record_calendar_detail(
        role_id="role-A", observation={
            "recognized": True, "event_id": "BEAR_HUNT", "countdown_raw": None,
            "preview_start_raw": "2026-10-01 00:00", "time_zone": None,
            "battle_start_raw": None,
        }, observed_at=stamp, path=path,
    )
    assert event_schedule.load(path)["role-A|BEAR_HUNT"].reserved_start == reservation.reserved_start
    reservation.live_window_state = "UNKNOWN"
    event_schedule.save({"role-A|BEAR_HUNT": reservation}, path)
    saved = event_schedule.latest_calendar_snapshot("role-A", path, kind="EVENT_DETAIL")
    assert saved["observation"]["time_zone"] is None
    assert saved["observation"]["battle_start_raw"] is None
    assert event_schedule.load(path)["role-A|BEAR_HUNT"].source == "CLIENT_DIRECT_SCHEDULE"


def test_next_calendar_entry_uses_fresh_geometry_and_role_inspection_only(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    rows = [{"event_id": "ONE", "occurrence_key": "ONE|10/01", "tap_norm": [0.2, 0.3]},
            {"event_id": "TWO", "occurrence_key": "TWO|10/01", "tap_norm": [0.2, 0.5]}]
    event_schedule.record_calendar_snapshot(
        role_id="role-A", observation={"recognized": True, "entries": rows},
        observed_at=stamp, path=path,
    )
    event_schedule.record_calendar_detail(
        role_id="role-A", observation={"recognized": True, "event_id": "ONE",
                                      "matched_occurrence_key": "ONE|10/01"},
        observed_at=stamp + timedelta(seconds=1), path=path,
    )
    fresh = [{**rows[0], "tap_norm": [0.8, 0.2]}, {**rows[1], "tap_norm": [0.8, 0.6]}]
    next_row = event_schedule.calendar_next_entry("role-A", fresh, path)
    assert next_row["event_id"] == "TWO" and next_row["tap_norm"] == [0.8, 0.6]
    assert event_schedule.calendar_next_entry("role-B", fresh, path)["event_id"] == "ONE"
    assert "details_observed" not in fresh[0]
    # Removing a current-frame target cannot revive its old saved click point.
    assert event_schedule.calendar_next_entry("role-A", [{**fresh[1], "tap_norm": None}], path) is None


def test_old_or_unrecognized_calendar_observation_cannot_replace_newer_grid(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    grid = {"recognized": True, "entries": [{"event_id": "CURRENT"}], "visible_dates_raw": ["10/01"]}
    event_schedule.record_calendar_snapshot(role_id="role-A", observation=grid, observed_at=stamp, path=path)
    for observation, observed_at in (({"recognized": False}, stamp + timedelta(seconds=1)),
                                    ({"recognized": True, "entries": []}, "bad timestamp"),
                                    ({"recognized": True, "entries": []}, stamp - timedelta(minutes=1))):
        event_schedule.record_calendar_snapshot(
            role_id="role-A", observation=observation, observed_at=observed_at, path=path,
        )
    assert event_schedule.latest_calendar_snapshot("role-A", path)["entries"][0]["event_id"] == "CURRENT"


def test_detail_outcome_does_not_transfer_to_later_occurrence_or_wrong_explicit_key(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    row = {"event_id": "BEAR", "display_name": "巨熊行动", "occurrence_key": "BEAR|10/01",
           "calendar_dates_raw": ["10/01"], "tap_norm": [0.3, 0.4]}
    event_schedule.record_calendar_snapshot(role_id="role-A", observation={"recognized": True, "entries": [row]},
                                           observed_at=stamp, path=path)
    event_schedule.record_calendar_detail(role_id="role-A", observation={
        "recognized": True, "event_id": "BEAR", "matched_occurrence_key": "BEAR|WRONG",
    }, observed_at=stamp + timedelta(seconds=1), path=path)
    assert event_schedule.calendar_scan_pending("role-A", path)
    event_schedule.record_calendar_detail(role_id="role-A", observation={
        "recognized": True, "event_id": "BEAR", "matched_occurrence_key": row["occurrence_key"],
    }, observed_at=stamp + timedelta(seconds=2), path=path)
    assert not event_schedule.calendar_scan_pending("role-A", path)
    tomorrow = {**row, "occurrence_key": "BEAR|10/02", "calendar_dates_raw": ["10/02"]}
    assert event_schedule.calendar_next_entry("role-A", [tomorrow], path)["occurrence_key"] == "BEAR|10/02"


def test_stale_return_confirmation_cannot_clear_more_recent_detail(tmp_path):
    path = tmp_path / "schedule.json"
    stamp = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    event_schedule.record_calendar_detail(role_id="role-A", observation={
        "recognized": True, "event_id": "BEAR", "calendar_origin": "GRID_ENTRY",
    }, observed_at=stamp, path=path)
    assert not event_schedule.clear_calendar_detail_return_pending(
        "role-A", observed_at=stamp - timedelta(seconds=1), reason="old_frame", path=path,
    )
    assert event_schedule.calendar_detail_return_pending("role-A", path, now=stamp)
    assert not event_schedule.calendar_detail_return_pending("role-B", path, now=stamp)
    assert not event_schedule.calendar_detail_return_pending("role-A", path, now=stamp + timedelta(hours=1))
