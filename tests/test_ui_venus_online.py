"""ONLINE_UNKNOWN: the packet, the answer, and the chain the answer must survive.

Operator directive 2026-10-01, sections 4-13 and 28.  Each test names the section it is about,
because the value of this file is being able to answer "is section 8 actually enforced" by reading
one test rather than by re-reading the module.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import ui_venus_contract as c
from winter_agent_v2 import ui_venus_online as O


def _elements() -> O.ElementTable:
    return O.ElementTable(
        frame_id="f1", frame_hash="sha256:aa",
        items=(
            O.ElementItem("E1", "INFANTRY_ROW", "盾兵", "COMPOSITE_CONTROL", True, "middle"),
            O.ElementItem("E2", "LANCER_ROW", "矛兵", "COMPOSITE_CONTROL", True, "middle"),
            O.ElementItem("E3", "TITLE", "训练营", "TEXT_LABEL", False, "top"),
        ),
    )


def _empty_elements() -> O.ElementTable:
    return O.ElementTable(frame_id="f1", frame_hash="sha256:aa", items=())


def _packet(elements: O.ElementTable | None = None, **overrides) -> O.UIVenusContextPacketV1:
    base = dict(
        identity=O.Identity("role_01", "s1", "COLLECT_TRAINING", "TRAINING", "TRAINING"),
        frame=O.FrameRef("f1", "2026-10-01T00:00:00Z", "sha256:aa"),
        world=O.WorldRef("PAGE_TRAINING", 0.96),
        session=O.SessionRef("s1", "RUNNING", 3, 2, 1, 2, None),
        elements=elements if elements is not None else _elements(),
        allowed_actions=("CLICK_ELEMENT", "SCROLL", "BACK", "OBSERVE"),
    )
    base.update(overrides)
    return O.UIVenusContextPacketV1(**base)


def _reply(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def _execute(target: str = "E2", **extra) -> str:
    payload = {
        "decision": "EXECUTE", "action_type": "CLICK_ELEMENT", "target_element_id": target,
        "semantic_target": "", "candidate_bbox_norm": None, "expected_page": "PAGE_TRAINING",
        "expected_result": "TRAINING_MENU_OPEN", "confidence": 0.91, "reason": "当前帧可执行控件。",
    }
    payload.update(extra)
    return _reply(**payload)


class PacketShapeTests(unittest.TestCase):
    def test_the_packet_wire_shape_is_section_4s(self):
        packet = _packet()
        wire = packet.as_wire()
        for key in ("mode", "identity", "frame", "world", "session", "allowed_actions",
                    "elements", "last_feedback", "recent_history", "relevant_knowledge",
                    "failure_context", "risk", "context_budget", "optional_visual_history"):
            self.assertIn(key, wire, key)
        self.assertEqual(wire["mode"], c.MODE_ONLINE)
        self.assertEqual(wire["identity"]["goal_id"], "COLLECT_TRAINING")
        self.assertEqual(wire["frame"]["frame_id"], "f1")
        self.assertEqual(wire["world"]["page"], "PAGE_TRAINING")
        self.assertEqual(wire["context_budget"]["max_context_tokens"], c.MAX_MODEL_CONTEXT)
        self.assertEqual(wire["context_budget"]["output_reserve_tokens"], c.OUTPUT_RESERVE)

    def test_the_element_table_carries_its_own_frame_identity(self):
        """Section 5's check needs both halves, so the table must state which frame it belongs to."""
        wire = _packet().as_wire()
        self.assertEqual(wire["elements"]["frame_id"], "f1")
        self.assertEqual(wire["elements"]["frame_hash"], "sha256:aa")

    def test_a_renderable_packet_is_json(self):
        rendered = _packet().render()
        self.assertIn("This screen's packet", rendered)
        self.assertIn("领取", rendered.replace("盾兵", "领取"), "the client's own text travels")

    def test_an_empty_allowed_action_set_is_refused(self):
        verdict = _packet(allowed_actions=()).validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_SCHEMA_INVALID)

    def test_the_missing_required_fields_are_reported_not_raised(self):
        packet = O.UIVenusContextPacketV1()
        self.assertIn("frame_id", packet.missing_required())
        self.assertIn("goal_id", packet.missing_required())

    def test_a_stale_element_table_is_discarded_by_the_packet_itself(self):
        """Section 5: screenshot and element table of two different frames must never be decided on."""
        packet = _packet(elements=O.ElementTable("f2", "sha256:bb", ()))
        verdict = packet.validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.CONTEXT_FRAME_MISMATCH)

    def test_the_box_is_offered_only_when_no_reliable_element_exists(self):
        """Section 8/9: asking for a region on a screen full of controls is tokens nobody reads."""
        self.assertFalse(_packet().needs_box)
        self.assertTrue(_packet(elements=_empty_elements()).needs_box)

    def test_plain_ocr_text_does_not_count_as_a_reliable_element(self):
        """The distinction that keeps visually-grounded steps possible at all.

        A line of text the frame printed is offerable but not *identified*, so its presence must not
        make the model's box illegal -- which is what ``reliable`` (section 8) and ``pressable``
        (the planner's rule) exist as two properties to express.
        """
        plain = O.ElementItem("E1", text="挂机收益")
        self.assertTrue(plain.pressable, "a reply may still name it")
        self.assertFalse(plain.reliable, "but it is not a control the frame identified")
        self.assertTrue(_packet(elements=O.ElementTable(
            "f1", "sha256:aa", (plain,))).needs_box)

    def test_an_unmeasured_pressability_is_not_the_same_as_a_refusal(self):
        """Tri-state: ``None`` must not be written to the wire as ``False``."""
        self.assertIsNone(O.ElementItem("E1").as_wire()["executable"])
        self.assertTrue(O.ElementItem("E1").pressable)
        self.assertFalse(O.ElementItem("E1", executable=False).pressable)


