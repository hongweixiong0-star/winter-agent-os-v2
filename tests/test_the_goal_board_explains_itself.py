# -*- coding: utf-8 -*-
"""The 今日目标 board must explain itself, and must not answer questions the engine did not.

Operator report, 2026-10-10: many rows read 未知（引擎未判定）, most read 待规划, and several showed
0% progress.  Tracing the columns to their real sources found that **one** of those three had a data
cause and the other two were the board answering questions nobody had asked:

  * 未知 came from ``GoalStatus.UNKNOWN``.  It was correct for every row that carried it -- and the
    rows carried their own reason (``evidence.blocker``, ``availability_state``,
    ``required_observation``) which the 阻塞原因 column never read, so the board showed "—".
  * 待规划 is ``(goal["available_skills"] or ["待规划"])[0]``.  For ``USE_FREE_ARENA_ATTEMPTS`` and
    ``LABYRINTH_DAILY`` the empty tuple is deliberate and documented (``_append_prepared_workflows``:
    "These records deliberately have no skills. The map currently lacks a production reader for
    attempt counters... registering the workflow must not invite the scheduler to navigate by
    guessed controls").  The board printed the fallback for a decision that had a reason.
  * ``EXPIRED`` was missing from the status table, so 3 rows printed the raw token; and because
    ``completion`` is ``1.0`` for an expired window by construction, those rows also read **100%** --
    "window closed" rendered as "task finished", which is the conflation ``GoalStatus.EXPIRED``
    exists to remove.

These tests pin the fixed behaviour and the two earlier fixes they sit next to, so the third
recurrence of "the reason existed and the link did not" is caught by a test rather than by a report.
"""
from __future__ import annotations

import pytest

from tools import control_panel
from winter_agent_v2.goal_library import GoalStatus


# --------------------------------------------------------------------------- the status table

def test_every_goal_status_the_library_can_emit_has_words():
    """A status missing from the table prints its raw token -- which is how EXPIRED leaked out."""
    table = control_panel.ControlPanel.GOAL_STATUS_ZH
    missing = [member.value for member in GoalStatus if member.value not in table]
    assert missing == [], f"these statuses would print as raw tokens: {missing}"


def test_the_expired_and_not_open_statuses_read_as_windows_not_as_failure():
    table = control_panel.ControlPanel.GOAL_STATUS_ZH
    assert table["EXPIRED"] == "窗口已结束"
    assert table["SCHEDULED_NOT_OPEN"] == "窗口未开启"


def test_unknown_no_longer_claims_the_engine_did_not_decide():
    """It did decide; what was missing was the observation.  The old wording pointed at the scheduler."""
    assert "引擎未判定" not in control_panel.ControlPanel.GOAL_STATUS_ZH["UNKNOWN"]


# --------------------------------------------------------------------------- 优先级

def test_an_unpriced_goal_is_not_given_a_priority_band():
    cell = control_panel.ControlPanel._goal_priority_cell
    assert cell(None) == "—"
    assert cell("") == "—"


def test_the_priority_bands_themselves_are_unchanged():
    cell = control_panel.ControlPanel._goal_priority_cell
    assert cell(5000.0) == "P0"
    assert cell(2000) == "P0"
    assert cell(915.0) == "P1"
    assert cell(500) == "P1"
    assert cell(159.2) == "P2"
    assert cell(0) == "P2"


def test_a_boolean_is_not_read_as_a_priority():
    """``isinstance(True, int)`` is true, so True would otherwise rank as P2."""
    assert control_panel.ControlPanel._goal_priority_cell(True) == "—"


# --------------------------------------------------------------------------- 进度

def test_a_closed_window_is_not_rendered_as_a_hundred_percent():
    cell = control_panel.ControlPanel._goal_progress_cell
    assert cell("EXPIRED", 1.0) == "窗口已结束"


def test_an_unopened_window_is_not_rendered_as_zero_percent():
    cell = control_panel.ControlPanel._goal_progress_cell
    assert cell("SCHEDULED_NOT_OPEN", 0.0) == "窗口未开启"


def test_ordinary_goals_still_render_a_percentage():
    cell = control_panel.ControlPanel._goal_progress_cell
    assert cell("READY", 0.0) == "0%"
    assert cell("DISCOVERED", 0.5) == "50%"


def test_a_missing_completion_does_not_crash_the_board(capsys):
    cell = control_panel.ControlPanel._goal_progress_cell
    assert cell("READY", None) == "0%"
    assert cell("READY", "not a number") == "—"


# --------------------------------------------------------------------------- 阻塞原因

