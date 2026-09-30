"""The control centre's one local-model cell, and the two lines under it.

Operator directive 2026-09-30: the console has to answer *which* model, *is it up*, and *what did
it last decide* -- without the operator opening a log -- and it may not dress a model's own claim
up as a verified outcome, nor show a known Skill's work as model reasoning.

The tests live here rather than in ``test_local_planner.py`` because they exercise
``tools/control_panel``, not the planner: that file exists to pin the protocol between the runtime
and the local model, and a console test failing there would point at the wrong file.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ui_planner  # noqa: E402


class TheConsoleShowsTheOneLocalModelTest(unittest.TestCase):
    def test_the_console_reads_the_verdict_from_the_verifier_only(self):
        """Not from the model: a plan with no settlement must say 未验证, never "passed"."""
        from tools import control_panel

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steps.jsonl"
            path.write_text(
                json.dumps({"recorded_at": "2026-09-30T14:00:00+00:00", "decision": "EXECUTE",
                            "target_element_id": "E4"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(control_panel._settlement_line(path), "Verifier 未验证")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"record": "outcome", "verifier_ok": False,
                                         "skill": "AI_ADVICE[TAP]"}, ensure_ascii=False) + "\n")
            self.assertEqual(control_panel._settlement_line(path),
                             "Verifier FAIL（AI_ADVICE[TAP]）")

    def test_a_settlement_is_never_mistaken_for_a_plan(self):
        """The two row kinds share a file, so the reader has to tell them apart."""
        from tools import control_panel

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steps.jsonl"
            path.write_text(
                json.dumps({"recorded_at": "t", "source": ui_planner.SOURCE_LOCAL_GUI_MODEL,
                            "goal": "EXPLORATION", "page_key": "UNKNOWN::x",
                            "decision": "EXECUTE", "target_element_id": "E4"},
                           ensure_ascii=False) + "\n"
                + json.dumps({"record": "outcome", "verifier_ok": True},
                             ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            plan = control_panel._last_plan_row(path)
            self.assertEqual(plan.get("target_element_id"), "E4")
            self.assertNotIn("record", plan)


    def test_a_row_from_the_retired_provider_is_not_a_last_decision(self):
        """Measured falsehood 2026-09-30: the newest plan row was an old provider's timeout.

        The first version of the reader accepted any row carrying a ``decision`` key, so the
        window's "最近调用" line claimed the model had been asked about ``BEAST_HUNT`` on
        ``UNKNOWN::发起集结`` -- a screen this build never asked it about.
        """
        from tools import control_panel

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steps.jsonl"
            path.write_text(json.dumps({
                "recorded_at": "2026-09-30T12:11:19+00:00", "source": "LOCAL_QWEN",
                "page_key": "UNKNOWN::发起集结", "goal": "BEAST_HUNT", "decision": "",
                "error": "LOCAL_QWEN_TIMEOUTERROR",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(control_panel._last_plan_row(path), {})

    def test_the_panel_and_the_planner_agree_on_the_source_string(self):
        """A silent divergence would hide every last decision while the ledger stayed full."""
        from tools import control_panel

        self.assertEqual(control_panel.LOCAL_GUI_SOURCE, ui_planner.SOURCE_LOCAL_GUI_MODEL)
        self.assertEqual(control_panel.LOCAL_GUI_PLAN_LEDGER_PATH,
                         ROOT / "learning/local_planner_steps.jsonl")
        self.assertEqual(control_panel.LOCAL_GUI_LEDGER_PATH,
                         ROOT / "learning/local_gui_model_calls.jsonl")