class ParsingTests(unittest.TestCase):
    def test_a_contract_shaped_reply_parses(self):
        parsed = O.parse_action(_execute(), elements=_elements())
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.action is not None
        self.assertEqual(parsed.action.target_element_id, "E2")
        self.assertEqual(parsed.action.basis, "FRAME_ELEMENT")

    def test_the_nested_planner_shape_still_parses(self):
        """One protocol, two spellings; the nested one is what the deployed server is asked for."""
        parsed = O.parse_action(json.dumps({
            "decision": "EXECUTE", "action": {"type": "CLICK_ELEMENT", "target_element_id": "E1"},
            "expected": {"page": "POPUP", "result": "CLAIMED"}, "reason": "点领取",
        }, ensure_ascii=False), elements=_elements())
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.action is not None
        self.assertEqual(parsed.action.action_type, "CLICK_ELEMENT")
        self.assertEqual(parsed.action.target_element_id, "E1")
        self.assertEqual(parsed.action.expected_result, "CLAIMED")

    def test_a_reply_that_is_not_json_is_named(self):
        """The code is the name; the JSON error that follows it is the diagnostic.

        Asserted as a prefix rather than by equality because the reader attaches *which* parse error
        it hit -- the same way ``PLAN_DECISION_UNKNOWN`` carries the offending word -- and
        ``canonical_code`` folds the detail away for counting.
        """
        error = O.parse_action("hello", elements=_elements()).error
        self.assertTrue(error.startswith(c.PLAN_NOT_JSON), error)
        self.assertEqual(c.canonical_code(error), c.PLAN_NOT_JSON)

    def test_a_json_array_is_not_an_object(self):
        self.assertEqual(O.parse_action("[1,2]", elements=_elements()).error, c.PLAN_NOT_AN_OBJECT)

    def test_an_unknown_decision_is_refused(self):
        error = O.parse_action(_reply(decision="DO_IT", reason="x"), elements=_elements()).error
        self.assertTrue(error.startswith(c.PLAN_DECISION_UNKNOWN), error)

    def test_a_reply_that_transports_a_pixel_is_refused_by_name(self):
        """The element path's whole guarantee: a model that answers with a pixel is refused."""
        error = O.parse_action(
            _reply(decision="EXECUTE", action_type="CLICK_ELEMENT", x=340, y=812, reason="点这里"),
            elements=_elements()).error
        self.assertTrue(error.startswith(c.PLAN_GEOMETRY_TRANSPORTED), error)

    def test_a_paragraph_reason_is_refused(self):
        error = O.parse_action(
            _reply(decision="OBSERVE", action_type="OBSERVE", reason="因为信息不足。" * 10),
            elements=_elements()).error
        self.assertEqual(error, c.PLAN_REASON_TOO_LONG)

    def test_a_non_execute_step_carries_no_basis(self):
        """Stamping FRAME_ELEMENT on an OBSERVE would read as if a frame had justified something."""
        parsed = O.parse_action(
            _reply(decision="OBSERVE", action_type="OBSERVE", reason="看不清"), elements=_elements())
        assert parsed.action is not None
        self.assertEqual(parsed.action.basis, "")
        self.assertFalse(parsed.action.taps)


