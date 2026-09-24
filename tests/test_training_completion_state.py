from winter_agent_v2.goal_library import GoalLibrary, GoalStatus
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import _quick_panel_queue_state


def test_queue_word_mapping_keeps_completed_idle_busy_and_unknown_distinct():
    assert _quick_panel_queue_state("已完成") == ("COMPLETED", False)
    assert _quick_panel_queue_state("空闲中") == ("IDLE", True)
    assert _quick_panel_queue_state("训练中") == ("IN_PROGRESS", False)
    assert _quick_panel_queue_state("unknown") == ("UNKNOWN", None)


def test_completed_camps_are_not_offered_for_retraining_or_repeated_collection():
    camps = {
        camp: {
            "status": "COMPLETED",
            "queue_available": False,
            "source_word": "已完成",
            "badge": "PRESENT",
        }
        for camp in ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP")
    }
    goals = GoalLibrary().discover(WorldState(page=Page.HOME, camps=camps), observations={})
    by_id = {goal.goal_id: goal for goal in goals}

    assert len(by_id) == len(goals)
    for goal_id in ("SHIELD_CAMP_TRAINING", "LANCER_CAMP_TRAINING", "MARKSMAN_CAMP_TRAINING"):
        goal = by_id[goal_id]
        assert goal.status is GoalStatus.BLOCKED
        assert goal.available_skills == ()
        assert goal.evidence["condition"] == "finished_batch_waiting_for_verified_collection"
        assert goal.evidence["source_word"] == "已完成"
        assert goal.evidence["badge"] == "PRESENT"


def test_idle_camp_remains_independently_trainable_next_to_completed_camps():
    camps = {
        "SHIELD_CAMP": {"status": "COMPLETED", "queue_available": False},
        "LANCER_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "空闲中"},
        "MARKSMAN_CAMP": {"status": "COMPLETED", "queue_available": False},
    }
    goals = {goal.goal_id: goal for goal in GoalLibrary().discover(
        WorldState(page=Page.HOME, camps=camps), observations={}
    )}

    assert goals["SHIELD_CAMP_TRAINING"].status is GoalStatus.BLOCKED
    assert goals["LANCER_CAMP_TRAINING"].status is GoalStatus.READY
    assert goals["LANCER_CAMP_TRAINING"].available_skills == ("TRAIN_TROOPS",)
    assert goals["MARKSMAN_CAMP_TRAINING"].status is GoalStatus.BLOCKED
