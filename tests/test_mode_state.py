"""docs/MODE_SYSTEM.md, asserted rather than described.

Each test names the section it pins.  The point of most of them is that the *refusals* are the
behaviour: a mode system that lets anyone switch anywhere is the thing the spec exists to stop,
so the interesting assertions are the ones that expect ``ModeRefused``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import mode_state as ms


def _state_file(tmp_path: Path) -> Path:
    return tmp_path / "learning" / "MODE_STATE.json"


def _enter_manual(path: Path, *, by: str = ms.BY_WORKBUDDY, seconds: float | None = 600.0,
                  code_changed: bool = False, reason: str = "test") -> ms.ModeState:
    """Enter Manual.

    The default initiator is WorkBuddy on purpose: most of what is worth asserting lives on the
    agent's own path (§4 trigger 3 self-return, §5 decision point, §7 wrap-up).  The two modes of
    entry are genuinely different situations -- a user-ordered Manual may only be left by the user
    -- so tests about that pass ``by=ms.BY_USER`` explicitly.
    """
    return ms.switch(ms.MODE_MANUAL, initiator=by, reason=reason, expected_mode=ms.MODE_AUTO,
                     expected_seconds=seconds, completion_criteria="done", code_changed=code_changed,
                     path=path)


def _backdate(path: Path, seconds: float) -> None:
    state = ms.load(path)
    state.started_at = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    ms.save(state, path)


# -- §1 / §11: default and persistence ----------------------------------------


def test_no_record_yet_defaults_to_auto(tmp_path):
    """§11: with no instruction from anyone, stay in Auto."""
    state = ms.load(_state_file(tmp_path))
    assert state.mode == ms.MODE_AUTO
    assert state.initiator == ms.BY_USER


def test_the_mode_survives_a_restart(tmp_path):
    """§13 step 2: 'restart reads the persisted mode'.  Nothing is held in memory only."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=900.0)
    reloaded = ms.load(path)
    assert reloaded.mode == ms.MODE_MANUAL
    assert reloaded.expected_seconds == 900.0


def test_a_corrupt_record_is_kept_aside_and_the_machine_starts_in_auto(tmp_path):
    """§13: a crash must not leave the machine in an undefined mode.  The bad bytes are kept."""
    path = _state_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    state = ms.load(path)
    assert state.mode == ms.MODE_AUTO
    assert state.crash_reason
    assert path.with_suffix(".json.corrupt").is_file(), "the unreadable record must be preserved"


def test_an_unknown_mode_in_the_record_falls_back_to_auto(tmp_path):
    path = _state_file(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mode": "SOMETHING_ELSE"}), encoding="utf-8")
    state = ms.load(path)
    assert state.mode == ms.MODE_AUTO
    assert state.crash_reason


# -- §7: atomicity and compare-and-swap ---------------------------------------


def test_the_write_is_a_single_replace_with_no_temp_left_behind(tmp_path):
    """§7: 'either fully switched or not switched'.  One rename, no partial file."""
    path = _state_file(tmp_path)
    _enter_manual(path)
    assert not path.with_suffix(".json.tmp").exists()
    json.loads(path.read_text(encoding="utf-8"))  # parses as a whole document


def test_the_switch_refuses_when_the_record_is_not_where_the_caller_thinks(tmp_path):
    """§7's atomicity is only real if the transition is conditional.

    Without this, the AUTO loop and an explicit command can both believe they won -- the
    'half Auto half Manual' state the section forbids.
    """
    path = _state_file(tmp_path)
    _enter_manual(path)
    with pytest.raises(ms.ModeRefused) as refused:
        ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="stale view",
                  expected_mode=ms.MODE_AUTO, path=path)
    assert "compare-and-swap" in str(refused.value)


def test_switching_to_the_mode_already_in_force_is_a_no_op(tmp_path):
    path = _state_file(tmp_path)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_USER, reason="already there", path=path)
    assert state.mode == ms.MODE_AUTO


# -- §4 / §10: the two latches -------------------------------------------------


