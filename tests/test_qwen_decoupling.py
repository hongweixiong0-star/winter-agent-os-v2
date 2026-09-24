"""The local planner is optional, and the decisions stay model-free (operator section 7).

The requirement this file protects, restated for the 2026-09-25 directive: **V2's decision
loop never depends on a model.**  A local Qwen may plan *how* to operate one screen
(``winter_agent_v2/ui_planner.py``, through ``winter_agent_v2/local_qwen.py``), and with that
whole feature switched off every already-rule-based, already-skill-backed, already-LIVE_VERIFIED
capability still runs.

An earlier version of this file asserted something stronger that is now false by design: that
no module in the package may name a model endpoint and nothing may call one.  That was written
when the planner did not exist.  The directive replaces it, so the assertions were rewritten
rather than relaxed -- each one below still fails if the property it names stops holding:

* the **selection** loop (brain, scheduler, skills, verifier) must not import the planner;
* the model endpoint must be reachable from **exactly one** file, so "which model" stays a
  one-file question and a second client cannot appear unnoticed;
* with ``local_planner.enabled=false`` the brain and the registry behave exactly as before;
* a failure of the local model must be a **value**, not an exception (that is what "not a
  dependency" means in practice).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import local_qwen  # noqa: E402
from winter_agent_v2 import ui_planner  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The one file allowed to know where the model lives.
MODEL_CLIENT = "local_qwen.py"

#: The one file allowed to turn a reply into an action.
PLANNER = "ui_planner.py"

#: Tokens that would mean a *second* model client had appeared in the package.
ENDPOINT_TOKENS = (":11434", "openai", "chat.completions", "llm_client", "LLMClient",
                   "requests.post", "httpx", "aiohttp")

#: The decision loop.  None of these may reach a model.
DECISION_LOOP = ("brain.py", "scheduler.py", "skills.py", "verifier.py", "goal_library.py",
                 "executor.py", "executor_router.py", "maa_executor.py")


class OneClientAndNoSecondTest(unittest.TestCase):
    def test_the_model_endpoint_is_reachable_from_exactly_one_module(self):
        offenders: list[str] = []
        for source in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            if source.name == MODEL_CLIENT:
                continue
            text = source.read_text(encoding="utf-8")
            for token in ENDPOINT_TOKENS:
                if token in text:
                    offenders.append(f"{source.name}: {token}")
        self.assertEqual(
            offenders, [],
            "the local model endpoint must stay in winter_agent_v2/local_qwen.py so the "
            "client can be replaced without touching V2: " + ", ".join(offenders),
        )

    def test_only_the_planner_reads_the_client(self):
        callers: list[str] = []
        for source in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            if source.name in (MODEL_CLIENT, PLANNER):
                continue
            if "local_qwen" in source.read_text(encoding="utf-8"):
                callers.append(source.name)
        self.assertEqual(
            callers, [],
            "the planner is the only consumer of the local model: " + ", ".join(callers),
        )

    def test_the_decision_loop_does_not_import_the_planner(self):
        for name in DECISION_LOOP:
            text = (ROOT / "winter_agent_v2" / name).read_text(encoding="utf-8")
            self.assertNotIn("ui_planner", text, name)
            self.assertNotIn("local_qwen", text, name)


class PlannerIsOffByDefaultAndSwitchableTest(unittest.TestCase):
    def test_a_config_without_the_section_builds_no_planner(self):
        self.assertIsNone(local_qwen.from_config({}, root=ROOT))
        self.assertIsNone(ui_planner.from_config({}, root=ROOT))

    def test_enabled_false_builds_no_planner(self):
        config = {"local_planner": {"enabled": False, "model": local_qwen.DEFAULT_MODEL}}
        self.assertIsNone(local_qwen.from_config(config, root=ROOT))
        self.assertIsNone(ui_planner.from_config(config, root=ROOT))

    def test_enabled_true_builds_one_from_the_config_section(self):
        config = {
            "local_planner": {
                "enabled": True, "endpoint": "http://127.0.0.1:9", "model": "some-local-tag",
                "num_ctx": 4096, "max_steps_per_run": 1,
            }
        }
        client = local_qwen.from_config(config, root=ROOT)
        self.assertIsNotNone(client)
        assert client is not None
        self.assertEqual(client.model, "some-local-tag")
        self.assertEqual(client.num_ctx, 4096)

    def test_the_shipped_config_enables_the_planner(self):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        self.assertTrue(config["local_planner"]["enabled"])
        # Section 4: keep the existing 8K context.
        self.assertEqual(int(config["local_planner"]["num_ctx"]), 8192)

    def test_the_shipped_config_retires_the_workbuddy_channel(self):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        self.assertFalse(config["workbuddy_channel"]["enabled"])
        self.assertEqual(config["workbuddy_channel"]["answer_production"], "LOCAL_QWEN")


class RuleBasedBrainStillDecidesTest(unittest.TestCase):
    """The behaviour the operator asked to protect, exercised with no planner configured."""

    def test_the_brain_decides_with_no_planner_configured(self):
        brain = RuleBrain(current_goal="MAIL")
        decision = brain.decide(WorldState(page=Page.HOME, confidence=0.99), v2_registry())
        self.assertTrue(decision.skill)
        self.assertNotEqual(decision.skill, "WAIT")

    def test_a_known_skill_route_is_deterministic(self):
        state = WorldState(page=Page.HOME, confidence=0.99)
        first = RuleBrain(current_goal="MAIL").decide(state, v2_registry()).skill
        second = RuleBrain(current_goal="MAIL").decide(state, v2_registry()).skill
        self.assertEqual(first, second, "the same state must give the same decision")

    def test_the_registry_is_available_with_no_planner(self):
        self.assertTrue(v2_registry().all())

    def test_the_runtime_takes_an_advisor_and_defaults_to_the_old_one(self):
        """Injected like ``maa_adapter``, and ``None`` means "behave as before"."""
        import inspect

        from winter_agent_v2.runtime import LiveRuntime

        params = inspect.signature(LiveRuntime.__init__).parameters
        self.assertIn("advisor", params)
        self.assertIsNone(params["advisor"].default)


class ModelFailureIsAValueNotAnExceptionTest(unittest.TestCase):
    """``ask_json`` must never raise: a stopped server is a result, not a crash."""

    def test_an_unreachable_server_returns_a_failed_call(self):
        client = local_qwen.LocalQwen(
            endpoint="http://127.0.0.1:9",  # discard port: nothing listens
            ledger_path=ROOT / "learning" / "_tmp_planner_call_test.jsonl",
        )
        call = client.ask_json(system="s", user="u", timeout_s=2.0)
        self.assertFalse(call.ok)
        self.assertIn("LOCAL_QWEN", call.error)
        self.assertEqual(call.text, "")

    def test_a_failed_call_is_still_recorded(self):
        ledger = ROOT / "learning" / "_tmp_planner_call_test.jsonl"
        ledger = Path(ledger)
        ledger.unlink(missing_ok=True)
        client = local_qwen.LocalQwen(endpoint="http://127.0.0.1:9", ledger_path=ledger)
        client.ask_json(system="s", user="u", timeout_s=2.0)
        try:
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["ok"])
        finally:
            ledger.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
