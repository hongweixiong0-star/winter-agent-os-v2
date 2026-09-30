"""ACCEPTANCE §22 needs a number, not a narrative.

``00_MASTER_RULES`` §22 defines the project's success as "AUTO runs >= 72h unattended with
``unexpected_worker_exits = 0``".  Nothing measured it: ``learning/runtime_snapshot.json``
describes only the current moment, so the 2026-09-30 reports could state "5.9 hours with zero
episodes" but could not answer "what is the longest self-continuing AUTO run so far?".

``learning/auto_uptime.jsonl`` is that ledger -- one row per finished round, written by the panel
at the single point where it has already decided whether another round follows.  These tests pin
three things:

* the fold answers the acceptance question (3 consecutive continuing rounds = the operator's
  verification bar for the 2026-09-30 exit-code fix),
* a damaged ledger degrades instead of raising, because a measurement must never stop the run,
* the panel's round-completion path actually writes it -- including the full chain from the
  child's real result payload, which is where the 11:53 halt lived.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime_snapshot import (  # noqa: E402
    append_uptime_ledger,
    read_uptime_ledger,
    summarize_uptime,
    uptime_ledger_row,
)


def _row(seconds: int, *, continues: bool, halt: str = "系统故障", reason: str = "MAX_ACTIONS_REACHED"):
    return {
        "recorded_at": f"2026-09-30T03:{seconds:02d}:00+00:00",
        "stop_reason": reason,
        "stop_category": "COMPLETED" if continues else "SYSTEM_FAILURE",
        "healthy": continues,
        "continues": continues,
        "halt_reason": "" if continues else halt,
        "executed": 23,
    }


class AcceptanceIsComputableCase:
    def test_three_continuing_rounds_meet_the_operators_bar(self):
        summary = summarize_uptime([_row(1, continues=True), _row(2, continues=True), _row(3, continues=True)])
        assert summary["longest_consecutive_continues"] == 3
        assert summary["acceptance_required"] == 3
        assert summary["acceptance_met"] is True

    def test_two_continuing_rounds_do_not(self):
        summary = summarize_uptime([_row(1, continues=True), _row(2, continues=True), _row(3, continues=False)])
        assert summary["longest_consecutive_continues"] == 2
        assert summary["acceptance_met"] is False

    def test_the_window_is_measured_from_the_rows_so_it_cannot_be_confused_with_72h(self):
        summary = summarize_uptime([_row(1, continues=True), _row(2, continues=True), _row(3, continues=True)])
        assert summary["longest_window_seconds"] == 120
        assert summary["longest_window_seconds"] < 72 * 3600

    def test_a_streak_that_ended_still_counts_as_the_best_ever(self):
        rows = [_row(1, continues=True), _row(2, continues=True), _row(3, continues=True),
                _row(4, continues=False), _row(5, continues=True)]
        summary = summarize_uptime(rows)
        assert summary["longest_consecutive_continues"] == 3
        assert summary["current_consecutive_continues"] == 1
        assert summary["halted_rounds"] == 1

    def test_the_last_halt_reason_survives_the_fold(self):
        summary = summarize_uptime([_row(1, continues=True), _row(2, continues=False, halt="系统故障：MAX_ACTIONS_REACHED")])
        assert "MAX_ACTIONS_REACHED" in summary["last_halt_reason"]

    def test_an_empty_ledger_says_so_instead_of_guessing(self):
        summary = summarize_uptime([])
        assert summary["rounds"] == 0
        assert summary["acceptance_met"] is False
        assert summary["last_halt_reason"] == ""


class TheLedgerDegradesInsteadOfRaisingCase:
    def test_a_damaged_line_is_skipped_not_fatal(self, tmp_path: Path):
        path = tmp_path / "auto_uptime.jsonl"
        path.write_text(
            json.dumps(_row(1, continues=True)) + "\n" + "{not json at all\n" + "\n"
            + json.dumps(_row(2, continues=True)) + "\n",
            encoding="utf-8",
        )
        rows = read_uptime_ledger(path)
        assert len(rows) == 2
        assert summarize_uptime(rows)["longest_consecutive_continues"] == 2

    def test_a_missing_ledger_is_an_empty_ledger(self, tmp_path: Path):
        assert read_uptime_ledger(tmp_path / "nothing.jsonl") == []

    def test_a_row_is_appended_not_rewritten(self, tmp_path: Path):
        path = tmp_path / "auto_uptime.jsonl"
        append_uptime_ledger(path, uptime_ledger_row(
            recorded_at="2026-09-30T03:00:00+00:00", stop_reason="MAX_ACTIONS_REACHED",
            stop_category="COMPLETED", healthy=True, continues=True))
        append_uptime_ledger(path, uptime_ledger_row(
            recorded_at="2026-09-30T03:05:00+00:00", stop_reason="MAX_ACTIONS_REACHED",
            stop_category="COMPLETED", healthy=True, continues=True))
        assert len(read_uptime_ledger(path)) == 2

    def test_an_unwritable_path_does_not_raise(self, tmp_path: Path):
        # A file where the ledger's parent directory should be: the append cannot succeed, and
        # the caller (the running panel) must not be taken down by its own measurement.
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        append_uptime_ledger(blocker / "auto_uptime.jsonl", _row(1, continues=True))


class ThePanelRecordsTheRoundItJustDecidedCase:
    """The wiring, driven through the panel's own round-completion path.

    ``cp.ControlPanel._record_auto_round`` and ``cp.summarize_runtime_result`` are the real
    functions; only the Tk window and the device are absent (the method needs neither).
    """

    def _panel_stub(self, monkeypatch, tmp_path: Path):
        """A stub that carries exactly the interface the recorder is allowed to use.

        Measured live 2026-09-30 12:24:46: an earlier version of the recorder read
        ``self._state``, and the real panel wrote ``运行时长台账写入失败 ... AttributeError:
        'ControlPanel' object has no attribute '_state'`` on every round -- because ``_state``
        belongs to ``QueuePump``.  This stub had been given ``_state`` too, so it agreed with the
        bug instead of catching it.  The test below now checks the interface against the real
        class rather than against this dict.
        """
        cp = importlib.import_module("tools.control_panel")
        ledger = tmp_path / "auto_uptime.jsonl"
        monkeypatch.setattr(cp, "AUTO_UPTIME_LEDGER_PATH", ledger)
        from winter_agent_v2.runtime_snapshot import RuntimeSnapshot

        def _read():
            return RuntimeSnapshot(role_id="1063040265")

        panel = type("PanelStub", (), {})()
        panel.runtime_store = type("Store", (), {"read": staticmethod(_read)})()
        panel._append = lambda message: None
        panel._record_auto_round = cp.ControlPanel._record_auto_round.__get__(panel)
        return cp, panel, ledger

    def test_the_recorder_only_touches_attributes_the_real_panel_has(self):
        """Structural, because the failure was an interface the stub invented.

        Live failure this pins: 2026-09-30 12:24:46, ``运行时长台账写入失败（不影响 AUTO）：
        AttributeError: 'ControlPanel' object has no attribute '_state'`` on every round --
        ``_state`` belongs to ``QueuePump``, and the stub had been handed one too, so the test
        agreed with the bug instead of catching it.

        Checked against the class source rather than ``hasattr``: the panel assigns these in
        ``__init__`` (``self.runtime_store = RuntimeSnapshotStore(...)``), so they are instance
        attributes and would fail a class-level ``hasattr`` even though every real panel has them.
        """
        import ast

        cp = importlib.import_module("tools.control_panel")
        names = set(cp.ControlPanel._record_auto_round.__code__.co_names)
        tree = ast.parse(Path(cp.__file__).read_text(encoding="utf-8"))
        defined: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    defined.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined.add(target.id)
        for name in ("_state", "loaded_revision", "role_id", "runtime_store", "_append",
                     "AUTO_UPTIME_LEDGER_PATH"):
            if name in names:
                assert name in defined, (
                    f"the recorder reaches for {name!r}, which nothing in control_panel.py ever"
                    " assigns or defines -- this is the 12:24:46 AttributeError"
                )

    def test_a_continuing_round_is_written_as_continuing(self, monkeypatch, tmp_path: Path):
        cp, panel, ledger = self._panel_stub(monkeypatch, tmp_path)
        summary = cp.summarize_runtime_result(
            {"stop_reason": "MAX_ACTIONS_REACHED", "steps": []}, 0)
        panel._record_auto_round(summary, summary["reason"], halt_reason="")
        rows = read_uptime_ledger(ledger)
        assert len(rows) == 1
        assert rows[0]["continues"] is True
        assert rows[0]["halt_reason"] == ""
        assert rows[0]["role_id"] == "1063040265"

    def test_a_halted_round_records_why(self, monkeypatch, tmp_path: Path):
        cp, panel, ledger = self._panel_stub(monkeypatch, tmp_path)
        summary = cp.summarize_runtime_result(
            {"stop_reason": "MAX_ACTIONS_REACHED", "steps": []}, 2)
        halt = cp.auto_halt_reason(
            healthy=summary["healthy"], reason=summary["reason"], continuous=True,
            stop_requested=False, paused=False, fatal=False)
        panel._record_auto_round(summary, summary["reason"], halt_reason=halt)
        row = read_uptime_ledger(ledger)[0]
        assert row["continues"] is False
        assert "MAX_ACTIONS_REACHED" in row["halt_reason"]


class TheWholeChainFromTheChildProcessCase:
    """The 11:53 round end to end: real payload, real classifier, real continuance rule.

    This is the test that would have caught the halt: the old exit code (2, from ``verified``)
    makes ``summarize_runtime_result`` say ``healthy=False`` even though the round's own stop
    reason is a declared completion, and the panel then declines the next round.
    """

    #: The measured shape: 23 steps, 22 verifiers PASS, one ``OPEN_BEAST_SEARCH_TAB`` miss.
    _MISS = {"execution": {"executed": True}, "verification": {"ok": False, "reason": "BEAST_SEARCH_TAB_NOT_PROVEN"}}
    _PASS = {"execution": {"executed": True}, "verification": {"ok": True, "reason": "OK"}}

    def _payload(self):
        return {"stop_reason": "MAX_ACTIONS_REACHED",
                "steps": [self._MISS] + [self._PASS] * 22}

    def _decide(self, exit_code: int):
        cp = importlib.import_module("tools.control_panel")
        summary = cp.summarize_runtime_result(self._payload(), exit_code)
        halt = cp.auto_halt_reason(
            healthy=summary["healthy"], reason=summary["reason"], continuous=True,
            stop_requested=False, paused=False, fatal=False)
        return summary, halt

    def test_the_old_exit_code_still_reproduces_the_halt(self):
        """Keeps the regression honest: this is what the child used to return."""
        summary, halt = self._decide(2)
        assert summary["stop_category"] == "COMPLETED"   # the 11:50 classifier fix is real
        assert summary["healthy"] is False               # ... and the exit code overrode it
        assert halt, "the 11:58 halt is reproduced, so the fix is testable"

    def test_the_fixed_exit_code_lets_auto_continue(self):
        summary, halt = self._decide(0)
        assert summary["failures"] == 1, "the miss must stay visible in the summary"
        assert summary["healthy"] is True
        assert halt == "", "one miss inside a finished round must not stop AUTO"

    def test_the_child_returns_that_zero_for_the_measured_round(self):
        run_live = importlib.import_module("tools.run_live")
        accepted = {"MAX_ACTIONS_REACHED", "TARGET_SKILL_VERIFIED"}
        assert run_live.run_outcome_exit_code("MAX_ACTIONS_REACHED", accepted) == 0


@pytest.mark.parametrize("reason", ["MAX_ACTIONS_REACHED", "TARGET_SKILL_VERIFIED"])
def test_completed_stops_are_the_ones_that_keep_auto_alive(reason: str):
    cp = importlib.import_module("tools.control_panel")
    summary = cp.summarize_runtime_result({"stop_reason": reason, "steps": []}, 0)
    assert summary["stop_category"] == "COMPLETED"
    assert cp.auto_halt_reason(
        healthy=summary["healthy"], reason=summary["reason"], continuous=True,
        stop_requested=False, paused=False, fatal=False) == ""
