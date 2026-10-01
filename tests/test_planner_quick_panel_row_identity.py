from pathlib import Path

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


def state(path):
    return WorldState(page=Page.HOME, quick_panel={
        "open": True, "handle": {"measured_on": str(path)}, "rows": [{
            "key": "BUILDING", "label": "Embassy", "arrow_basis": "ROW_BUTTON_SCAN",
            "arrow_box_norm": {"x_norm": 0.53, "y_norm": 0.2, "w_norm": 0.06, "h_norm": 0.04},
        }],
    })


def test_current_frame_panel_button_is_distinct_from_its_text_label(tmp_path):
    frame = tmp_path / "fresh.png"
    regions, boxes = LiveRuntime._quick_panel_advice_regions(state(frame), frame)
    assert boxes[0]["element_kind"] == "INTERACTIVE_CONTROL"
    assert boxes[0]["element_semantic"] == "QUICK_PANEL_ROW_BUILDING"
    assert boxes[0]["element_executable"] is True
    assert regions[0]["basis"] == "CURRENT_FRAME_QUICK_PANEL_ROW"
    assert regions[0]["box_norm"] == state(frame).quick_panel["rows"][0]["arrow_box_norm"]


def test_previous_frame_row_metadata_cannot_ground_current_button(tmp_path):
    assert LiveRuntime._quick_panel_advice_regions(state(tmp_path / "old.png"),
                                                  tmp_path / "fresh.png") == ([], [])


def test_unmeasured_row_arrow_is_not_made_clickable(tmp_path):
    frame = tmp_path / "fresh.png"
    world = state(frame)
    world.quick_panel["rows"][0]["arrow_basis"] = "HISTORICAL_POSITION"
    assert LiveRuntime._quick_panel_advice_regions(world, frame) == ([], [])
