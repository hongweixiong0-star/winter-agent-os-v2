"""A task has to exist before it can be scheduled, and existing is not the same as being runnable.

Operator directive 2026-09-23 §一/§二/§三.  The six semantics it names, and where each one is produced:

    CURRENTLY_ACTIONABLE   -> READY        the frame's own reading
    SCHEDULED_NOT_OPEN     -> same name    a known activity whose window has not opened
    OPEN_BUT_NOT_READY     -> BLOCKED      the capability gate, or a queue that is busy
    WAITING_GAME_CONDITION -> BLOCKED      with ``retry_after`` and ``evidence["condition"]``
    UNKNOWN_AVAILABILITY   -> UNKNOWN      a page that could not be read
    COMPLETED              -> COMPLETE     the work was done
    EXPIRED                -> same name    a limited-time window that closed

There is no second task system here on purpose: two statuses were genuinely missing, and the other
five are the project's own words.

Why the two mattered, measured with this library before they existed
(``learning/_probe_existence.py`` is the instrument):

* a bear hunt **opening in two hours** was emitted ``READY`` with ``priority 5000`` -- it outbid the
  sweep tickets that age to 180 and sat level with ``CLEAR_INTEL`` (500), so "exists, not open yet"
  was priced and scheduled as work;
* a bear hunt that had **ended** was emitted ``COMPLETE`` -- §一's "本次任务实际完成" -- so a closed
  window and a finished task were the same record, and §五's "某次活动已经结束，不等于以后不再有同类
  活动" had nowhere to live;
* and neither goal existed at all unless the current frame printed them.  Of 7593 production episodes
  5 carried ``minimum_guarantee`` and none carried ``bear``, so "we are not standing on the page that
  draws it" and "this task does not exist" were the same state of the world.

The §七 acceptance list, scenario by scenario, is at the bottom of this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from winter_agent_v2.event_goal import WindowState, known_activities  # noqa: E402
from winter_agent_v2.goal_library import (  # noqa: E402
    NOT_ACTIONABLE,
    GoalLibrary,
    GoalStatus,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402

BEAR = next(a for a in known_activities() if a.event_id == "BEAR_HUNT")


def board(world: WorldState) -> dict[str, object]:
    return {goal.goal_id: goal for goal in GoalLibrary().discover(world, observations={})}


def bear_frame(**bear) -> WorldState:
    return WorldState(page=Page.EVENT, confidence=0.99, events={"bear": bear})


# --------------------------------------------------------------- §一 the six semantics


def test_a_task_that_can_be_done_now_is_ready():
    """CURRENTLY_ACTIONABLE -- and the only status that is scheduled."""
    goal = board(bear_frame(status="ACTIVE", remaining_seconds=900))["PARTICIPATE_BEAR"]
    assert goal.status is GoalStatus.READY
    assert goal.priority != float("-inf")
    assert goal.available_skills, "an actionable task must offer something to run"


def test_a_task_whose_window_has_not_opened_is_not_ready_and_not_gone():
    """SCHEDULED_NOT_OPEN, and the ticket stays on the board.

    §一: 尚未开放和暂时受阻的任务必须保留记录，但不得冒充当前可执行任务参加普通排序.  Both halves are
    asserted here, because either one alone is a different bug: a goal that disappears loses the plan
    (§二), and a goal that stays schedulable is the two-hour bear hunting a slot it cannot use.
    """
    goal = board(bear_frame(seconds_to_start=7200))["PARTICIPATE_BEAR"]
    assert goal.status is GoalStatus.SCHEDULED_NOT_OPEN
    assert goal.status in NOT_ACTIONABLE
    assert goal.priority == float("-inf"), "it must not enter the ranking"
    assert goal.remaining_seconds == 7200, "and it must keep when it opens"


def test_a_window_that_closed_is_expired_not_completed():
    """EXPIRED vs COMPLETED: §五 -- 某次活动已经结束，不等于以后不再有同类活动."""
    goal = board(bear_frame(status="FINISHED"))["PARTICIPATE_BEAR"]
    assert goal.status is GoalStatus.EXPIRED
    assert goal.status is not GoalStatus.COMPLETE, "the task was not finished by us; the window shut"


def test_a_limited_time_window_that_has_run_out_is_not_scheduled():
    """A closed event page must not stay selectable at a negative deadline.

    Measured 2026-09-23: ``deadline_pressure(0)`` is -100_000, which pushes such a goal down the board
    without ever taking it off it -- so a closed event could still be picked on a frame where nothing
    else had a price.
    """
    world = WorldState(page=Page.EVENT, confidence=0.99, events={"minimum_guarantee": {
        "event_id": "KINGDOM_OF_POWER_CURRENT", "points_missing": 68750, "remaining_seconds": 0,
        "available_skills": ["TRAIN_TROOPS"],
    }})
    goal = board(world)["EVENT_MINIMUM_GUARANTEE"]
    assert goal.status is GoalStatus.EXPIRED
    assert goal.priority == float("-inf")


def test_a_busy_queue_is_a_game_condition_not_a_finished_task():
    """WAITING_GAME_CONDITION, recorded with the condition and the recovery (§一/§六).

    The label was COMPLETE until 2026-09-23, which is §一's "本次任务实际完成": so "the client will not
    let this start yet" and "there is nothing left to train" were the same record, and §六's
    "记录具体恢复条件" had nothing to record against.
    """
    world = WorldState(page=Page.TRAINING, confidence=0.99,
                       training={"status": "IN_PROGRESS", "queue_available": False, "timer": "01:00:00"})
    goal = board(world)["KEEP_TRAINING_PRODUCTIVE"]
    assert goal.status is GoalStatus.BLOCKED
    assert goal.status is not GoalStatus.COMPLETE
    assert goal.evidence["condition"] == "queue_busy"
    assert goal.retry_after == "01:00:00", "the queue's own timer is the recovery condition"


def test_a_page_that_could_not_be_read_is_unknown_not_absent():
    """UNKNOWN_AVAILABILITY: §四 -- an unreadable entry is not permission to go and look."""
    world = WorldState(page=Page.EVENT, confidence=0.99, events={"bear": {"status": None}})
    goal = board(world)["PARTICIPATE_BEAR"]
    assert goal.status is GoalStatus.UNKNOWN
    assert goal.priority == float("-inf")


# --------------------------------------------------------------- §二 the window, from the record


def test_the_registry_says_which_activities_are_real_enough_to_plan_against():
    """Only entries the registry itself vouches for, by its own policy."""
    activities = {a.event_id: a for a in known_activities()}
    assert "BEAR_HUNT" in activities
    for activity in activities.values():
        assert activity.gate in {"REVIEWED", "VERIFIED"}, "a DISCOVERED lead is not a plan"
        assert activity.prepare, f"{activity.event_id} has nothing to prepare (§二)"
        assert activity.participation_conditions, f"{activity.event_id} has no participation rule"
        assert activity.next_open_condition, f"{activity.event_id} has no next-open condition"


def test_no_event_claims_a_start_time_it_never_measured():
    """§二: 如果时间信息不可靠，保留 UNKNOWN，不编造活动时间.

    Every event this project has ever recorded has ``start``/``end`` null, because no live reading has
    ever produced either.  The window is therefore answered from what the client *printed* (a cooldown,
    a countdown) via ``next_open_condition``, and an activity with no reliable time reports UNKNOWN
    rather than a guess.
    """
    for activity in known_activities():
        assert not activity.time_is_known, (
            f"{activity.event_id} claims a start/end time; if that is real, cite the frame"
        )
        assert activity.next_open_condition.get("evidence") or activity.next_open_condition.get("note"), (
            f"{activity.event_id}'s next-open condition must say where it came from"
        )
    assert BEAR.window() in {WindowState.EXPIRED, WindowState.UNKNOWN}


def test_a_known_activity_is_on_the_board_even_when_no_frame_draws_it():
    """Existence no longer requires the current frame -- the deepest half of the conflation."""
    goals = board(WorldState(page=Page.MAP, confidence=0.99))
    assert "SCHEDULED_BEAR_HUNT" in goals, (
        "a known activity must hold a plan on a frame that shows nothing about it"
    )
    goal = goals["SCHEDULED_BEAR_HUNT"]
    assert goal.available_skills == (), "a plan is not a task: it may not be selected"
    assert goal.priority == float("-inf")
    assert goal.evidence["prepare"], "and it has to carry what §三 says to have ready"


def test_the_plan_is_not_duplicated_when_the_frame_does_draw_it():
    """One event, one record -- the live one, because it is the one that may act."""
    goals = board(bear_frame(seconds_to_start=7200))
    assert "PARTICIPATE_BEAR" in goals
    assert "SCHEDULED_BEAR_HUNT" not in goals, (
        "two records for one event would be two places for the answer to disagree"
    )


# --------------------------------------------------------------- §五 the instance is not the cycle


def test_the_next_occurrence_is_woken_by_a_real_reading_not_by_the_clock():
    """§三: 到达预计开放时间后，仍须结合游戏内日历、倒计时、入口或其他真实状态确认是否开放."""
    assert board(bear_frame(seconds_to_start=7200))["PARTICIPATE_BEAR"].status is GoalStatus.SCHEDULED_NOT_OPEN
    assert board(bear_frame(seconds_to_start=60))["PARTICIPATE_BEAR"].status is GoalStatus.READY
    assert board(bear_frame(status="ACTIVE", remaining_seconds=60))["PARTICIPATE_BEAR"].status is GoalStatus.READY


# --------------------------------------------------------------- §七 acceptance, scenario by scenario


def test_scenario_1_a_known_activity_that_is_not_open_keeps_its_plan_and_is_not_hunted(monkeypatch):
    """§七.1: V2 保留任务和准备计划，但不反复寻找尚未出现的入口.

    "Not hunted" is checkable rather than asserted in prose: a goal with no skills cannot be chosen,
    and ``rank`` skips it, so no navigation towards an entrance that is not drawn can be produced by
    this goal on any frame.
    """
    goals = board(WorldState(page=Page.MAP, confidence=0.99))
    plan = goals["SCHEDULED_BEAR_HUNT"]
    assert plan.evidence["prepare"] and plan.evidence["knowledge"]
    chosen = GoalLibrary().best(tuple(goals.values()))
    assert chosen is None or chosen.goal_id != "SCHEDULED_BEAR_HUNT"


def test_scenario_2_when_it_opens_it_becomes_the_task_the_run_can_do():
    """§七.2: 活动开放后，V2 能及时发现并开始有效操作.

    "及时发现" is a property of where the timestamp comes from: the window is read from the client's
    own countdown on the frame the run is standing on, not from a stored schedule, so the transition
    happens on the first frame that shows it -- no timer to be late against.
    """
    closed = board(bear_frame(seconds_to_start=7200))["PARTICIPATE_BEAR"]
    opened = board(bear_frame(seconds_to_start=60))["PARTICIPATE_BEAR"]
    assert closed.status is GoalStatus.SCHEDULED_NOT_OPEN and closed.priority == float("-inf")
    assert opened.status is GoalStatus.READY and opened.priority != float("-inf")


def test_scenario_3_after_it_ends_the_task_stops_but_the_knowledge_stays():
    """§七.3: 不继续执行过期活动任务，但保留下次活动所需知识."""
    goals = board(WorldState(page=Page.MAP, confidence=0.99))
    record = goals["SCHEDULED_BEAR_HUNT"]
    assert record.status is GoalStatus.EXPIRED, "the occurrence that ended is recorded as ended"
    assert record.evidence["knowledge"], "and the knowledge for the next one survives it"
    assert record.evidence["occurrence"]["state"] == "EXPIRED"
    assert "prepare" in record.evidence


def test_scenario_4_without_the_dot_the_page_is_not_entered(monkeypatch):
    """§七.4: 邮件、联盟宝箱无对应红点时，不再无条件进入页面.

    Two layers, both asserted: the goal does not exist (this file's concern is the goal layer), and the
    executor refuses even if a decision is made anyway (``test_entry_badges.TheExecutorBackstopTest``).
    """
    refused = board(WorldState(page=Page.MAP, confidence=0.99, red_dots={
        "BTN_OPEN_MAIL": {"state": "ABSENT"}, "TILE_ALLIANCE_GIFTS": {"state": "ABSENT"}}))
    assert "MAIL_ROUTINE" not in refused
    assert "ALLIANCE_ROUTINE" not in refused
    permitted = board(WorldState(page=Page.MAP, confidence=0.99, red_dots={
        "BTN_OPEN_MAIL": {"state": "PRESENT"}, "TILE_ALLIANCE_GIFTS": {"state": "PRESENT"}}))
    assert permitted["MAIL_ROUTINE"].status is GoalStatus.DISCOVERED


def test_scenario_5_training_and_research_do_not_need_a_dot():
    """§七.5: 训练、科研等不依赖红点的任务，仍能按实际状态正常执行.

    Their eligibility is the queue's own busy/idle state, and a missing red-dot ledger must not touch
    it -- which is the other half of §四's "不得为所有任务统一套用有红点才存在".
    """
    idle = board(WorldState(page=Page.TRAINING, confidence=0.99,
                            training={"status": "IDLE", "queue_available": True, "troop_type": "INFANTRY"}))
    # The camp goal, not the legacy aggregate name: a reading that names its troop type is attributed
    # to its own barracks (``camp_training``), so the id is SHIELD_CAMP_TRAINING here.  Which id it is
    # does not matter to this scenario -- that it is priced and runnable without any red dot does.
    training = next(goal for goal_id, goal in idle.items() if goal_id.endswith("_CAMP_TRAINING"))
    assert training.status in {GoalStatus.READY, GoalStatus.DISCOVERED}
    assert training.priority != float("-inf")
    research = board(WorldState(page=Page.RESEARCH, confidence=0.99,
                                research={"status": "IDLE", "queue_available": True}))["KEEP_RESEARCH_PRODUCTIVE"]
    assert research.priority != float("-inf"), "a free research queue is work with no dot involved"


def test_scenario_6_an_unrunnable_task_does_not_end_the_batch():
    """§七.6: 一个任务尚未开放或受阻时，Scheduler 能立即选择其他可执行任务，而不是全局 SAFE_STOP.

    The point is that the not-open task is *not on the ranking at all*, so it cannot consume the
    cycle in the first place -- which is stronger than relying on the runtime's yield-and-retry, and it
    is why this is fixed at the goal layer rather than in the scheduler.
    """
    world = bear_frame(seconds_to_start=7200)
    goals = board(world)
    ranked = GoalLibrary().rank(tuple(goals.values()), world)
    ranked_ids = {goal.goal_id for goal, _ in ranked}
    assert "PARTICIPATE_BEAR" not in ranked_ids
    assert ranked, "and there is still other work to choose from"


@pytest.mark.parametrize("status", sorted(s.value for s in NOT_ACTIONABLE))
def test_nothing_in_the_not_actionable_set_is_ever_ranked(status):
    """The one comparison that decides executability, checked over the whole set."""
    goals = board(WorldState(page=Page.MAP, confidence=0.99))
    for goal in goals.values():
        if goal.status.value == status:
            assert goal.priority == float("-inf"), f"{goal.goal_id} is {status} and still priced"
