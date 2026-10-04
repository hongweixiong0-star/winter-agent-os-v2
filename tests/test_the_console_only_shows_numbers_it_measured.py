"""The console must not print a number it did not measure.

Three reports from the operator, 2026-10-04, and they are one defect wearing three faces.
Each surface displayed a figure that looked measured and was not:

1. ``learning/event_goal_state.json`` was **595 h old** -- a hand-recorded live observation
   from 2026-09-09 that no process in the tree ever refreshes -- and the 活动低保 page still
   showed its 当前积分 / 低保目标 / 积分缺口 / 已执行计划 as the only figures there were,
   behind a prefix.  Reported as "继续展示 25 天前的模板".
2. Every row of 今日目标 showed **99%**, because the confidence cell rendered
   ``snapshot["confidence"]`` -- one number for the whole frame -- under a column of Goals,
   while all 33 Goals carried ``confidence: null``.  Reported as "置信度都是 99%".
3. Every 阻塞原因 cell showed **"—"**, because it read ``goal["blocked_reason"]``, a key
   that is not among ``GoalState``'s 15 fields and that nothing writes -- while the
   capability gate was holding named reasons for several Goals.  Reported as "阻塞原因
   为什么很多是空的".

The load-bearing assertions are the negative ones: the frame's confidence must not appear
in a Goal row, a stale record's numbers must not appear as values, and an unblocked Goal must
not render "—" as though the answer were unknown.  A test that only checked the happy path
would have passed before this commit, which is why the first thing each class does is prove
the defect is real on the inputs that produced it.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from winter_agent_v2 import state_truth as st
from winter_agent_v2.goal_library import GoalState, GoalStateStore, GoalStatus
from winter_agent_v2.models import Page, WorldState

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "tools" / "control_panel.py"
NOW = datetime(2026, 10, 4, 6, 30, tzinfo=timezone.utc)


def _load_panel():
    """``tools/control_panel.py`` is a script, not a package module, for this test's needs."""
    spec = importlib.util.spec_from_file_location("cp_under_test", PANEL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def panel():
    return _load_panel()


def _write(root: Path, relative: str, payload: object) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# 1. A stale activity record expires, and its numbers are not today's plan
# --------------------------------------------------------------------------------------


class AnExpiredActivityRecordIsNotTodaysPlanTests:
    def test_the_measured_record_is_expired_and_says_why(self, tmp_path):
        """The operator's own file: verified 2026-09-09, 28 795 s of window, 595 h ago."""
        _write(tmp_path, st.EVENT_STATE, {
            "event_id": "KINGDOM_OF_POWER_CURRENT", "name": "最强王国·击败野兽",
            "verified_at": "2026-09-09T16:00:00+08:00",
            "remaining_seconds_at_verification": 28795,
            "current_points": 11250, "target_points": 80000, "points_missing": 68750,
            "plan": "优先完成 Intel 野怪", "source": "LIVE_CLIENT",
        })
        row = st.legacy_event_row_for(tmp_path, now=NOW)
        assert row["expired"] is True
        assert row["planner_usable"] is False
        assert row["status"] == st.HISTORY
        assert "599 小时" in row["note"] or "窗口早已结束" in row["note"]

    def test_a_record_with_no_countdown_still_expires_by_ttl(self, tmp_path):
        """The TTL is the only rule available to a record that saved no countdown."""
        _write(tmp_path, st.EVENT_STATE, {
            "event_id": "X", "name": "无倒计时活动",
            "verified_at": (NOW - timedelta(hours=40)).isoformat(),
        })
        row = st.legacy_event_row_for(tmp_path, now=NOW)
        assert row["expired"] is True
        assert row["status"] == st.HISTORY
        assert "TTL 6 小时" in row["note"]

    def test_a_record_inside_its_own_window_is_not_expired(self, tmp_path):
        _write(tmp_path, st.EVENT_STATE, {
            "event_id": "X", "name": "进行中", "verified_at": (NOW - timedelta(minutes=20)).isoformat(),
            "remaining_seconds_at_verification": 7200,
        })
        row = st.legacy_event_row_for(tmp_path, now=NOW)
        assert row["expired"] is False
        assert row["planner_usable"] is True

    def test_a_record_without_a_verification_time_cannot_be_current(self, tmp_path):
        _write(tmp_path, st.EVENT_STATE, {"event_id": "X", "name": "无时间"})
        row = st.legacy_event_row_for(tmp_path, now=NOW)
        assert row["expired"] is True
        assert row["planner_usable"] is False

    def test_the_expiry_verdict_travels_with_the_row(self, tmp_path):
        """No reader re-derives the rule -- that is how two readers come to disagree."""
        _write(tmp_path, st.EVENT_STATE, {
            "event_id": "X", "name": "老记录",
            "verified_at": (NOW - timedelta(hours=595)).isoformat(),
            "remaining_seconds_at_verification": 28795,
        })
        row = st.legacy_event_row_for(tmp_path, now=NOW)
        assert row["expired"] is True
        assert row["ttl_seconds"] == st.EVENT_CURRENT_SECONDS

    def test_a_missing_field_must_not_become_a_benign_status(self, tmp_path):
        """``event_state`` used to read ``updated_at``/``recorded_at``; the file writes
        ``verified_at``.  The empty stamp became ``age=None`` and ``_grade`` turned that
        into PERSISTED -- "saved, fine" -- for a 595 h old record."""
        _write(tmp_path, st.EVENT_STATE, {
            "event_id": "X", "name": "老记录",
            "verified_at": (NOW - timedelta(hours=595)).isoformat(),
            "remaining_seconds_at_verification": 28795,
        })
        audit = st.TruthAudit(tmp_path, now=NOW)
        value = audit.report().by_name("event_state")
        assert value.status == st.STALE, "a 595 h old record must not be graded by a default"
        assert value.age_seconds is not None and value.age_seconds > 595 * 3600 - 60
        assert value.observed_at


# --------------------------------------------------------------------------------------
# 2. The confidence column is about a Goal, not about the frame
# --------------------------------------------------------------------------------------


class TheConfidenceColumnIsAboutTheGoalTests:
    """2026-10-04, second round: the column itself is gone, which is the stronger statement.

    The first fix made the cell honest -- it read the Goal's *own* confidence and printed
    未计算 when there was none, which was every row, because ``GoalState`` has no such field.
    That left a column whose every cell said 未计算: honest, and no information.  The operator's
    audit rule is "不要因为'以后可能有用'就保留", so the column was removed and ``GoalState``
    did not change.  The assertions below are therefore about the *absence* of a per-row
    confidence, which is a property no rendering of a fake number can satisfy.
    """

    def test_the_board_has_no_confidence_column_at_all(self, panel):
        source = PANEL_PATH.read_text(encoding="utf-8")
        start = source.index("def _goals(")
        board = source[start:source.index("def _refresh_goal_board")]
        assert '"confidence"' not in board, (
            "a per-Goal confidence is not computed anywhere, so it must not be a column"
        )
        assert "_goal_confidence_cell" not in source, (
            "the helper existed only for the removed column"
        )

    def test_the_goal_board_never_prints_the_frames_confidence_per_row(self, panel, tmp_path, monkeypatch):
        """The defect, reproduced on the shape that produced it: 99% in every row."""
        _write(tmp_path, "learning/goal_state.json", {
            "observed_at": NOW.isoformat(), "page": "TRAINING", "confidence": 0.99,
            "goals": [
                {"goal_id": "KEEP_BUILDING_PRODUCTIVE", "status": "READY", "completion": 0.0,
                 "available_skills": ["START_BUILD"], "evidence": {}},
                {"goal_id": "CLEAR_INTEL", "status": "DISCOVERED", "completion": 0.0,
                 "available_skills": ["READ_INTEL_LIST"], "evidence": {}},
            ],
        })
        monkeypatch.setattr(panel, "ROOT", tmp_path)
        rows = _capture_goal_rows(panel)
        assert len(rows) == 2
        assert all(len(row) == 9 for row in rows), "the board is nine columns wide"
        assert not any("99%" in str(cell) for row in rows for cell in row), (
            "the frame's confidence must not be printed once per Goal"
        )

    def test_the_frame_confidence_is_still_shown_once_and_labelled(self, panel, tmp_path, monkeypatch):
        _write(tmp_path, "learning/goal_state.json", {
            "observed_at": NOW.isoformat(), "page": "TRAINING", "confidence": 0.99, "goals": [],
        })
        monkeypatch.setattr(panel, "ROOT", tmp_path)
        stub = _BoardStub(panel.ControlPanel)
        panel.ControlPanel._refresh_goal_board(stub)
        meta = stub.goal_board_meta.value
        assert "99%" in meta
        assert "不是每个目标的置信度" in meta, "the one real number must say what it is about"


# --------------------------------------------------------------------------------------
# 3. The blocker column carries a reason, and never a bare "—" for an actionable Goal
# --------------------------------------------------------------------------------------


class TheBlockerColumnCarriesAReasonTests:
    GATE = {"KEEP_BUILDING_PRODUCTIVE": {
        "goal_id": "KEEP_BUILDING_PRODUCTIVE", "state": "BLOCKED", "capability": "START_BUILD",
        "reason": "repair budget exhausted (2/2) after CODE_CHANGED", "streak": 0,
        "until": "2026-09-30T17:39:30+00:00",
    }}

    def test_the_gates_own_words_are_rendered(self, panel):
        cell = panel.ControlPanel._blocked_cell(
            {"goal_id": "KEEP_BUILDING_PRODUCTIVE", "status": "READY", "evidence": {}}, self.GATE
        )
        assert "START_BUILD" in cell
        assert "repair budget exhausted" in cell
        assert "BLOCKED" in cell

    def test_a_streak_is_stated_in_episodes(self, panel):
        gate = {"X": {"state": "DEFERRED", "reason": "advanced no part of this goal", "streak": 3}}
        cell = panel.ControlPanel._blocked_cell({"goal_id": "X", "status": "READY", "evidence": {}}, gate)
        assert "连续 3 个 episode 无进展" in cell

    def test_a_busy_queue_is_named_from_the_goals_own_evidence(self, panel):
        """The frame's reason, for the Goals the library itself marked BLOCKED."""
        cell = panel.ControlPanel._blocked_cell({
            "goal_id": "SHIELD_CAMP_TRAINING", "status": "BLOCKED",
            "evidence": {"reason": "this_camp_is_training", "condition": "camp_queue_busy"},
            "retry_after": "11:17:36",
        }, {})
        assert "正在训练" in cell
        assert "11:17:36" in cell

    def test_an_unrecognised_reason_is_shown_as_its_own_code(self, panel):
        cell = panel.ControlPanel._blocked_cell({
            "goal_id": "X", "status": "BLOCKED", "evidence": {"reason": "some_new_code"},
        }, {})
        assert "some_new_code" in cell, "an unknown reason is information, not a gap to fill in"

    def test_an_actionable_goal_is_not_labelled_unknown(self, panel):
        for status in ("READY", "DISCOVERED"):
            cell = panel.ControlPanel._blocked_cell({"goal_id": "X", "status": status, "evidence": {}}, {})
            assert cell != "—", f"{status} with nothing holding it back is not an unknown"
            assert "未被阻塞" in cell

    def test_a_ready_goals_satisfied_condition_is_not_a_blocker(self, panel):
        """``condition`` on a READY Goal is the precondition that *is* met."""
        cell = panel.ControlPanel._blocked_cell({
            "goal_id": "OBSERVE_FISHING_STATE", "status": "READY",
            "evidence": {"condition": "fresh_fishing_read"},
        }, {})
        assert "fresh_fishing_read" not in cell
        assert "未被阻塞" in cell

    def test_a_blocked_goal_with_no_evidence_says_exactly_that(self, panel):
        cell = panel.ControlPanel._blocked_cell(
            {"goal_id": "X", "status": "BLOCKED", "evidence": {}}, {}
        )
        assert "没有带原因" in cell

    def test_the_goal_board_reads_the_written_blockers(self, panel, tmp_path, monkeypatch):
        _write(tmp_path, "learning/goal_state.json", {
            "observed_at": NOW.isoformat(), "page": "HOME", "confidence": 0.99,
            "goals": [{"goal_id": "DAILY_ACTIVITY_TARGET", "status": "DISCOVERED",
                       "completion": 0.0, "available_skills": [], "evidence": {}}],
            "blockers": {"DAILY_ACTIVITY_TARGET": {
                "state": "BLOCKED", "capability": "READ_DAILY_PROGRESS",
                "reason": "repair budget exhausted (2/2)", "streak": 0, "until": "",
            }},
        })
        monkeypatch.setattr(panel, "ROOT", tmp_path)
        rows = _capture_goal_rows(panel)
        blocked_cell = rows[0][7]
        assert "READ_DAILY_PROGRESS" in blocked_cell
        assert blocked_cell != "—"


# --------------------------------------------------------------------------------------
# the link: the runtime records the gate's reasons beside the Goals it explains
# --------------------------------------------------------------------------------------


class TheRuntimeRecordsWhyEachGoalWaitsTests:
    def _write_snapshot(self, tmp_path, **kwargs):
        store = GoalStateStore(tmp_path / "learning" / "goal_state.json")
        world = WorldState(page=Page.HOME, confidence=0.99)
        store.write(world, [GoalState("KEEP_BUILDING_PRODUCTIVE", GoalStatus.READY)],
                    role_id="1061663148", **kwargs)
        return json.loads((tmp_path / "learning" / "goal_state.json").read_text(encoding="utf-8"))

    def test_blockers_round_trip(self, tmp_path):
        payload = self._write_snapshot(tmp_path, blockers={
            "KEEP_BUILDING_PRODUCTIVE": {"state": "BLOCKED", "reason": "why", "streak": 2},
        })
        assert payload["blockers"]["KEEP_BUILDING_PRODUCTIVE"]["reason"] == "why"

    def test_an_older_caller_still_works(self, tmp_path):
        payload = self._write_snapshot(tmp_path)
        assert payload["blockers"] == {}

    def test_the_per_role_board_carries_them_too(self, tmp_path):
        payload = self._write_snapshot(tmp_path, blockers={"X": {"reason": "r"}})
        assert "blockers" in payload["roles"]["1061663148"]

    def test_the_goal_model_is_unchanged(self):
        """``blocked_reason`` is not a ``GoalState`` field, and must not become one here:
        the reason belongs to the gate and its evidence, not to the Goal's identity.

        The field list is asserted exactly, so that "the model did not move" is a fact and
        not a count that happens to still match.  ``priority`` is deliberately absent: it is
        a property computed from the fields, added by ``_serialize`` afterwards -- which is
        why the written record has 15 keys and the dataclass has 14.
        """
        assert set(GoalState.__dataclass_fields__) == {
            "goal_id", "status", "completion", "remaining_seconds", "reward_value",
            "daily_loss", "event_synergy", "development_value", "resource_cost", "risk",
            "available_skills", "retry_after", "evidence", "distance",
        }
        assert "blocked_reason" not in GoalState.__dataclass_fields__


# --------------------------------------------------------------------------------------


class _BoardStub:
    """Just enough of the Treeview + StringVar pair that ``_refresh_goal_board`` touches.

    Missing attributes fall through to the real ``ControlPanel``, so the helper methods the
    board calls (``_blocked_cell``) are the shipped one rather
    than copies -- a stub with its own copies would pass while the panel was broken.
    """

    def __init__(self, panel_cls):
        object.__setattr__(self, "rows", [])
        object.__setattr__(self, "goal_board", self)
        object.__setattr__(self, "_panel_cls", panel_cls)

        class _Var:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

        object.__setattr__(self, "goal_board_meta", _Var())

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_panel_cls"), name)

    def get_children(self):
        return []

    def delete(self, _item):
        return None

    def insert(self, _parent, _index, values):
        self.rows.append(tuple(values))


def _capture_goal_rows(panel) -> list[tuple]:
    stub = _BoardStub(panel.ControlPanel)
    panel.ControlPanel._refresh_goal_board(stub)
    return stub.rows
