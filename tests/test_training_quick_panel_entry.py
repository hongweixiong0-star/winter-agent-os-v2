from tests.test_quick_panel_is_the_state_source import brain_for, home, v2_registry


def test_a_measured_quick_panel_handle_is_not_blocked_by_exhausted_generic_exploration():
    brain = brain_for("TRAIN")
    brain.ordinary_scan_exhausted = True
    closed_panel = {"open": False, "handle": {"state": "COLLAPSED"}, "rows": []}
    decision = brain.decide(home(closed_panel), v2_registry())
    assert decision.skill == "TRY_ORDINARY_CONTROL"
    assert "quick_panel" in decision.reason
