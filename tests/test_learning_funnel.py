"""The learning funnel: an unmeasured stage is reported as unmeasured, never as zero.

Directive 2026-10-01 sections 36-38.  The rule this file exists to protect is the one that makes
the funnel usable for diagnosis: "nothing writes this down yet" and "this never happened" are
opposite findings, and a fold that renders both as ``0`` destroys the distinction the funnel is
built on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from winter_agent_v2 import learning_funnel as lf


def _write(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows and isinstance(rows[0], dict) and "recorded_at" not in rows[0]:
        rows = list(rows)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )


class EmptyProjectTests(unittest.TestCase):
    def test_an_empty_project_reports_unmeasured_where_it_has_no_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            funnel = lf.build_funnel(root=tmp)
        stages = {stage.stage: stage for stage in funnel.funnel}
        # No record anywhere: the count is None and the reason is a sentence, not a zero.
        self.assertIsNone(stages["grounding_valid"].count)
        self.assertTrue(stages["grounding_valid"].unmeasured_reason)
        # A stage whose source exists and is simply empty *is* measurable, and reads 0.
        self.assertEqual(stages["model_proposed"].count, 0)

    def test_stages_the_registry_owns_are_never_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            funnel = lf.build_funnel(root=tmp)
        stages = {stage.stage: stage for stage in funnel.funnel}
        for name in ("live_verified", "stable"):
            self.assertIsNone(stages[name].count)
            self.assertIn("REGISTRY_OWNS_THIS", stages[name].unmeasured_reason)

    def test_the_funnel_order_is_the_directives_order(self):
        self.assertEqual(lf.FUNNEL_STAGES[0], "unknown_observed")
        self.assertEqual(lf.FUNNEL_STAGES[-1], "stable")
        with tempfile.TemporaryDirectory() as tmp:
            funnel = lf.build_funnel(root=tmp)
        self.assertEqual(tuple(stage.stage for stage in funnel.funnel), lf.FUNNEL_STAGES)


class CountingTests(unittest.TestCase):
    def test_a_planner_call_on_a_named_page_is_counted_as_a_known_screen_call(self):
        """§37's KNOWN_MODEL_CALLS, reported as evidence rather than as an assertion of zero."""
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / lf.PLANNER_LEDGER, [
                {"recorded_at": now.isoformat(), "source": "LOCAL_GUI_MODEL",
                 "page_key": "UNKNOWN::活动", "goal": "DAILY", "decision": "EXECUTE"},
                {"recorded_at": now.isoformat(), "source": "LOCAL_GUI_MODEL",
                 "page_key": "MAP", "goal": "DAILY", "decision": "EXECUTE"},
            ])
            funnel = lf.build_funnel(root=root, now=now)
        self.assertEqual(funnel.metrics["KNOWN_MODEL_CALLS_TODAY"], 1)
        self.assertEqual(funnel.metrics["UNKNOWN_MODEL_CALLS_TODAY"], 2)

    def test_a_retired_source_is_still_read_as_a_planner_call(self):
        """The ledger's history calls the provider ``LOCAL_QWEN``; a fold that knew only the new
        name would report "no calls at all" about a day that had plenty."""
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / lf.PLANNER_LEDGER, [
                {"recorded_at": now.isoformat(), "source": "LOCAL_QWEN", "page_key": "MAP",
                 "goal": "DAILY", "decision": "EXECUTE"},
            ])
            funnel = lf.build_funnel(root=root, now=now)
        self.assertEqual(funnel.metrics["UNKNOWN_MODEL_CALLS_TODAY"], 1)

    def test_the_completion_rate_is_over_finished_steps_only(self):
        """A rate over every row would fall whenever the agent correctly *observed* something."""
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / lf.EPISODES, [
                {"recorded_at": now.isoformat(), "result": "SUCCESS"},
                {"recorded_at": now.isoformat(), "result": "FAILURE"},
                {"recorded_at": now.isoformat(), "result": "PROGRESS"},
                {"recorded_at": now.isoformat(), "result": "INCOMPLETE"},
            ])
            funnel = lf.build_funnel(root=root, now=now)
        self.assertEqual(funnel.metrics["game_task_completion_rate_n"], 2)
        self.assertEqual(funnel.metrics["GAME_TASK_COMPLETION_RATE"], 0.5)

    def test_a_rate_with_no_denominator_is_none_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            funnel = lf.build_funnel(root=tmp)
        self.assertIsNone(funnel.metrics["GAME_TASK_COMPLETION_RATE"])
        self.assertIsNone(funnel.metrics["UNKNOWN_VERIFIER_PASS_RATE"])
        self.assertIsNone(funnel.console["重复 UNKNOWN 调用率"])

    def test_the_window_actually_excludes_older_rows(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=5)).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / lf.PLANNER_LEDGER, [
                {"recorded_at": old, "source": "LOCAL_GUI_MODEL", "page_key": "MAP",
                 "goal": "DAILY", "decision": "EXECUTE"},
            ])
            funnel = lf.build_funnel(root=root, now=now, window_days=1)
        self.assertEqual(funnel.metrics["UNKNOWN_MODEL_CALLS"], 1)
        self.assertEqual(funnel.metrics["UNKNOWN_MODEL_CALLS_TODAY"], 0)

    def test_a_row_with_no_timestamp_is_not_counted_as_today(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / lf.PLANNER_LEDGER, [
                {"source": "LOCAL_GUI_MODEL", "page_key": "MAP", "goal": "DAILY",
                 "decision": "EXECUTE"},
            ])
            funnel = lf.build_funnel(root=root, now=now)
        self.assertEqual(funnel.metrics["UNKNOWN_MODEL_CALLS"], 1)
        self.assertEqual(funnel.metrics["UNKNOWN_MODEL_CALLS_TODAY"], 0)


class ConsoleTests(unittest.TestCase):
    def test_the_console_uses_a_dash_for_an_unmeasured_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            funnel = lf.build_funnel(root=tmp)
        text = lf.render_console(funnel)
        self.assertIn("新 Stable Skill", text)
        self.assertIn("—", text)

    def test_every_console_line_names_what_it_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            funnel = lf.build_funnel(root=tmp)
        self.assertEqual(
            set(funnel.console),
            {"今日 UI-Venus 调用", "UNKNOWN 次数", "UNKNOWN 成功解决", "Verifier 通过数",
             "新 Candidate Skill", "新 Stable Skill", "Skill Repair 成功数",
             "新增 Candidate Page", "新增 Confirmed Page", "重复 UNKNOWN 调用率",
             "KNOWN_MODEL_CALLS", "今日游戏任务完成率"},
        )
        for value in funnel.sources.values():
            self.assertTrue(str(value))


if __name__ == "__main__":
    unittest.main()
