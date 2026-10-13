# -*- coding: utf-8 -*-
"""When the writer stops, the board must say so -- not keep showing the last good rows.

V2-P0 §六 asks for the failure scenarios, not only the happy path: "验证调度器停机、WorldState
过期、Registry 缺项、Verifier 缺失和执行失败等场景".  The first two meet on this board.

`source_freshness` declares the file and its budget:

    Source("learning/goal_state.json", "今日目标板", 900, "运行·目标", writer=WRITER_LOOP)

and the panel already owns the mechanism that turns an exceeded budget into words --
`_source_age_note`, whose own docstring predicts this bug:

    "Empty-when-fine so a caller can concatenate it unconditionally and get the honest line either
     way, instead of writing an ``if`` at every use site and eventually forgetting one -- which is
     how the columns got into this state."

The 今日目标板 was the third call site that forgot.  Two consequences, one test each:

1. a **stale** snapshot (writer stopped, file still there) rendered as if live, because the meta
   line printed only `observed_at` and never asked whether that reading was current;
2. an **unreadable** snapshot returned early with the previous rows and meta left in place, so a
   board whose source had gone was indistinguishable from a live one.  ``GoalStateStore.write``
   is atomic (temp file + ``replace``), so this is a fault and not a half-written file.
"""
from __future__ import annotations

import time

from tools import control_panel
from winter_agent_v2 import source_freshness

KEY = "learning/goal_state.json"


# --------------------------------------------------------------------- the declared contract

def test_the_goal_board_source_is_declared_with_its_budget():
    """The number the board now consults.  Pinned so a silent budget change is a test failure."""
    source = source_freshness.SOURCE_BY_KEY[KEY] if hasattr(source_freshness, "SOURCE_BY_KEY") else None
    if source is None:                       # the table is exposed by lookup, not by name
        ages = source_freshness.all_ages(control_panel.ROOT)
        source = ages[KEY].source
    assert source.label == "今日目标板"
    assert source.ttl_seconds == 900


# --------------------------------------------------------------------- the meta line

def test_a_fresh_snapshot_gets_exactly_the_line_it_always_had():
    """The fix is additive: with no note, the text is unchanged."""
    text = control_panel.ControlPanel._goal_board_meta_text(
        {"page": "HOME", "confidence": 0.99, "observed_at": "2026-10-10T12:29:19Z"}, "")
    assert text == (
        "识别页面：HOME · 整帧识别置信度：99%"
        "（这是页面识别，不是每个目标的置信度）· 时间：2026-10-10T12:29:19Z"
    )


def test_a_stale_snapshot_says_so_on_the_meta_line():
    note = "　（今日目标板8.0 小时前，已过期）"
    text = control_panel.ControlPanel._goal_board_meta_text(
        {"page": "MAP", "confidence": 0.99, "observed_at": "2026-10-10T04:00:00Z"}, note)
    assert note in text
    assert text.endswith(note)


def test_a_malformed_confidence_is_not_rounded_into_a_number():
    text = control_panel.ControlPanel._goal_board_meta_text(
        {"page": "HOME", "confidence": None, "observed_at": "—"}, "")
    assert "无法读出" in text
    assert "0%" not in text


def test_a_missing_snapshot_field_does_not_crash_the_line():
    text = control_panel.ControlPanel._goal_board_meta_text({}, "")
    assert "UNKNOWN" in text and "—" in text


# --------------------------------------------------------------------- the unreadable case

def test_an_unreadable_snapshot_says_there_is_no_reading():
    text = control_panel.ControlPanel._goal_board_unreadable_text("JSONDecodeError", "")
    assert "读取失败" in text
    assert "JSONDecodeError" in text
    assert "没有真实读数" in text


def test_an_unreadable_snapshot_also_carries_the_age_when_there_is_one():
    note = "　（今日目标板2.0 小时前，已过期）"
    text = control_panel.ControlPanel._goal_board_unreadable_text("FileNotFoundError", note)
    assert text.endswith(note)


# --------------------------------------------------------------------- _source_age_note itself

def _panel_with(ages: dict):
    """A panel instance without Tk, built the way this project's own wiring tests build runtimes."""
    panel = control_panel.ControlPanel.__new__(control_panel.ControlPanel)
    panel._freshness_ages = ages
    panel._freshness_at = time.monotonic()      # inside the memo window, so these ages are used
    panel.process = None                        # the "not running" branch of _freshness()
    return panel


def _age(status: str, seconds: float) -> source_freshness.SourceAge:
    source = source_freshness.Source(KEY, "今日目标板", 900.0, "运行·目标")
    return source_freshness.SourceAge(source=source, status=status, age_seconds=seconds)


def test_a_current_source_produces_no_note():
    panel = _panel_with({KEY: _age(source_freshness.FRESH, 5.0)})
    assert panel._source_age_note(KEY) == ""


def test_a_stale_source_produces_a_note_naming_the_board_and_the_age():
    panel = _panel_with({KEY: _age(source_freshness.STALE, 28800.0)})
    note = panel._source_age_note(KEY)
    assert note != ""
    assert "今日目标板" in note
    assert "已过期" in note
    assert "小时前" in note


def test_an_unknown_key_produces_no_note_rather_than_a_wrong_one():
    panel = _panel_with({})
    assert panel._source_age_note("learning/does_not_exist.json") == ""
