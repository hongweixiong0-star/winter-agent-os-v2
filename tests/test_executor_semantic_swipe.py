from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from winter_agent_v2.executor import Executor
from winter_agent_v2.executor_router import BackendLedger, ExecutorRouter, RoutingTable
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Action, Decision, Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import v2_registry


class Device:
    def __init__(self):
        self.inputs = []

    def status(self):
        return SimpleNamespace(connected=True, resolution=(720, 1280))

    def swipe(self, *args):
        self.inputs.append(("swipe", *args))

    def tap(self, *args):
        self.inputs.append(("tap", *args))


def executor(target, *, production=True):
    device = Device()
    return Executor(production=production, dry_run=not production, device=device,
                    target_resolver=lambda _: target, backend="MAA"), device


def test_semantic_swipe_executes_measured_four_norm_endpoints_on_existing_device():
    live, device = executor((0.4, 0.75, 0.4, 0.3))
    result = live.execute(Action("SWIPE", "QUICK_PANEL_SCROLL_CURRENT", payload={"duration_ms": 450}))
    assert result.executed and result.backend == "MAA"
    assert device.inputs == [("swipe", 288, 960, 288, 384, 450)]


def test_existing_explicit_swipe_and_two_norm_tap_remain_compatible():
    live, device = executor((0.25, 0.5))
    assert live.execute(Action("TAP_SEMANTIC", "CONTROL")).executed
    assert live.execute(Action("SWIPE", "0.4,0.75,0.4,0.3")).executed
    assert device.inputs == [("tap", 180, 640), ("swipe", 288, 960, 288, 384, 300)]


@pytest.mark.parametrize("target,error", [(None, "SEMANTIC_TARGET_NOT_VERIFIED"),
    ((0.4, 0.75), "SWIPE_TARGET_INVALID"),
    ((0.4, 1.5, 0.4, 0.3), "SWIPE_TARGET_OUT_OF_BOUNDS"),
    ((0.4, float("nan"), 0.4, 0.3), "SWIPE_TARGET_OUT_OF_BOUNDS")])
def test_unverified_or_bad_semantic_swipe_never_sends_input(target, error):
    live, device = executor(target)
    result = live.execute(Action("SWIPE", "QUICK_PANEL_SCROLL_CURRENT"))
    assert not result.executed and result.error == error
    assert device.inputs == []


@pytest.mark.parametrize("target", ["QUICK_PANEL_SCROLL_CURRENT", "0.4,0.75,0.4,0.3"])
def test_swipe_dry_run_never_issues_device_input(target):
    live, device = executor((0.4, 0.75, 0.4, 0.3), production=False)
    result = live.execute(Action("SWIPE", target))
    assert not result.executed and result.error == "DRY_RUN_BLOCKED_DEVICE_ACTION"
    assert device.inputs == []


def test_four_norm_gesture_cannot_be_unpacked_as_tap():
    live, device = executor((0.4, 0.75, 0.4, 0.3))
    result = live.execute(Action("TAP_SEMANTIC", "QUICK_PANEL_SCROLL_CURRENT"))
    assert not result.executed and result.error == "SEMANTIC_TARGET_INVALID"
    assert device.inputs == []


@pytest.mark.parametrize("current_gesture,production,error", [
    ([0.4, 0.75, 0.4, 0.3], True, None),
    (None, True, "SEMANTIC_TARGET_NOT_VERIFIED"),
    ([0.4, 0.75, 0.4, 0.3], False, "ALL_BACKENDS_UNAVAILABLE"),
])
def test_registered_panel_swipe_runs_through_scheduler_router_and_single_maa_input(
    tmp_path, monkeypatch, current_gesture, production, error,
):
    """Exercise the actual semantic resolver through the ordinary executor route."""
    frame = tmp_path / "current.png"
    live = object.__new__(LiveRuntime)
    live._ocr_service = Mock(return_value=object())
    monkeypatch.setattr("winter_agent_v2.ocr.read_quick_panel", lambda *_: {
        "open": True, "scroll_swipe_norm": current_gesture})
    world = WorldState(page=Page.HOME, quick_panel={"open": True})
    resolver = lambda semantic: live._resolve_semantic_target(semantic, world, frame_path=frame)
    maa_device, adb_device = Device(), Device()
    adb = Executor(production=production, dry_run=not production, device=adb_device,
                   target_resolver=resolver, backend="ADB")
    adapter = SimpleNamespace(available=lambda: True, unavailable_reason=None)
    router = ExecutorRouter(
        adb_executor=adb, maa_adapter=adapter, adb_resolver=resolver,
        routing=RoutingTable(skills={"SCROLL_QUICK_PANEL_TASKS": {
            "preferred": "MAA", "fallback": "ADB", "recognition_backend": "V2",
        }}), ledger=BackendLedger(path=tmp_path / "backend.jsonl"),
    )
    router.maa_executor = Executor(
        production=production, dry_run=not production, device=maa_device, backend="MAA",
        target_resolver=lambda semantic: router.maa_resolver(semantic, "SCROLL_QUICK_PANEL_TASKS"),
    )
    scheduler = Scheduler(brain=RuleBrain(), registry=v2_registry(), executor=router)
    tick = scheduler.tick(world, Decision("SCROLL_QUICK_PANEL_TASKS", "measured_current_rows", 1.0,
                                          "quick_panel_scrolled"))
    assert tick.execution is not None
    assert tick.execution.error == error
    assert tick.execution.executed is (error is None)
    assert adb_device.inputs == [], "a semantic miss or an issued MAA input must not double-run on ADB"
    assert maa_device.inputs == ([] if error else [("swipe", 288, 960, 288, 384, 450)])
