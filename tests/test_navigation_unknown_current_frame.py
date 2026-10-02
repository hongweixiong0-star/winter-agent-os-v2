from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import PANEL_DEPENDENT_NAVIGATION_TARGETS, LiveRuntime


def runtime(tmp_path):
    live = object.__new__(LiveRuntime)
    live.role_id = "role-a"
    live._committed_goal = "MARKSMAN_CAMP_TRAINING"
    live.execution_mode = "PRODUCTION"
    live._advised_control = Mock(return_value=(0.3, 0.4))
    live.device = SimpleNamespace(screenshot=Mock())
    live._capture_path = Mock(return_value=tmp_path / "fresh.png")
    live._device_lost = Mock(return_value=False)
    live._observe = Mock(return_value=WorldState(page=Page.HOME))
    live._l1_state = lambda frame, _: frame.page.value
    live._ocr_service = Mock(return_value=object())
    live._advice_evidence = Mock(return_value=([{
        "text": "训练", "basis": "CURRENT_FRAME_OCR",
        "box_norm": {"x_norm": 0.6, "y_norm": 0.4, "w_norm": 0.1, "h_norm": 0.1},
    }], [], (), ""))
    return live


def test_known_page_missing_navigation_uses_existing_advisor(tmp_path):
    live = runtime(tmp_path)
    assert live._unknown_navigation_target("TRAINING_CAMP_BODY_FROM_FOCUS", WorldState(page=Page.HOME),
        tmp_path / "before.png", skill_id="TAP_FOCUSED_TRAINING_CAMP_MARKSMAN") == (0.3, 0.4)
    live._advised_control.assert_called_once()
    assert live._unknown_semantic_target == live._unknown_skill_id == ""


@pytest.mark.parametrize("skill", ["TRAIN_TROOPS", "START_RALLY", "DISPATCH_MARCH", "USE_ITEM"])
def test_resource_actions_do_not_gain_model_retry(tmp_path, skill):
    live = runtime(tmp_path)
    assert live._unknown_navigation_target("BUTTON", WorldState(page=Page.HOME),
        tmp_path / "before.png", skill_id=skill) is None
    live._advised_control.assert_not_called()


def test_unknown_role_cannot_use_navigation_proposal(tmp_path):
    live = runtime(tmp_path)
    live.role_id = ""
    assert live._unknown_navigation_target("CAMP", WorldState(page=Page.HOME),
        tmp_path / "before.png", skill_id="OPEN_MARKSMAN_TRAINING") is None
    live._advised_control.assert_not_called()


def test_provider_failure_only_defers_current_navigation(tmp_path):
    live = runtime(tmp_path)
    live._advised_control.side_effect = TimeoutError("server unavailable")
    assert live._unknown_navigation_target("CAMP", WorldState(page=Page.HOME),
        tmp_path / "before.png", skill_id="OPEN_MARKSMAN_TRAINING") is None
    assert live._advised_learn_context == {}


def test_a_control_that_needs_the_search_panel_is_not_asked_for_while_it_is_closed(tmp_path):
    """Asking the model here is asking a question the runtime has already answered.

    Measured 2026-10-02, three times in thirty minutes (05:39:48, 05:46:46, 06:08:21): the runtime
    pressed BACK -- the next BACK in that same run is labelled ``close_resource_search_for_daily_goal``
    -- and then ran OPEN_BEAST_SEARCH_TAB, whose target BEAST_SEARCH_TAB exists only while the
    resource search panel is drawn.  The registered locator refused for exactly that reason
    (``if frame.page is not Page.MAP or not frame.resource_search_open: return None``), and the
    runtime then spent a model call and an UNKNOWN trace asking where the tab was.

    The model's own replies name the target and say it is not on the screen -- that is what the
    question fix bought (the three reasons are target-level; the three before it were goal-level).
    So the ~14 s of the only escalation channel bought back an answer the frame already carried.
    The recovery is to re-establish the precondition: SEARCH_RESOURCE opens the panel and the same
    chain already runs it successfully two steps earlier.
    """
    live = runtime(tmp_path)
    frame = WorldState(page=Page.MAP)
    assert getattr(frame, "resource_search_open", False) is False
    assert live._unknown_navigation_target(
        "BEAST_SEARCH_TAB", frame, tmp_path / "before.png",
        skill_id="OPEN_BEAST_SEARCH_TAB") is None
    live._advised_control.assert_not_called()


def test_the_panel_guard_and_the_resolver_agree_on_the_precondition(tmp_path):
    """The condition lives in two places, so their agreement is pinned rather than assumed.

    A target is skipped by the guard *because* the resolver would refuse it for a reason the model
    cannot see.  If the resolver's condition ever changes, this is what notices -- and a guard that
    outlived its condition would silently stop offering the model a question it could answer.
    """
    live = runtime(tmp_path)
    frame = WorldState(page=Page.MAP)
    assert PANEL_DEPENDENT_NAVIGATION_TARGETS, "the guard would be vacuous"
    for semantic in sorted(PANEL_DEPENDENT_NAVIGATION_TARGETS):
        assert live._resolve_semantic_target(semantic, frame, frame_path=None) is None, (
            f"{semantic} is guarded as panel-dependent but the resolver answers without the panel"
        )


