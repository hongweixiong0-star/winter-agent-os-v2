"""A goal whose entry sits on the city HUD must not be sent there through a panel.

Measured 2026-10-05, goal ``KEEP_TRAINING_PRODUCTIVE``, skill ``OPEN_INFANTRY_TRAINING`` -- the
whole of its history, 114 rows and 65 failures, and the separation is total:

    quick_panel.open = False    49/54 SUCCESS   (91%)
    quick_panel.open = True      0/60 SUCCESS   (0%)

every failure with an **empty** ``after_screenshot`` and duration 0.06-0.13 s (no tap was sent),
every one ``SEMANTIC_TARGET_NOT_VERIFIED`` carrying ``UNKNOWN_NAV:PROVIDER_ANSWERED_NOTHING``.

The skill taps ``BTN_OPEN_TRAINING_FROM_CAMP`` -- the 训练 control on the selected barracks'
action bar, drawn at the bottom-left of the city frame -- and the quick panel is drawn **over**
it.  The failing frame shows the panel open on the 野外 tab (the camp rows live on 城镇),
``read_quick_panel`` returning no ``camps`` section, and the action bar nowhere in sight.

So the panel's being open is a *sufficient* condition for failure, and the step is refused while
it is.  This is the same shape as the ``close_resource_search_*`` guards that were added when the
resource-search panel covered the 回城 door -- see
``test_route_goal_requires_home.test_an_open_resource_search_panel_is_closed_first`` -- and it is
driven the same way: the decision, not the description.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import verify_quick_panel_scrolled_back  # noqa: E402


def _panel(rows_by_key):
    """An open panel on HOME whose visible rows sit at the given ``y_norm`` values."""
    return WorldState(page=Page.HOME, quick_panel={
        "open": True,
        "rows": [{"key": key, "y_norm": y} for key, y in rows_by_key.items()],
    })

#: The four goal ids the branch serves; all four must behave alike.
GOALS = ("KEEP_TRAINING_PRODUCTIVE", "SHIELD_CAMP_TRAINING",
         "LANCER_CAMP_TRAINING", "MARKSMAN_CAMP_TRAINING")

COVERED_REASON = "quick_panel_is_open_on_a_tab_without_the_training_entry_so_the_camp_bar_is_covered"
DISPATCH_REASON = "panel_open_but_training_unread_so_the_page_that_answers_it_is_the_step"

#: The rows the failing frames actually carried: the 野外 tab, no camp row among them.
WILDERNESS_ROWS = [
    {"key": "HERO_RECRUIT", "kind": "", "control": "ARROW",
     "arrow_norm": [0.5618, 0.3664], "status": "IN_PROGRESS"},
    {"key": "PET_TREASURE", "kind": "", "control": "ARROW",
     "arrow_norm": [0.5618, 0.5109], "status": "COMPLETED"},
    {"key": "MY_REWARDS", "kind": "", "control": "DONE",
     "arrow_norm": [0.3792, 0.5941], "done_norm": [0.5618, 0.6018], "status": "COMPLETED"},
]

#: The frame ``test_unanswered_training_opens_the_training_page`` was written on: the panel open on
#: the tab that DOES draw the training section.  Kept here as the other side of the boundary.
TRAINING_TAB_ROWS = [{"key": "TRAINING", "label": "部队训练"}]


def decide(goal_id, *, panel_open, rows=(), camps=None):
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = goal_id
    world = WorldState(
        page=Page.HOME,
        quick_panel={"open": panel_open, "rows": list(rows), "camps": dict(camps or {})},
        training={},
    )
    return brain.decide(world, v2_registry())


def test_a_closed_panel_still_dispatches_the_training_entry():
    # The guard must not swallow the path that works: 49 of the 54 closed-panel attempts
    # succeeded, and this is the step they took.
    for goal_id in GOALS:
        decision = decide(goal_id, panel_open=False)
        assert decision.skill == "OPEN_INFANTRY_TRAINING", (goal_id, decision.skill)
        assert decision.reason == DISPATCH_REASON


BACK_SKILL = "SCROLL_QUICK_PANEL_BACK"
BACK_REASON = "the_sweep_left_the_panel_below_the_training_section_so_the_band_goes_back_up"


def test_an_open_panel_without_the_training_section_moves_the_band_back_instead_of_giving_up():
    """The cause is the *scroll*, and this is the step that undoes it.

    The panel is one continuous list; the sweep walks it down to reach the rows the other goals
    want and leaves it there.  Measured 2026-10-05: of the 61 panel-open training failures, **59 had
    ``OPEN_QUICK_PANEL`` -> ``SCROLL_QUICK_PANEL_TASKS`` earlier in the same run**, and the 部队训练
    section sits directly under the tab strip while the sweep leaves the panel four sections further
    down.
    """
    for goal_id in GOALS:
        decision = decide(goal_id, panel_open=True, rows=WILDERNESS_ROWS)
        assert decision.skill != "OPEN_INFANTRY_TRAINING", (
            f"{goal_id}: the panel covers this skill's control -- 0 of 61 panel-open attempts "
            f"succeeded, every one with an empty after-frame"
        )
        assert decision.skill == BACK_SKILL, (goal_id, decision.skill, decision.reason)
        assert decision.reason == BACK_REASON
        assert decision.expected_result == "quick_panel_scrolled_back"


def test_the_band_move_is_bounded_and_then_stops_naming_the_cover():
    # A swipe whose band does not move must not become a loop on a panel that stays put.
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = GOALS[0]
    world = WorldState(page=Page.HOME,
                       quick_panel={"open": True, "rows": list(WILDERNESS_ROWS)}, training={})
    budget = brain.MAX_PANEL_SCROLL_BACK_ATTEMPTS_PER_RUN
    assert budget >= 1, "a bound of zero would make the step unreachable"
    for _ in range(budget):
        assert brain.decide(world, v2_registry()).skill == BACK_SKILL
    decision = brain.decide(world, v2_registry())
    assert decision.skill == "SAFE_STOP", (decision.skill, decision.reason)
    assert decision.reason == COVERED_REASON


def test_the_refusal_names_the_cover_and_not_the_goal():
    # A stop is only useful if a later reader can grep why. The reason names the panel, which is
    # the thing that changed -- the goal did nothing wrong here.
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = GOALS[0]
    world = WorldState(page=Page.HOME,
                       quick_panel={"open": True, "rows": list(WILDERNESS_ROWS)}, training={})
    for _ in range(brain.MAX_PANEL_SCROLL_BACK_ATTEMPTS_PER_RUN):
        brain.decide(world, v2_registry())
    decision = brain.decide(world, v2_registry())
    assert "quick_panel" in decision.reason
    assert "training_entry" in decision.reason
    assert "covered" in decision.reason


def test_a_panel_that_draws_the_training_section_still_dispatches():
    """The other side of the boundary, and the reason the guard is not "the panel is open".

    ``test_unanswered_training_opens_the_training_page`` pins a *deliberate* change with its own
    measurement: on a frame whose panel draws the 部队训练 row, the training page is the step that
    answers the goal.  An earlier version of this guard refused every open panel and turned that
    file red -- which is the A/B doing its job.  The drawn section, not the panel's state, is what
    separates a covered control from a visible one.
    """
    for goal_id in GOALS:
        decision = decide(goal_id, panel_open=True, rows=TRAINING_TAB_ROWS)
        assert decision.skill == "OPEN_INFANTRY_TRAINING", (goal_id, decision.skill, decision.reason)
        assert decision.reason == DISPATCH_REASON


def test_a_camp_row_is_evidence_the_section_is_drawn():
    # Same boundary reached from the section's own rows rather than its header.
    decision = decide(GOALS[0], panel_open=True, rows=[
        {"key": "SHIELD_CAMP", "kind": "CAMP", "control": "DONE",
         "arrow_norm": [0.5618, 0.4273], "done_norm": [0.5618, 0.4345], "status": "COMPLETED"},
    ])
    assert decision.reason != COVERED_REASON, decision.reason


def test_the_panels_own_row_still_wins_when_the_panel_can_answer():
    # The panel-native path above is the whole point of reading the panel: when it can reach the
    # camp's own task page, the guard must never be consulted.  The row carries the two fields
    # that branch requires, `ROW_BUTTON_SCAN` and an `arrow_norm`, so this reaches it rather than
    # falling through to the power route.
    rows = [{"key": "SHIELD_CAMP", "kind": "CAMP", "control": "ARROW",
             "arrow_basis": "ROW_BUTTON_SCAN",
             "arrow_norm": [0.5618, 0.4273], "status": "IDLE"}]
    camps = {"SHIELD_CAMP": {"queue_available": True, "status": "IDLE"}}
    decision = decide("KEEP_TRAINING_PRODUCTIVE", panel_open=True, rows=rows, camps=camps)
    assert decision.skill == "OPEN_TASK_FROM_QUICK_PANEL_SHIELD", (decision.skill, decision.reason)
    assert decision.reason == "quick_panel_row_shield_camp_enters_its_own_task_page"
    assert decision.reason != COVERED_REASON


def test_the_stop_uses_the_projects_own_name_for_it():
    from winter_agent_v2.runtime_snapshot import AgentState

    # Named through the project's own vocabulary rather than a literal, so a rename of the state
    # breaks here instead of leaving two spellings to disagree in production.  ``SAFE_STOP`` needs
    # no verifier binding: ``runtime_snapshot`` reads it off the decision and turns the cycle into
    # that state, which is why this branch's neighbouring stop has always been able to take it.
    brain = RuleBrain(current_goal="TRAIN")
    brain.goal_id = GOALS[0]
    world = WorldState(page=Page.HOME,
                       quick_panel={"open": True, "rows": list(WILDERNESS_ROWS)}, training={})
    for _ in range(brain.MAX_PANEL_SCROLL_BACK_ATTEMPTS_PER_RUN):
        brain.decide(world, v2_registry())
    decision = brain.decide(world, v2_registry())
    # ``==``, not ``is``: the brain names the stop as a plain string and ``AgentState`` is a
    # ``str`` enum, so the two compare equal by value and are not the same object.
    assert decision.skill == AgentState.SAFE_STOP


def test_the_band_move_is_dispatchable():
    # A decision naming a skill without a verifier binding is never executed (the RR-003 class).
    from winter_agent_v2.runtime import LiveRuntime

    assert BACK_SKILL in LiveRuntime.VERIFIED_ATOMIC


class TheBandMoveVerifierTests:
    """``verify_quick_panel_scrolled_back`` must prove the *direction*, unlike the forward one.

    The forward verifier accepts any change in the visible rows.  If this one copied it, the very
    swipe the sweep already performed would be credited as undoing it.
    """

    def test_rows_moving_down_the_screen_is_the_proof(self):
        before = _panel({"HERO_RECRUIT": 0.3625, "PET_TREASURE": 0.507})
        after = _panel({"HERO_RECRUIT": 0.4125, "PET_TREASURE": 0.557})
        result = verify_quick_panel_scrolled_back(before, after)
        assert result.ok, result.evidence
        assert result.reason == "OK"
        assert result.evidence["moved_down"] == {"HERO_RECRUIT": 0.05, "PET_TREASURE": 0.05}

    def test_a_row_revealed_above_the_old_band_is_the_proof(self):
        before = _panel({"PET_TREASURE": 0.507})
        after = _panel({"LANCER_CAMP": 0.31, "PET_TREASURE": 0.557})
        result = verify_quick_panel_scrolled_back(before, after)
        assert result.ok, result.evidence
        assert result.evidence["revealed_above"] == ["LANCER_CAMP"]

    def test_a_second_downward_scroll_is_not_credited(self):
        # The forward gesture: rows move UP the screen and new rows come from below.
        before = _panel({"SHIELD_CAMP": 0.41, "LANCER_CAMP": 0.50})
        after = _panel({"LANCER_CAMP": 0.44, "MARKSMAN_CAMP": 0.53})
        result = verify_quick_panel_scrolled_back(before, after)
        assert not result.ok
        assert result.reason == "QUICK_PANEL_SCROLL_BACK_NOT_PROVEN"

    def test_no_change_is_not_credited(self):
        rows = {"HERO_RECRUIT": 0.3625, "PET_TREASURE": 0.507}
        assert not verify_quick_panel_scrolled_back(_panel(rows), _panel(rows)).ok

    def test_a_swipe_that_left_the_city_is_not_a_band_move(self):
        before = _panel({"HERO_RECRUIT": 0.3625})
        after = WorldState(page=Page.MAP, quick_panel={"open": True,
                                                      "rows": [{"key": "HERO_RECRUIT",
                                                                "y_norm": 0.45}]})
        assert not verify_quick_panel_scrolled_back(before, after).ok


def test_the_two_gestures_are_the_same_reading_reversed():
    """The evidence a later reader needs, on a frame rather than on a fabricated matrix.

    Both endpoints come from ``read_quick_panel``'s own band measurement, so the backward gesture is
    a current-frame reading and not a coordinate -- and if that ever stops being true, the two
    tuples stop being each other's reverse and this fails.
    """
    import json as _json
    from pathlib import Path as _Path

    from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend, read_quick_panel

    frame = (ROOT / "dataset/raw/control_panel/runtime_auto/20261005_172103_372127"
             / "20261005_172103_372127_step_015_before_20261005T092234016617.png")
    if not frame.exists():
        import pytest

        pytest.skip("the frame was pruned by retention; it lives under runtime_auto")
    config = _json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
    service = OCRService(ResilientOCRBackend(RapidOCRBackend(_Path(config["ocr"]["module_path"]))))
    panel = read_quick_panel(frame, service)
    forward = panel.get("scroll_swipe_norm")
    backward = panel.get("scroll_back_swipe_norm")
    assert forward is not None and backward is not None, (
        "this frame carries a four-row band, so both gestures must be derivable"
    )
    assert list(backward) == [forward[0], forward[3], forward[2], forward[1]]
    assert forward[1] > forward[3], "the sweep's gesture drags up, revealing rows below"
    assert backward[1] < backward[3], "and the backward one drags down"