class ValidatorTests(unittest.TestCase):
    def _validated(self, raw: str, packet: O.UIVenusContextPacketV1 | None = None, **kwargs):
        packet = packet if packet is not None else _packet()
        parsed = O.parse_action(raw, elements=packet.elements)
        assert parsed.action is not None, parsed.error
        return O.validate_action(parsed.action, packet=packet, **kwargs)

    def test_a_good_action_is_admitted(self):
        verdict = self._validated(_execute())
        self.assertTrue(verdict.ok, verdict.as_row())
        self.assertEqual(verdict.code, "")

    def test_an_element_this_frame_does_not_have_is_refused(self):
        """Section 13's PLAN_TARGET_NOT_ON_THIS_FRAME."""
        verdict = self._validated(_execute(target="E99"))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_TARGET_NOT_ON_THIS_FRAME)
        self.assertEqual(verdict.stage, "ELEMENT_EXISTENCE")

    def test_a_text_label_is_not_a_control(self):
        verdict = self._validated(_execute(target="E3"))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_TARGET_IS_NOT_A_CONTROL)

    def test_an_action_outside_the_allowed_set_is_refused(self):
        """Section 13's PLAN_ACTION_NOT_ALLOWED, which is *not* the same refusal as an unknown word.

        The distinction is worth a test: ``SCROLL`` is one of the seven action types, so the schema
        stage accepts it, and only the offered set can refuse it.  A packet that offered everything
        would make this checkpoint unobservable.
        """
        offered = _packet(allowed_actions=("CLICK_ELEMENT",))
        verdict = self._validated(_execute(action_type="SCROLL"), packet=offered)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_ACTION_NOT_ALLOWED)
        self.assertEqual(verdict.stage, "ALLOWED_ACTIONS")

    def test_the_offered_set_does_not_refuse_what_it_offered(self):
        """The other half of the checkpoint: the same reply is admitted when SCROLL was offered."""
        offered = _packet(allowed_actions=("CLICK_ELEMENT", "SCROLL"))
        verdict = self._validated(_execute(action_type="SCROLL"), packet=offered)
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_box_is_unnecessary_when_a_reliable_element_was_offered(self):
        """Section 8: "已经有 E2，模型却绕过 E2 返回裸坐标" is the named refusal."""
        verdict = self._validated(_execute(
            target=None, semantic_target="CLOSE_BUTTON", candidate_bbox_norm=[0.91, 0.02, 0.07, 0.07]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_BBOX_UNNECESSARY)

    def test_a_box_is_allowed_when_the_frame_offered_nothing_reliable(self):
        """Section 9: the screenshot channel stays open, and refusing ``elements == []`` is over."""
        packet = _packet(elements=_empty_elements())
        verdict = self._validated(
            _execute(target=None, semantic_target="UNKNOWN_CLOSE_BUTTON",
                     candidate_bbox_norm=[0.91, 0.02, 0.07, 0.07]),
            packet=packet)
        self.assertTrue(verdict.ok, verdict.as_row())
        self.assertIn("deferred", verdict.detail, "grounding is the runtime's next link")

    def test_a_box_over_nothing_is_refused_when_this_frame_is_available(self):
        """Section 10: UNKNOWN_GROUNDING_FAILED, and the box never reaches the executor."""
        packet = _packet(elements=_empty_elements())
        verdict = self._validated(
            _execute(target=None, semantic_target="X", candidate_bbox_norm=[0.10, 0.10, 0.05, 0.05]),
            packet=packet, ground_regions=[])
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.UNKNOWN_GROUNDING_FAILED)
        self.assertEqual(verdict.stage, "GROUNDING")

    def test_a_box_over_a_real_region_is_grounded_on_the_frames_own_geometry(self):
        packet = _packet(elements=_empty_elements())
        regions = [{"x_norm": 0.90, "y_norm": 0.01, "w_norm": 0.09, "h_norm": 0.09, "text": ""}]
        verdict = self._validated(
            _execute(target=None, semantic_target="X", candidate_bbox_norm=[0.91, 0.02, 0.07, 0.07]),
            packet=packet, ground_regions=regions)
        self.assertTrue(verdict.ok, verdict.as_row())
        self.assertIn(c.CURRENT_FRAME_VERIFIED_REGION, verdict.detail)

    def test_the_proposed_region_is_the_frames_not_the_models(self):
        """Section 6/10: the overlay's text positions are never tap coordinates."""
        region, reason = O.local_ground(
            (0.91, 0.02, 0.07, 0.07),
            regions=[{"x_norm": 0.88, "y_norm": 0.0, "w_norm": 0.12, "h_norm": 0.12, "id": "REAL"}])
        self.assertEqual(reason, "")
        assert region is not None
        self.assertEqual(region["id"], "REAL")
        self.assertEqual(region["x_norm"], 0.88, "the frame's box, not the model's proposal")

    def test_a_region_that_is_only_a_readout_is_refused(self):
        """Section 10's three exclusions: a label, a resource count and HUD text are all *drawn*."""
        for kind in O.READOUT_KINDS:
            region, reason = O.local_ground(
                (0.91, 0.02, 0.07, 0.07),
                regions=[{"x_norm": 0.90, "y_norm": 0.01, "w_norm": 0.09, "h_norm": 0.09,
                          "kind": kind}])
            self.assertIsNone(region, kind)
            self.assertEqual(reason, O.GROUNDING_READOUT_TEXT, kind)

    def test_a_previous_frames_region_cannot_ground_this_step(self):
        """Section 22: a previous frame is reference only, and ``grounding_allowed`` is false."""
        region, reason = O.local_ground(
            (0.91, 0.02, 0.07, 0.07),
            regions=[{"x_norm": 0.90, "y_norm": 0.01, "w_norm": 0.09, "h_norm": 0.09}],
            frame_now=c.FrameIdentity("f2", "sha256:bb"),
            frame_then=c.FrameIdentity("f1", "sha256:aa"))
        self.assertIsNone(region)
        self.assertEqual(reason, O.GROUNDING_STALE_FRAME)
        self.assertFalse(O.VisualHistory(previous_key_frame="f0", purpose="compare").as_wire()
                         ["grounding_allowed"])

    def test_a_frame_that_moved_under_us_is_a_stale_plan(self):
        """Section 13's PLAN_FRAME_STALE: ~6 s of generation against a live game."""
        verdict = self._validated(
            _execute(), frame_now=c.FrameIdentity("f1", "sha256:zz"))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_FRAME_STALE)

    def test_a_goal_switch_is_refused(self):
        """Section 12: the Global Scheduler has already chosen; the model may not choose another."""
        verdict = self._validated(_execute(), claim_goal="KEEP_TRAINING_PRODUCTIVE")
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_GOAL_SCOPE_VIOLATION)

    def test_a_role_switch_is_refused(self):
        """Section 24: runtime state never crosses roles."""
        verdict = self._validated(_execute(), claim_role="role_02")
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_ROLE_SCOPE_VIOLATION)

    def test_the_same_goal_and_role_pass_their_own_checks(self):
        verdict = self._validated(_execute(), claim_goal="COLLECT_TRAINING", claim_role="role_01")
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_spend_is_blocked_by_the_envelope(self):
        """Section 25: the model may not enlarge its own permissions."""
        raw = _execute(target="E1", semantic_target="购买钻石")
        verdict = self._validated(raw)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_SPEND_BLOCKED)
        self.assertEqual(verdict.stage, "RISK_SPEND")

    def test_complete_is_admitted_only_as_a_claim(self):
        """Section 11: COMPLETE "只能转换为 MODEL_COMPLETE_CLAIM"; the Verifier decides."""
        verdict = self._validated(_reply(
            decision="COMPLETE", action_type="OBSERVE", reason="画面显示训练已开始。"))
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.code, c.MODEL_COMPLETE_CLAIM)
        self.assertEqual(verdict.stage, "COMPLETE_CLAIM")

    def test_defer_is_how_a_wrong_page_is_answered(self):
        verdict = self._validated(_reply(
            decision="DEFER", action_type="OBSERVE", reason="当前页面不属于当前 Goal。"))
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.code, "", "a defer is not a claim about the goal")

    def test_an_execute_with_no_target_at_all_is_refused(self):
        verdict = self._validated(_reply(
            decision="EXECUTE", action_type="CLICK_ELEMENT", reason="点它"))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_EXECUTE_WITHOUT_TARGET)

    def test_the_refusal_stages_are_the_directives_stages(self):
        """Every stage the chain can stop at must be one of section 13's nine, in its own words."""
        seen = {
            self._validated(_execute(target="E99")).stage,
            self._validated(_execute(action_type="SCROLL"),
                            packet=_packet(allowed_actions=("CLICK_ELEMENT",))).stage,
            self._validated(_execute(), claim_goal="OTHER").stage,
            self._validated(_execute(), claim_role="role_09").stage,
            self._validated(_execute(target="E1", semantic_target="购买")).stage,
            self._validated(_reply(decision="EXECUTE", action_type="CLICK_ELEMENT", reason="x")).stage,
        }
        for stage in seen:
            self.assertIn(stage, c.VALIDATION_STAGES, stage)
        self.assertNotIn("", seen, "a refusal that stopped nowhere is a refusal nobody can act on")