def measured():
    return {"text": "训练", "basis": "CURRENT_FRAME_OCR", "point": [0.1, 0.1],
            "box_norm": {"x_norm": 0.05, "y_norm": 0.05, "w_norm": 0.1, "h_norm": 0.1}}


def test_after_inference_target_is_relocated_not_reused(tmp_path):
    live = runtime(tmp_path)
    hit, path, after = live._refresh_advised_region("HOME", "", WorldState(page=Page.HOME), measured())
    assert hit["point"] == pytest.approx([0.65, 0.45])
    assert path == tmp_path / "fresh.png"
    live._device_lost.assert_called_once_with(live.device.screenshot, path)


def test_page_transition_during_inference_rejects_old_target(tmp_path):
    live = runtime(tmp_path)
    live._observe.return_value = WorldState(page=Page.MAP)
    assert live._refresh_advised_region("HOME", "", WorldState(page=Page.HOME), measured()) is None
    live._advice_evidence.assert_not_called()


def test_same_word_on_multiple_controls_is_not_a_unique_identity(tmp_path):
    live = runtime(tmp_path)
    hit = live._advice_evidence.return_value[0][0]
    live._advice_evidence.return_value = ([hit, dict(hit)], [], (), "")
    assert live._refresh_advised_region("HOME", "", WorldState(page=Page.HOME), measured()) is None


def test_role_change_after_inference_rejects_proposal(tmp_path):
    live = runtime(tmp_path)
    live._multi_role_enabled = True
    live.role_switch_controller = SimpleNamespace(identify_current_role=Mock(return_value=("role-b", 0.99)))
    assert live._refresh_advised_region("HOME", "", WorldState(page=Page.HOME), measured()) is None


def test_expired_or_foreign_validation_lease_rejects_proposal(tmp_path):
    live = runtime(tmp_path)
    live.execution_mode = "DEVELOPMENT_VALIDATION"
    live.device_lease = SimpleNamespace(holder=lambda: None)
    assert live._refresh_advised_region("HOME", "", WorldState(page=Page.HOME), measured()) is None


def test_navigation_conditions_are_rechecked_after_model(tmp_path):
    live = runtime(tmp_path)
    live._unknown_skill_id = "OPEN_MARKSMAN_TRAINING"
    live.registry = SimpleNamespace(get=lambda _: SimpleNamespace(ready=lambda _: False))
    assert live._refresh_advised_region("HOME", "", WorldState(page=Page.HOME), measured()) is None


def pending_retry(live):
    live._navigation_unknown_pending = {("role-a", "MARKSMAN_CAMP_TRAINING"): {
        "skill": "OPEN_MARKSMAN_TRAINING", "semantic": "CAMP", "page": Page.HOME,
        "reason": "CAMP_MENU_NOT_PROVEN",
    }}
    live._failed_controls = {"CAMP": "CAMP_MENU_NOT_PROVEN"}
    live.registry = SimpleNamespace(get=lambda _: SimpleNamespace(ready=lambda _: True))


def test_failed_navigation_can_only_resume_selected_same_goal_once(tmp_path):
    live = runtime(tmp_path)
    pending_retry(live)
    allowed = {"OPEN_MARKSMAN_TRAINING"}
    assert live._take_failed_navigation_retry("OTHER_GOAL", WorldState(page=Page.HOME), allowed) is None
    decision = live._take_failed_navigation_retry("MARKSMAN_CAMP_TRAINING", WorldState(page=Page.HOME), allowed)
    assert decision.skill == "OPEN_MARKSMAN_TRAINING"
    assert live._force_unknown_navigation_target == "CAMP"
    assert "CAMP" not in live._failed_controls
    assert live._take_failed_navigation_retry("MARKSMAN_CAMP_TRAINING", WorldState(page=Page.HOME), allowed) is None


def test_changed_navigation_page_cannot_resume_failed_action(tmp_path):
    live = runtime(tmp_path)
    pending_retry(live)
    assert live._take_failed_navigation_retry("MARKSMAN_CAMP_TRAINING", WorldState(page=Page.MAP),
                                             {"OPEN_MARKSMAN_TRAINING"}) is None
    assert live._failed_controls["CAMP"] == "CAMP_MENU_NOT_PROVEN"


def test_retry_cannot_bypass_current_skill_preconditions(tmp_path):
    live = runtime(tmp_path)
    pending_retry(live)
    live.registry.get = lambda _: SimpleNamespace(ready=lambda _: False)
    assert live._take_failed_navigation_retry("MARKSMAN_CAMP_TRAINING", WorldState(page=Page.HOME),
                                             {"OPEN_MARKSMAN_TRAINING"}) is None
    assert "CAMP" in live._failed_controls
