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
import tempfile
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
            self.assertEqual(advice.source, ui_planner.SOURCE_LOCAL_GUI_MODEL)

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
    """Stands in for ``local_gui_model.LocalGUIModel`` so no test needs the model to exist.

    ``image_path`` is accepted and recorded rather than ignored: the planner is required to
    attach the request's own frame, and a stub that swallowed the argument would let that
    requirement regress silently.
    """

    def __init__(self, text: str, *, ok: bool = True, error: str = "") -> None:
        self.model = "stub-local-tag"
        self.provider = "STUB"
        self.quantization = "TEST"
        self.endpoint = "http://127.0.0.1:0"
        self.multimodal = True
        self.text = text
        self.ok = ok
        self.error = error
        self.calls = 0
        self.prompts: list[str] = []
        self.images: list[str | None] = []

    def available(self, *, force: bool = False):
        return (self.ok, "stub")

    def ask_json(self, *, system: str, user: str, purpose: str = "", element_count: int = 0,
                 image_path=None, timeout_s=None):
        from winter_agent_v2 import local_gui_model

        self.calls += 1
        self.prompts.append(user)
        self.images.append(image_path)
        return local_gui_model.GUIModelCall(
            ok=self.ok, text=self.text, error=self.error, model=self.model,
            latency_ms=1.0, prompt_chars=len(user),
            image_sent=bool(image_path), image_bytes=1 if image_path else 0,
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

    def setUp(self):
        # ``capture_dir`` used to be ``ROOT / "learning" / "_tmp_runtime_advisor"`` -- a path inside
        # the production learning tree.  Nothing happened to create it on this code path, so the
        # test passed, but it was a latent production write of exactly the kind the 2026-09-30 P0
        # isolation asks to remove.
        self._tmp = tempfile.TemporaryDirectory(prefix="runtime-advisor-")

    def tearDown(self):
        self._tmp.cleanup()

    def _runtime(self, **kwargs):
        from types import SimpleNamespace

        from winter_agent_v2.runtime import LiveRuntime

        return LiveRuntime(
            device=SimpleNamespace(), vision=None, semantic_vision=SimpleNamespace(),
            capture_dir=Path(self._tmp.name), **kwargs
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


class TheScreenshotChannelIsOpenButTheBoxIsNotTrustedTest(unittest.TestCase):
    """The 2026-09-30 capability, and the fence around it.

    Before this, ``elements == []`` ended the step: with an empty table the model had nothing
    to name, so a screen whose controls print no text was unplannable no matter what it looked
    like.  The migration lets the model point at what it can *see* -- but only as an untrusted
    proposal that the current frame still has to justify.  These tests hold both halves.
    """

    def test_an_empty_element_table_no_longer_ends_the_step(self):
        """The old behaviour, pinned as gone: no elements must not mean no plan."""
        parsed = ui_planner.parse_plan(
            reply(goal="EXPLORATION", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": None},
                  semantic_target="the compass icon", reason="no text on this control"),
            elements=[],
        )
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.plan is not None
        self.assertEqual(parsed.plan.basis, ui_planner.BASIS_VISION_PROPOSAL)
        self.assertEqual(parsed.plan.semantic_target, "the compass icon")

    def test_a_normalised_proposal_is_accepted_and_kept(self):
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": None},
                  semantic_target="close button",
                  candidate_bbox_norm=[0.85, 0.03, 0.1, 0.05],
                  reason="the X at the top right"),
            elements=[],
        )
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.plan is not None
        self.assertEqual(parsed.plan.candidate_bbox_norm, (0.85, 0.03, 0.1, 0.05))

    def test_pixel_coordinates_are_refused_by_the_new_channel_too(self):
        """A pixel is not a normalised fraction, so the old rule survives the new channel."""
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": None},
                  semantic_target="close button",
                  candidate_bbox_norm=[612, 38, 72, 64], reason="top right"),
            elements=[],
        )
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.error, "PLAN_BOX_NOT_NORMALISED")

    def test_a_malformed_box_is_refused_with_its_own_reason(self):
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": None},
                  semantic_target="x", candidate_bbox_norm=[0.1, 0.1, 0.2], reason="r"),
            elements=[],
        )
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.error, "PLAN_BOX_NOT_FOUR_NUMBERS")

    def test_raw_geometry_is_still_refused_even_next_to_the_allowed_key(self):
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": None},
                  semantic_target="x", candidate_bbox_norm=[0.1, 0.1, 0.2, 0.2],
                  point={"x": 340, "y": 812}, reason="r"),
            elements=[],
        )
        self.assertFalse(parsed.ok)
        self.assertTrue(parsed.error.startswith("PLAN_TRANSPORTED_GEOMETRY"), parsed.error)

    def test_a_named_element_that_is_not_on_this_screen_is_still_refused(self):
        """An invented id must not fall through to the screenshot channel either."""
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": "E9"},
                  semantic_target="whatever", reason="r"),
            elements=ELEMENTS,
        )
        self.assertFalse(parsed.ok)
        self.assertTrue(parsed.error.startswith("PLAN_TARGET_NOT_ON_THIS_SCREEN"), parsed.error)

    def test_an_execute_with_neither_element_nor_semantic_target_is_refused(self):
        parsed = ui_planner.parse_plan(
            reply(goal="G", decision="EXECUTE",
                  action={"type": "CLICK_ELEMENT", "target_element_id": None}, reason="r"),
            elements=[],
        )
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.error, "PLAN_EXECUTE_WITHOUT_TARGET")

    def test_the_visual_plan_reaches_the_advice_as_a_bbox_hint(self):
        """It becomes ``target_bbox`` -- which the frame still has to justify before a tap."""
        with tempfile.TemporaryDirectory() as tmp:
            advisor = _advisor_with(
                Path(tmp),
                reply(goal="G", decision="EXECUTE",
                      action={"type": "CLICK_ELEMENT", "target_element_id": None},
                      semantic_target="close button",
                      candidate_bbox_norm=[0.85, 0.03, 0.1, 0.05], reason="the X"),
            )
            advice = advisor.take_request(_request())
            self.assertIsInstance(advice, unknown_advisor.Advice)
            assert advice is not None
            self.assertEqual(advice.target_bbox,
                             {"x_norm": 0.85, "y_norm": 0.03, "w_norm": 0.1, "h_norm": 0.05})
            self.assertIn(ui_planner.BASIS_VISION_PROPOSAL, advice.note)

    def test_the_untrusted_region_is_not_grounded_by_the_frame_that_lacks_it(self):
        """The fence: a proposal over nothing is refused by the EXISTING grounding code."""
        with tempfile.TemporaryDirectory() as tmp:
            advisor = _advisor_with(
                Path(tmp),
                reply(goal="G", decision="EXECUTE",
                      action={"type": "CLICK_ELEMENT", "target_element_id": None},
                      semantic_target="close button",
                      candidate_bbox_norm=[0.85, 0.03, 0.1, 0.05], reason="the X"),
            )
            advice = advisor.take_request(_request())
            assert advice is not None
            # A frame that drew something entirely elsewhere must not justify the proposal.
            elsewhere = [{"box_norm": {"x_norm": 0.05, "y_norm": 0.4,
                                       "w_norm": 0.1, "h_norm": 0.05}, "point": (0.1, 0.42)}]
            self.assertIsNone(unknown_advisor.justified_point(advice, elsewhere))
            # And the same proposal IS grounded when the frame really drew that region.
            here = [{"box_norm": {"x_norm": 0.85, "y_norm": 0.03,
                                  "w_norm": 0.1, "h_norm": 0.05}, "point": (0.9, 0.055)}]
            self.assertIsNotNone(unknown_advisor.justified_point(advice, here))


