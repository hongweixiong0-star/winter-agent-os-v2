"""Qwen is an optional provider, never a runtime dependency (operator section 7).

The requirement: with no LLM enabled at all, every already-rule-based,
already-skill-backed, already-LIVE_VERIFIED capability still runs.  The Qwen code
and its parser stay in the tree for later optional use -- the instruction is to
remove the *hard dependency*, not the code.

Measured 2026-09-17, and the reason this file can be short: there is no LLM client
anywhere on the runtime path.  No ``qwen``/``llm`` module exists in
``winter_agent_v2``, nothing imports one, and ``parse_qwen_decision`` in
``brain.py`` has exactly one caller -- a test.  The live AUTO loop has been running
rule-based the whole time.

So these tests do not "prove decoupling" by exercising a disabled path; they pin
the property that makes the decoupling true, so a future change that quietly
introduces a model dependency fails here instead of in the field at 3am.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain, parse_qwen_decision  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

# Things that would mean a provider had crept onto the runtime path.
PROVIDER_TOKENS = (
    "requests.post", "httpx", "aiohttp", "openai", "ollama", "llama_cpp",
    "transformers", "torch", "llm_client", "LLMClient", "chat.completions",
    ":11434",
)


class NoProviderOnTheRuntimePathTest(unittest.TestCase):
    def test_the_package_has_no_llm_module(self):
        names = {p.name.lower() for p in (ROOT / "winter_agent_v2").glob("*.py")}
        self.assertFalse([n for n in names if "qwen" in n or "llm" in n or "local_model" in n])

    def test_no_runtime_module_calls_a_model_provider(self):
        offenders: list[str] = []
        for source in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            text = source.read_text(encoding="utf-8")
            for token in PROVIDER_TOKENS:
                if token in text:
                    offenders.append(f"{source.name}: {token}")
        self.assertEqual(offenders, [], "a model provider is reachable from the runtime: "
                         + ", ".join(offenders))

    def test_the_decision_loop_module_does_not_import_a_provider(self):
        text = (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8")
        for token in PROVIDER_TOKENS:
            self.assertNotIn(token, text, token)


class RuleBasedBrainStillDecidesTest(unittest.TestCase):
    """The behaviour the operator actually asked to protect."""

    def test_the_brain_decides_with_no_provider_configured(self):
        brain = RuleBrain(current_goal="MAIL")
        decision = brain.decide(WorldState(page=Page.HOME, confidence=0.99), v2_registry())
        self.assertTrue(decision.skill)
        self.assertNotEqual(decision.skill, "WAIT")

    def test_a_known_skill_route_is_deterministic(self):
        brain = RuleBrain(current_goal="MAIL")
        state = WorldState(page=Page.HOME, confidence=0.99)
        first = brain.decide(state, v2_registry()).skill
        second = RuleBrain(current_goal="MAIL").decide(state, v2_registry()).skill
        self.assertEqual(first, second, "the same state must give the same decision")

    def test_the_registry_is_available_with_no_provider(self):
        self.assertTrue(v2_registry().all())


class QwenParserIsKeptButOptionalTest(unittest.TestCase):
    def test_the_parser_is_still_present_for_future_optional_use(self):
        # Section 7 says do not delete the code yet, only the dependency.
        self.assertTrue(callable(parse_qwen_decision))

    def test_nothing_on_the_runtime_path_calls_the_parser(self):
        callers: list[str] = []
        for source in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            if source.name == "brain.py":
                continue  # that is where it is defined
            if "parse_qwen_decision" in source.read_text(encoding="utf-8"):
                callers.append(source.name)
        for source in sorted((ROOT / "tools").glob("*.py")):
            if "parse_qwen_decision" in source.read_text(encoding="utf-8"):
                callers.append(f"tools/{source.name}")
        self.assertEqual(callers, [], "the Qwen parser must not be on the runtime path: "
                         + ", ".join(callers))


class DeadKeyRemovedTest(unittest.TestCase):
    """A config key that implies a dependency must not survive without a consumer."""

    def test_the_qwen_busy_fallback_key_is_gone(self):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        retry = config.get("retry", {})
        self.assertNotIn("qwen_busy_fallback", retry)
        # ...and the removal is explained where a reader would look for it.
        self.assertTrue(any("qwen_busy_fallback" in str(k) for k in retry))
        note = next(str(v) for k, v in retry.items() if "qwen_busy_fallback" in str(k))
        self.assertIn("ZERO consumers", note)

    def test_no_qwen_key_is_left_without_a_consumer(self):
        config_text = (ROOT / "config/v2.json").read_text(encoding="utf-8")
        for key in re.findall(r'"(qwen[a-z_]*)"', config_text):
            self.assertTrue(key.endswith("_removed_2026_09_17"),
                            f"{key} looks like a live Qwen key; either wire it or remove it")


if __name__ == "__main__":
    unittest.main()
