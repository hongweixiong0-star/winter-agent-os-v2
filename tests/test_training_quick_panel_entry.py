from tests.test_quick_panel_is_the_state_source import brain_for, home, v2_registry


def test_a_measured_quick_panel_handle_is_not_blocked_by_exhausted_generic_exploration():
    brain = brain_for("TRAIN")
    brain.ordinary_scan_exhausted = True
    closed_panel = {"open": False, "handle": {"state": "COLLAPSED"}, "rows": []}
    decision = brain.decide(home(closed_panel), v2_registry())
    assert decision.skill == "TRY_ORDINARY_CONTROL"
    assert "quick_panel" in decision.reason


def test_productive_training_yields_when_the_quick_panel_entry_is_not_observed():
    brain = brain_for("TRAIN", goal_id="KEEP_TRAINING_PRODUCTIVE")
    decision = brain.decide(home({"open": False, "rows": []}), v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == (
        "training_quick_panel_entry_not_observed_so_the_known_failing_power_detour_is_skipped"
    )


def test_productive_research_yields_when_the_quick_panel_entry_is_not_observed():
    brain = brain_for("RESEARCH", goal_id="KEEP_RESEARCH_PRODUCTIVE")
    decision = brain.decide(home({"open": False, "rows": []}), v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert decision.reason == (
        "research_quick_panel_entry_not_observed_so_the_known_failing_power_detour_is_skipped"
    )
