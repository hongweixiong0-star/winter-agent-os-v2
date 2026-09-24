from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_panel_building_queue_opened


def panel_state(*, arrow=True):
    return WorldState(
        page=Page.HOME,
        building={"name": "队列1", "status": "IDLE", "queue_available": True},
        quick_panel={
            "open": True,
            "building": {"status": "IDLE", "queue_available": True},
            "rows": [
                {
                    "key": "BUILDING",
                    "kind": "BUILDING",
                    "label": "队列1",
                    "status": "IDLE",
                    "control": "ARROW" if arrow else "NONE",
                    "arrow_norm": [0.5618, 0.2812],
                    "arrow_basis": "ROW_BUTTON_SCAN" if arrow else "PANEL_RELATIVE_ESTIMATE",
                    "badge": "PRESENT",
                }
            ],
        },
        confidence=0.99,
    )


def test_idle_building_row_is_routed_to_its_current_frame_arrow():
    brain = RuleBrain(current_goal="KEEP_BUILDING_PRODUCTIVE")

    decision = brain.decide(panel_state(), v2_registry())

    assert decision.skill == "OPEN_TASK_FROM_QUICK_PANEL_BUILDING"
    assert decision.expected_result == "task_page_open"


def test_building_row_does_not_use_an_estimated_arrow():
    brain = RuleBrain(current_goal="KEEP_BUILDING_PRODUCTIVE")

    decision = brain.decide(panel_state(arrow=False), v2_registry())

    assert decision.skill != "OPEN_TASK_FROM_QUICK_PANEL_BUILDING"


def test_building_row_target_comes_from_the_current_frame_arrow_scan():
    runtime = object.__new__(LiveRuntime)
    runtime._control_ledger = {}
    runtime._semantic_records_cache = None
    runtime._printed_reads = []
    runtime._printed_printed = set()
    runtime._printed_boxes = {}

    point = runtime._resolve_semantic_target(
        "QUICK_PANEL_ROW_BUILDING", panel_state()
    )

    assert point == (0.5618, 0.2812)


def test_building_row_arrival_requires_a_live_building_action_surface():
    before = panel_state()
    opened = WorldState(
        page=Page.HOME,
        building={"name": "仓库", "upgrade_tap_norm": [0.72, 0.61]},
    )
    unchanged = WorldState(page=Page.HOME, building={"name": "队列1"})

    assert verify_panel_building_queue_opened(before, opened).ok
    assert not verify_panel_building_queue_opened(before, unchanged).ok