class FrameGateTests(unittest.TestCase):
    def test_a_proven_mismatch_is_refused(self):
        """"These are two different frames" is decidable and must be refused."""
        verdict = O.frame_gate(c.FrameIdentity("f1", "sha256:aa"), c.FrameIdentity("f1", "sha256:bb"))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.CONTEXT_FRAME_MISMATCH)

    def test_an_unmeasured_pair_is_named_rather_than_silently_passed(self):
        """"Nobody measured it" is not the same fact as "they differ", and the row says which."""
        verdict = O.frame_gate(c.FrameIdentity(), c.FrameIdentity())
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.code, c.PLAN_FRAME_INCOMPLETE)
        self.assertIn("assumed neither", verdict.detail)

    def test_a_matching_pair_is_consistent(self):
        same = c.FrameIdentity("f1", "sha256:aa")
        self.assertEqual(O.frame_gate(same, same).code, "")


class IdentityTests(unittest.TestCase):
    def test_the_identity_is_made_of_the_four_things_section_28_names(self):
        identity = O.unknown_state_identity(
            goal_id="COLLECT_TRAINING", page="PAGE_TRAINING", semantic="CTRL[训练]",
            state_signature="abc123")
        self.assertEqual(identity, "COLLECT_TRAINING|PAGE_TRAINING|CTRL[训练]|abc123")
        for part in ("COLLECT_TRAINING", "PAGE_TRAINING", "CTRL[训练]", "abc123"):
            self.assertIn(part, identity)

    def test_two_different_goals_are_two_different_unknowns(self):
        """Section 28: the same screen for another goal is not the same UNKNOWN."""
        first = O.unknown_state_identity(goal_id="A", page="P", semantic="S", state_signature="h")
        second = O.unknown_state_identity(goal_id="B", page="P", semantic="S", state_signature="h")
        self.assertNotEqual(first, second)

    def test_a_visual_lookalike_does_not_license_the_old_action(self):
        """Section 28: pHash narrows the search; it never decides reuse."""
        self.assertFalse(O.phash_is_sufficient(True))
        self.assertFalse(O.phash_is_sufficient(False))
        self.assertEqual(O.IDENTITY_PARTS, ("goal_id", "page", "semantic", "state_signature"))


