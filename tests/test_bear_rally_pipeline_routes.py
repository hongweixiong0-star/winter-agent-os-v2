"""Bear rally controls are available to the production MAA recognition path."""

from __future__ import annotations

from pathlib import Path

from winter_agent_v2.executor_router import RoutingTable


ROOT = Path(__file__).resolve().parents[1]


def test_bear_start_and_join_routes_use_current_candidate_assets_with_adb_fallback():
    table = RoutingTable.load()

    expected = {
        "START_RALLY": ("BTN_START_RALLY", "dataset/candidate/bear_rally/btn_start_rally__bear_trap_detail__9db2cb89__0.png"),
        "JOIN_RALLY": ("BTN_JOIN_ROW", "dataset/candidate/bear_rally/btn_join_row__bear_rally_panel__ba0c11fc__0.png"),
    }
    for skill_id, (semantic, source_template) in expected.items():
        entry = table.skills[skill_id]
        node = table.recognition_node(skill_id, semantic)

        assert node is not None
        assert entry["preferred"] == "MAA"
        assert entry["fallback"] == "ADB"
        assert entry["recognition_backend"] == "MAA"
        assert entry["promoted"] is False
        assert node["kind"] == "TEMPLATE"
        assert node["source_template"] == source_template
        assert (ROOT / source_template).is_file()
        assert node["roi"]
