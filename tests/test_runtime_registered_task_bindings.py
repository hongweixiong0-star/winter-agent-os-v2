"""Registered ordinary routes must reach a real post-action verifier."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from winter_agent_v2.executor import Executor
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Decision, MarchState, Page, SkillState, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import v2_registry


BOUND_TASKS = (
    "OPEN_EVENT_CALENDAR_FROM_HOME", "OPEN_EVENT_CALENDAR_FROM_MAP",
    "OPEN_EVENT_CALENDAR_TAB", "READ_EVENT_CALENDAR",
    "OPEN_EVENT_CALENDAR_DETAIL", "RETURN_EVENT_CALENDAR",
    "COLLECT_TRAINING_BATCH", "OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT_EPIC",
    "OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE", "FREE_HERO_RECRUIT_ADVANCED",
    "FREE_HERO_RECRUIT_EPIC", "SCROLL_QUICK_PANEL_TASKS", "VERIFY_GATHERING",
    "OPEN_BUILDING_UPGRADE", "DAILY_HERO_RECRUIT",
)


@pytest.mark.parametrize("skill_id", BOUND_TASKS)
def test_registered_task_has_binding_but_unchanged_unknown_does_not_pass(skill_id):
    assert v2_registry().get(skill_id) is not None
    assert callable(LiveRuntime.VERIFIED_ATOMIC[skill_id])
    assert not LiveRuntime.VERIFIED_ATOMIC[skill_id](WorldState(), WorldState()).ok


def calendar():
    return WorldState(page=Page.EVENT, events={"calendar": {
        "recognized": True, "visible_dates_raw": ["10/01", "10/02"],
        "entries": [{"event_id": "CANYON_CLASH", "tap_norm": [0.4, 0.5]}],
        "next_detail_event_id": "CANYON_CLASH",
    }})


def detail(event_id="CANYON_CLASH"):
    return WorldState(page=Page.EVENT, events={"calendar_detail": {
        "recognized": True, "event_id": event_id,
    }})


def test_calendar_bindings_check_page_structure_and_target_identity():
    binding = LiveRuntime.VERIFIED_ATOMIC
    for source in (Page.HOME, Page.MAP):
        key = f"OPEN_EVENT_CALENDAR_FROM_{source.value}"
        assert binding[key](WorldState(page=source), calendar()).ok
        assert not binding[key](WorldState(page=source), WorldState(page=Page.EVENT)).ok
    assert binding["OPEN_EVENT_CALENDAR_TAB"](detail(), calendar()).ok
    assert binding["READ_EVENT_CALENDAR"](calendar(), calendar()).ok
    empty = WorldState(page=Page.EVENT, events={"calendar": {"recognized": True}})
    assert not binding["READ_EVENT_CALENDAR"](calendar(), empty).ok
    assert binding["OPEN_EVENT_CALENDAR_DETAIL"](calendar(), detail()).ok
    assert not binding["OPEN_EVENT_CALENDAR_DETAIL"](calendar(), detail("OTHER_EVENT")).ok
    assert binding["RETURN_EVENT_CALENDAR"](detail(), calendar()).ok
    assert not binding["RETURN_EVENT_CALENDAR"](detail(), detail()).ok


def test_completed_training_requires_reward_or_fresh_trainable_idle_queue():
    verify = LiveRuntime.VERIFIED_ATOMIC["COLLECT_TRAINING_BATCH"]
    before = WorldState(page=Page.TRAINING, training={
        "claimable": True, "claim_button_norm": [0.5, 0.8], "troop_type": "MARKSMAN",
    })
    assert not verify(before, before).ok
    assert verify(before, WorldState(page=Page.POPUP, popup="GENERIC_REWARD")).ok
    assert verify(before, WorldState(page=Page.TRAINING, training={
        "claimable": False, "queue_available": True, "trainable": True,
    })).ok
    assert not verify(before, WorldState(page=Page.TRAINING, training={
        "claimable": False, "queue_available": None,
    })).ok


@pytest.mark.parametrize("kind", ["ADVANCED", "EPIC"])
def test_free_recruit_binding_cannot_satisfy_the_other_card_or_repeat_unchanged(kind):
    key = "HERO_RECRUIT_" + kind
    verify = LiveRuntime.VERIFIED_ATOMIC["FREE_" + key]
    before = WorldState(page=Page.HERO, rewards={"hero_recruit_rows": [{
        "key": key, "free_available": True, "free_remaining": 1,
    }]})
    assert not verify(before, before).ok
    assert verify(before, replace(before, rewards={"hero_recruit_rows": [{
        "key": key, "free_available": False, "free_remaining": 0,
    }]})).ok
    other = replace(before, rewards={"hero_recruit_rows": [{
        "key": "HERO_RECRUIT_OTHER", "free_available": True, "free_remaining": 1,
    }]})
    assert not verify(other, WorldState(page=Page.POPUP, popup="HERO_RECRUIT_REWARD")).ok


def test_navigation_bindings_prove_arrival_and_not_task_completion():
    binding = LiveRuntime.VERIFIED_ATOMIC
    home = WorldState(page=Page.HOME, quick_panel={"open": True})
    hero = WorldState(page=Page.HERO)
    epic = binding["OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT_EPIC"]
    assert epic(home, hero).ok
    assert not epic(home, WorldState(page=Page.ALLIANCE)).ok
    daily = binding["DAILY_HERO_RECRUIT"](WorldState(page=Page.DAILY), hero)
    assert daily.ok and daily.reason == "HERO_RECRUIT_PAGE_OPENED"
    assert not binding["DAILY_HERO_RECRUIT"](WorldState(page=Page.DAILY), WorldState(page=Page.DAILY)).ok
    opened = WorldState(page=Page.BUILDING, building={"upgrade_dialog_visible": True})
    assert binding["OPEN_BUILDING_UPGRADE"](home, opened).ok
    assert not binding["OPEN_BUILDING_UPGRADE"](home, WorldState(page=Page.BUILDING)).ok
    assert not binding["BUILDING_UPGRADE"](home, opened).ok


def test_pet_navigation_scroll_and_gathering_use_measured_state():
    binding = LiveRuntime.VERIFIED_ATOMIC
    before = WorldState(page=Page.HOME, quick_panel={"open": True, "rows": [{
        "key": "PET_TREASURE", "y_norm": 0.7, "control": "ARROW",
        "arrow_basis": "ROW_BUTTON_SCAN", "badge": "PRESENT",
    }]})
    assert binding["OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE"](
        before, WorldState(page=Page.PET_TREASURE)).ok
    assert not binding["OPEN_TASK_FROM_QUICK_PANEL_PET_TREASURE"](before, before).ok
    after = replace(before, quick_panel={"open": True, "rows": [{
        **before.quick_panel["rows"][0], "y_norm": 0.6,
    }]})
    assert binding["SCROLL_QUICK_PANEL_TASKS"](before, after).ok
    assert not binding["SCROLL_QUICK_PANEL_TASKS"](before, before).ok
    gathering = WorldState(page=Page.MAP, marches=(MarchState.GATHERING,), resource_target="WOOD")
    assert binding["VERIFY_GATHERING"](WorldState(page=Page.RESOURCE_DETAIL), gathering).ok
    assert not binding["VERIFY_GATHERING"](gathering, replace(gathering, marches=())).ok


def test_blocked_disproved_quick_panel_collect_actions_stay_blocked():
    registry = v2_registry()
    world = WorldState(page=Page.HOME)
    ready = {skill.id for skill in registry.ready(world)}
    for camp in ("SHIELD", "LANCER", "MARKSMAN"):
        key = "COLLECT_FINISHED_TRAINING_" + camp
        assert registry.get(key).state is SkillState.BLOCKED
        assert key not in ready


class FakeDevice:
    """The test never creates a real device adapter or lease."""

    def __init__(self):
        self.inputs = []

    def status(self):
        return SimpleNamespace(connected=True, resolution=(720, 1280))

    def tap(self, x, y):
        self.inputs.append(("tap", x, y))

    def press_back(self):
        self.inputs.append(("back",))


@pytest.mark.parametrize("skill_id", [item for item in BOUND_TASKS if item != "SCROLL_QUICK_PANEL_TASKS"])
def test_bound_task_atomic_action_reaches_existing_scheduler_and_executor(skill_id):
    registry = v2_registry()
    skill = registry.get(skill_id)
    world = WorldState(page=skill.required_page or Page.HOME)
    device = FakeDevice()
    executor = Executor(production=True, dry_run=False, device=device,
                        target_resolver=lambda target: (0.5, 0.5))
    scheduler = Scheduler(brain=RuleBrain(), registry=registry, executor=executor)
    result = scheduler.tick(world, Decision(skill_id, "test_registered_route", 1.0, "observed"))
    assert result.execution is not None
    assert result.execution.executed, result.execution.error
    assert result.decision.skill == skill_id