class SchemaTests(unittest.TestCase):
    def test_the_schema_is_section_7s_shape(self):
        schema = O.action_schema(needs_box=True)
        self.assertEqual(set(schema["properties"]),
                         {"decision", "action_type", "target_element_id", "semantic_target",
                          "expected_page", "expected_result", "confidence", "reason",
                          c.VISION_BOX_KEY})
        self.assertEqual(schema["properties"]["decision"]["enum"], list(c.DECISIONS))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["reason"]["maxLength"], c.REASON_MAX_CHARS)

    def test_the_box_is_omitted_when_the_frame_cannot_use_one(self):
        self.assertNotIn(c.VISION_BOX_KEY, O.action_schema(needs_box=False)["properties"])

    def test_the_action_vocabulary_is_the_directives_seven(self):
        self.assertEqual(set(O.action_schema()["properties"]["action_type"]["enum"]),
                         set(c.ACTION_TYPES))
        self.assertEqual(len(c.ACTION_TYPES), 7)

    def test_the_planners_projection_describes_the_same_protocol(self):
        """``ui_planner.response_schema`` is a token-budgeted projection of this one.

        Asserted rather than assumed: two schemas that describe different protocols would be a
        model trained on one and validated against the other, and the disagreement would only show
        up as a live refusal nobody could explain.
        """
        from winter_agent_v2 import ui_planner

        projected = ui_planner.response_schema(needs_box=True)
        contract = O.action_schema(needs_box=True)
        # Every field the projection asks for is a field this contract defines (the projection
        # nests `action`/`expected`, both of which the tolerant reader above accepts).
        for key in projected["properties"]:
            if key in ("action", "expected"):
                continue
            self.assertIn(key, contract["properties"], key)
        self.assertEqual(projected["properties"]["decision"]["enum"], list(c.DECISIONS))

    def test_the_prompt_states_the_rules_the_validator_enforces(self):
        """A rule enforced but never stated is a model failing for a reason nobody told it."""
        for phrase in ("Do not select another goal", "Never invent elements",
                       "Never use old coordinates", "return OBSERVE", "return DEFER",
                       "return BLOCKED", "COMPLETE is only a claim", "The Verifier decides",
                       "JSON only"):
            self.assertIn(phrase, O.SYSTEM_PROMPT, phrase)


