"""SKILL_REPAIR: what a broken skill is told, and the patch it may propose.

Operator directive 2026-10-01, sections 14-15 and 30.  The tests are named after the section they
enforce, because the value of this file is being able to answer "does a repair really refuse to
overwrite a stable skill" by reading one test rather than by re-reading the module.

The three claims this file exists to keep true:

* a repair packet says this skill *used to work* (section 14), so a model is never re-deriving a
  route from a single failing frame;
* a repair is a change to a rule, never to a position, and that is enforced by a closed vocabulary
  plus a named refusal rather than by a prompt sentence (sections 15/30);
* nothing here can promote -- ``may_overwrite_stable`` is a function that always answers ``False``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import ui_venus_contract as c
from winter_agent_v2 import ui_venus_repair as R


def _packet(**overrides) -> R.UIVenusSkillRepairPacketV1:
    base = dict(
        identity=R.RepairIdentity("role_01", "COLLECT_TRAINING", "SKILL_OPEN_TRAINING"),
        frame_id="f1", frame_hash="sha256:aa", page="PAGE_CITY",
        existing_skill=R.ExistingSkill(
            skill_id="SKILL_OPEN_TRAINING", maturity="STABLE",
            semantic_target="训练", expected_result="TRAINING_MENU_OPEN",
            known_visual_rules=("城郊右下角的盾形按钮",),
        ),
        previous_success_evidence=(
            R.SuccessEvidence("ep_001", "PAGE_CITY", "PAGE_TRAINING", "PASS"),
            R.SuccessEvidence("ep_002", "PAGE_CITY", "PAGE_TRAINING", "PASS"),
        ),
        current_failure=R.FailureState(3, "TARGET_NOT_FOUND", "", "same_control_retried"),
        elements={"frame_id": "f1", "items": []},
    )
    base.update(overrides)
    return R.UIVenusSkillRepairPacketV1(**base)


def _reply(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def _proposal(**extra) -> str:
    payload = {
        "analysis_type": R.ANALYSIS_TYPE,
        "skill_id": "SKILL_OPEN_TRAINING",
        "diagnosis": "VISUAL_LAYOUT_DRIFT",
        "semantic_target": "训练营入口",
        "proposed_change": {"type": "VISUAL_RULE", "description": "入口图标改为盾形，位于城郊右侧"},
        "candidate_bbox_norm": None,
        "expected_result": "TRAINING_MENU_OPEN",
        "confidence": 0.8,
        "evidence_refs": ["ep_001", "ep_002"],
        "required_validation": ["REPLAY", "SHADOW", "LIVE_VERIFIER"],
        "reason": "入口位置改变了。",
    }
    payload.update(extra)
    return _reply(**payload)


def _parsed(raw: str, packet: R.UIVenusSkillRepairPacketV1 | None = None):
    return R.parse_repair_candidate(raw, packet=packet if packet is not None else _packet())


def _validated(raw: str, packet: R.UIVenusSkillRepairPacketV1 | None = None, **kwargs):
    packet = packet if packet is not None else _packet()
    parsed = _parsed(raw, packet)
    assert parsed.candidate is not None, parsed.error
    return R.validate_repair_candidate(parsed.candidate, packet=packet, **kwargs)


class PacketShapeTests(unittest.TestCase):
    def test_the_packet_wire_shape_is_section_14s(self):
        wire = _packet().as_wire()
        for key in ("mode", "identity", "current_frame", "current_world", "existing_skill",
                    "previous_success_evidence", "current_failure", "current_elements",
                    "relevant_knowledge", "constraints", "context_budget"):
            self.assertIn(key, wire, key)
        self.assertEqual(wire["mode"], c.MODE_SKILL_REPAIR)
        self.assertEqual(wire["identity"]["skill_id"], "SKILL_OPEN_TRAINING")
        self.assertEqual(wire["context_budget"]["max_context_tokens"], c.MAX_MODEL_CONTEXT)

    def test_the_model_is_told_this_skill_used_to_work(self):
        """Section 14: "必须告诉模型：这是一个以前成功过、现在失效的 Skill".

        Both halves have to be on the wire.  The successes are what make the question "why did this
        stop working" answerable; without them the model would be re-deriving the route from one
        failing frame and could conclude something that contradicts two recorded successes.
        """
        wire = _packet().as_wire()
        self.assertEqual(wire["existing_skill"]["maturity"], "STABLE")
        self.assertEqual(len(wire["previous_success_evidence"]), 2)
        self.assertEqual(wire["previous_success_evidence"][0]["episode_id"], "ep_001")
        self.assertEqual(wire["current_failure"]["consecutive_failures"], 3)
        self.assertEqual(wire["current_failure"]["verifier_reason"], "TARGET_NOT_FOUND")

    def test_the_constraints_are_closed_on_the_wire_whatever_the_object_says(self):
        """Section 14's three false values, and the reason they are written rather than echoed."""
        wire = R.RepairConstraints().as_wire()
        self.assertEqual(wire, {
            "direct_production_patch_allowed": False,
            "direct_stable_overwrite_allowed": False,
            "absolute_coordinate_learning_allowed": False,
        })
        # Even a hand-built object that claims otherwise is written closed: the wire can never
        # grant a permission, and the validator below refuses the object rather than trusting it.
        forced = R.RepairConstraints(direct_production_patch_allowed=True).as_wire()
        self.assertFalse(forced["direct_production_patch_allowed"])

    def test_a_permission_a_packet_should_never_have_is_refused_rather_than_assumed(self):
        """The closed values are load-bearing: the validator reads the field, not the wire."""
        packet = _packet(constraints=R.RepairConstraints(direct_stable_overwrite_allowed=True))
        verdict = _validated(_proposal(), packet=packet)
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_WOULD_TOUCH_PRODUCTION)

    def test_a_packet_with_no_skill_id_is_refused(self):
        verdict = _packet(identity=R.RepairIdentity("role_01", "G", "")).validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_SCHEMA_INVALID)

    def test_a_repair_with_no_failure_is_not_a_repair(self):
        """No recorded failure means this is an UNKNOWN, which is a different mode's question."""
        verdict = _packet(current_failure=R.FailureState(0, "", "", "")).validate()
        self.assertFalse(verdict.ok)
        self.assertIn("no recorded failure", verdict.detail)

    def test_a_packet_with_no_current_frame_is_refused(self):
        verdict = _packet(frame_hash="").validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.CONTEXT_FRAME_MISMATCH)

    def test_an_element_table_from_another_frame_is_refused(self):
        """Section 5's concern, arriving through section 14's packet."""
        verdict = _packet(elements={"frame_id": "f9", "items": []}).validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.CONTEXT_FRAME_MISMATCH)

    def test_the_evidence_index_is_the_episodes_and_the_frame(self):
        packet = _packet()
        self.assertEqual(packet.evidence_ids(), {"ep_001", "ep_002", "f1"})

    def test_a_renderable_packet_is_json(self):
        rendered = _packet().render()
        self.assertIn("This skill's repair packet", rendered)
        self.assertIn("TARGET_NOT_FOUND", rendered)

    def test_the_repair_reason_cap_is_its_own_number(self):
        """Sections 1/12's brevity rule, at this mode's own bound."""
        self.assertEqual(R.REPAIR_REASON_MAX_CHARS, 120)
        self.assertEqual(
            R.repair_schema()["properties"]["reason"]["maxLength"], R.REPAIR_REASON_MAX_CHARS)