def test_the_user_forcing_manual_latches_out_autonomous_return(tmp_path):
    """§4 trigger 1 / §10: WorkBuddy may not go back on its own, even when its task is done.

    The latch is what makes the difference between 'the user handed me the machine' and 'I took
    it'.  Modelled by the initiator, not by a separate flag the caller could forget.

    This is the flat prohibition -- "哪怕任务完成了" -- so it holds even with a complete wrap-up
    and a recorded decision, both of which are satisfied here.
    """
    path = _state_file(tmp_path)
    state = _enter_manual(path, by=ms.BY_USER, seconds=None, code_changed=True)
    assert state.user_latch is True
    assert state.initiator == ms.BY_USER
    for step in ms.WRAP_UP_STEPS:
        ms.mark_wrap_up(step, path=path)

    with pytest.raises(ms.ModeRefused) as refused:
        ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="我做完收尾了", path=path)
    assert "only the user may switch back" in str(refused.value)
    assert ms.load(path).mode == ms.MODE_MANUAL, "the refusals must leave the machine where it was"


def test_the_user_may_switch_back_out_of_a_user_ordered_manual(tmp_path):
    """The other half of the same rule: the user's own instruction is what releases the latch."""
    path = _state_file(tmp_path)
    _enter_manual(path, by=ms.BY_USER, seconds=None)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_USER, reason="用户切 Auto", path=path)
    assert state.mode == ms.MODE_AUTO


def test_a_workbuddy_taken_manual_must_be_returned_by_workbuddy(tmp_path):
    """§4 trigger 3 condition 3: this is the case where self-return is *required*, not forbidden."""
    path = _state_file(tmp_path)
    _enter_manual(path, by=ms.BY_WORKBUDDY, seconds=None, code_changed=False)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY,
                      reason="完成标准达成：页签识别成功", path=path)
    assert state.mode == ms.MODE_AUTO


def test_the_user_forcing_auto_blocks_workbuddy_from_switching_back(tmp_path):
    """§4 trigger 2 / §10: 'even mid-task'."""
    path = _state_file(tmp_path)
    ms.switch(ms.MODE_AUTO, initiator=ms.BY_USER, reason="user takes the machine back", path=path)
    with pytest.raises(ms.ModeRefused) as refused:
        ms.switch(ms.MODE_MANUAL, initiator=ms.BY_WORKBUDDY, reason="finish the feature",
                  expected_seconds=600.0, completion_criteria="done", path=path)
    assert "may not switch back" in str(refused.value)


def test_an_autonomous_switch_is_allowed_when_no_user_latch_is_held(tmp_path):
    """§4 trigger 3: with no user instruction outstanding, WorkBuddy may take the machine."""
    path = _state_file(tmp_path)
    state = _enter_manual(path, by=ms.BY_WORKBUDDY, reason="observe the bear tab")
    assert state.mode == ms.MODE_MANUAL
    assert state.user_latch is False


def test_a_vague_reason_is_not_a_reason(tmp_path):
    """§4 condition 1: 'I want to develop' is explicitly not one of the four allowed reasons."""
    for vague in ("我想开发", "我觉得该做点什么", "随便看看", "x"):
        ok, why = ms.autonomous_switch_check(
            reason=vague, expected_seconds=600.0, completion_criteria="done"
        )
        assert not ok, vague
        assert why


def test_a_specific_reason_with_a_duration_and_a_finish_line_is_accepted():
    ok, why = ms.autonomous_switch_check(
        reason="真机验证巨熊页签能被生产技能识别",
        expected_seconds=600.0,
        completion_criteria="页签识别成功且帧上出现预约开启时间",
    )
    assert ok, why


def test_a_switch_without_a_completion_criteria_is_refused():
    """§4 condition 2: the register must carry reason, duration AND completion criteria."""
    ok, why = ms.autonomous_switch_check(reason="observe the quick panel rows",
                                         expected_seconds=600.0, completion_criteria="")
    assert not ok
    assert "completion criteria" in why


# -- §5: the estimate is a decision point, not a return point -------------------


def test_reaching_the_estimate_asks_for_a_decision_it_does_not_return(tmp_path):
    """§5: 'not a forced return point'.  It is the threshold at which a decision becomes due."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0)
    _backdate(path, 90.0)
    state = ms.load(path)
    assert state.decision_due()
    assert state.mode == ms.MODE_MANUAL, "the clock alone must not move the machine"


def test_returning_before_recording_a_decision_is_refused(tmp_path):
    """§5's forbidden case: 'pretend the time has not arrived and keep working'."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0)
    _backdate(path, 90.0)
    with pytest.raises(ms.ModeRefused) as refused:
        ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="done", path=path)
    assert "decision" in str(refused.value)