class LedgerTests(unittest.TestCase):
    def test_an_admitted_action_is_recorded_with_its_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = O.OnlineLedger(Path(tmp) / "online.jsonl")
            packet = _packet()
            parsed = O.parse_action(_execute(), elements=packet.elements)
            assert parsed.action is not None
            verdict = O.validate_action(parsed.action, packet=packet)
            row = ledger.record_action(parsed.action, verdict=verdict, trace_id="t1",
                                       page_key="UNKNOWN::x", goal_id="COLLECT_TRAINING")
            rows = ledger.rows()
        self.assertTrue(row["admitted"])
        self.assertEqual(rows[0]["trace_id"], "t1")
        self.assertEqual(rows[0]["target_element_id"], "E2")
        self.assertNotIn("x_norm", rows[0], "no coordinate is ever filed")

    def test_a_refusal_is_recorded_too(self):
        """The refusals are the interesting half: they are a finding about the model."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = O.OnlineLedger(Path(tmp) / "online.jsonl")
            ledger.record_refusal(code=c.PLAN_BBOX_UNNECESSARY, stage="ELEMENT_EXISTENCE",
                                  detail="2 reliable elements were offered", trace_id="t2")
            rows = ledger.rows()
        self.assertFalse(rows[0]["admitted"])
        self.assertEqual(rows[0]["verdict"]["code"], c.PLAN_BBOX_UNNECESSARY)
        self.assertEqual(rows[0]["verdict"]["family"], "TARGET")

    def test_refusals_are_counted_by_the_contracts_own_code(self):
        rows = [
            {"admitted": True, "verdict": {"ok": True, "code": ""}},
            {"admitted": False, "verdict": {"ok": False, "code": c.PLAN_BBOX_UNNECESSARY}},
            {"admitted": False, "verdict": {"ok": False, "code": c.PLAN_BBOX_UNNECESSARY}},
            {"admitted": False, "error": "PLAN_TARGET_NOT_ON_THIS_SCREEN: 'E9'"},
        ]
        self.assertEqual(O.count_refusals(rows),
                         {c.PLAN_BBOX_UNNECESSARY: 2, c.PLAN_TARGET_NOT_ON_THIS_FRAME: 1})

    def test_a_rate_with_no_attempts_is_unmeasured_not_zero(self):
        """Section 26: "no attempts" and "all refused" are opposite facts and the same number."""
        self.assertIsNone(O.admitted_rate([]))
        self.assertEqual(O.admitted_rate([{"admitted": True}, {"admitted": False}]), 0.5)
        self.assertEqual(O.admitted_rate([{"admitted": False}]), 0.0)

    def test_the_ledger_path_is_this_modes_own(self):
        self.assertEqual(O.ONLINE_LEDGER_PATH.parts[0], "learning")
        self.assertNotEqual(O.ONLINE_LEDGER_PATH, Path("learning/ui_venus_repair.jsonl"))
        self.assertNotEqual(O.ONLINE_LEDGER_PATH, Path("learning/ui_venus_offline.jsonl"))


if __name__ == "__main__":
    unittest.main()