class ParsingTests(unittest.TestCase):
    def test_a_contract_shaped_reply_parses(self):
        parsed = _parsed(_proposal())
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.diagnosis, "VISUAL_LAYOUT_DRIFT")
        self.assertEqual(parsed.candidate.proposed_change.type, "VISUAL_RULE")
        self.assertEqual(parsed.candidate.evidence_refs, ("ep_001", "ep_002"))

    def test_a_reply_that_is_not_json_is_named(self):
        error = _parsed("not json at all").error
        self.assertTrue(error.startswith(R.REPAIR_NOT_JSON), error)
        self.assertEqual(c.canonical_code(error), R.REPAIR_NOT_JSON)

    def test_a_json_array_is_not_an_object(self):
        self.assertEqual(_parsed("[1,2]").error, R.REPAIR_NOT_AN_OBJECT)

    def test_the_online_protocols_keys_are_refused_here(self):
        """A repair reply that carries a tap is answering the other mode's question."""
        error = _parsed(_reply(decision="EXECUTE", x=340, y=812, reason="点这里")).error
        self.assertTrue(error.startswith(R.REPAIR_GEOMETRY_TRANSPORTED), error)

    def test_a_pixel_coordinate_is_refused_by_name(self):
        error = _parsed(_proposal(candidate_bbox_norm=[340, 812, 40, 40])).error
        self.assertEqual(error, c.PLAN_BOX_NOT_NORMALISED)

    def test_an_invented_diagnosis_is_refused(self):
        """The diagnosis *is* the repair action, so an invented one is an invented act."""
        error = _parsed(_proposal(diagnosis="BUTTON_TOO_SMALL")).error
        self.assertTrue(error.startswith(R.REPAIR_DIAGNOSIS_UNKNOWN), error)

    def test_an_answer_to_a_different_question_is_refused(self):
        error = _parsed(_proposal(analysis_type="CANDIDATE_PAGE")).error
        self.assertTrue(error.startswith(R.REPAIR_ANALYSIS_TYPE_UNKNOWN), error)

    def test_a_missing_analysis_type_defaults_to_the_only_legal_one(self):
        payload = json.loads(_proposal())
        del payload["analysis_type"]
        parsed = _parsed(json.dumps(payload, ensure_ascii=False))
        self.assertTrue(parsed.ok, parsed.error)

    def test_a_paragraph_reason_is_refused(self):
        error = _parsed(_proposal(reason="这个控件没有找到。" * 20)).error
        self.assertEqual(error, c.PLAN_REASON_TOO_LONG)

    def test_the_flat_change_spelling_is_read_too(self):
        """One protocol, two spellings: ``proposed_change.type`` and the flat pair."""
        parsed = _parsed(_reply(
            diagnosis="ENTRY_MOVED", change_type="ROUTE", change_description="改走联盟界面",
            evidence_refs="ep_001", required_validation="replay,live_verifier", reason="入口改道。",
            skill_id="SKILL_OPEN_TRAINING",
        ))
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.proposed_change.type, "ROUTE")
        self.assertEqual(parsed.candidate.required_validation, ("REPLAY", "LIVE_VERIFIER"))

    def test_a_missing_skill_id_is_taken_from_the_packet(self):
        """The model is answering about one skill; restating the id is not how it says which."""
        parsed = _parsed(_reply(diagnosis="UNKNOWN", proposed_change={"type": "RETIRE"},
                                evidence_refs=["ep_001"], required_validation=["LIVE_VERIFIER"],
                                reason="无法判断。"))
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.skill_id, "SKILL_OPEN_TRAINING")


