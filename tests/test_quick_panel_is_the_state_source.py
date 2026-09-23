"""The 快捷面板 is the in-city state source and the in-city entry, and the detour is gone.

Operator directive 2026-09-23 (快捷面板作为城内任务主要状态与导航入口).  What is pinned here, and the
measurement behind each one:

§一.2 / §二 — the panel's reading reaches the goal layer.  Across the 57 production frames with the
    panel open, the panel carried a 建筑队列 reading in 56 and a 科技研究 reading in 57, while
    ``WorldState.building`` and ``WorldState.research`` were **empty in all 57**: the state was read
    off the frame and dropped, so nothing could reuse it.

§一.6 / §五 — the proven 加成总览 route is a fallback, not a default.  ``train_goal_power_overview``
    and ``research_goal_power_overview`` (the steps taken *to learn a state*) are 20 steps in the
    corpus and **every one of them failed** ``POWER_DETAILS_NOT_PROVEN``.  Run
    ``20260923_215819_292688`` spent 4 of its 6 steps on that detour and its recovery while the panel
    had already read all three barracks and the lab thirty seconds earlier.

§四 — the row must belong to the row it came from.  ``goal=LANCER_CAMP_TRAINING`` at 13:59:41 was
    answered ``quick_panel_shield_camp_is_idle`` -- the *shield* camp's line, because the idle-camp
    scan took the first entry in dict order.

§二 — 已完成 and 空闲中 are two of the client's words and both mean the barracks has no queue running,
    which is why the reading keeps ``source_word``: "the queue finished" and "nothing is running" are
    the same availability and different facts.

§八.7 — being on the goal's own page is never a reason to go back to the city for the panel.

The green tick is **not** asserted as a control anywhere: its centre has been tapped and measured a
dead end (``brain._QUICK_PANEL_ROW_CLAIM_SKILL`` records it), so the tests below pin that a tick row is
neither entered nor collected -- and that refusing it does not turn into the detour either.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import HybridVision  # noqa: E402
from winter_agent_v2.runtime_snapshot import is_fatal_stop  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402


def brain_for(goal: str, *, goal_id: str = "") -> RuleBrain:
    brain = RuleBrain(current_goal=goal)
    brain.goal_id = goal_id or goal
    return brain


def row(key, status, word, control, basis, arrow, *, kind="CAMP", **extra):
    return {"kind": kind, "key": key, "label": key, "y_norm": 0.4, "status": status,
            "source_word": word, "control": control, "arrow_basis": basis, "arrow_norm": arrow,
            "badge": "UNKNOWN", **extra}


#: The 2026-09-23 13:59:41 frame, as the reader wrote it: all three barracks 已完成 with the client's
#: tick in their control slot, the lab 空闲中 with a located arrow, the building queue running.
REAL_PANEL = {
    "open": True,
    "handle": {"state": "EXPANDED"},
    "rows": [
        row("SHIELD_CAMP", "IDLE", "已完成", "DONE", "PANEL_RELATIVE_ESTIMATE", [0.3903, 0.4262]),
        row("LANCER_CAMP", "IDLE", "已完成", "DONE", "PANEL_RELATIVE_ESTIMATE", [0.3903, 0.4832]),
        row("MARKSMAN_CAMP", "IDLE", "已完成", "DONE", "PANEL_RELATIVE_ESTIMATE", [0.3903, 0.5402]),
        row("RESEARCH", "IDLE", "空闲中", "ARROW", "ROW_BUTTON_SCAN", [0.5618, 0.6277],
            kind="RESEARCH"),
    ],
    "camps": {
        "SHIELD_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "已完成"},
        "LANCER_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "已完成"},
        "MARKSMAN_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "已完成"},
    },
    "research": {"status": "IDLE", "queue_available": True, "source_word": "空闲中"},
    "building": {"name": "使馆升级中", "status": "IN_PROGRESS", "queue_available": False,
                 "timer": "09:29:06", "source_word": "09:29:06"},
}


def home(panel: dict, **fields) -> WorldState:
    camps = dict(panel.get("camps") or {})
    return WorldState(page=Page.HOME, confidence=0.99, quick_panel=panel, camps=camps, **fields)


#: The training page as the reader wrote it on 2026-09-23 07:28:39, the step that trained 射手 --
#: copied rather than paraphrased, because the route's branch turns on the client's own words
#: (``status=AVAILABLE`` with ``trainable``, and the camp tabs it drew) and a fixture with invented
#: words tests a reading that cannot happen.
TRAINING_PAGE = WorldState(
    page=Page.TRAINING, confidence=0.99,
    training={"troop_type": "MARKSMAN", "status": "AVAILABLE", "queue_available": True,
              "trainable": True, "train_button_basis": "LABEL",
              "train_button_norm": [0.7361, 0.8621],
              "camps_seen": ["盾兵营", "矛兵营", "射手营"], "camp_open_label": "射手营",
              "camp_tab_norm": {"盾兵营": [0.1868, 0.984], "矛兵营": [0.5, 0.984],
                                "射手营": [0.8139, 0.984]}},
    camps={"MARKSMAN_CAMP": {"camp": "MARKSMAN_CAMP", "label": "射手营", "status": "AVAILABLE",
                             "troop_type": "MARKSMAN", "training": False, "queue_available": True,
                             "batch_count": None, "timer": None, "selected": False,
                             "source": "PAGE_IS_THIS_CAMP", "confidence": 0.0, "observed": True,
                             "busy": False}},
)


# --------------------------------------------------------------- §一.2 / §二  the state reaches the goal layer


def test_the_panels_building_and_research_readings_reach_the_goal_layer():
    """The panel is a state source, not just a place to tap.

    Measured: 56 of 57 panel frames carried a 建筑队列 reading and 57 carried a 科技研究 reading, and
    ``WorldState.building`` / ``WorldState.research`` were empty in all 57 -- so the goal layer could
    not see either, which is what sent the training and research goals to the power route to ask again.
    """
    state = HybridVision._with_quick_panel(WorldState(page=Page.HOME), REAL_PANEL)
    assert state.building["status"] == "IN_PROGRESS"
    assert state.building["timer"] == "09:29:06"
    assert state.research["status"] == "IDLE"
    assert state.research["queue_available"] is True


def test_a_page_reading_still_wins_over_the_panel():
    """The panel is the overlay; a page that really read the same thing is the stronger statement."""
    underneath = WorldState(page=Page.BUILDING, building={"status": "IDLE", "queue_available": True,
                                                          "source": "PAGE"})
    state = HybridVision._with_quick_panel(underneath, REAL_PANEL)
    assert state.building == {"status": "IDLE", "queue_available": True, "source": "PAGE"}


def test_both_idle_words_are_kept_so_a_reader_can_tell_them_apart():
    """§二: 倒计时、空闲中、已完成 应结合所属行分别解释.

    Both words mean the barracks has no queue running, and they are different facts -- 已完成 is "the
    batch you started has finished", 空闲中 is "nothing is running".  The reader keeps the word, so the
    goal's evidence can say which one it was instead of flattening them into "IDLE".
    """
    words = {str(item.get("source_word")) for item in REAL_PANEL["rows"]}
    assert words == {"已完成", "空闲中"}
    assert all(item["status"] == "IDLE" for item in REAL_PANEL["rows"])


def test_a_row_scrolled_out_of_view_is_unknown_never_absent():
    """§二/§八.6: 某行未出现在当前可见区域时，不能把该行状态记为"无任务"或 ABSENT.

    The state layer already does this (``entry_badges.quick_panel_badges``) and it is the reason
    scrolling is a *finding* improvement rather than a correctness one: a row nobody looked at reports
    UNKNOWN with a reason, so nothing downstream can read "not seen" as "no work".
    """
    from winter_agent_v2 import entry_badges

    closed = entry_badges.quick_panel_badges(WorldState(page=Page.HOME, quick_panel={"open": False}))
    assert all(badge.state == entry_badges.UNKNOWN for badge in closed.values())
    assert {badge.reason for badge in closed.values()} == {"quick_panel_is_closed"}

    partial = dict(REAL_PANEL)
    partial["rows"] = [row("SHIELD_CAMP", "IDLE", "已完成", "DONE", "PANEL_RELATIVE_ESTIMATE", [0.39, 0.43])]
    badges = entry_badges.quick_panel_badges(WorldState(page=Page.HOME, quick_panel=partial))
    lancer = next(badge for entry, badge in badges.items() if "LANCER" in entry)
    assert lancer.state == entry_badges.UNKNOWN
    assert lancer.reason == "row_not_read_this_frame"


# --------------------------------------------------------------- §一.6 / §五  the detour is a fallback


def test_a_panel_that_answered_the_state_is_not_re_opened_as_an_overview():
    """The heart of §五: the 实力详情 route exists to learn a state that is already on the frame.

    Which of the two refusals answers is the frame's business, and both are fine: the row branch names
    the barracks and its own word, the route branch names the reading that answered.  What is not fine
    is the route being walked at all.
    """
    decision = brain_for("TRAIN").decide(home(REAL_PANEL), v2_registry())
    assert decision.skill != "OPEN_POWER_OVERVIEW"
    assert "quick_panel" in decision.reason
    assert is_fatal_stop(decision.reason) is False, "it steps aside; it does not end the batch"


def test_a_camp_goal_with_an_enterable_row_still_uses_the_row():
    """The positive half: when the panel draws a real button, that row is the entry (§四)."""
    panel = dict(REAL_PANEL)
    panel["rows"] = [row("SHIELD_CAMP", "IDLE", "空闲中", "ARROW", "ROW_BUTTON_SCAN", [0.5618, 0.4262])]
    panel["camps"] = {"SHIELD_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "空闲中"}}
    decision = brain_for("TRAIN").decide(home(panel), v2_registry())
    assert decision.skill == "OPEN_TASK_FROM_QUICK_PANEL_SHIELD"


def test_the_lab_reading_also_stops_the_research_detour():
    decision = brain_for("RESEARCH").decide(home(REAL_PANEL), v2_registry())
    assert decision.skill != "OPEN_POWER_OVERVIEW"


def test_the_panel_is_not_answering_when_it_is_closed_so_the_proven_route_runs():
    """§一.6 -- and the reason says which case it is rather than naming the route alone."""
    closed = {"open": False, "handle": {"state": "COLLAPSED"}, "rows": []}
    decision = brain_for("RESEARCH").decide(home(closed), v2_registry())
    assert decision.skill in {"TRY_ORDINARY_CONTROL", "OPEN_POWER_OVERVIEW"}


def test_a_goal_the_panel_does_not_serve_keeps_the_proven_route():
    """A goal whose route has no panel row kind is not this layer's business."""
    decision = brain_for("MAIL").decide(home(REAL_PANEL), v2_registry())
    assert decision.skill != "OPEN_TASK_FROM_QUICK_PANEL_SHIELD"


