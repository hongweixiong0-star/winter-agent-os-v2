"""The structured-UI-action protocol, and the refusals it owes the game.

Operator directive 2026-09-25 sections 4–8.  The properties a test can hold, as opposed to the
ones only a live client can:

* the packet is bounded and carries no geometry, so there is nothing for the model to transport;
* a reply naming a coordinate is refused **by name**, and a reply naming an element this screen
  does not have is refused with its own reason;
* ``EXECUTE`` with an element id becomes an ``Advice`` whose anchor is that element's own
  printed text -- which is what lets the existing ``grounded_region`` produce the point from the
  current frame, i.e. the model never supplies a position;
* every non-executing decision (``OBSERVE``/``REPLAN``/``COMPLETE``/``DEFER``/``BLOCKED``) taps
  nothing, and ``COMPLETE`` is filed as an unverified *claim*;
* budgets are bounded, so a screen cannot consume a run.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import ui_planner  # noqa: E402
from winter_agent_v2 import unknown_advisor  # noqa: E402

ELEMENTS = [
    {"id": "E1", "text": "领取", "area": "middle"},
    {"id": "E2", "text": "关闭", "area": "top"},
    {"id": "E3", "text": "确定", "area": "bottom"},
]


def reply(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def execute(target: str = "E1", action: str = "CLICK_ELEMENT", **extra) -> str:
    payload = {
        "goal": "DAILY_ROUTINE",
        "decision": "EXECUTE",
        "action": {"type": action, "target_element_id": target},
        "expected": {"page": "POPUP"},
        "reason": "点击领取",
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class GeometryIsRefusedTest(unittest.TestCase):
    def test_a_reply_carrying_a_point_is_refused_by_name(self):
        parsed = ui_planner.parse_plan(execute(x=340, y=812), elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TRANSPORTED_GEOMETRY", parsed.error)
        self.assertIn("x", parsed.error)

    def test_a_nested_point_is_found_too(self):
        raw = reply(goal="G", decision="EXECUTE",
                    action={"type": "CLICK_ELEMENT", "target_element_id": "E1",
                            "box": {"x_norm": 0.4, "y_norm": 0.7}},
                    expected={"page": "P"}, reason="r")
        parsed = ui_planner.parse_plan(raw, elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TRANSPORTED_GEOMETRY", parsed.error)

    def test_the_packet_shows_no_coordinates_at_all(self):
        packet = ui_planner.build_packet(
            goal="DAILY_ROUTINE", current_page="UNKNOWN::挂机收益", elements=ELEMENTS,
            world_state={"page": "UNKNOWN", "confidence": 0.2, "resources": {"meat": 10}},
        )
        body = json.dumps(packet, ensure_ascii=False)
        for token in ('"x"', '"y"', "x_norm", "y_norm", "box", "point"):
            self.assertNotIn(token, body, token)
        self.assertEqual(packet["available_actions"], list(ui_planner.OFFERED_ACTIONS))


class OnlyWhatWasOfferedTest(unittest.TestCase):
    def test_an_element_this_screen_does_not_have_is_refused(self):
        parsed = ui_planner.parse_plan(execute(target="E9"), elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_TARGET_NOT_ON_THIS_SCREEN", parsed.error)

    def test_an_action_outside_the_offered_set_is_refused(self):
        parsed = ui_planner.parse_plan(execute(action="BACK"), elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_ACTION_NOT_OFFERED", parsed.error)

    def test_input_text_is_refused_as_an_unimplemented_capability(self):
        """Named, not silently dropped: there is no text-entry path in this project yet."""
        parsed = ui_planner.parse_plan(execute(action="INPUT_TEXT"), elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.error, "UI_ACTION_INPUT_TEXT_NOT_IMPLEMENTED")

    def test_an_unknown_decision_is_refused(self):
        raw = reply(goal="G", decision="MAYBE", reason="r")
        parsed = ui_planner.parse_plan(raw, elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_DECISION_UNKNOWN", parsed.error)

    def test_a_non_json_reply_is_refused(self):
        parsed = ui_planner.parse_plan("I would tap the 领取 button.", elements=ELEMENTS)
        self.assertFalse(parsed.ok)
        self.assertIn("PLAN_NOT_JSON", parsed.error)

    def test_prose_wrapped_json_is_still_refused_rather_than_guessed_at(self):
        parsed = ui_planner.parse_plan("Here you go:\n" + execute(), elements=ELEMENTS)
        self.assertFalse(parsed.ok)


class DecisionVocabularyTest(unittest.TestCase):
    def test_the_six_decisions_are_exactly_the_directive_s_vocabulary(self):
        self.assertEqual(
            ui_planner.DECISIONS,
            ("EXECUTE", "OBSERVE", "REPLAN", "COMPLETE", "DEFER", "BLOCKED"),
        )

    def test_every_non_executing_decision_parses_without_an_action(self):
        for decision in ui_planner.NON_TAPPING_DECISIONS:
            parsed = ui_planner.parse_plan(
                reply(goal="G", decision=decision, reason="because"), elements=ELEMENTS
            )
            self.assertTrue(parsed.ok, decision)
            assert parsed.plan is not None
            self.assertEqual(parsed.plan.decision, decision)
            self.assertEqual(parsed.plan.target_element_id, "")

    def test_execute_without_an_action_is_refused(self):
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE", reason="r"), elements=ELEMENTS
        )
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.error, "PLAN_EXECUTE_WITHOUT_ACTION")


class PlanBecomesTheExistingAdviceTest(unittest.TestCase):
    """No second protocol: the plan is translated into ``unknown_advisor.Advice``."""

    def _advisor(self, tmp: Path) -> ui_planner.ManagedAdvisor:
        client = _StubClient(execute())
        return ui_planner.ManagedAdvisor(
            client=client,
            ledger=ui_planner.PlannerLedger(tmp / "steps.jsonl"),
            root=tmp,
        )

    def test_an_execute_plan_yields_an_ordinary_control_advice_anchored_on_its_own_text(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            advisor = self._advisor(Path(tmp))
            request = _request()
            advice = advisor.take_request(request)
            self.assertIsInstance(advice, unknown_advisor.Advice)
            assert advice is not None
            self.assertEqual(advice.action_kind, unknown_advisor.ACTION_ORDINARY)
            self.assertEqual(advice.proposed_action, "领取")
            # The anchor is the client's own words -- so the point is produced later, from the
            # frame, by the existing grounded_region.  No geometry passed through the model.
            self.assertEqual(advice.target_anchor, {"text": "领取"})
            self.assertEqual(advice.source, ui_planner.SOURCE_LOCAL_QWEN)

    def test_a_non_executing_decision_taps_nothing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            advisor = ui_planner.ManagedAdvisor(
                client=_StubClient(reply(goal="G", decision="DEFER", reason="not now")),
                ledger=ui_planner.PlannerLedger(Path(tmp) / "steps.jsonl"),
                root=Path(tmp),
            )
            self.assertIsNone(advisor.take_request(_request()))

    def test_complete_is_recorded_as_an_unverified_claim(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ledger = ui_planner.PlannerLedger(Path(tmp) / "steps.jsonl")
            advisor = ui_planner.ManagedAdvisor(
                client=_StubClient(reply(goal="G", decision="COMPLETE", reason="looks done")),
                ledger=ledger, root=Path(tmp),
            )
            advisor.take_request(_request())
            rows = [json.loads(line) for line in
                    (Path(tmp) / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
            claims = [row for row in rows if row.get("decision") == "COMPLETE_CLAIM"]
            self.assertEqual(len(claims), 1)
            self.assertFalse(claims[0]["verified"])

    def test_a_model_that_is_down_leaves_the_cycle_without_an_answer(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            advisor = ui_planner.ManagedAdvisor(
                client=_StubClient("", ok=False, error="LOCAL_QWEN_UNREACHABLE"),
                ledger=ui_planner.PlannerLedger(Path(tmp) / "steps.jsonl"),
                root=Path(tmp),
            )
            self.assertIsNone(advisor.take_request(_request()))
            self.assertIn("UNREACHABLE", advisor.last_outcome.get("error", ""))

    def test_a_refusal_is_filed_with_its_own_reason(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            advisor = ui_planner.ManagedAdvisor(
                client=_StubClient(execute(x=1, y=2)),
                ledger=ui_planner.PlannerLedger(Path(tmp) / "steps.jsonl"),
                root=Path(tmp),
            )
            self.assertIsNone(advisor.take_request(_request()))
            self.assertIn("PLAN_TRANSPORTED_GEOMETRY", advisor.last_outcome.get("error", ""))


class BudgetsAreBoundedTest(unittest.TestCase):
    def test_a_screen_cannot_consume_the_whole_run(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = _StubClient(execute())
            advisor = ui_planner.ManagedAdvisor(
                client=client,
                ledger=ui_planner.PlannerLedger(Path(tmp) / "steps.jsonl"),
                root=Path(tmp), max_steps_per_screen=1, max_steps_per_run=5,
            )
            self.assertIsNotNone(advisor.take_request(_request()))
            before = client.calls
            advisor.take_request(_request())
            self.assertEqual(client.calls, before, "the screen budget must stop the second call")

    def test_the_run_budget_stops_the_calls(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = _StubClient(execute())
            advisor = ui_planner.ManagedAdvisor(
                client=client,
                ledger=ui_planner.PlannerLedger(Path(tmp) / "steps.jsonl"),
                root=Path(tmp), max_steps_per_screen=9, max_steps_per_run=1,
            )
            advisor.take_request(_request())
            before = client.calls
            advisor._requests.clear()
            advisor.take_request(_request(page_key="OTHER::屏幕"))
            self.assertEqual(client.calls, before)


class ElementsComeFromTheQuestionItselfTest(unittest.TestCase):
    def test_elements_are_the_questions_own_recorded_ocr(self):
        request = _request()
        elements = ui_planner.elements_from_request(request)
        self.assertEqual([e["text"] for e in elements], ["领取", "关闭"])
        self.assertEqual([e["id"] for e in elements], ["E1", "E2"])

    def test_a_repeated_word_is_offered_once(self):
        request = unknown_advisor.UnknownRequest(
            request_id="r", unknown_type=unknown_advisor.UNKNOWN_CONTROL,
            page_label="UNKNOWN", page_key="UNKNOWN::x",
            ocr_texts=("确定", "确定", "取消"),
        )
        elements = ui_planner.elements_from_request(request)
        self.assertEqual([e["text"] for e in elements], ["确定", "取消"])


# ---------------------------------------------------------------------------- stubs
def _request(page_key: str = "UNKNOWN::挂机收益"):
    return unknown_advisor.UnknownRequest(
        request_id=f"unknown__control__{abs(hash(page_key)) % 10**8}",
        unknown_type=unknown_advisor.UNKNOWN_CONTROL,
        page_label="UNKNOWN", page_key=page_key, goal="DAILY_ROUTINE",
        ocr_texts=("领取", "关闭"),
        ocr_boxes=({"x_norm": 0.3, "y_norm": 0.45, "w_norm": 0.2, "h_norm": 0.06},
                   {"x_norm": 0.9, "y_norm": 0.03, "w_norm": 0.05, "h_norm": 0.04}),
    )


class _StubClient:
    """Stands in for ``local_qwen.LocalQwen`` so no test needs the model to exist."""

    def __init__(self, text: str, *, ok: bool = True, error: str = "") -> None:
        self.model = "stub-local-tag"
        self.endpoint = "http://127.0.0.1:0"
        self.text = text
        self.ok = ok
        self.error = error
        self.calls = 0
        self.prompts: list[str] = []

    def available(self, *, force: bool = False):
        return (self.ok, "stub")

    def ask_json(self, *, system: str, user: str, purpose: str = "", element_count: int = 0,
                 timeout_s=None):
        from winter_agent_v2 import local_qwen

        self.calls += 1
        self.prompts.append(user)
        return local_qwen.QwenCall(
            ok=self.ok, text=self.text, error=self.error, model=self.model,
            latency_ms=1.0, prompt_chars=len(user),
        )


class TheRuntimeTakesTheAdvisorWithoutLearningWhatItIsTest(unittest.TestCase):
    """The injection point, pinned where it actually broke.

    The first version of this added ``advisor=None`` to ``__init__`` and then set
    ``self._advisor = advisor or UnknownAdvisor()`` -- but ``self._advisor`` is assigned inside
    ``run()``, not ``__init__``, so the parameter was not in scope there and **every run** raised
    ``NameError``.  ``tools/check_wiring.py`` cannot see it (it never calls ``run``); the
    neighbourhood tests that do call it can, which is why they are the regression set for anything
    touching the runtime's entry point.

    Behavioural coverage of ``run()`` lives in ``tests/test_refusal_yields_the_cycle.py``.  These
    are the cheap structural assertions that catch the same scope mistake immediately.
    """

    def _runtime(self, **kwargs):
        from types import SimpleNamespace

        from winter_agent_v2.runtime import LiveRuntime

        return LiveRuntime(
            device=SimpleNamespace(), vision=None, semantic_vision=SimpleNamespace(),
            capture_dir=ROOT / "learning" / "_tmp_runtime_advisor", **kwargs
        )

    def test_the_factory_is_stored_under_its_own_name(self):
        def factory():
            return "an advisor"

        runtime = self._runtime(advisor=factory)
        self.assertIs(runtime._advisor_factory, factory)

    def test_an_instance_is_accepted_too(self):
        runtime = self._runtime(advisor="an advisor")
        self.assertEqual(runtime._advisor_factory, "an advisor")

    def test_the_default_is_the_pre_existing_reader(self):
        runtime = self._runtime()
        self.assertIsNone(runtime._advisor_factory)

    def test_run_builds_the_advisor_from_the_factory(self):
        source = (ROOT / "winter_agent_v2" / "runtime.py").read_text(encoding="utf-8")
        # The exact line that raised NameError.  It must not come back: a bare ``advisor``
        # identifier is only valid where the parameter exists, which is ``__init__``.
        self.assertNotIn("self._advisor = advisor or", source)
        self.assertIn("_advisor_factory", source)
        self.assertIn("self._advisor = factory()", source)


if __name__ == "__main__":
    unittest.main()
