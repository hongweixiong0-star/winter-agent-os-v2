from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry


def done_panel_state():
    return WorldState(
        page=Page.HOME,
        quick_panel={
            "open": True,
            "rows": [
                {
                    "key": "SHIELD_CAMP",
                    "kind": "CAMP",
                    "status": "IDLE",
                    "control": "DONE",
                    "source_word": "已完成",
                    "done_norm": [0.56, 0.43],
                    "label_norm": [0.31, 0.43],
                }
            ],
            "camps": {
                "SHIELD_CAMP": {
                    "status": "IDLE",
                    "queue_available": True,
                    "source_word": "已完成",
                }
            },
        },
        confidence=0.99,
    )


def test_done_camp_row_is_yielded_instead_of_clicked_as_an_entry():
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = "SHIELD_CAMP_TRAINING"

    decision = brain.decide(done_panel_state(), v2_registry())

    assert decision.skill == "SAFE_STOP"
    assert "draws_no_enter_control" in decision.reason


def test_done_camp_label_cannot_fall_through_to_a_click_target():
    runtime = object.__new__(LiveRuntime)
    runtime._control_ledger = {}
    runtime._semantic_records_cache = None
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}

    point = runtime._resolve_semantic_target(
        "QUICK_PANEL_ROW_SHIELD_CAMP", done_panel_state()
    )

    assert point is None