# --------------------------------------------------------------- §四  the row it came from


def test_the_idle_camp_is_the_one_the_goal_names():
    """§二/§四: 确定目标任务行.

    Measured 2026-09-23 13:59:41: ``goal=LANCER_CAMP_TRAINING`` was answered
    ``quick_panel_shield_camp_is_idle``, because the scan took the first idle camp in dict order.
    """
    panel = dict(REAL_PANEL)
    panel["rows"] = [
        row("SHIELD_CAMP", "IDLE", "空闲中", "ARROW", "ROW_BUTTON_SCAN", [0.5618, 0.4262]),
        row("LANCER_CAMP", "IDLE", "空闲中", "ARROW", "ROW_BUTTON_SCAN", [0.5618, 0.4832]),
    ]
    panel["camps"] = {
        "SHIELD_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "空闲中"},
        "LANCER_CAMP": {"status": "IDLE", "queue_available": True, "source_word": "空闲中"},
    }
    brain = brain_for("TRAIN", goal_id="LANCER_CAMP_TRAINING")
    decision = brain.decide(home(panel), v2_registry())
    assert decision.skill == "OPEN_TASK_FROM_QUICK_PANEL_LANCER"
    assert "lancer" in decision.reason


def test_a_goal_never_acts_on_a_look_alike_row_it_does_not_own():
    """Only the 盾兵 row is enterable, and the goal is the 矛兵 one: it must not take the shield row."""
    panel = dict(REAL_PANEL)
    panel["rows"] = [
        row("SHIELD_CAMP", "IDLE", "空闲中", "ARROW", "ROW_BUTTON_SCAN", [0.5618, 0.4262]),
        row("LANCER_CAMP", "IDLE", "已完成", "DONE", "PANEL_RELATIVE_ESTIMATE", [0.3903, 0.4832]),
    ]
    brain = brain_for("TRAIN", goal_id="LANCER_CAMP_TRAINING")
    decision = brain.decide(home(panel), v2_registry())
    assert decision.skill != "OPEN_TASK_FROM_QUICK_PANEL_SHIELD"
    assert "lancer" in decision.reason


