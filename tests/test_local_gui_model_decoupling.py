"""The local GUI model is optional, and the decisions stay model-free (operator section 7).

The requirement this file protects, restated for the 2026-09-30 model migration: **V2's
decision loop never depends on a model.**  A local GUI model may plan *how* to operate one
screen (``winter_agent_v2/ui_planner.py``, through ``winter_agent_v2/local_gui_model.py``),
and with that whole feature switched off every already-rule-based, already-skill-backed,
already-LIVE_VERIFIED capability still runs.

This began as ``test_qwen_decoupling.py``.  It was renamed with the model rather than
duplicated: the properties are about *a local model being optional*, not about which one, and
two near-identical files is how a second source of truth starts.

Each assertion below still fails if the property it names stops holding:

* the **selection** loop (brain, scheduler, skills, verifier) must not import the planner;
* the model endpoint must be reachable from **exactly one** file, so "which model" stays a
  one-file question and a second client cannot appear unnoticed;
* with ``local_planner.enabled=false`` the brain and the registry behave exactly as before;
* a failure of the local model must be a **value**, not an exception (that is what "not a
  dependency" means in practice);
* and, new on 2026-09-30, the **screenshot is mandatory**: the one thing this migration exists
  to fix is that the old client sent a goal, a page and an OCR table and no picture.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import local_gui_model  # noqa: E402
from winter_agent_v2 import ui_planner  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: The one file allowed to know where the model lives.
MODEL_CLIENT = "local_gui_model.py"

#: How a module can actually reach the client: an ``import`` statement, in either direction.
#: Prose that merely names the file is not a reference -- see
#: ``test_only_the_planner_reads_the_client`` for the false positive that taught us the
#: difference.
CLIENT_IMPORT = re.compile(
    r"^\s*(?:from\s+[\w.]*\blocal_gui_model\b[\w.]*\s+import\b"
    r"|(?:from\s+[\w.]+\s+)?import\s+[\w.,\s]*\blocal_gui_model\b)",
    re.M,
)

#: The one file allowed to turn a reply into an action.
PLANNER = "ui_planner.py"

#: Tokens that would mean a *second* model client had appeared in the package.  ``:11434`` is
#: the retired Ollama endpoint and ``:18080`` the port this machine's llama-server took; a
#: mention of either outside the client file means something else is talking to a model.
ENDPOINT_TOKENS = (":11434", ":18080", "openai", "chat.completions", "llm_client", "LLMClient",
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
            "the local model endpoint must stay in winter_agent_v2/local_gui_model.py so the "
            "client can be replaced without touching V2: " + ", ".join(offenders),
        )

    def test_only_the_planner_reads_the_client(self):
        """The invariant is "who can *reach* it", so only import statements count.

        This used to be a bare substring search for ``local_gui_model``, and on 2026-09-30 it
        produced its first false positive: ``unknown_advisor.py``'s docstring names the module
        plus the test that pins it -- prose, pointing at the client, not a consumer of it.  A
        scanner that cannot tell an import from a sentence punishes documentation, which is
        exactly backwards.  The check now requires the reference to be an ``import`` statement,
        which is the only way a module can actually reach the code.
        """
        callers: list[str] = []
        for source in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            if source.name in (MODEL_CLIENT, PLANNER):
                continue
            if CLIENT_IMPORT.search(source.read_text(encoding="utf-8")):
                callers.append(source.name)
        self.assertEqual(
            callers, [],
            "the planner is the only consumer of the local model: " + ", ".join(callers),
        )

    def test_a_mention_in_prose_is_not_a_consumer(self):
        """The counter-case, so the scanner above cannot silently go back to substring matching."""
        self.assertIsNotNone(CLIENT_IMPORT.search("from . import local_gui_model\n"))
        self.assertIsNotNone(CLIENT_IMPORT.search("from winter_agent_v2 import local_gui_model\n"))
        self.assertIsNotNone(
            CLIENT_IMPORT.search("from winter_agent_v2.local_gui_model import LocalGUIModel\n"))
        self.assertIsNotNone(CLIENT_IMPORT.search("import local_gui_model\n"))
        for prose in ("``tests/test_local_gui_model_decoupling.py``",
                      "the local_gui_model client is the only one",
                      "see winter_agent_v2/local_gui_model.py"):
            self.assertIsNone(CLIENT_IMPORT.search(prose), prose)

    def test_the_decision_loop_does_not_import_the_planner(self):
        for name in DECISION_LOOP:
            text = (ROOT / "winter_agent_v2" / name).read_text(encoding="utf-8")
            self.assertNotIn("ui_planner", text, name)
            self.assertNotIn("local_gui_model", text, name)

    def test_the_retired_qwen_client_is_gone(self):
        """The migration is only complete if the old module cannot be imported by accident."""
        self.assertFalse(
            (ROOT / "winter_agent_v2" / "local_qwen.py").exists(),
            "local_qwen.py still exists; the model it named is no longer the runtime model",
        )


class PlannerIsOffByDefaultAndSwitchableTest(unittest.TestCase):
    def test_a_config_without_the_section_builds_no_planner(self):
        self.assertIsNone(local_gui_model.from_config({}, root=ROOT))
        self.assertIsNone(ui_planner.from_config({}, root=ROOT))

    def test_enabled_false_builds_no_planner(self):
        config = {"local_planner": {"enabled": False, "model": local_gui_model.DEFAULT_MODEL}}
        self.assertIsNone(local_gui_model.from_config(config, root=ROOT))
        self.assertIsNone(ui_planner.from_config(config, root=ROOT))

    def test_enabled_true_builds_one_from_the_config_section(self):
        config = {
            "local_planner": {
                "enabled": True, "endpoint": "http://127.0.0.1:9", "model": "some-local-tag",
                "context": 4096, "max_steps_per_run": 1,
            }
        }
        client = local_gui_model.from_config(config, root=ROOT)
        self.assertIsNotNone(client)
        assert client is not None
        self.assertEqual(client.model, "some-local-tag")
        self.assertEqual(client.context, 4096)
        self.assertEqual(client.num_ctx, 4096, "num_ctx and context are one quantity")

    def test_the_shipped_config_enables_the_planner(self):
        config = json.loads((ROOT / "config" / "v2.json").read_text(encoding="utf-8"))
        planner = config["local_planner"]
        self.assertTrue(planner["enabled"])
        # The 2026-09-30 window, and read from ``context_budget`` rather than written again: the
        # manager is what reserves the reply space inside this number, so a literal here would be
        # a third copy of a quantity that must be one.
        from winter_agent_v2 import context_budget

        self.assertEqual(int(planner["context"]), context_budget.MAX_MODEL_CONTEXT)
        self.assertEqual(context_budget.MAX_MODEL_CONTEXT, 32768)
        # The two windows this number used to be.  Neither may come back as a production default.
        self.assertNotIn(int(planner["context"]), (8192, 16384))
        self.assertGreaterEqual(int(planner["output_reserve"]), 4096)
        # The 2026-09-30 migration, pinned so a silent revert is a test failure.
        self.assertEqual(planner["provider"], "UI_VENUS")
        self.assertEqual(planner["model"], "UI-Venus-2-9B")
        self.assertEqual(planner["quantization"], "Q4_K_M")
        self.assertTrue(planner["multimodal"])
        # And the model it replaced must not still be named as the deployed one.  Checked on
        # the field that names a model rather than on the whole section, because the section
        # legitimately *mentions* the old tag in its note as the thing it replaced.
        self.assertNotIn("qwen", str(planner["model"]).lower())
        self.assertNotIn("11434", str(planner["endpoint"]))

    def test_the_shipped_config_retires_the_workbuddy_channel(self):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        self.assertFalse(config["workbuddy_channel"]["enabled"])
        self.assertEqual(config["workbuddy_channel"]["answer_production"], "LOCAL_GUI_MODEL")


class MultimodalScreenshotIsMandatoryTest(unittest.TestCase):
    """The P0 this migration exists for, pinned so it cannot regress to a text-only client.

    The old client sent ``goal`` + ``current_page`` + an OCR element table and **no image**, so
    the model answered about a screen it could not see.  Measured 2026-09-30: asked blind it
    invented a "Play for Free" button that does not exist; asked with the frame it read the
    real in-game text.  These tests hold the client to the promise.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gui-model-")
        self.ledger = Path(self._tmp.name) / "calls.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_call_with_no_screenshot_is_refused_by_name(self):
        client = local_gui_model.LocalGUIModel(
            endpoint="http://127.0.0.1:9", ledger_path=self.ledger, multimodal=True)
        call = client.ask_json(system="s", user="u", timeout_s=2.0)
        self.assertFalse(call.ok)
        self.assertEqual(call.error, "LOCAL_GUI_MODEL_NO_SCREENSHOT")
        self.assertFalse(call.image_sent)
        # Refused *before* the network is touched: there is nothing to ask about.
        self.assertEqual(call.latency_ms, 0.0)

    def test_the_frame_is_inlined_and_not_passed_as_a_path(self):
        """A path is not a screenshot.  The bytes must be in the payload, base64-encoded."""
        image = Path(self._tmp.name) / "frame.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pretend-pixels" * 8)
        client = local_gui_model.LocalGUIModel(
            endpoint="http://127.0.0.1:9", ledger_path=self.ledger)
        content = client._user_content("the packet text", image)
        self.assertIsInstance(content, list, "a multimodal turn is a parts list, not a string")
        kinds = [part.get("type") for part in content]
        self.assertEqual(kinds, ["text", "image_url"])
        url = content[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"), url[:40])
        self.assertNotIn(str(image), url, "the path must not travel in place of the bytes")

    def test_a_sent_frame_is_recorded_so_the_claim_is_measurable(self):
        image = Path(self._tmp.name) / "frame.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
        client = local_gui_model.LocalGUIModel(
            endpoint="http://127.0.0.1:9", ledger_path=self.ledger)
        client.ask_json(system="s", user="u", image_path=image, timeout_s=2.0)
        rows = [json.loads(line) for line in self.ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        # The endpoint is a discard port, so the *call* failed -- but the frame was read and
        # is on the record, which is what "SCREENSHOT_INPUT" has to mean to be checkable.
        self.assertGreater(rows[0]["image_bytes"], 0)
        self.assertTrue(rows[0]["image_digest"])

    def test_the_shipped_config_asks_for_multimodal(self):
        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        self.assertTrue(config["local_planner"]["multimodal"])
        planner = ui_planner.from_config(config, root=ROOT)
        assert planner is not None
        self.assertTrue(planner.client.multimodal)


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

    def setUp(self):
        # Not ``ROOT / "learning" / ...``: this file wrote its scratch ledger into the production
        # learning tree, where the manifest classifies it RUNTIME_MUTABLE as ``learning/**/*.jsonl``.
        # ``tests/conftest.py`` refuses that write now (2026-09-30 P0,
        # PRODUCTION_RUNTIME_FILES_TOUCHED_BY_TESTS = 0), and the refusal is how it was found.
        self._tmp = tempfile.TemporaryDirectory(prefix="gui-model-ledger-")
        self.ledger = Path(self._tmp.name) / "planner_call.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_unreachable_server_returns_a_failed_call(self):
        client = local_gui_model.LocalGUIModel(
            endpoint="http://127.0.0.1:9",  # discard port: nothing listens
            ledger_path=self.ledger, multimodal=False,
        )
        call = client.ask_json(system="s", user="u", timeout_s=2.0)
        self.assertFalse(call.ok)
        self.assertIn("LOCAL_GUI_MODEL", call.error)
        self.assertEqual(call.text, "")

    def test_a_failed_call_is_still_recorded(self):
        ledger = self.ledger
        ledger.unlink(missing_ok=True)
        client = local_gui_model.LocalGUIModel(
            endpoint="http://127.0.0.1:9", ledger_path=ledger, multimodal=False)
        client.ask_json(system="s", user="u", timeout_s=2.0)
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])

    def test_a_reasoning_only_reply_is_not_reported_as_empty(self):
        """Measured 2026-09-30: with thinking left on, the model fills reasoning and not content."""
        body = {"choices": [{"finish_reason": "length",
                             "message": {"content": "", "reasoning_content": "thinking..."}}]}
        self.assertEqual(local_gui_model.LocalGUIModel._reply_text(body), "thinking...")

    def test_content_wins_over_reasoning(self):
        body = {"choices": [{"message": {"content": "the answer", "reasoning_content": "t"}}]}
        self.assertEqual(local_gui_model.LocalGUIModel._reply_text(body), "the answer")


if __name__ == "__main__":
    unittest.main()
