from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.goal_library import GoalLibrary, GoalStatus
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_daily_task_followed


def daily_row(task_id="DAILY_ALLIANCE_CONTRIBUTE", current=4, target=5, frame="frame.png"):
    return {
        "task_id": task_id,
        "state": "AVAILABLE",
        "progress": {"current": current, "target": target},
        "source_frame": frame,
        "action_button": {
            "semantic_id": "BTN_DAILY_TASK_GO",
            "basis": "CURRENT_FRAME_OCR_BOX_AND_ADJACENT_TASK_ROW",
            "bbox_norm": [0.70, 0.40, 0.10, 0.08],
        },
    }


def test_live_daily_row_becomes_existing_alliance_goal_and_keeps_task_identity():
    row = daily_row(frame="live.png")
    goals = GoalLibrary().discover(WorldState(page=Page.DAILY, confidence=0.98,
                                                daily={"tasks": [row]}))

    alliance = next(goal for goal in goals if goal.goal_id == "ALLIANCE_DONATION")
    assert alliance.status is GoalStatus.READY
    assert "FOLLOW_DAILY_TASK" in alliance.available_skills
    assert alliance.evidence["daily_task_id"] == "DAILY_ALLIANCE_CONTRIBUTE"
    assert sum(goal.goal_id == "ALLIANCE_DONATION" for goal in goals) == 1


def test_alliance_goal_survives_daily_go_navigation_back_to_city():
    goals = GoalLibrary().discover(
        WorldState(page=Page.HOME, confidence=0.98),
        alliance_continuation_goal_id="ALLIANCE_DONATION",
    )
    alliance = next(goal for goal in goals if goal.goal_id == "ALLIANCE_DONATION")
    assert alliance.status is GoalStatus.READY
    assert alliance.available_skills == ("OPEN_ALLIANCE",)


def test_fresh_daily_rows_wake_the_daily_panel_goal_from_home():
    row = daily_row(frame="prior-observation.png")
    goals = GoalLibrary().discover(
        WorldState(page=Page.HOME, confidence=0.98),
        observations={"daily": {"reading": {"status": "AVAILABLE", "claimable_count": 0,
                                               "tasks": [row]}, "overdue": False}},
    )
    daily = next(goal for goal in goals if goal.goal_id == "DAILY_ACTIVITY_TARGET")
    assert daily.status is GoalStatus.READY
    assert "OPEN_DAILY" in daily.available_skills


def test_brain_follows_only_the_selected_current_incomplete_row():
    row = daily_row(frame="live.png")
    brain = RuleBrain(current_goal="ALLIANCE")
    brain.goal_id = "ALLIANCE_DONATION"
    brain.daily_task_id = row["task_id"]

    decision = brain.decide(WorldState(page=Page.DAILY, confidence=0.98,
                                       daily={"tasks": [row]}), v2_registry())
    assert decision.skill == "FOLLOW_DAILY_TASK"
    assert decision.expected_result == "daily_task_destination_open"

    row["state"] = "COMPLETED"
    refused = brain.decide(WorldState(page=Page.DAILY, confidence=0.98,
                                      daily={"tasks": [row]}), v2_registry())
    assert refused.skill == "SAFE_STOP"


def test_daily_go_target_is_from_selected_row_in_current_frame_only(tmp_path: Path):
    frame = tmp_path / "daily.png"
    runtime = LiveRuntime.__new__(LiveRuntime)
    runtime.brain = SimpleNamespace(daily_task_id="DAILY_ALLIANCE_CONTRIBUTE")
    world = WorldState(page=Page.DAILY, confidence=0.98,
                       daily={"tasks": [daily_row(frame=str(frame))]})

    assert runtime._resolve_semantic_target("BTN_DAILY_TASK_GO", world, frame_path=frame) == (0.75, 0.44)
    assert runtime._resolve_semantic_target("BTN_DAILY_TASK_GO", world, frame_path=tmp_path / "stale.png") is None


def test_daily_navigation_verifier_requires_a_real_destination_or_row_change():
    row = daily_row()
    before = WorldState(page=Page.DAILY, confidence=0.98, daily={"tasks": [row]})
    unchanged = verify_daily_task_followed(before, before)
    assert not unchanged.ok

    home = WorldState(page=Page.HOME, confidence=0.98)
    assert verify_daily_task_followed(before, home).ok

    changed = daily_row(current=5, target=5)
    after = WorldState(page=Page.DAILY, confidence=0.98, daily={"tasks": [changed]})
    assert verify_daily_task_followed(before, after).ok


def test_claimable_daily_reward_precedes_a_selected_go_row():
    brain = RuleBrain(current_goal="DAILY")
    brain.daily_task_id = "DAILY_INTEL_CLUES"
    world = WorldState(page=Page.DAILY, confidence=0.98, daily={
        "tab": "TASKS", "status": "CLAIMABLE",
        "tasks": [daily_row("DAILY_INTEL_CLUES")],
    })

    decision = brain.decide(world, v2_registry())

    assert decision.skill == "DAILY_CLAIM_REWARDS"