class ValidatorTests(unittest.TestCase):
    def test_a_good_candidate_is_admitted(self):
        verdict = _validated(_proposal())
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_candidate_about_another_skill_is_refused(self):
        verdict = _validated(_proposal(skill_id="SKILL_SOMETHING_ELSE"))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_SKILL_MISMATCH)

    def test_a_production_patch_is_refused_by_name(self):
        """Section 15/30: a candidate is not a write."""
        verdict = _validated(_proposal(proposed_change={"type": "PRODUCTION_PATCH"}))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_WOULD_TOUCH_PRODUCTION)

    def test_a_stable_overwrite_is_refused_by_name(self):
        verdict = _validated(_proposal(proposed_change={"type": "STABLE_OVERWRITE"}))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_WOULD_TOUCH_PRODUCTION)

    def test_learning_a_coordinate_as_a_repair_is_refused(self):
        """The constitution's one rule: a position is never a learned artefact."""
        verdict = _validated(_proposal(proposed_change={"type": "ABSOLUTE_COORDINATE"}))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_LEARNS_A_COORDINATE)

    def test_a_position_smuggled_into_the_prose_is_refused(self):
        """The typed door is closed by the vocabulary; the description is the untyped one."""
        for description in ("入口移到 x=340, y=812", "点 (0.86, 0.68)", "坐标 340, 812"):
            verdict = _validated(_proposal(
                proposed_change={"type": "VISUAL_RULE", "description": description}))
            self.assertFalse(verdict.ok, description)
            self.assertEqual(verdict.code, R.REPAIR_LEARNS_A_COORDINATE, description)

    def test_a_rule_described_in_words_is_not_a_coordinate(self):
        verdict = _validated(_proposal(
            proposed_change={"type": "VISUAL_RULE", "description": "入口在城郊右侧，盾形按钮"}))
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_an_invented_change_type_is_refused(self):
        verdict = _validated(_proposal(proposed_change={"type": "MOVE_BUTTON"}))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_CHANGE_TYPE_UNKNOWN)

    def test_no_change_at_all_is_refused(self):
        verdict = _validated(_proposal(proposed_change={}))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_SCHEMA_INVALID)

    def test_a_conclusion_with_no_citation_is_refused(self):
        """Section 17's traceability rule, at the repair door."""
        verdict = _validated(_proposal(evidence_refs=[]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_NO_EVIDENCE_REFS)

    def test_a_citation_the_packet_never_showed_is_refused(self):
        verdict = _validated(_proposal(evidence_refs=["ep_999"]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_EVIDENCE_NOT_IN_PACKET)

    def test_one_resolvable_citation_is_enough_to_follow(self):
        """The rule is "none of these can be followed", not "all of these are perfect".

        A partly-wrong citation list still has a reachable chain, and the whole list is written to
        the ledger -- so a reviewer sees the bad reference rather than losing the good one.
        ``validate_candidate`` in the offline mode applies the same rule, deliberately.
        """
        verdict = _validated(_proposal(evidence_refs=["ep_001", "ep_999"]))
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_candidate_with_no_route_to_reality_is_refused(self):
        """A repair that cannot be live-verified has no path out of the candidate folder."""
        verdict = _validated(_proposal(required_validation=["REPLAY", "SHADOW"]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_NOT_LIVE_VALIDATED)

    def test_no_required_validation_is_refused(self):
        verdict = _validated(_proposal(required_validation=[]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_NO_REQUIRED_VALIDATION)

    def test_an_invented_check_is_refused(self):
        verdict = _validated(_proposal(required_validation=["REPLAY", "TRUST_ME"]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, R.REPAIR_VALIDATION_UNKNOWN)

    def test_a_route_diagnosis_answered_with_a_locator_change_is_refused(self):
        """The classic misrepair: the page moved and the model re-locates a control on it.

        Refused because the two lead to different repairs and the promotion gate treats them
        differently -- folding them would let "the route is gone" be recorded as "the button moved".
        """
        for diagnosis in R.ROUTE_DIAGNOSES:
            verdict = _validated(_proposal(diagnosis=diagnosis,
                                           proposed_change={"type": "VISUAL_RULE"}))
            self.assertFalse(verdict.ok, diagnosis)
            self.assertEqual(verdict.code, R.REPAIR_CHANGE_TYPE_UNKNOWN, diagnosis)

    def test_a_route_diagnosis_answered_with_a_route_change_is_admitted(self):
        verdict = _validated(_proposal(diagnosis="SKILL_OUTDATED",
                                       proposed_change={"type": "ROUTE", "description": "改走联盟页"}))
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_proposed_region_is_grounded_on_the_current_frame_not_trusted(self):
        """Sections 10/15: the one geometry channel, and it never reaches anything unverified."""
        region = {"x_norm": 0.85, "y_norm": 0.62, "w_norm": 0.10, "h_norm": 0.10, "text": ""}
        boxed = _proposal(candidate_bbox_norm=[0.86, 0.63, 0.08, 0.08])
        verdict = _validated(boxed, ground_regions=[])
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.UNKNOWN_GROUNDING_FAILED)
        self.assertEqual(verdict.stage, "GROUNDING")

        grounded = _validated(boxed, ground_regions=[region])
        self.assertTrue(grounded.ok, grounded.as_row())

    def test_a_previous_frames_region_cannot_ground_a_repair(self):
        """Section 22 arrives here too: the packet's frame is the current one, or it is nothing."""
        verdict = _validated(
            _proposal(candidate_bbox_norm=[0.86, 0.63, 0.08, 0.08]),
            ground_regions=[{"x_norm": 0.85, "y_norm": 0.62, "w_norm": 0.10, "h_norm": 0.10}],
            frame_now=c.FrameIdentity("f2", "sha256:bb"),
        )
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.UNKNOWN_GROUNDING_FAILED)

    def test_a_repair_never_overwrites_a_stable_skill(self):
        """Sections 15 and 30, as a function so the answer is greppable."""
        self.assertFalse(R.may_overwrite_stable())
        self.assertFalse(R.may_overwrite_stable(_parsed(_proposal()).candidate))

    def test_the_refusal_stages_are_the_contracts_own(self):
        """Repair keeps its own validator but reuses section 13's stage *names*.

        Deliberately the same nine words: a report folding all three ledgers would otherwise have
        to know which mode's vocabulary it was reading before it could interpret a stage.
        """
        parsed = _parsed("not json")
        self.assertFalse(parsed.ok)
        self.assertEqual(parsed.error.split(":", 1)[0], R.REPAIR_NOT_JSON)
        for stage in (_validated(_proposal(skill_id="OTHER")).stage,
                      _validated(_proposal(evidence_refs=[])).stage,
                      _packet(frame_hash="").validate().stage):
            self.assertIn(stage, c.VALIDATION_STAGES, stage)

    def test_a_passing_verdict_is_not_a_permission(self):
        """The distinction the whole mode turns on: admitted to be *tried*, not admitted to write."""
        verdict = _validated(_proposal())
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.code, "")
        self.assertFalse(R.may_overwrite_stable())


class SchemaTests(unittest.TestCase):
    def test_the_schema_publishes_the_closed_vocabularies(self):
        schema = R.repair_schema()
        self.assertEqual(schema["properties"]["diagnosis"]["enum"], list(R.DIAGNOSES))
        self.assertEqual(schema["properties"]["analysis_type"]["enum"], [R.ANALYSIS_TYPE])
        self.assertEqual(schema["properties"]["proposed_change"]["properties"]["type"]["enum"],
                         list(R.CHANGE_TYPES))
        self.assertFalse(schema["additionalProperties"])

    def test_the_change_vocabulary_has_no_position_in_it(self):
        """The coordinate rule enforced by the vocabulary, not by a check someone must run."""
        for name in R.CHANGE_TYPES:
            self.assertNotIn("POSITION", name)
            self.assertNotIn("COORDINATE", name)
            self.assertNotIn("PIXEL", name)
        self.assertEqual(len(R.CHANGE_TYPES), 5)

    def test_the_forbidden_change_types_stay_forbidden(self):
        """Listed by name so a reply that asks for one gets its own refusal, not a schema error."""
        for name in R.FORBIDDEN_CHANGE_TYPES:
            self.assertNotIn(name, R.CHANGE_TYPES, name)
        self.assertIn("PRODUCTION_PATCH", R.FORBIDDEN_CHANGE_TYPES)
        self.assertIn("ABSOLUTE_COORDINATE", R.FORBIDDEN_CHANGE_TYPES)

    def test_the_validation_vocabulary_includes_a_live_check(self):
        self.assertEqual(set(R.LIVE_VALIDATIONS), {"LIVE_VERIFIER"})
        for name in R.LIVE_VALIDATIONS:
            self.assertIn(name, R.REQUIRED_VALIDATION_KINDS)

    def test_the_trigger_modules_vocabulary_folds_onto_this_one(self):
        """Two vocabularies for "what is wrong" would let one repair be counted under two names."""
        from winter_agent_v2 import skill_repair

        for judgement in skill_repair.JUDGEMENTS:
            self.assertIn(judgement, R.JUDGEMENT_TO_DIAGNOSIS, judgement)
            self.assertIn(R.JUDGEMENT_TO_DIAGNOSIS[judgement], R.DIAGNOSES, judgement)

    def test_the_route_diagnoses_are_a_subset_of_the_vocabulary(self):
        for name in R.ROUTE_DIAGNOSES:
            self.assertIn(name, R.DIAGNOSES)

    def test_the_prompt_states_the_rules_the_validator_enforces(self):
        for phrase in ("used to work", "Propose a change to a RULE, never to a position",
                       "You cannot change the skill directly", "evidence_refs", "JSON only",
                       "one short sentence"):
            self.assertIn(phrase, R.SYSTEM_PROMPT, phrase)


class AdapterTests(unittest.TestCase):
    def test_the_trigger_modules_request_reaches_the_contracts_shape(self):
        """The runtime already files a ``RepairRequest``; this is the same facts, typed.

        The assertion that matters is ``validate`` passing.  The trigger spells the skill's aim
        ``old_semantic`` and its verifier's requirement ``verifier_expectation``; an adapter reading
        only this contract's spellings would produce a packet whose skill states neither a target
        nor an expected result, and ``validate`` refuses exactly that -- so the mis-spelling would
        show up as repairs quietly stopping rather than as an error.
        """
        from winter_agent_v2 import skill_repair

        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame_001.png"
            frame.write_bytes(b"\x89PNG\r\n\x1a\n the bytes are the identity")
            request = skill_repair.RepairRequest(
                request_id="r1", skill_id="SKILL_OPEN_TRAINING", page_key="PAGE_CITY",
                goal_id="COLLECT_TRAINING", frame_path=str(frame),
                old_semantic="训练", old_target_text="训练, 开始训练",
                old_success_pages=("PAGE_TRAINING",), verifier_expectation="TRAINING_MENU_OPEN",
                failure_kinds=("TARGET_NOT_FOUND",), consecutive_failures=3,
                failure_frames=(str(frame),), role_id="role_01",
            )
            packet = R.packet_from_request(
                request, maturity="STABLE", known_visual_rules=("盾形按钮",),
                success_evidence=[{"episode_id": "ep_001", "page_before": "PAGE_CITY",
                                   "page_after": "PAGE_TRAINING", "verifier": "PASS"}],
                elements={"frame_id": "frame_001", "items": []},
            )
            verdict = packet.validate()

        self.assertEqual(packet.identity.skill_id, "SKILL_OPEN_TRAINING")
        self.assertEqual(packet.frame_id, "frame_001")
        self.assertTrue(packet.frame_hash.startswith("sha256:"))
        self.assertEqual(packet.existing_skill.semantic_target, "训练")
        self.assertEqual(packet.existing_skill.expected_result, "TRAINING_MENU_OPEN")
        self.assertEqual(packet.current_failure.verifier_reason, "TARGET_NOT_FOUND")
        self.assertEqual(packet.previous_success_evidence[0].episode_id, "ep_001")
        self.assertIn("ep_001", packet.evidence_ids())
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_request_with_no_frame_cannot_become_a_valid_packet(self):
        """Section 14 needs a picture.  Nothing is invented to fill the gap."""
        from winter_agent_v2 import skill_repair

        request = skill_repair.RepairRequest(
            request_id="r1", skill_id="SKILL_OPEN_TRAINING", frame_path="",
            old_semantic="训练", verifier_expectation="TRAINING_MENU_OPEN",
            failure_kinds=("TARGET_NOT_FOUND",), consecutive_failures=3,
        )
        packet = R.packet_from_request(request)
        self.assertEqual(packet.frame_id, "")
        verdict = packet.validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, c.CONTEXT_FRAME_MISMATCH)

    def test_a_trigger_proposal_becomes_a_candidate(self):
        from winter_agent_v2 import skill_repair

        proposal = skill_repair.RepairProposal(
            request_id="r1", skill_id="SKILL_OPEN_TRAINING", judgement="ENTRY_MOVED",
            reason="入口改道。", new_semantic_target="联盟页面入口", expected_result="MENU_OPEN",
        )
        candidate = R.candidate_from_proposal(proposal, packet=_packet())
        self.assertEqual(candidate.diagnosis, "ENTRY_MOVED")
        self.assertEqual(candidate.proposed_change.type, R.CHANGE_SEMANTIC_TARGET)
        self.assertIn(R.VALIDATION_LIVE_VERIFIER, candidate.required_validation)
        self.assertTrue(candidate.evidence_refs, "an adapted candidate must still be traceable")
        self.assertEqual(candidate.confidence, 0.0,
                         "the trigger's proposal has no confidence field; nothing is invented")
        self.assertTrue(R.validate_repair_candidate(candidate, packet=_packet()).ok,
                        "an adapter must not produce a candidate its own gate rejects")

    def test_a_route_diagnosis_is_adapted_as_a_route_change(self):
        """The ordering inside the adapter, and why it cannot be the other way round.

        A proposal can say "the route is gone" *and* name the control on the new route.  Taking the
        semantic-target branch first would emit ``SEMANTIC_TARGET`` for a route diagnosis, which
        ``validate_repair_candidate`` refuses -- a repair filed and then silently dropped.  The
        words still travel in ``semantic_target``; only the *change type* is the route's.
        """
        from winter_agent_v2 import skill_repair

        proposal = skill_repair.RepairProposal(
            request_id="r1", skill_id="SKILL_OPEN_TRAINING", judgement="SKILL_OUTDATED",
            reason="路线已不存在。", new_semantic_target="联盟入口", expected_result="MENU_OPEN",
        )
        candidate = R.candidate_from_proposal(proposal, packet=_packet())
        self.assertEqual(candidate.diagnosis, "SKILL_OUTDATED")
        self.assertEqual(candidate.proposed_change.type, R.CHANGE_ROUTE)
        self.assertEqual(candidate.semantic_target, "联盟入口")
        self.assertTrue(R.validate_repair_candidate(candidate, packet=_packet()).ok)

    def test_an_unmapped_judgement_becomes_unknown_rather_than_a_guess(self):
        class Fake:
            judgement = "SOMETHING_NEW"
            skill_id = "SKILL_OPEN_TRAINING"
            new_semantic_target = ""
            candidate_bbox_norm = None
            evidence_refs = ()
            expected_result = ""
            confidence = 0.0
            reason = ""
            source = ""

        candidate = R.candidate_from_proposal(Fake(), packet=_packet())
        self.assertEqual(candidate.diagnosis, "UNKNOWN")
        self.assertEqual(candidate.evidence_refs, ("f1",), "the frame is a real reference")


class LedgerTests(unittest.TestCase):
    def test_a_candidate_row_says_it_is_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = R.RepairLedger(Path(tmp) / "repair.jsonl")
            parsed = _parsed(_proposal())
            assert parsed.candidate is not None
            verdict = R.validate_repair_candidate(parsed.candidate, packet=_packet())
            row = ledger.record_candidate(parsed.candidate, verdict=verdict, trace_id="t1")
            rows = ledger.rows()
        self.assertEqual(row["status"], "CANDIDATE")
        self.assertTrue(row["admitted"])
        self.assertEqual(rows[0]["diagnosis"], "VISUAL_LAYOUT_DRIFT")
        self.assertIn("not_yet", rows[0])
        self.assertIsNone(rows[0]["proposed_region_untrusted"], "no coordinate is ever filed")
        self.assertNotIn("x_norm", rows[0])

    def test_a_refusal_is_recorded_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = R.RepairLedger(Path(tmp) / "repair.jsonl")
            ledger.record_refusal(code=R.REPAIR_LEARNS_A_COORDINATE, stage="SCHEMA",
                                  detail="proposed_change.type='ABSOLUTE_COORDINATE'",
                                  trace_id="t2", skill_id="SKILL_OPEN_TRAINING")
            rows = ledger.rows()
        self.assertFalse(rows[0]["admitted"])
        self.assertEqual(rows[0]["verdict"]["code"], R.REPAIR_LEARNS_A_COORDINATE)
        self.assertEqual(rows[0]["verdict"]["family"], "REPAIR")

    def test_the_repair_codes_fold_to_their_own_family(self):
        """Section 30's independence, visible in the data: three modes, three prefixes."""
        self.assertEqual(c.code_family(R.REPAIR_NO_EVIDENCE_REFS), "REPAIR")
        self.assertNotEqual(c.code_family(R.REPAIR_NO_EVIDENCE_REFS),
                            c.code_family(c.PLAN_TARGET_NOT_ON_THIS_FRAME))

    def test_the_ledger_path_is_this_modes_own(self):
        self.assertEqual(R.REPAIR_LEDGER_PATH.parts[0], "learning")
        self.assertNotEqual(R.REPAIR_LEDGER_PATH, Path("learning/ui_venus_online.jsonl"))
        self.assertNotEqual(R.REPAIR_LEDGER_PATH, Path("learning/ui_venus_offline.jsonl"))


if __name__ == "__main__":
    unittest.main()