class TheVerdictIsJoinedBackToTheAnswerTest(unittest.TestCase):
    """An advised step's verdict must be provable from record, not inferred.

    The planner's ledger held the proposal and ``episodes.jsonl`` held the verdict, with nothing
    joining them -- so "the local model acted and the verifier passed" could not be read off the
    artifacts, and the model's own confidence looked the same as a verified step.  Operator
    directive 2026-09-30 is explicit that the model may not certify itself, so the join is made
    at the one place that knows both, and only for the step that consumed the answer.
    """

    @staticmethod
    def _decision(skill: str = "ORDINARY_CONTROL[搜索]"):
        from winter_agent_v2.models import Decision

        return Decision(skill=skill, reason="", confidence=0.0, expected_result="")

    def test_an_outcome_row_settles_the_answer_it_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "steps.jsonl"
            advisor = ui_planner.ManagedAdvisor(
                client=_StubClient("{}"), ledger=ui_planner.PlannerLedger(path), root=Path(tmp),
            )
            advisor.note_outcome("unknown__control__abc", verifier_ok=True,
                                 skill="ORDINARY_CONTROL[搜索]", result="SUCCESS",
                                 evidence={"panel_readable_after": True})
            rows = [json.loads(line) for line in
                    path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 1, rows)
            self.assertEqual(rows[0]["record"], "outcome")
            self.assertEqual(rows[0]["request_id"], "unknown__control__abc")
            self.assertIs(rows[0]["verifier_ok"], True)
            self.assertEqual(rows[0]["skill"], "ORDINARY_CONTROL[搜索]")
            self.assertEqual(rows[0]["source"], ui_planner.SOURCE_LOCAL_GUI_MODEL)

    def test_an_answer_with_no_request_id_settles_nothing(self):
        """A settlement needs something to attach to, so an empty id must not leave a bare row."""
        with tempfile.TemporaryDirectory() as tmp:
            advisor = _advisor_with(Path(tmp), "{}")
            advisor.note_outcome("", verifier_ok=True)
            self.assertFalse((Path(tmp) / "steps.jsonl").exists())

    def test_a_step_the_model_did_not_drive_is_never_settled(self):
        """The safety property in one line: no id, no settlement."""
        from winter_agent_v2.runtime import LiveRuntime

        settled: list[str] = []

        class _Advisor:
            def note_outcome(self, request_id, **kwargs):
                settled.append(request_id)

        runtime = object.__new__(LiveRuntime)
        runtime._advisor = _Advisor()
        runtime._advised_request_id = ""
        runtime._settle_advised_step(self._decision(), None, "SUCCESS")
        self.assertEqual(settled, [])

    def test_the_step_that_consumed_the_answer_is_settled_once_and_cleared(self):
        from winter_agent_v2.runtime import LiveRuntime

        seen: list[tuple[str, dict]] = []

        class _Advisor:
            def note_outcome(self, request_id, **kwargs):
                seen.append((request_id, kwargs))

        class _Verdict:
            ok = True
            evidence = {"page_returned": True}

        runtime = object.__new__(LiveRuntime)
        runtime._advisor = _Advisor()
        runtime._advised_request_id = "unknown__control__zzz"
        runtime._settle_advised_step(self._decision(), _Verdict(), "SUCCESS")
        self.assertEqual([row[0] for row in seen], ["unknown__control__zzz"])
        self.assertIs(seen[0][1]["verifier_ok"], True)
        self.assertEqual(seen[0][1]["evidence"], {"page_returned": True})
        # Consumed, not re-filed: a second call for the same step must settle nothing.
        runtime._settle_advised_step(self._decision(), _Verdict(), "SUCCESS")
        self.assertEqual(len(seen), 1)
        self.assertEqual(runtime._advised_request_id, "")

    def test_a_broken_ledger_cannot_fail_an_issued_action(self):
        """Settlement is bookkeeping; it must never raise into the step that already ran."""
        from winter_agent_v2.runtime import LiveRuntime

        class _Advisor:
            def note_outcome(self, request_id, **kwargs):
                raise OSError("disk full")

        runtime = object.__new__(LiveRuntime)
        runtime._advisor = _Advisor()
        runtime._advised_request_id = "x"
        runtime._settle_advised_step(self._decision(), None, "SUCCESS")
        self.assertEqual(runtime._advised_request_id, "")


def _advisor_with(root: Path, text: str):
    return ui_planner.ManagedAdvisor(
        client=_StubClient(text), ledger=ui_planner.PlannerLedger(root / "steps.jsonl"),
        root=root,
    )


if __name__ == "__main__":
    unittest.main()
