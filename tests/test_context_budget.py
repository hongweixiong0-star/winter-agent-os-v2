"""The 32K input budget: three numbers, one order of sacrifice, and nothing silently dropped.

Operator directive 2026-09-30 (second half), sections 1-3 and 9.  What a test can hold here, as
opposed to what only a live server can:

* ``MAX_MODEL_CONTEXT`` is 32768, the reply keeps at least 4096 of it, and the input budget is
  what is left -- stated as an arithmetic identity so the three cannot drift apart;
* the launch tool and the packet builder read that same number instead of carrying a second
  copy, which is what makes "the window the server was started with" and "the window the planner
  budgets against" the same fact rather than two that happen to agree today;
* when a packet does not fit, sections are dropped in the directive's own P0/P1/P2 order, and
  the P0 set survives every trim;
* the element table never goes below its floor, and the history loses its *oldest* rows first;
* a packet that cannot be made to fit says so instead of being sent over the wall.

The estimate is checked against the served tokenizer's measured ratio rather than against taste:
``estimate_tokens("Hello world, 你好世界")`` was 6 real tokens on 2026-09-30, and the heuristic
is required to over-state it, because over-stating trims early and under-stating sends a prompt
the server refuses.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ``tools/`` explicitly: ``conftest`` adds it only when the state-manifest guard needs it, and the
# pinning tests below import the launch tool directly.  Same two lines the tools themselves use.
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from winter_agent_v2 import context_budget  # noqa: E402
from winter_agent_v2 import local_gui_model  # noqa: E402
from winter_agent_v2 import ui_planner  # noqa: E402

#: Measured with ``/tokenize`` against the served UI-Venus-2-9B vocabulary on 2026-09-30.
MEASURED_SAMPLE_TEXT = "Hello world, 你好世界"
MEASURED_SAMPLE_TOKENS = 6


def elements(count: int = 40) -> list[dict]:
    return [
        {"id": f"E{index + 1}", "text": f"控件{index + 1}", "area": "middle",
         "kind": "COMPOSITE_CONTROL", "semantic": f"control {index + 1}", "executable": True}
        for index in range(count)
    ]


def history(count: int = 16) -> list[dict]:
    return [
        {"step": index + 1, "skill": "TRY_ORDINARY_CONTROL", "control": f"按钮{index + 1}",
         "expected": "POPUP", "observed": "NONE", "verifier": "FAIL"}
        for index in range(count)
    ]


def big_packet() -> dict:
    """A packet that is far too large for the budget it will be measured against."""
    return ui_planner.build_packet(
        goal="DAILY_ROUTINE",
        role_id="BUILDER",
        current_page="UNKNOWN::欢迎回来",
        world_state={"page": "HOME", "confidence": 0.8, "stamina": 120,
                     "resources": {"wood": 99999, "food": 99999, "iron": 99999},
                     "training": ["a", "b", "c"], "research": ["x"],
                     "building": ["q"], "hospital": ["h"], "defense": ["d"],
                     "player": {"name": "x" * 40}, "march": {"queue": 2}},
        elements=elements(40),
        relevant_knowledge=["knowledge one " * 20, "knowledge two " * 20, "knowledge three " * 20],
        last_verifier_outcome={"ok": False, "skill": "TRY_ORDINARY_CONTROL", "result": "FAILURE"},
        recent_steps=history(16),
        session={"step_index": 9, "no_progress_count": 4, "remaining_steps": 1},
        remaining_steps=1,
        step_index=9,
    )


class TheWindowIsThirtyTwoKTest(unittest.TestCase):
    def test_the_three_numbers_are_one_arithmetic_identity(self):
        self.assertEqual(context_budget.MAX_MODEL_CONTEXT, 32768)
        self.assertGreaterEqual(context_budget.OUTPUT_RESERVE, 4096)
        self.assertEqual(
            context_budget.MAX_INPUT_BUDGET,
            context_budget.MAX_MODEL_CONTEXT - context_budget.OUTPUT_RESERVE,
        )
        self.assertEqual(context_budget.MAX_INPUT_BUDGET, 28672)

    def test_the_manager_defaults_to_the_module_numbers(self):
        manager = context_budget.ContextBudgetManager()
        self.assertEqual(manager.max_model_context, 32768)
        self.assertEqual(manager.output_reserve, 4096)
        self.assertEqual(manager.max_input_budget, 28672)

    def test_the_manager_is_configurable_but_keeps_the_reserve(self):
        manager = context_budget.ContextBudgetManager(max_model_context=16384,
                                                      output_reserve=4096)
        self.assertEqual(manager.max_input_budget, 12288)

    def test_a_reserve_that_eats_the_window_is_refused(self):
        # Every call would fail with an over-budget refusal that looks like a model fault, so the
        # impossible configuration is refused at construction rather than discovered per step.
        with self.assertRaises(ValueError):
            context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=4096)


class TheClientAndTheLauncherReadTheOneNumberTest(unittest.TestCase):
    def test_the_client_defaults_to_the_budget_window(self):
        self.assertEqual(local_gui_model.DEFAULT_CONTEXT, context_budget.MAX_MODEL_CONTEXT)

    def test_the_runtime_config_asks_for_the_same_window(self):
        config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        section = config["local_planner"]
        self.assertEqual(int(section["context"]), context_budget.MAX_MODEL_CONTEXT)
        self.assertGreaterEqual(int(section["output_reserve"]), 4096)
        # The two literals that would be the first sign of drift: the retired 8K window and the
        # half-way 16K one.  Neither may appear as a production default anywhere in this section.
        self.assertNotIn(int(section["context"]), (8192, 16384))

    def test_the_launch_tool_asks_for_the_same_window(self):
        import launch_gui_model_server  # noqa: PLC0415 - tools/ is added to sys.path by conftest

        self.assertEqual(launch_gui_model_server.CONTEXT, context_budget.MAX_MODEL_CONTEXT)
        profile = launch_gui_model_server.ServerProfile()
        args = profile.server_args()
        self.assertEqual(args[args.index("-c") + 1], str(context_budget.MAX_MODEL_CONTEXT))

    def test_the_image_charge_matches_the_launch_flag(self):
        # The budget accounts for the frame as a fixed 1024 tokens; that is only true because the
        # launch flags pin it.  A launch tool whose image tokens moved would silently make every
        # prompt estimate wrong, so the coupling is asserted rather than documented.
        import launch_gui_model_server  # noqa: PLC0415

        args = launch_gui_model_server.ServerProfile().server_args()
        self.assertEqual(args[args.index("--image-max-tokens") + 1],
                         str(context_budget.IMAGE_TOKENS))
        self.assertEqual(args[args.index("--image-min-tokens") + 1],
                         str(context_budget.IMAGE_TOKENS))


class TheEstimateOnlyEverOverStatesTest(unittest.TestCase):
    def test_the_measured_sample_is_not_under_stated(self):
        self.assertGreaterEqual(context_budget.estimate_tokens(MEASURED_SAMPLE_TEXT),
                                MEASURED_SAMPLE_TOKENS)

    def test_cjk_costs_more_than_ascii_per_character(self):
        # Same character count on both sides, because that is the claim: per character, CJK is
        # the expensive case.  (Measured against the served tokenizer: ~0.5 versus ~0.31.)
        cjk = context_budget.estimate_tokens("你好世界你好世界你好世界你好")
        ascii_text = context_budget.estimate_tokens("a" * 12)
        self.assertGreater(cjk, ascii_text)

    def test_an_empty_string_costs_nothing(self):
        self.assertEqual(context_budget.estimate_tokens(""), 0)

    def test_a_packet_is_measured_as_the_json_that_travels(self):
        packet = {"goal": "G", "available_elements": elements(3)}
        self.assertGreater(context_budget.estimate_packet_tokens(packet), 0)
        # The rendered form is what the model sees, so the estimate has to move with it.
        self.assertGreater(context_budget.estimate_packet_tokens(packet),
                           context_budget.estimate_tokens("G"))


class TheSacrificeFollowsTheDirectiveOrderTest(unittest.TestCase):
    def _trim(self, manager: context_budget.ContextBudgetManager):
        return manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=big_packet())

    def test_world_state_extras_go_before_anything_else(self):
        fitted, report = self._trim(context_budget.ContextBudgetManager(
            max_model_context=4096, output_reserve=1024))
        self.assertTrue(any(name.startswith("world_state") for name in report.dropped_sections))
        self.assertEqual(report.dropped_sections[0].split(":")[0], "world_state")

    def test_history_falls_to_the_floor_before_knowledge_is_touched(self):
        manager = context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=1024)
        _, report = self._trim(manager)
        names = [name.split(":")[0] for name in report.dropped_sections]
        self.assertIn("history", names)
        if "knowledge" in names:
            self.assertLess(names.index("history"), names.index("knowledge"))

    def test_the_history_that_survives_is_the_newest(self):
        manager = context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=1024)
        fitted, report = self._trim(manager)
        kept = fitted.get("recent_steps") or []
        self.assertLess(len(kept), 16)
        self.assertEqual([row["step"] for row in kept],
                         list(range(16 - len(kept) + 1, 17)))

    def test_the_report_names_what_it_dropped(self):
        _, report = self._trim(context_budget.ContextBudgetManager(
            max_model_context=4096, output_reserve=1024))
        row = report.to_row()
        self.assertTrue(row["dropped_sections"])
        self.assertEqual(row["max_model_context"], 4096)
        self.assertEqual(row["max_input_budget"], 3072)
        self.assertGreater(row["elements_dropped"], 0)

    def test_a_packet_inside_the_budget_is_returned_untouched(self):
        packet = big_packet()
        manager = context_budget.ContextBudgetManager()
        fitted, report = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=packet)
        self.assertEqual(report.dropped_sections, ())
        self.assertEqual(len(fitted["available_elements"]), len(packet["available_elements"]))
        self.assertEqual(len(fitted["recent_steps"]), 16)
        self.assertTrue(report.within_budget)


class TheP0CoreSurvivesEveryTrimTest(unittest.TestCase):
    def test_goal_page_actions_session_and_verdict_survive(self):
        manager = context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=1024)
        fitted, _ = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=big_packet())
        self.assertEqual(fitted["goal"], "DAILY_ROUTINE")
        self.assertEqual(fitted["current_page"], "UNKNOWN::欢迎回来")
        self.assertIn("screenshot", fitted)
        self.assertTrue(fitted["available_actions"])
        self.assertIn("session", fitted)
        self.assertIn("last_verifier_outcome", fitted)

    def test_the_element_table_never_goes_below_its_floor(self):
        manager = context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=1024)
        fitted, report = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=big_packet())
        self.assertGreaterEqual(len(fitted["available_elements"]), context_budget.ELEMENT_FLOOR)
        self.assertGreaterEqual(report.elements_kept, context_budget.ELEMENT_FLOOR)

    def test_a_smaller_table_than_the_floor_is_not_invented(self):
        packet = big_packet()
        packet["available_elements"] = elements(4)
        manager = context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=1024)
        fitted, _ = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=packet)
        self.assertEqual(len(fitted["available_elements"]), 4)


class ThePacketSaysWhetherItWasTrimmedTest(unittest.TestCase):
    def test_the_context_block_compares_shown_against_available(self):
        manager = context_budget.ContextBudgetManager(max_model_context=4096, output_reserve=1024)
        fitted, _ = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=big_packet())
        block = fitted["context"]
        self.assertEqual(block["max_context"], 4096)
        self.assertEqual(block["steps_available"], 16)
        self.assertLess(block["steps_shown"], block["steps_available"])
        # 40 elements were handed to ``build_packet``; the packet-level cap is
        # ``ELEMENT_TARGET``, so *that* is what the manager was given and the number it reports.
        self.assertEqual(block["elements_available"], context_budget.ELEMENT_TARGET)

    def test_an_untouched_packet_still_reports_its_own_sizes(self):
        manager = context_budget.ContextBudgetManager()
        fitted, _ = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=big_packet())
        self.assertEqual(fitted["context"]["steps_shown"], 16)
        self.assertEqual(fitted["context"]["elements_shown"], context_budget.ELEMENT_TARGET)


class APacketThatCannotFitIsSaidSoTest(unittest.TestCase):
    def test_within_budget_is_false_rather_than_a_truncated_prompt(self):
        # A window this small cannot hold the system prompt plus the P0 core, and the honest
        # answer is a refusal the caller turns into LOCAL_GUI_MODEL_INPUT_OVER_BUDGET -- not a
        # prompt the server would truncate at the oldest end, where the frame lives.
        manager = context_budget.ContextBudgetManager(max_model_context=2000, output_reserve=500)
        _, report = manager.fit(system=ui_planner.SYSTEM_PROMPT, packet=big_packet())
        self.assertFalse(report.within_budget)
        self.assertLess(report.headroom, 0)


class TheEstimatorIsCheckedAgainstTheServerTest(unittest.TestCase):
    def test_totals_keep_the_estimate_beside_the_measurement(self):
        totals = context_budget.BudgetTotals()
        totals.add(actual=1200, estimated=1500)
        totals.add(actual=1400, estimated=1600)
        summary = totals.summary()
        self.assertEqual(summary["n"], 2)
        self.assertEqual(summary["max"], 1400)
        self.assertEqual(summary["p50"], 1300)
        self.assertGreater(summary["estimate_ratio_p50"], 0)

    def test_a_server_that_reported_no_usage_is_not_counted_as_zero_input(self):
        totals = context_budget.BudgetTotals()
        totals.add(actual=0, estimated=1500)
        self.assertEqual(totals.summary()["n"], 0)


class FromConfigTest(unittest.TestCase):
    def test_a_disabled_planner_builds_no_budget_machinery(self):
        self.assertIsNone(context_budget.from_config({"local_planner": {"enabled": False}}))

    def test_no_config_at_all_is_not_an_error(self):
        self.assertIsNone(context_budget.from_config(None))
        self.assertIsNone(context_budget.from_config({}))

    def test_the_section_decides_the_window(self):
        manager = context_budget.from_config({"local_planner": {"enabled": True,
                                                               "context": 32768,
                                                               "output_reserve": 4096,
                                                               "history_steps": 16}})
        self.assertIsNotNone(manager)
        assert manager is not None
        self.assertEqual(manager.max_input_budget, 28672)
        self.assertEqual(manager.history_target, 16)

    def test_the_shipped_config_is_the_production_window(self):
        config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        manager = context_budget.from_config(config)
        self.assertIsNotNone(manager)
        assert manager is not None
        self.assertEqual(manager.max_model_context, 32768)
        self.assertEqual(manager.max_input_budget, 28672)


if __name__ == "__main__":
    unittest.main()