def test_a_tick_row_is_neither_entered_nor_collected_nor_a_reason_to_detour():
    """The tick's own centre has been tapped and collected nothing; the row is not an enter target.

    Refusing it must not become the detour either: the state is on the frame (this is §五), and the
    加成总览 route measured 100% failure while doing that.
    """
    decision = brain_for("TRAIN").decide(home(REAL_PANEL), v2_registry())
    assert decision.skill != "OPEN_TASK_FROM_QUICK_PANEL_SHIELD"
    assert decision.skill != "OPEN_POWER_OVERVIEW"


# --------------------------------------------------------------- §六 / §八.7 / §八.8


def test_a_busy_panel_steps_aside_instead_of_holding_the_batch():
    """§六: 不要因为某个兵营忙碌…就结束整轮 AUTO."""
    panel = dict(REAL_PANEL)
    panel["camps"] = {camp: {"status": "IN_PROGRESS", "queue_available": False, "source_word": "训练中"}
                      for camp in ("SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP")}
    decision = brain_for("TRAIN").decide(home(panel), v2_registry())
    assert decision.skill == "SAFE_STOP"
    assert is_fatal_stop(decision.reason) is False


def test_being_on_the_goals_own_page_is_not_a_reason_to_go_home_for_the_panel():
    """§八.7, on a real training-page frame (the reader's own words and boxes, 07:28:39)."""
    decision = brain_for("TRAIN").decide(TRAINING_PAGE, v2_registry())
    assert decision.skill == "TRAIN_TROOPS", "the page the goal came for is where it works"
    assert "quick_panel" not in decision.reason


