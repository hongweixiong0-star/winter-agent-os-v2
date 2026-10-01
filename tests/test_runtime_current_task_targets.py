"""Registered task actions use current controls, never prior scan coordinates."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image, ImageDraw

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import OCRResult, OCRToken
from winter_agent_v2.runtime import LiveRuntime


def token(text, x, y, width=100, height=24):
    return OCRToken(text, 0.99, ((x, y), (x + width, y),
                               (x + width, y + height), (x, y + height)))


@pytest.fixture
def frame(tmp_path):
    path = tmp_path / "current.png"
    Image.new("RGB", (720, 1280), "white").save(path)
    return path


def runtime(tokens=()):
    live = object.__new__(LiveRuntime)
    live._ocr_service = Mock(return_value=SimpleNamespace(
        recognize=Mock(return_value=OCRResult(tuple(tokens), "current"))))
    live._calendar_role_id = Mock(return_value="role-a")
    live.semantic_vision = SimpleNamespace(find=Mock(return_value=SimpleNamespace(center_norm=(0.1, 0.1))))
    return live


def test_panel_swipe_is_remeasured_from_current_frame(monkeypatch, frame):
    live = runtime()
    fresh = Mock(return_value={"open": True, "scroll_swipe_norm": [0.4, 0.75, 0.4, 0.3]})
    monkeypatch.setattr("winter_agent_v2.ocr.read_quick_panel", fresh)
    world = WorldState(page=Page.HOME, quick_panel={
        "open": True, "scroll_swipe_norm": [0.2, 0.9, 0.2, 0.1]})

    assert live._resolve_semantic_target("QUICK_PANEL_SCROLL_CURRENT", world,
                                          frame_path=frame) == (0.4, 0.75, 0.4, 0.3)
    fresh.assert_called_once_with(frame, live._ocr_service.return_value)


@pytest.mark.parametrize("gesture", [None, [0.4, 0.7], [0.4, 1.1, 0.4, 0.3],
                                     [0.4, float("nan"), 0.4, 0.3], [0.4, 0.3, 0.4, 0.7]])
def test_unmeasured_or_invalid_panel_swipe_cannot_reuse_old_gesture(monkeypatch, frame, gesture):
    live = runtime()
    monkeypatch.setattr("winter_agent_v2.ocr.read_quick_panel", lambda *_: {
        "open": True, "scroll_swipe_norm": gesture})
    world = WorldState(page=Page.HOME, quick_panel={"open": True,
                      "scroll_swipe_norm": [0.4, 0.75, 0.4, 0.3]})
    assert live._resolve_semantic_target("QUICK_PANEL_SCROLL_CURRENT", world, frame_path=frame) is None


@pytest.mark.parametrize("page,opened", [(Page.HOME, False), (Page.MAP, True)])
def test_panel_swipe_requires_current_city_panel(frame, page, opened):
    live = runtime()
    assert live._resolve_semantic_target("QUICK_PANEL_SCROLL_CURRENT", WorldState(
        page=page, quick_panel={"open": opened}), frame_path=frame) is None
    live._ocr_service.assert_not_called()


def recruit_tokens(advanced=1, epic=1, epic_button=True):
    tokens = [token("英雄", 10, 10), token("招募", 120, 10),
              token("高级招募", 30, 200), token("今日免费招募剩余：%d次" % advanced, 30, 300),
              token("免费", 500, 400, 60), token("史诗招募", 30, 600),
              token("今日免费招募剩余：%d次" % epic, 30, 700)]
    if epic_button:
        tokens.append(token("免费", 500, 800, 60))
    return tokens


@pytest.mark.parametrize("kind,y", [("ADVANCED", 412), ("EPIC", 812)])
def test_free_recruit_uses_its_current_card_control(frame, kind, y):
    live = runtime(recruit_tokens())
    world = WorldState(page=Page.HERO, rewards={"hero_recruit_rows": [{
        "key": "HERO_RECRUIT_" + kind, "free_button_norm": [0.1, 0.1]}]})
    assert live._resolve_semantic_target("BTN_FREE_RECRUIT_" + kind, world,
                                        frame_path=frame) == pytest.approx((530 / 720, y / 1280), abs=0.0001)
    live._semantic.find.assert_not_called()


@pytest.mark.parametrize("remaining,button", [(0, True), (1, False)])
def test_free_recruit_rechecks_count_and_free_label(frame, remaining, button):
    live = runtime(recruit_tokens(epic=remaining, epic_button=button))
    assert live._resolve_semantic_target("BTN_FREE_RECRUIT_EPIC", WorldState(
        page=Page.HERO, rewards={"hero_recruit_rows": [{"free_available": True}]}), frame_path=frame) is None


def test_home_panel_recruit_label_cannot_match_free_spending_control(frame):
    live = runtime(recruit_tokens())
    assert live._resolve_semantic_target("BTN_FREE_RECRUIT_EPIC", WorldState(
        page=Page.HOME, quick_panel={"open": True}), frame_path=frame) is None
    live._semantic.find.assert_not_called()
    live._ocr_service.assert_not_called()


def calendar_tokens():
    return [token("常规活动", 20, 20, 150, 38),
            token("9月25日", 80, 300), token("9月26日", 250, 300),
            token("峡谷会战", 150, 430, 100, 30), token("堡垒争夺", 300, 600, 100, 30)]


def calendar_frame(frame):
    image = Image.open(frame).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((130, 430, 330, 500), fill=(250, 100, 20))
    draw.rectangle((280, 600, 480, 670), fill=(20, 100, 250))
    image.save(frame)


def test_calendar_next_detail_keeps_current_occurrence_geometry(monkeypatch, frame):
    calendar_frame(frame)
    live = runtime(calendar_tokens())
    choose = Mock(side_effect=lambda _role, entries: entries[1])
    monkeypatch.setattr("winter_agent_v2.event_schedule.calendar_next_entry", choose)
    world = WorldState(page=Page.EVENT, events={"calendar": {
        "recognized": True, "entries": [{"tap_norm": [0.1, 0.1]}]}})
    assert live._resolve_semantic_target("EVENT_CALENDAR_NEXT_DETAIL", world,
                                        frame_path=frame) == pytest.approx((350 / 720, 615 / 1280), abs=0.00001)
    role, entries = choose.call_args.args
    assert role == "role-a"
    assert entries[1]["event_id"] == "FORTRESS_CONTEST"
    assert entries[1]["occurrence_key"]
    assert entries[1]["title_box"]
    live._semantic.find.assert_not_called()


def test_calendar_with_all_current_entries_inspected_has_no_target(monkeypatch, frame):
    calendar_frame(frame)
    live = runtime(calendar_tokens())
    monkeypatch.setattr("winter_agent_v2.event_schedule.calendar_next_entry", lambda *_: None)
    assert live._resolve_semantic_target("EVENT_CALENDAR_NEXT_DETAIL", WorldState(
        page=Page.EVENT, events={"calendar": {"recognized": True}}), frame_path=frame) is None


@pytest.mark.parametrize("world", [WorldState(page=Page.HOME), WorldState(page=Page.EVENT),
    WorldState(page=Page.EVENT, events={"calendar": {"recognized": True},
                                      "calendar_detail": {"recognized": True}})])
def test_calendar_detail_target_requires_current_uncovered_grid(frame, world):
    live = runtime(calendar_tokens())
    assert live._resolve_semantic_target("EVENT_CALENDAR_NEXT_DETAIL", world, frame_path=frame) is None
    live._semantic.find.assert_not_called()


def test_home_template_cannot_impersonate_regular_event_calendar_tab(frame):
    live = runtime()
    assert live._resolve_semantic_target("EVENT_CALENDAR_TAB", WorldState(page=Page.HOME), frame_path=frame) is None
    live._semantic.find.assert_not_called()


def test_recognized_regular_event_panel_still_uses_existing_tab_template(frame):
    live = runtime()
    world = WorldState(page=Page.EVENT, events={"calendar_detail": {"recognized": True}})
    assert live._resolve_semantic_target("EVENT_CALENDAR_TAB", world, frame_path=frame) == (0.1, 0.1)