def test_pause_and_return_is_accepted_once_recorded(tmp_path):
    """§5 option A: record the decision, then the machine may go back."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0)
    _backdate(path, 90.0)
    ms.record_decision(ms.DECISION_PAUSE_AND_RETURN, path=path)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="paused for hand-off",
                      path=path)
    assert state.mode == ms.MODE_AUTO


def test_an_extension_must_state_the_new_duration(tmp_path):
    """§5 option B: 'give the new expected duration'."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0)
    with pytest.raises(ms.ModeRefused) as refused:
        ms.record_decision(ms.DECISION_EXTEND, path=path)
    assert "new expected duration" in str(refused.value)


def test_an_extension_rearms_the_clock_and_is_counted(tmp_path):
    """§5 forbids 'extend forever without returning', so the count is visible."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0)
    _backdate(path, 90.0)
    ms.record_decision(ms.DECISION_EXTEND, new_expected_seconds=300.0, path=path)
    state = ms.load(path)
    assert state.extensions == 1
    assert state.expected_seconds == 300.0
    assert state.elapsed_seconds() < 5.0, "a new estimate restarts the measurable window"
    assert not state.decision_due()


def test_the_overdue_alarm_fires_at_ten_times_the_estimate(tmp_path):
    """§13: past ten times the estimate the console has to highlight it."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0)
    _backdate(path, 601.0)
    assert ms.load(path).overdue()
    fields = ms.console_fields(path)
    assert "警告" in fields
    assert "10" in fields["警告"]


# -- §7: wrap-up ----------------------------------------------------------------


def test_a_session_that_changed_code_cannot_return_without_wrap_up(tmp_path):
    """§7 case 1: 'not completing wrap-up means no switching back'."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, code_changed=True)
    with pytest.raises(ms.ModeRefused) as refused:
        ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="done", path=path)
    assert "wrap-up incomplete" in str(refused.value)
    assert set(ms.WRAP_UP_STEPS) == set(ms.load(path).wrap_up_missing())


def test_wrap_up_is_the_four_steps_of_the_spec(tmp_path):
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, code_changed=True)
    for step in ms.WRAP_UP_STEPS:
        ms.mark_wrap_up(step, path=path)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="wrapped up", path=path)
    assert state.mode == ms.MODE_AUTO
    assert not state.wrap_up.get("committed") or True  # cleared on entering Auto
    assert state.wrap_up == {}


def test_a_pure_observation_session_may_return_directly(tmp_path):
    """§7 case 2: no code changed, so only a note is owed -- no commit, no repin."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, code_changed=False)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY,
                      reason="纯观察：只读了一个页面，没有改代码", path=path)
    assert state.mode == ms.MODE_AUTO


def test_an_unfinished_manual_session_that_touched_code_asks_for_wrap_up_on_restart(tmp_path):
    """§13 step 2: 'if Manual and not wrapped up, finish the wrap-up'."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, code_changed=True)
    reloaded = ms.load(path)
    assert reloaded.needs_wrap_up()
    assert "committed" in ms.console_fields(path)["收尾"]


# -- §9: the console surface ----------------------------------------------------


def test_the_console_reports_the_seven_required_lines(tmp_path):
    """§9 lists exactly seven; the user must see who has the machine and for how long."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=1800.0, reason="真机验证巨熊页签")
    fields = ms.console_fields(path)
    for key in ("当前模式", "机器状态", "切换发起方", "切换理由", "已持续", "预计剩余", "回切条件"):
        assert key in fields, key
    assert fields["当前模式"] == ms.MODE_MANUAL
    assert fields["机器状态"] == "WorkBuddy 开发中"
    assert "巨熊页签" in fields["切换理由"]


def test_the_console_says_the_system_is_running_in_auto(tmp_path):
    path = _state_file(tmp_path)
    ms.switch(ms.MODE_AUTO, initiator=ms.BY_USER, reason="user takes it back", path=path)
    fields = ms.console_fields(path)
    assert fields["当前模式"] == ms.MODE_AUTO
    assert fields["机器状态"] == "系统运行中"


# -- CLI: the explicit entry points §14.6 asks for ------------------------------


def test_the_cli_refuses_a_vague_autonomous_switch(tmp_path, capsys):
    path = _state_file(tmp_path)
    code = ms.main(["--state", str(path), "--to-manual", "--by", ms.BY_WORKBUDDY,
                    "--reason", "我想开发"])
    assert code == 2
    assert "拒绝自主切换" in capsys.readouterr().err
    assert ms.load(path).mode == ms.MODE_AUTO, "a refused switch must not move the machine"