def test_a_camp_goal_on_another_barracks_page_switches_to_its_own():
    """The same per-camp rule on the page itself: 盾兵 goal, 射手 page open -> switch tabs, not train."""
    decision = brain_for("TRAIN", goal_id="SHIELD_CAMP_TRAINING").decide(TRAINING_PAGE, v2_registry())
    assert decision.skill == "SELECT_TRAINING_CAMP", (
        "acting on the open barracks would train the wrong troops"
    )


def test_the_fallback_route_says_which_case_it_is():
    """§八.8: 旧路线只在面板不可用或确有必要时使用，并记录实际原因.

    Checked over the reasons this file's own cases produce: none of them is the old
    ``*_goal_requires_power_route`` / ``*_goal_power_overview`` string, because those named the route
    without saying why it was allowed.
    """
    retired = {"train_goal_power_overview", "research_goal_power_overview",
               "training_goal_requires_power_route", "research_goal_requires_power_route"}
    seen = set()
    for goal, panel in (("TRAIN", REAL_PANEL), ("RESEARCH", REAL_PANEL)):
        seen.add(brain_for(goal).decide(home(panel), v2_registry()).reason)
    assert not (seen & retired), f"a reason still names the route instead of the case: {seen & retired}"
    assert all("quick_panel" in reason or "panel" in reason for reason in seen)
