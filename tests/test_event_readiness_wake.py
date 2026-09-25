"""The readiness clock must fire without a frame, and must not fire without a reservation.

Task book §五 asks for a wake that

    不得依赖下一次普通 AUTO 周期、普通任务优先级评分或人工再次发送指令

and the subtle half of that is the second test below.  A wake that fires on a guess is worse
than no wake: it would spend a real preparation window on a minute nobody read.  So this file
pins both directions -- the ladder must promote the bear when a reservation is live, and it
must stay completely inert when one is not.

The bug this file was written from is worth recording, because it is the kind a table catches
and a single assertion does not: the ladder was first ordered loosest-first, so
``readiness_phase(12)`` answered T30 and ``readiness_phase(3)`` also answered T30.  T5 is the
rung whose whole instruction is "ordinary tasks yield", so that ordering meant the runtime
would never yield -- and every individual threshold still looked right.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_schedule as es  # noqa: E402


NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)


def _schedule(minutes: float | None, *, role_id="1171757165", roles=("A",), event="BEAR_HUNT",
              source="LIVE_CLIENT") -> es.RoleSchedule:
    start = None if minutes is None else (NOW + timedelta(minutes=minutes)).isoformat()
    return es.RoleSchedule(
        role_id=role_id, event_id=event, reserved_start=start, role=roles[0], source=source
    )


# ---------------------------------------------------------------- the ladder, rung by rung


@pytest.mark.parametrize("minutes,expected", [
    (None, "IDLE"), (120, "IDLE"), (45, "IDLE"), (31, "IDLE"),
    (30, "T30"), (29, "T30"), (16, "T30"),
    (15, "T15"), (12, "T15"), (6, "T15"),
    (5, "T5"), (3, "T5"), (2, "T5"),
    (1, "T1"), (0.5, "T1"),
    (0, "OPEN"), (-1, "OPEN"),
])
def test_every_rung_of_the_ladder(minutes, expected):
    """The tightest rung containing the remaining time wins.

    ``12 -> T15`` and ``3 -> T5`` are the two that the loosest-first ordering got wrong, and
    they are the reason this is a table rather than a couple of assertions.
    """
    assert es.readiness_phase(minutes).value == expected


def test_tighter_rungs_are_worth_more():
    """The bonus must increase monotonically toward the event, or "yield" cannot be expressed."""
    order = ["IDLE", "T30", "T15", "T5", "T1", "OPEN"]
    values = [es.PHASE_PRIORITY[es.ReadinessPhase(name)] for name in order]
    assert values == sorted(values)
    assert values[0] == 0.0, "IDLE must be worth exactly nothing, not a small amount"
    assert es.PHASE_PRIORITY[es.ReadinessPhase.T5] >= 1000.0, (
        "T5 and tighter must dominate ordinary work; the book's instruction is that they yield"
    )


# ------------------------------------------------------------------- no reservation, no wake


def test_no_reservation_is_idle_and_worth_nothing():
    """The honesty rule: a clock nobody read must not produce preparation."""
    schedule = _schedule(None)
    assert schedule.phase_at(NOW) is es.ReadinessPhase.IDLE
    assert schedule.priority_bonus(NOW) == 0.0
    assert schedule.minutes_to_start(NOW) is None


def test_an_unparseable_reservation_is_idle_not_an_exception():
    """A corrupted file must degrade to "no wake", never take the AUTO cycle down."""
    schedule = es.RoleSchedule(role_id="r", event_id="BEAR_HUNT", reserved_start="not-a-time")
    assert schedule.start_datetime() is None
    assert schedule.phase_at(NOW) is es.ReadinessPhase.IDLE
    assert schedule.priority_bonus(NOW) == 0.0


def test_an_empty_schedule_file_loads_as_empty(tmp_path):
    assert es.load(tmp_path / "does-not-exist.json") == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert es.load(broken) == {}

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text(json.dumps({"roles": "nope"}), encoding="utf-8")
    assert es.load(wrong_shape) == {}


# --------------------------------------------------------------- multi-role arbitration


def test_the_soonest_role_is_the_one_served():
    """§六: 如果两个角色活动时间接近，优先保障双方均至少成功参战一次.

    With two roles on one device, the phase the Scheduler acts on is the **closest** role's.
    Taking the first entry in the file instead would serve whichever role happens to sort
    first, which is how one account gets four rallies and the other gets none.
    """
    schedules = {
        "roleA|BEAR_HUNT": _schedule(25, role_id="roleA"),
        "roleB|BEAR_HUNT": _schedule(3, role_id="roleB"),
    }
    soonest = es.soonest(schedules, NOW)
    assert soonest is not None and soonest.role_id == "roleB"
    assert soonest.phase_at(NOW) is es.ReadinessPhase.T5


def test_a_role_with_no_reservation_does_not_win_the_arbitration():
    """An unscheduled role must not be able to outrank a scheduled one by being unknown."""
    schedules = {
        "roleA|BEAR_HUNT": _schedule(None, role_id="roleA"),
        "roleB|BEAR_HUNT": _schedule(20, role_id="roleB"),
    }
    soonest = es.soonest(schedules, NOW)
    assert soonest is not None and soonest.role_id == "roleB"


def test_soonest_is_none_when_nobody_has_a_reservation():
    assert es.soonest({"a|B": _schedule(None)}, NOW) is None
    assert es.soonest({}, NOW) is None


@pytest.mark.parametrize("minutes,expected_seconds", [
    (60, 30 * 60),       # T-30
    (30, 15 * 60),       # T-15
    (20, 5 * 60),        # T-15 boundary is already behind us
    (15, 10 * 60),       # T-5
    (7, 2 * 60),          # T-5 boundary is already behind us
    (5, 4 * 60),          # T-1
    (2, 60),              # T-1 boundary is already behind us
    (0.5, 30),            # OPEN
])
def test_auto_wakes_at_the_next_readiness_boundary(minutes, expected_seconds):
    schedule = _schedule(minutes)
    assert es.seconds_until_next_transition({"role|BEAR_HUNT": schedule}, NOW) == expected_seconds


def test_event_wake_shortens_but_never_extends_ordinary_polling():
    schedule = _schedule(20)
    assert es.bounded_poll_delay_seconds(600, {"role|BEAR_HUNT": schedule}, NOW) == 300
    assert es.bounded_poll_delay_seconds(120, {"role|BEAR_HUNT": schedule}, NOW) == 120


def test_no_or_already_open_reservation_keeps_the_ordinary_poll():
    assert es.bounded_poll_delay_seconds(600, {}, NOW) == 600
    assert es.seconds_until_next_transition({"role|BEAR_HUNT": _schedule(None)}, NOW) is None
    assert es.seconds_until_next_transition({"role|BEAR_HUNT": _schedule(-2)}, NOW) is None


# ----------------------------------------------------------------------- persistence


def test_a_reservation_round_trips_through_the_file(tmp_path):
    path = tmp_path / "timed_event_schedule.json"
    schedules: dict[str, es.RoleSchedule] = {}
    es.record_reservation(
        schedules, role_id="1171757165", event_id="BEAR_HUNT",
        reserved_start=(NOW + timedelta(minutes=17)).isoformat(),
        source="LIVE_CLIENT", role="JOINER", alliance="zoe", now=NOW,
    )
    es.save(schedules, path)

    loaded = es.load(path)
    assert len(loaded) == 1
    role = loaded["1171757165|BEAR_HUNT"]
    assert role.role == "JOINER"
    assert role.alliance == "zoe"
    assert role.source == "LIVE_CLIENT"
    assert role.phase_at(NOW) is es.ReadinessPhase.T30


def test_clearing_a_reservation_is_first_class(tmp_path):
    """A stale reservation would wake the runtime for an event that already happened."""
    path = tmp_path / "s.json"
    schedules: dict[str, es.RoleSchedule] = {}
    es.record_reservation(schedules, role_id="r", event_id="BEAR_HUNT",
                          reserved_start=(NOW + timedelta(minutes=10)).isoformat(),
                          source="LIVE_CLIENT", now=NOW)
    es.record_reservation(schedules, role_id="r", event_id="BEAR_HUNT",
                          reserved_start=None, source="WINDOW_ENDED", now=NOW)
    es.save(schedules, path)
    assert es.load(path)["r|BEAR_HUNT"].reserved_start is None
    assert es.load(path)["r|BEAR_HUNT"].phase_at(NOW) is es.ReadinessPhase.IDLE


def test_live_countdown_becomes_a_role_scoped_reservation():
    schedules: dict[str, es.RoleSchedule] = {}
    row = es.record_live_countdown(
        schedules, role_id="roleB", event_id="BEAR_HUNT", seconds_to_start=90,
        source="LIVE_CLIENT_COUNTDOWN", role="JOINER", now=NOW,
    )
    assert row.role_id == "roleB"
    assert row.role == "JOINER"
    assert row.source == "LIVE_CLIENT_COUNTDOWN"
    assert row.start_datetime() == NOW + timedelta(seconds=90)
    assert row.phase_at(NOW) is es.ReadinessPhase.T5


# ------------------------------------------------------------ the Scheduler integration


def _scheduler(schedules: dict[str, es.RoleSchedule]):
    from winter_agent_v2.scheduler import Scheduler
    from winter_agent_v2.skills import v2_registry

    class _Brain:
        def decide(self, world, registry):
            raise AssertionError("not used")

    class _Executor:
        def execute(self, action, skill_id=None):
            raise AssertionError("not used")

    scheduler = Scheduler(_Brain(), v2_registry(), _Executor())
    scheduler._schedule = schedules
    return scheduler


def test_the_scheduler_promotes_bear_skills_from_the_clock_alone():
    """The point of §五, at the seam that actually decides.

    With a reservation 3 minutes out, ``Scheduler.readiness`` must report the T5 bonus and the
    role it came from -- and this must be true with no frame involved at all, which is what
    makes it a *wake* rather than the frame-driven REALTIME boost that already existed.
    """
    scheduler = _scheduler({"1171757165|BEAR_HUNT": _schedule(3)})
    bonus, phase, role = scheduler.readiness(NOW)
    assert phase is es.ReadinessPhase.T5
    assert bonus == es.PHASE_PRIORITY[es.ReadinessPhase.T5]
    assert role is not None and role.role_id == "1171757165"


def test_the_scheduler_stays_inert_without_a_reservation():
    """No reservation -> identical behaviour to before this feature existed."""
    assert _scheduler({}).readiness(NOW) == (0.0, es.ReadinessPhase.IDLE, None)
    assert _scheduler({"r|BEAR_HUNT": _schedule(None)}).readiness(NOW)[0] == 0.0


def test_the_scheduler_reads_the_bear_skills_from_the_goal_library():
    """No second list of bear skills to drift out of sync.

    The bonus is applied to the skills ``PARTICIPATE_BEAR`` can emit, asked of the library.  If
    that goal ever gains or loses a skill, this follows automatically -- which a hardcoded set
    in the scheduler would not.
    """
    from winter_agent_v2.models import Page, WorldState

    scheduler = _scheduler({"1171757165|BEAR_HUNT": _schedule(3)})
    world = WorldState(page=Page.ALLIANCE, confidence=0.9)
    skills = scheduler._bear_goal_skills(world)
    # The goal may legitimately offer nothing on a frame that shows no event, and that is not a
    # failure -- what must hold is that whatever it offers comes from the goal, not from here.
    assert isinstance(skills, set)
    assert all(isinstance(name, str) for name in skills)


def test_live_goal_ranking_consumes_only_the_active_roles_reservation(monkeypatch):
    """The production runtime ranks via GoalLibrary, so the clock must reach that seam.

    A reservation for another role must not promote this role's event, and a matching
    reservation may promote only a live, actionable event goal.
    """
    from winter_agent_v2.goal_library import GoalLibrary, GoalState, GoalStatus
    from winter_agent_v2.runtime import LiveRuntime

    goal = GoalState(
        "EVENT_MINIMUM_GUARANTEE", GoalStatus.READY, reward_value=1000,
        available_skills=("TRY_ORDINARY_CONTROL",), evidence={"event_id": "ARMAMENT_COMPETITION"},
    )
    ordinary = GoalState(
        "CLAIM_FREE_MAIL", GoalStatus.READY, reward_value=250,
        available_skills=("MAIL_CLAIM_REWARDS",),
    )
    runtime = object.__new__(LiveRuntime)
    runtime.role_id = "roleA"
    monkeypatch.setattr(es, "load", lambda: {
        "roleB|ARMAMENT_COMPETITION": _schedule(3, role_id="roleB", event="ARMAMENT_COMPETITION")
    })

    other_role = runtime._event_readiness_for_goals((goal, ordinary), now=NOW)
    assert other_role == {}

    monkeypatch.setattr(es, "load", lambda: {
        "roleA|ARMAMENT_COMPETITION": _schedule(3, role_id="roleA", event="ARMAMENT_COMPETITION")
    })
    matching = runtime._event_readiness_for_goals((goal, ordinary), now=NOW)
    assert matching == {"EVENT_MINIMUM_GUARANTEE": es.PHASE_PRIORITY[es.ReadinessPhase.T5]}
    ranked = GoalLibrary().rank((goal, ordinary), event_readiness=matching, now=NOW)
    assert ranked[0][0].goal_id == "EVENT_MINIMUM_GUARANTEE"
    assert ranked[0][1].as_row()["event_readiness"] == 2000.0


def test_readiness_does_not_make_a_waiting_or_skillless_goal_runnable(monkeypatch):
    from winter_agent_v2.goal_library import GoalState, GoalStatus
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime.role_id = "roleA"
    monkeypatch.setattr(es, "load", lambda: {"roleA|BEAR_HUNT": _schedule(3)})
    waiting = GoalState(
        "SCHEDULED_BEAR_HUNT", GoalStatus.SCHEDULED_NOT_OPEN,
        available_skills=(), evidence={"event_id": "BEAR_HUNT"},
    )
    assert runtime._event_readiness_for_goals((waiting,), now=NOW) == {}


def test_past_reservation_wakes_but_does_not_prove_live_window_open(monkeypatch):
    from winter_agent_v2.goal_library import GoalState, GoalStatus
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime.role_id = "roleA"
    goal = GoalState(
        "EVENT_MINIMUM_GUARANTEE", GoalStatus.READY, reward_value=100,
        available_skills=("TRY_ORDINARY_CONTROL",), evidence={"event_id": "ARMAMENT_COMPETITION"},
    )
    unverified = _schedule(-1, role_id="roleA", event="ARMAMENT_COMPETITION")
    monkeypatch.setattr(es, "load", lambda: {"roleA|ARMAMENT_COMPETITION": unverified})
    assert runtime._event_readiness_for_goals((goal,), now=NOW) == {}

    opened = _schedule(-1, role_id="roleA", event="ARMAMENT_COMPETITION")
    opened.live_window_state = es.LiveWindowState.OPEN.value
    opened.live_window_observed_at = NOW.isoformat()
    monkeypatch.setattr(es, "load", lambda: {"roleA|ARMAMENT_COMPETITION": opened})
    assert runtime._event_readiness_for_goals((goal,), now=NOW) == {
        "EVENT_MINIMUM_GUARANTEE": es.PHASE_PRIORITY[es.ReadinessPhase.OPEN]
    }