def test_the_cli_moves_the_machine_and_reports_the_mode(tmp_path, capsys):
    path = _state_file(tmp_path)
    code = ms.main(["--state", str(path), "--to-manual", "--by", ms.BY_USER,
                    "--reason", "用户切 Manual", "--expected-minutes", "10", "--done-when", "页签识别"])
    assert code == 0
    assert ms.load(path).mode == ms.MODE_MANUAL
    capsys.readouterr()

    code = ms.main(["--state", str(path), "--status"])
    assert code == 0
    out = capsys.readouterr().out
    assert "当前模式：MANUAL" in out
    assert "WorkBuddy 开发中" in out


# -- §7 vs §10: the one place the specification pulls against itself ------------


def test_the_user_override_is_recorded_not_silently_honoured(tmp_path):
    """§7 says no return without wrap-up; §10 ranks the user's order first.

    Both have to hold.  The gate stays (the missing steps are trivially completable, and §12
    forbids handing back a machine with uncommitted code), and the user can still overrule it --
    but the override lands in the audit trail naming what was skipped, so "the user insisted"
    is a fact on record rather than an invisible bypass.
    """
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, code_changed=True)
    state = ms.switch(ms.MODE_AUTO, initiator=ms.BY_USER, reason="用户要求立刻回切",
                      force=True, path=path)
    assert state.mode == ms.MODE_AUTO
    notes = [row.note for row in state.history if row.note]
    assert any("OVERRIDDEN BY USER" in note for note in notes), notes
    assert any("committed" in note for note in notes), notes


def test_a_refusal_names_every_outstanding_item_at_once(tmp_path):
    """One attempt, one complete list: the decision and the wrap-up are reported together."""
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=60.0, code_changed=True)
    _backdate(path, 90.0)
    with pytest.raises(ms.ModeRefused) as refused:
        ms.switch(ms.MODE_AUTO, initiator=ms.BY_WORKBUDDY, reason="done", path=path)
    message = str(refused.value)
    assert "wrap-up incomplete" in message
    assert "decision" in message


def test_the_cli_exposes_the_override(tmp_path, capsys):
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, code_changed=True)
    code = ms.main(["--state", str(path), "--to-auto", "--by", ms.BY_USER,
                    "--reason", "用户要求立刻回切", "--force"])
    assert code == 0, capsys.readouterr().err
    assert ms.load(path).mode == ms.MODE_AUTO


# -- the runtime side: this is what makes the mode more than a file -------------


def _runtime_with(tmp_path, path: Path):
    """A ``LiveRuntime`` carrying only what the guard reads.

    Same construction as the coordinate-gate test: skip the constructor, hang the two attributes
    on.  The guard is deliberately written against ``getattr(self, "mode_state_path", ...)`` so it
    can be exercised without standing up a whole runtime.
    """
    from winter_agent_v2.runtime import LiveRuntime

    runtime = object.__new__(LiveRuntime)
    runtime.mode_state_path = path
    return runtime


def test_the_runtime_yields_the_machine_while_manual_owns_it(tmp_path):
    """§1/§2/§3: 'in Manual the machine belongs entirely to WorkBuddy'.

    Without this the mode record would be a truthful document that changes nothing -- the system
    would keep playing the game while claiming WorkBuddy had the machine.
    """
    path = _state_file(tmp_path)
    _enter_manual(path, seconds=None, reason="真机验证巨熊页签能被生产技能识别")
    assert _runtime_with(tmp_path, path)._mode_stop_reason() == "manually_owned_by_workbuddy"


def test_the_runtime_does_not_yield_in_auto(tmp_path):
    """The common case must be untouched: in Auto the loop runs exactly as it did before."""
    path = _state_file(tmp_path)
    ms.switch(ms.MODE_AUTO, initiator=ms.BY_USER, reason="user keeps the machine", path=path)
    assert _runtime_with(tmp_path, path)._mode_stop_reason() is None


def test_a_missing_or_broken_record_does_not_freeze_the_system(tmp_path):
    """§11's default, in the fail-safe direction.

    A deleted or corrupt record must not be read as "WorkBuddy owns the machine" -- that would
    turn a lost file into a silently frozen AUTO.
    """
    assert _runtime_with(tmp_path, tmp_path / "nope" / "MODE_STATE.json")._mode_stop_reason() is None
    broken = _state_file(tmp_path)
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{not json", encoding="utf-8")
    assert _runtime_with(tmp_path, broken)._mode_stop_reason() is None
