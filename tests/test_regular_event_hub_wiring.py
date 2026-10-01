from pathlib import Path
from types import SimpleNamespace

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.goal_library import GoalLibrary, GoalStatus
from winter_agent_v2.goal_library import GoalState
from winter_agent_v2.capability_gate import CapabilityGate
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import OCRResult, OCRToken
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import (
    verify_event_calendar_open, verify_event_calendar_read,
    verify_event_calendar_tab_open, verify_regular_event_tabs_scrolled,
)


def hub_world(*, calendar=False, dx=0.0):
    return WorldState(page=Page.EVENT, events={"regular_events_hub": {
        "recognized": True, "calendar_tab_visible": calendar,
        "calendar_tab_tap_norm": [0.12, 0.13] if calendar else None,
        "scroll_to_start_norm": None if calendar else [0.2, 0.13, 0.8, 0.13],
        "tab_positions_norm": {"峡谷会战": [0.2 + dx, 0.13],
                               "兵工厂争夺战": [0.8 + dx, 0.13]},
    }})


def test_regular_hub_navigation_can_continue_same_goal_without_claiming_scan_complete():
    before, after = WorldState(page=Page.HOME), hub_world()
    verified = verify_event_calendar_open(before, after)
    assert verified.ok and verified.evidence["navigation_progress_only"]
    assert not verify_event_calendar_read(before, after).ok
    goals = []
    GoalLibrary._append_event_calendar_goal(goals, after, role_id="B")
    assert len(goals) == 1 and goals[0].goal_id == "DISCOVER_EVENT_CALENDAR"
    assert goals[0].status is GoalStatus.READY
    assert goals[0].completion == 0
    assert goals[0].available_skills == ("SCROLL_REGULAR_EVENT_TABS",)
    brain = RuleBrain()
    brain.goal_id = goals[0].goal_id
    step = brain.decide(after, v2_registry())
    assert step.skill == "SCROLL_REGULAR_EVENT_TABS"
    assert step.skill in LiveRuntime.VERIFIED_ATOMIC


def test_calendar_tab_after_hub_still_requires_real_calendar_structure():
    before = hub_world(calendar=True)
    goals = []
    GoalLibrary._append_event_calendar_goal(goals, before, role_id="A")
    assert goals[0].available_skills == ("OPEN_EVENT_CALENDAR_TAB",)
    assert not verify_event_calendar_tab_open(before, before).ok
    grid = WorldState(page=Page.EVENT, events={"calendar": {
        "recognized": True, "visible_dates_raw": ["10/02", "10/03"],
        "entries": [{"event_id": "CANYON_CLASH"}],
    }})
    assert verify_event_calendar_tab_open(before, grid).ok


def test_unrelated_event_page_does_not_pass_regular_entry_navigation():
    after = WorldState(page=Page.EVENT, events={"hub": "SUPER_ACTIVITY"})
    assert not verify_event_calendar_open(WorldState(page=Page.HOME), after).ok
    goals = []
    GoalLibrary._append_event_calendar_goal(goals, after, role_id="A")
    assert goals == []


def test_scroll_success_needs_real_strip_change_not_ocr_jitter_or_sent_input():
    before = hub_world()
    assert not verify_regular_event_tabs_scrolled(before, before).ok
    assert not verify_regular_event_tabs_scrolled(before, hub_world(dx=0.001)).ok
    assert verify_regular_event_tabs_scrolled(before, hub_world(dx=0.1)).ok
    assert verify_regular_event_tabs_scrolled(before, hub_world(calendar=True)).ok
    assert not verify_regular_event_tabs_scrolled(before, WorldState(page=Page.HOME)).ok


def test_tab_actions_resolve_current_frame_hub_and_reject_cached_geometry(tmp_path):
    runtime = object.__new__(LiveRuntime)
    runtime._regular_event_hub_on_frame = lambda frame: {}
    cached = hub_world(calendar=True)
    frame = tmp_path / "current.png"
    assert runtime._resolve_semantic_target("EVENT_CALENDAR_TAB", cached, frame_path=frame) is None
    assert runtime._resolve_semantic_target("REGULAR_EVENT_TABS_SCROLL_CURRENT", hub_world(), frame_path=frame) is None
    runtime._regular_event_hub_on_frame = lambda path: hub_world().events["regular_events_hub"]
    assert runtime._resolve_semantic_target("REGULAR_EVENT_TABS_SCROLL_CURRENT", hub_world(), frame_path=frame) == (
        0.2, 0.13, 0.8, 0.13)
    assert runtime._resolve_semantic_target("REGULAR_EVENT_TABS_SCROLL_CURRENT", WorldState(page=Page.HOME), frame_path=frame) is None


def test_partial_tab_ocr_is_lifted_from_crop_to_same_frame(tmp_path):
    from PIL import Image
    def token(text, x, y, w, h):
        return OCRToken(text, 0.99, ((x, y), (x+w, y), (x+w, y+h), (x, y+h)))
    full = (token("常规活动", 95, 22, 135, 38),
            token("兵工厂争夺战", 493, 159, 134, 23),
            token("联盟总动员", 39, 211, 211, 48),
            token("积分：2550", 526, 273, 128, 27))
    calls = []
    def recognize(path, roi=None):
        calls.append((path, roi))
        if roi is None:
            return OCRResult(full, "fixture")
        origin = round(roi["y_norm"] * 1280)
        return OCRResult((token("峡谷会战", 115, 159-origin, 100, 23),), "fixture")
    frame = tmp_path / "current.png"
    Image.new("RGB", (720, 1280)).save(frame)
    runtime = object.__new__(LiveRuntime)
    runtime._ocr_service = lambda: SimpleNamespace(recognize=recognize)
    result = runtime._regular_event_hub_on_frame(frame)
    assert result["recognized"] and result["scroll_to_start_norm"]
    assert result["tab_positions_norm"]["峡谷会战"] == [round(165/720, 5), round(170.5/1280, 5)]
    assert len(calls) == 2 and calls[0][0] == calls[1][0] == frame


def test_scroll_budget_defers_calendar_without_stopping_other_ready_goals():
    runtime = object.__new__(LiveRuntime)
    runtime._calendar_tab_swipe_count = 4
    runtime._yielded_goals = set()
    runtime._policy_allows = lambda goal_id: True
    runtime._gate = lambda: CapabilityGate.empty()
    runtime._narrate_once = lambda text: None
    calendar = GoalState("DISCOVER_EVENT_CALENDAR", GoalStatus.READY,
                         available_skills=("SCROLL_REGULAR_EVENT_TABS",))
    mail = GoalState("MAIL_ROUTINE", GoalStatus.READY, available_skills=("OPEN_MAIL",))
    assert runtime._selectable([calendar, mail], []) == [mail]
    assert "DISCOVER_EVENT_CALENDAR" in runtime._yielded_goals
