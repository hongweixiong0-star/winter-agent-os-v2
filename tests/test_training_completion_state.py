from winter_agent_v2.goal_library import GoalLibrary, GoalStatus
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.ocr import _quick_panel_queue_state
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_completed_training_camp_inspected


def test_queue_word_mapping_keeps_completed_idle_busy_and_unknown_distinct():
    assert _quick_panel_queue_state("已完成") == ("COMPLETED", False)
    assert _quick_panel_queue_state("空闲中") == ("IDLE", True)
    assert _quick_panel_queue_state("训练中") == ("IN_PROGRESS", False)
    assert _quick_panel_queue_state("unknown") == ("UNKNOWN", None)


def test_completed_camps_offer_only_identity_checked_navigation():
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
        camp = goal_id.removesuffix("_TRAINING")
        assert goal.status is GoalStatus.READY
        assert goal.available_skills == (f"OPEN_COMPLETED_TRAINING_CAMP_{camp.removesuffix('_CAMP')}",)
        assert goal.evidence["condition"] == "inspect_exact_camp_before_collect_or_restart"
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

    assert goals["SHIELD_CAMP_TRAINING"].status is GoalStatus.READY
    assert goals["LANCER_CAMP_TRAINING"].status is GoalStatus.READY
    assert goals["LANCER_CAMP_TRAINING"].available_skills == ("TRAIN_TROOPS",)
    assert goals["MARKSMAN_CAMP_TRAINING"].status is GoalStatus.READY


def test_completed_camp_marker_routes_to_inspection_not_collection():
    world = WorldState(
        page=Page.HOME,
        quick_panel={
            "open": True,
            "camps": {"SHIELD_CAMP": {"status": "COMPLETED", "queue_available": False}},
            "rows": [{"key": "SHIELD_CAMP", "control": "DONE", "done_norm": [0.56, 0.43]}],
        },
    )
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = "SHIELD_CAMP_TRAINING"

    decision = brain.decide(world, v2_registry())

    assert decision.skill == "OPEN_COMPLETED_TRAINING_CAMP_SHIELD"
    assert "inspect_" in decision.reason
    assert decision.skill != "COLLECT_FINISHED_TRAINING_SHIELD"


def test_camp_inspection_verifier_checks_identity_and_never_claims_collection():
    before = WorldState(
        page=Page.HOME,
        quick_panel={"rows": [{"key": "SHIELD_CAMP", "control": "DONE", "done_norm": [0.56, 0.43]}]},
    )
    selected_shield = WorldState(
        page=Page.HOME,
        training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED", "camp_tap_norm": [0.44, 0.45]},
    )
    result = verify_completed_training_camp_inspected(before, selected_shield, camp="SHIELD")
    assert result.ok
    assert result.evidence["collection_verified"] is False

    wrong_camp = WorldState(page=Page.TRAINING, training={"troop_type": "LANCER"})
    assert not verify_completed_training_camp_inspected(before, wrong_camp, camp="SHIELD").ok