def test_a_prepared_workflow_shows_the_observation_it_is_waiting_for():
    """The arena/labyrinth shape, verbatim from the live snapshot."""
    goal = {
        "goal_id": "LABYRINTH_DAILY",
        "status": "UNKNOWN",
        "evidence": {
            "prepared_only": True,
            "availability": "AWAITING_LIVE",
            "blocker": "missing production observation: world.attempts",
            "required_observation": "Labyrinth attempts counter",
            "live_verified": False,
        },
    }
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert cell == "missing production observation: world.attempts"


def test_a_scheduled_goal_awaiting_a_live_reading_names_the_reading():
    goal = {
        "goal_id": "SCHEDULED_FISHING_TOURNAMENT",
        "status": "UNKNOWN",
        "evidence": {
            "availability_state": "AWAITING_LIVE_CLIENT_READING",
            "required_observation": "this event's own page once opened: whether its window is open",
        },
    }
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert cell.startswith("待观测：")
    assert "whether its window is open" in cell


def test_an_expired_goal_does_not_read_as_blocked_or_as_unknown():
    goal = {"goal_id": "SCHEDULED_BEAR_HUNT", "status": "EXPIRED", "evidence": {}}
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert cell == "本场窗口已结束（不是被拦，也不是本次任务完成）"
    assert cell != "—"


def test_a_silent_record_says_it_is_silent_rather_than_showing_a_dash():
    """A dash reads as "unknown", which is what these rows were not."""
    goal = {"goal_id": "MYSTERY", "status": "UNKNOWN", "evidence": {}}
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert cell != "—"
    assert "证据为空" in cell


# --------------------------------------------------------------------------- regressions

def test_a_ready_goal_still_says_it_is_not_blocked():
    goal = {"goal_id": "CLEAR_INTEL", "status": "READY", "evidence": {}}
    assert control_panel.ControlPanel._blocked_cell(goal, {}) == "就绪 · 未被阻塞（未选中＝调度顺序，不是被拦）"


def test_the_runtime_deferral_map_still_wins_over_everything_else():
    """The 2026-10-04 fix: ``blockers[id].reason`` is the scheduler's own decision."""
    goal = {"goal_id": "DAILY_ACTIVITY_TARGET", "status": "READY", "evidence": {}}
    blockers = {"DAILY_ACTIVITY_TARGET": {
        "reason": "READ_DAILY_PROGRESS: repair budget exhausted (2/2)", "capability": "READ_DAILY_PROGRESS",
        "state": "DEFERRED", "streak": 3, "until": "12:00",
    }}
    cell = control_panel.ControlPanel._blocked_cell(goal, blockers)
    assert "READ_DAILY_PROGRESS" in cell
    assert "连续 3 个 episode 无进展" in cell
    assert "12:00" in cell


def test_a_blocked_goal_with_a_frame_reason_still_translates_it():
    goal = {"goal_id": "KEEP_RESEARCH_PRODUCTIVE", "status": "BLOCKED", "retry_after": "9:31:00",
            "evidence": {"reason": "queue_busy"}}
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert cell == "队列忙，已有工作在进行 · 剩余 9:31:00"


def test_a_blocked_goal_with_no_reason_says_the_reading_was_empty():
    goal = {"goal_id": "X", "status": "BLOCKED", "evidence": {}}
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert "证据为空" in cell


def test_a_waiting_window_row_does_not_print_an_english_token():
    """Found by running the fix against the live snapshot, not by reading it.

    A row whose detail was already read carries ``condition="waiting_window"`` and no
    ``required_observation``, so it fell through to the raw-token branch -- the same defect the
    ``EXPIRED`` status had, in the column next to it.
    """
    goal = {
        "goal_id": "SCHEDULED_DISCOVERED_EVENT_X",
        "status": "UNKNOWN",
        "evidence": {
            "availability_state": "LIVE_DETAIL_ALREADY_OBSERVED",
            "required_observation": None,
            "condition": "waiting_window",
        },
    }
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert "waiting_window" not in cell
    assert cell == "等待开窗（细节已读到，等客户端公布窗口）"


def test_an_awaiting_live_row_does_not_print_an_english_token():
    goal = {
        "goal_id": "SCHEDULED_DISCOVERED_EVENT_Y",
        "status": "UNKNOWN",
        "evidence": {"availability_state": "AWAITING_LIVE_CLIENT_READING"},
    }
    cell = control_panel.ControlPanel._blocked_cell(goal, {})
    assert "AWAITING_LIVE_CLIENT_READING" not in cell


def test_every_translated_block_word_is_chinese():
    """A translation table that can hold an English token is a table that prints one."""
    import re
    for key, value in control_panel.ControlPanel.GOAL_BLOCK_ZH.items():
        assert re.search(r"[\u4e00-\u9fff]", value), f"{key} -> {value!r} carries no Chinese"
