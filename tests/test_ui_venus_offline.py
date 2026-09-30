"""OFFLINE_LEARNING: the evidence packet, the candidates, and the traceability rule.

Operator directive 2026-10-01, sections 16-22 and 30.  Each test names its section.

This mode's question is not "where do I click now" but "what should be learned from these episodes
that already happened", and everything here follows from that substitution: freshness stops
mattering and traceability starts, nothing produced is ever a fact, and the device is out of reach
by construction.  The three claims worth being able to check by reading one test:

* every conclusion cites evidence the packet really contains (section 17);
* every output is a candidate, never a fact and never an action (sections 18/21);
* there is no region channel here at all -- not even the one the online contract opens (section 30).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import ui_venus_contract as c
from winter_agent_v2 import ui_venus_offline as O


def _episodes() -> tuple[O.EvidenceEpisode, ...]:
    return (
        O.EvidenceEpisode(
            "ep_001", "role_01", "COLLECT_TRAINING",
            frames=(O.EvidenceFrame("f1", "screens/f1.png", "PAGE_TRAINING"),
                    O.EvidenceFrame("f2", "screens/f2.png", "PAGE_TRAINING")),
            actions=(O.EvidenceAction(1, "CLICK_ELEMENT", "训练"),
                     O.EvidenceAction(2, "CLICK_ELEMENT", "开始训练")),
            verifier=O.EvidenceVerifier("SUCCESS", "TRAINING_MENU_OPEN"),
        ),
        O.EvidenceEpisode(
            "ep_002", "role_01", "COLLECT_TRAINING",
            frames=(O.EvidenceFrame("f3", "screens/f3.png", "PAGE_TRAINING"),),
            actions=(O.EvidenceAction(1, "CLICK_ELEMENT", "训练"),),
            verifier=O.EvidenceVerifier("SUCCESS", "TRAINING_MENU_OPEN"),
        ),
    )


def _packet(**overrides) -> O.UIVenusLearningPacketV1:
    base = dict(
        scope=O.LearningScope("TRAINING", "TRAINING", O.ROLE_SCOPE_SHARED, "c1"),
        episodes=_episodes(),
        existing_knowledge=({"id": "k1", "text": "训练入口在城郊", "confidence": "OBSERVED"},),
        failure_summary=O.FailureSummary(2, 1, "TARGET_NOT_FOUND"),
    )
    base.update(overrides)
    return O.UIVenusLearningPacketV1(**base)


def _page_candidate(**overrides) -> O.OfflineLearningCandidateV1:
    base = dict(
        page_semantic="PAGE_TRAINING",
        visual_features=["盾形按钮", "顶部标题栏"],
        controls=[{"semantic": "训练", "text": "训练"}],
        evidence_refs=[{"episode_id": "ep_001", "frame_id": "f1"}, "ep_002"],
        confidence=0.7,
        reason="三帧为同一屏幕。",
    )
    base.update(overrides)
    return O.candidate_page(**base)


def _reply(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def _payload(analysis_type: str = "CANDIDATE_PAGE", body: dict | None = None, **extra) -> str:
    payload = {
        "analysis_type": analysis_type,
        "payload": body if body is not None else {
            "page_semantic": "PAGE_TRAINING", "visual_features": ["盾形按钮"],
        },
        "confidence": 0.7,
        "evidence_refs": [{"episode_id": "ep_001", "frame_id": "f1"}],
        "required_validation": ["REOBSERVE", "LIVE_NAVIGATION"],
        "reason": "三帧为同一屏幕。",
    }
    payload.update(extra)
    return _reply(**payload)


def _parsed(raw: str, packet: O.UIVenusLearningPacketV1 | None = None):
    return O.parse_candidate(raw, packet=packet if packet is not None else _packet())


def _validated(raw: str, packet: O.UIVenusLearningPacketV1 | None = None):
    packet = packet if packet is not None else _packet()
    parsed = _parsed(raw, packet)
    assert parsed.candidate is not None, parsed.error
    return O.validate_candidate(parsed.candidate, packet=packet)


class PacketShapeTests(unittest.TestCase):
    def test_the_packet_wire_shape_is_section_16s(self):
        wire = _packet().as_wire()
        for key in ("mode", "learning_scope", "evidence", "existing_knowledge", "existing_skill",
                    "failure_summary", "constraints", "context_budget"):
            self.assertIn(key, wire, key)
        self.assertEqual(wire["mode"], c.MODE_OFFLINE)
        self.assertEqual(wire["learning_scope"]["role_scope"], O.ROLE_SCOPE_SHARED)
        self.assertEqual(wire["evidence"]["episodes"][0]["episode_id"], "ep_001")
        self.assertEqual(wire["context_budget"]["output_reserve_tokens"], c.OUTPUT_RESERVE)

    def test_the_constraints_are_held_and_cannot_be_relaxed(self):
        """Section 16's four ``True``s: assertions about this mode, not permissions."""
        self.assertEqual(O.LearningConstraints().as_wire(), {
            "no_device_actions": True, "no_production_write": True,
            "no_direct_promotion": True, "no_absolute_coordinate_learning": True,
        })
        forced = O.LearningConstraints(no_device_actions=False)
        self.assertFalse(forced.all_held)
        self.assertTrue(forced.as_wire()["no_device_actions"],
                        "the wire can never describe a mode that touches the device")
        verdict = _packet(constraints=forced).validate()
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_SCHEMA_INVALID)

    def test_a_packet_with_no_episodes_has_nothing_to_learn_from(self):
        verdict = _packet(episodes=()).validate()
        self.assertFalse(verdict.ok)
        self.assertIn("no episodes", verdict.detail)

    def test_the_traceability_gaps_name_the_rule_that_broke(self):
        """Section 17 asks for a chain, so the report says which link is missing."""
        gappy = _packet(episodes=(
            O.EvidenceEpisode("ep_001", "role_01", "G",
                              frames=(O.EvidenceFrame("", "screens/x.png", "P"),),
                              actions=(O.EvidenceAction(0, "CLICK_ELEMENT", "训练"),),
                              verifier=O.EvidenceVerifier("", "")),
        ))
        gaps = " | ".join(gappy.traceability_gaps())
        self.assertIn("no frame_id", gaps)
        self.assertIn("no step id", gaps)
        self.assertIn("no verifier outcome", gaps)
        self.assertFalse(gappy.validate().ok)

    def test_a_duplicated_episode_id_is_a_gap(self):
        duplicated = _packet(episodes=_episodes() + (_episodes()[0],))
        self.assertIn("duplicate episode_id", " | ".join(duplicated.traceability_gaps()))

    def test_two_roles_may_only_be_compared_under_a_shared_scope(self):
        """Section 24: runtime state never crosses roles; page semantics may -- if declared."""
        cross = _packet(
            scope=O.LearningScope("TRAINING", "TRAINING", "role_01", "c1"),
            episodes=(_episodes()[0],
                      O.EvidenceEpisode("ep_002", "role_02", "COLLECT_TRAINING",
                                        frames=(O.EvidenceFrame("f3", "s.png", "P"),),
                                        verifier=O.EvidenceVerifier("SUCCESS", ""))),
        )
        self.assertIn("role_scope", " | ".join(cross.traceability_gaps()))
        self.assertFalse(cross.validate().ok)
        shared = _packet(scope=O.LearningScope("TRAINING", "TRAINING", O.ROLE_SCOPE_SHARED, "c1"),
                         episodes=cross.episodes)
        self.assertTrue(shared.validate().ok, shared.validate().as_row())

    def test_the_evidence_index_maps_an_episode_to_the_frames_it_can_vouch_for(self):
        self.assertEqual(_packet().evidence_index(),
                         {"ep_001": {"f1", "f2"}, "ep_002": {"f3"}})

    def test_a_renderable_packet_is_json(self):
        rendered = _packet().render()
        self.assertIn("Offline learning packet", rendered)
        self.assertIn("ep_001", rendered)


class ParsingTests(unittest.TestCase):
    def test_a_contract_shaped_reply_parses(self):
        parsed = _parsed(_payload())
        self.assertTrue(parsed.ok, parsed.error)
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.analysis_type, "CANDIDATE_PAGE")
        self.assertEqual(parsed.candidate.status, O.STATUS_CANDIDATE)
        self.assertEqual(parsed.candidate.evidence_refs[0].frame_id, "f1")

    def test_a_reply_that_is_not_json_is_named(self):
        error = _parsed("<html>").error
        self.assertTrue(error.startswith(O.OFFLINE_NOT_JSON), error)
        self.assertEqual(c.canonical_code(error), O.OFFLINE_NOT_JSON)

    def test_a_json_array_is_not_an_object(self):
        self.assertEqual(_parsed("[1,2]").error, O.OFFLINE_NOT_AN_OBJECT)

    def test_a_tap_is_refused_by_name(self):
        """Section 18: a model asked about the past may not volunteer a next action."""
        payload = json.loads(_payload())
        payload["decision"] = "EXECUTE"
        error = _parsed(json.dumps(payload, ensure_ascii=False)).error
        self.assertEqual(error, O.OFFLINE_DECISION_EXECUTE_FORBIDDEN)
        self.assertEqual(O.refuse_offline_execute({"decision": "EXECUTE"}),
                         O.OFFLINE_DECISION_EXECUTE_FORBIDDEN)

    def test_any_of_the_online_protocols_own_keys_is_a_different_question(self):
        for key in ("decision", "action_type", "target_element_id"):
            payload = json.loads(_payload())
            payload[key] = "OBSERVE"
            error = _parsed(json.dumps(payload, ensure_ascii=False)).error
            self.assertEqual(error, O.OFFLINE_ANALYSIS_TYPE_UNKNOWN, key)
        self.assertEqual(O.refuse_offline_execute({"target_element_id": "E1"}),
                         O.OFFLINE_ANALYSIS_TYPE_UNKNOWN)
        self.assertEqual(O.refuse_offline_execute({}), "")

    def test_an_invented_analysis_type_is_refused(self):
        payload = json.loads(_payload())
        payload["analysis_type"] = "CANDIDATE_NOTHING"
        error = _parsed(json.dumps(payload, ensure_ascii=False)).error
        self.assertTrue(error.startswith(O.OFFLINE_ANALYSIS_TYPE_UNKNOWN), error)

    def test_execute_is_not_even_a_legal_analysis_type(self):
        """The prohibition is the enum: ``EXECUTE`` cannot be generated because it is not a value."""
        self.assertNotIn("EXECUTE", O.ANALYSIS_TYPES)
        self.assertEqual(len(O.ANALYSIS_TYPES), 7)
        self.assertEqual(O.learning_schema()["properties"]["analysis_type"]["enum"],
                         list(O.ANALYSIS_TYPES))

    def test_there_is_no_region_channel_here_at_all(self):
        """Section 30: the online contract opens one geometry channel; this mode opens none.

        Not even the box.  A region inside the open ``payload`` object would otherwise be stored as
        candidate knowledge, which is a coordinate becoming a learned artefact.
        """
        self.assertNotIn(c.VISION_BOX_KEY, O.learning_schema()["properties"])
        for nested in ({"candidate_bbox_norm": [0.1, 0.2, 0.3, 0.4]},
                       {"payload": {"candidate_bbox_norm": [0.1, 0.2, 0.3, 0.4]}}):
            payload = json.loads(_payload())
            payload.update(nested)
            error = _parsed(json.dumps(payload, ensure_ascii=False)).error
            self.assertTrue(error.startswith(O.OFFLINE_GEOMETRY_TRANSPORTED), error)

    def test_a_pixel_smuggled_into_the_body_is_refused(self):
        payload = json.loads(_payload())
        payload["payload"]["tap_point"] = {"x": 340, "y": 812}
        error = _parsed(json.dumps(payload, ensure_ascii=False)).error
        self.assertTrue(error.startswith(O.OFFLINE_GEOMETRY_TRANSPORTED), error)
        self.assertIn("tap_point", error)

    def test_the_scan_that_does_this_is_this_modes_own(self):
        """``find_forbidden_geometry`` exempts the box on purpose; this mode does not inherit it."""
        probe = {"payload": {c.VISION_BOX_KEY: [0.1, 0.2, 0.3, 0.4]}}
        self.assertEqual(c.find_forbidden_geometry(probe), "")
        self.assertEqual(O.find_any_geometry(probe), f"payload.{c.VISION_BOX_KEY}")
        for key in c.FORBIDDEN_GEOMETRY_KEYS:
            self.assertIn(key, O.GEOMETRY_KEYS_FORBIDDEN_OFFLINE, key)

    def test_a_bare_string_citation_is_normalised(self):
        """Sections 19 and 20 use two citation shapes; a contract demanding one would refuse the
        other's data."""
        parsed = _parsed(_payload(evidence_refs=["ep_001"]))
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.evidence_refs[0].episode_id, "ep_001")
        self.assertEqual(parsed.candidate.evidence_refs[0].as_wire(), {"episode_id": "ep_001"})

    def test_a_paragraph_reason_is_refused(self):
        error = _parsed(_payload(reason="这一组帧看起一样。" * 20)).error
        self.assertEqual(error, c.PLAN_REASON_TOO_LONG)

    def test_the_scope_defaults_to_the_packets(self):
        parsed = _parsed(_payload())
        assert parsed.candidate is not None
        self.assertEqual(parsed.candidate.scope.cluster_id, "c1")


class ValidatorTests(unittest.TestCase):
    def test_a_good_candidate_is_admitted(self):
        verdict = _validated(_payload())
        self.assertTrue(verdict.ok, verdict.as_row())
        self.assertEqual(verdict.code, "")

    def test_a_candidate_that_is_not_a_candidate_is_refused(self):
        """Section 21: every offline output starts at ``CANDIDATE``, and that is not decorable."""
        candidate = O.OfflineLearningCandidateV1(
            analysis_type=O.CANDIDATE_PAGE,
            payload={"page_semantic": "PAGE_TRAINING", "visual_features": ["a"]},
            evidence_refs=(O.EvidenceRef("ep_001"),),
            required_validation=(O.VALIDATION_REOBSERVE,),
            status="STABLE",
        )
        verdict = O.validate_candidate(candidate, packet=_packet())
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_STATUS_NOT_CANDIDATE)

    def test_the_output_type_has_nowhere_to_put_a_tap(self):
        candidate = O.OfflineLearningCandidateV1(
            analysis_type=O.CANDIDATE_PAGE, payload={"decision": "EXECUTE"},
            evidence_refs=(O.EvidenceRef("ep_001"),), required_validation=(O.VALIDATION_REPLAY,),
        )
        verdict = O.validate_candidate(candidate, packet=_packet())
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_DECISION_EXECUTE_FORBIDDEN)
        self.assertFalse(hasattr(O.OfflineLearningCandidateV1(), "decision"))

    def test_geometry_in_a_hand_built_body_is_refused_too(self):
        """The raw reply is scanned at parse time; a directly built candidate is scanned here."""
        candidate = O.OfflineLearningCandidateV1(
            analysis_type=O.CANDIDATE_PAGE,
            payload={"page_semantic": "P", "visual_features": ["a"],
                     "candidate_controls": [{"semantic": "训练", "bbox": [1, 2, 3, 4]}]},
            evidence_refs=(O.EvidenceRef("ep_001"),), required_validation=(O.VALIDATION_REOBSERVE,),
        )
        verdict = O.validate_candidate(candidate, packet=_packet())
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_GEOMETRY_TRANSPORTED)

    def test_every_analysis_type_needs_its_own_body(self):
        """Sections 19/20: seven types, seven shapes, and an empty one is refused with the reason."""
        for analysis_type in O.ANALYSIS_TYPES:
            candidate = O.OfflineLearningCandidateV1(
                analysis_type=analysis_type, payload={},
                evidence_refs=(O.EvidenceRef("ep_001"),),
                required_validation=(O.VALIDATION_REPLAY,),
            )
            verdict = O.validate_candidate(candidate, packet=_packet())
            self.assertFalse(verdict.ok, analysis_type)
            self.assertEqual(verdict.code, O.OFFLINE_SCHEMA_INVALID, analysis_type)

    def test_every_analysis_type_is_admitted_with_its_own_body(self):
        bodies = {
            O.CANDIDATE_PAGE: {"page_semantic": "PAGE_TRAINING", "visual_features": ["盾形"]},
            O.CANDIDATE_UI_SEMANTIC: {"texts": ["挂机收益", "离线收益"], "semantic": "BTC_OFFLINE"},
            O.FAILURE_PATTERN_CANDIDATE: {"failure": "TARGET_NOT_FOUND"},
            O.CANDIDATE_STEP: {"semantic_action": "CLICK[训练]", "expected_result": "MENU_OPEN"},
            O.CANDIDATE_SKILL: {"steps": [{"semantic_action": "CLICK[训练]"},
                                          {"semantic_action": "CLICK[开始训练]"}]},
            O.SKILL_REPAIR_CANDIDATE: {"skill_id": "SKILL_X", "diagnosis": "ENTRY_MOVED"},
            O.NAVIGATION_EDGE_CANDIDATE: {"from_page": "PAGE_CITY", "to_page": "PAGE_TRAINING"},
        }
        self.assertEqual(set(bodies), set(O.ANALYSIS_TYPES), "one body per type, none missed")
        for analysis_type, body in bodies.items():
            candidate = O.OfflineLearningCandidateV1(
                analysis_type=analysis_type, payload=body,
                evidence_refs=(O.EvidenceRef("ep_001"),),
                required_validation=(O.VALIDATION_REPLAY,),
            )
            verdict = O.validate_candidate(candidate, packet=_packet())
            self.assertTrue(verdict.ok, f"{analysis_type}: {verdict.as_row()}")

    def test_a_skill_step_without_a_semantic_action_is_refused(self):
        candidate = O.OfflineLearningCandidateV1(
            analysis_type=O.CANDIDATE_SKILL, payload={"steps": [{"expected_result": "X"}]},
            evidence_refs=(O.EvidenceRef("ep_001"),), required_validation=(O.VALIDATION_REPLAY,),
        )
        verdict = O.validate_candidate(candidate, packet=_packet())
        self.assertFalse(verdict.ok)
        self.assertIn("semantic_action", verdict.detail)

    def test_a_conclusion_with_no_citation_is_refused(self):
        """Section 17's whole point.  A claim about "these episodes" must name them."""
        verdict = _validated(_payload(evidence_refs=[]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_NO_EVIDENCE_REFS)

    def test_a_citation_the_packet_never_carried_is_refused(self):
        verdict = _validated(_payload(evidence_refs=[{"episode_id": "ep_999"}]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_EVIDENCE_NOT_IN_PACKET)

    def test_a_frame_from_another_episode_is_not_a_citation(self):
        """Cross-episode provenance is exactly what section 17 forbids: nobody could follow it."""
        verdict = _validated(_payload(
            evidence_refs=[{"episode_id": "ep_001", "frame_id": "f3"}]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_EVIDENCE_NOT_IN_PACKET)

    def test_one_resolvable_citation_is_enough_to_follow(self):
        """The rule is "none of these can be followed", not "all of these are perfect".

        A partly-wrong citation list still has a reachable chain, and the whole list is written to
        the ledger -- so the bad reference is visible rather than the good one being thrown away.
        ``validate_repair_candidate`` applies the same rule, deliberately.
        """
        verdict = _validated(_payload(evidence_refs=[
            {"episode_id": "ep_001", "frame_id": "f1"}, {"episode_id": "ep_001", "frame_id": "f3"}]))
        self.assertTrue(verdict.ok, verdict.as_row())

    def test_a_candidate_with_no_route_to_reality_is_refused(self):
        verdict = _validated(_payload(required_validation=[]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_NO_REQUIRED_VALIDATION)

    def test_an_invented_check_is_refused(self):
        verdict = _validated(_payload(required_validation=["REPLAY", "TRUST_ME"]))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_VALIDATION_UNKNOWN)

    def test_the_promotion_chain_is_in_the_vocabulary(self):
        for name in (O.VALIDATION_REPLAY, O.VALIDATION_SHADOW, O.VALIDATION_LIVE_VERIFIER):
            self.assertIn(name, O.REQUIRED_VALIDATION_KINDS)

    def test_a_passing_verdict_is_not_a_promotion(self):
        verdict = _validated(_payload())
        self.assertTrue(verdict.ok)
        row = O.OfflineLearningCandidateV1().as_row()
        self.assertEqual(row["status"], O.STATUS_CANDIDATE)
        self.assertIn("not_yet", row)

    def test_confidence_is_not_verification(self):
        """Section 21: "confidence=0.99 ≠ 已验证".  A confident candidate is still a candidate."""
        high = _validated(_payload(confidence=0.99))
        self.assertTrue(high.ok)
        self.assertEqual(O.STATUS_CANDIDATE, "CANDIDATE")
        self.assertEqual(_parsed(_payload(confidence=0.99)).candidate.status, O.STATUS_CANDIDATE)

    def test_the_refusal_stages_are_the_contracts_own(self):
        for stage in (_validated(_payload(evidence_refs=[])).stage,
                      _validated(_payload(required_validation=[])).stage,
                      _packet(episodes=()).validate().stage):
            self.assertIn(stage, c.VALIDATION_STAGES, stage)


class BuilderTests(unittest.TestCase):
    def test_the_page_builder_produces_a_candidate_that_passes(self):
        candidate = _page_candidate()
        verdict = O.validate_candidate(candidate, packet=_packet())
        self.assertTrue(verdict.ok, verdict.as_row())
        self.assertEqual(candidate.analysis_type, O.CANDIDATE_PAGE)

    def test_the_skill_builder_produces_a_section_20_candidate(self):
        """Section 20's example, and the promotion chain it must ask for."""
        candidate = O.candidate_skill(
            skill_id="SKILL_TRAIN_TROOPS", goal_family="TRAINING",
            steps=[{"semantic_action": "CLICK[训练]", "expected_result": "MENU_OPEN"},
                   {"semantic_action": "CLICK[开始训练]", "expected_result": "QUEUE_STARTED"}],
            evidence_refs=[{"episode_id": "ep_001", "step": 1}], confidence=0.6,
            reason="两步稳定到达目标。",
        )
        verdict = O.validate_candidate(candidate, packet=_packet())
        self.assertTrue(verdict.ok, verdict.as_row())
        self.assertEqual(candidate.required_validation,
                         (O.VALIDATION_REPLAY, O.VALIDATION_SHADOW, O.VALIDATION_LIVE_VERIFIER))

    def test_the_failure_pattern_builder_still_needs_its_episodes(self):
        """A failure pattern is a claim about which episodes failed the same way."""
        without = O.candidate_failure_pattern(failure="TARGET_NOT_FOUND", evidence_refs=[])
        verdict = O.validate_candidate(without, packet=_packet())
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.code, O.OFFLINE_NO_EVIDENCE_REFS)

        with_evidence = O.candidate_failure_pattern(
            failure="TARGET_NOT_FOUND", evidence_refs=[{"episode_id": "ep_001"}],
            reason="同一控件两次未找到。")
        self.assertTrue(O.validate_candidate(with_evidence, packet=_packet()).ok)

    def test_the_navigation_edge_builder_needs_both_pages(self):
        candidate = O.candidate_navigation_edge(
            from_page="PAGE_CITY", to_page="PAGE_TRAINING", trigger="训练",
            evidence_refs=[{"episode_id": "ep_001", "frame_id": "f2"}], reason="稳定到达。")
        self.assertTrue(O.validate_candidate(candidate, packet=_packet()).ok)
        half = O.candidate_navigation_edge(from_page="PAGE_CITY", to_page="",
                                           evidence_refs=[{"episode_id": "ep_001"}])
        self.assertFalse(O.validate_candidate(half, packet=_packet()).ok)

    def test_a_candidate_row_says_it_is_a_candidate(self):
        row = _page_candidate().as_row(trace_id="t1")
        self.assertEqual(row["status"], "CANDIDATE")
        self.assertEqual(row["evidence_count"], 2)
        self.assertIn("not_yet", row)
        self.assertNotIn("x_norm", row)
        self.assertNotIn(c.VISION_BOX_KEY, row, "offline output has no region field to write")


class AdapterTests(unittest.TestCase):
    def test_episode_rows_reach_the_contracts_shape(self):
        packet = O.packet_from_episodes(
            [{"episode_id": "ep_001", "role_id": "role_01", "goal_id": "COLLECT_TRAINING",
              "frames": [{"frame_id": "f1", "path": "screens/f1.png", "page": "PAGE_TRAINING"}],
              "actions": [{"step": 1, "action": "CLICK_ELEMENT", "semantic_target": "训练"}],
              "verifier": {"outcome": "SUCCESS", "reason": "TRAINING_MENU_OPEN"}}],
            scope=O.LearningScope("TRAINING", "TRAINING", O.ROLE_SCOPE_SHARED, "c1"),
        )
        self.assertTrue(packet.validate().ok, packet.validate().as_row())
        self.assertEqual(packet.evidence_index(), {"ep_001": {"f1"}})
        self.assertEqual(packet.episodes[0].verifier.outcome, "SUCCESS")

    def test_a_cluster_without_named_evidence_produces_nothing(self):
        """Better to produce no candidate than one the validator will refuse on arrival."""
        class Cluster:
            cluster_id = "c1"
            representative = "screens/medoid.png"
            frames = ({"path": "screens/a.png"},)  # no episode_id: not citable

        self.assertIsNone(O.candidate_from_cluster(Cluster()))

    def test_the_real_cluster_type_is_what_the_adapter_reads(self):
        """Adapted against ``offline_learning``'s own dataclasses, not against an imagined shape.

        The producer names its frames ``representative`` / ``variants`` / ``members`` and the
        representative is a whole ``OfflineFrame`` rather than a path.  An adapter written for
        ``cluster.frames`` and ``str(cluster.representative)`` would find no evidence at all -- or
        raise on ``Path(frame_object)`` -- exactly when the nightly pass first produced real
        clusters, which is the worst moment for a typing layer to be wrong about its input.
        """
        from winter_agent_v2 import offline_learning

        def frame(path: str, episode: str) -> offline_learning.OfflineFrame:
            return offline_learning.OfflineFrame(
                frame_path=path, source="FAILURE_EPISODE", episode_id=episode, page_key="PAGE_X")

        medoid = frame("screens/medoid.png", "ep_001")
        variant = frame("screens/variant.png", "ep_001")
        member = frame("screens/member.png", "ep_002")
        cluster = offline_learning.UnknownCluster(
            cluster_id="cluster_007", size=3, representative=medoid,
            members=(medoid, member), variants=(variant,),
        )
        candidate = O.candidate_from_cluster(cluster)
        assert candidate is not None
        self.assertEqual(candidate.analysis_type, O.CANDIDATE_PAGE)
        self.assertEqual(candidate.payload["page_semantic"], "cluster_007")
        self.assertEqual(candidate.payload["visual_features"], ["medoid.png"])
        self.assertEqual([ref.frame_id for ref in candidate.evidence_refs],
                         ["medoid", "variant", "member"],
                         "the representative leads, and nothing is cited twice")
        self.assertEqual([ref.episode_id for ref in candidate.evidence_refs],
                         ["ep_001", "ep_001", "ep_002"])

    def test_a_cluster_of_the_real_type_is_cited_the_way_the_packet_names_frames(self):
        """The two adapters must agree on a frame's id, or every citation fails to resolve."""
        from winter_agent_v2 import offline_learning

        cluster = offline_learning.UnknownCluster(
            cluster_id="cluster_007", size=1,
            representative=offline_learning.OfflineFrame(
                frame_path="screens/medoid.png", source="FAILURE_EPISODE", episode_id="ep_001"),
        )
        candidate = O.candidate_from_cluster(cluster)
        assert candidate is not None
        packet = O.packet_from_episodes([{
            "episode_id": "ep_001",
            "frames": [{"path": "screens/medoid.png"}],
            "verifier": {"outcome": "SUCCESS"},
        }])
        self.assertEqual(packet.evidence_index(), {"ep_001": {"medoid"}})
        self.assertTrue(O.validate_candidate(candidate, packet=packet).ok)

    def test_a_cluster_becomes_a_page_candidate_without_inventing_a_page_name(self):
        """The clustering module keeps its own rule of not naming pages from pixels alone."""
        class Cluster:
            cluster_id = "cluster_007"
            representative = {"path": "screens/medoid.png", "hash_target": "screens/medoid.png"}
            frames = ({"path": "screens/f1.png", "episode_id": "ep_001", "frame_id": "f1"},
                      {"path": "screens/f3.png", "episode_id": "ep_002", "frame_id": "f3"})

        candidate = O.candidate_from_cluster(Cluster())
        assert candidate is not None
        self.assertEqual(candidate.analysis_type, O.CANDIDATE_PAGE)
        self.assertEqual(candidate.payload["page_semantic"], "cluster_007")
        self.assertEqual(len(candidate.evidence_refs), 2)
        self.assertTrue(O.validate_candidate(candidate, packet=_packet()).ok)

    def test_a_cluster_with_only_paths_cites_the_path_stem(self):
        """The fallback, and the convention a caller has to share with it.

        The path stem is used when the cluster carries no id -- and a packet whose episodes name
        their frames differently then refuses the candidate, which is the traceability rule doing
        its job rather than a defect: a citation nobody can resolve is not evidence.
        """
        class Cluster:
            cluster_id = "cluster_007"
            representative = {"path": "screens/a.png"}
            frames = ({"path": "screens/a.png", "episode_id": "ep_001"},
                      {"path": "screens/b.png", "episode_id": "ep_002"})

        candidate = O.candidate_from_cluster(Cluster())
        assert candidate is not None
        self.assertEqual([ref.frame_id for ref in candidate.evidence_refs], ["a", "b"])
        self.assertFalse(O.validate_candidate(candidate, packet=_packet()).ok)
        matching = O.packet_from_episodes(
            [{"episode_id": "ep_001", "frames": [{"frame_id": "a", "path": "screens/a.png"}]},
             {"episode_id": "ep_002", "frames": [{"frame_id": "b", "path": "screens/b.png"}]}],
            scope=O.LearningScope("T", "T", O.ROLE_SCOPE_SHARED, "c1"),
        )
        self.assertTrue(O.validate_candidate(candidate, packet=matching).ok)


class WiringTests(unittest.TestCase):
    """The offline pass's wiring: its clusters, typed through the contract and reported.

    What this layer is for, and what it deliberately is not: the nightly pass has already grouped
    the frames and written them, so the contract's job is to say which clusters could be *cited* --
    and to say it as a report rather than a gate, because a typing layer that could fail the pass
    would turn a nightly job into a nightly failure.
    """

    def _clusters(self) -> list[dict]:
        from winter_agent_v2 import offline_learning

        def row(cluster_id: str, episode: str, path: str) -> dict:
            return offline_learning.UnknownCluster(
                cluster_id=cluster_id, size=1,
                representative=offline_learning.OfflineFrame(
                    frame_path=path, source="FAILURE_EPISODE", episode_id=episode,
                    page_key="PAGE_X", failure_type="TARGET_NOT_FOUND"),
            ).as_row()

        return [row("cluster_001", "ep_001", "screens/a.png"),
                row("cluster_002", "ep_002", "screens/b.png"),
                row("cluster_003", "ep_003", "screens/c.png")]

    def test_the_passs_own_records_are_the_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for index, cluster in enumerate(self._clusters(), 1):
                (directory / f"cluster_00{index}.json").write_text(
                    json.dumps(cluster, ensure_ascii=False), encoding="utf-8")
            # A truncated record must be skipped, not fatal: an unreadable cluster file is not a
            # reason to lose the nightly report.
            (directory / "broken.json").write_text("{not json", encoding="utf-8")
            rows = O.clusters_from_dir(directory)
        self.assertEqual([row["cluster_id"] for row in rows],
                         ["cluster_001", "cluster_002", "cluster_003"])

    def test_every_cluster_is_typed_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = O.OfflineLedger(Path(tmp) / "offline.jsonl")
            report = O.record_clusters(self._clusters(), ledger=ledger)
            rows = ledger.rows()
        self.assertEqual(report["clusters"], 3)
        self.assertEqual(report["episodes"], 3)
        self.assertEqual(report["candidates"], 3)
        self.assertEqual(report["admitted"], 3, report)
        self.assertEqual(report["refused"], {})
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["status"], "CANDIDATE")
            self.assertTrue(row["admitted"])
            self.assertTrue(row["evidence_refs"], "a candidate with no citation is not a candidate")

    def test_a_cluster_with_no_provenance_is_counted_rather_than_dropped(self):
        """The count that the pass's own summary cannot express: `no_evidence`."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = O.OfflineLedger(Path(tmp) / "offline.jsonl")
            clusters = self._clusters() + [{"cluster_id": "cluster_004",
                                            "representative": {"path": "screens/d.png"}}]
            report = O.record_clusters(clusters, ledger=ledger)
            rows = ledger.rows()
        self.assertEqual(report["clusters"], 4)
        self.assertEqual(report["candidates"], 3)
        self.assertEqual(report["no_evidence"], 1)
        self.assertEqual(len(rows), 3, "nothing was invented for the cluster that had no episode")

    def test_the_packet_is_built_from_the_clusters_own_frames(self):
        """No second scan: the pass already said where every frame came from."""
        packet = O.packet_from_clusters(self._clusters())
        self.assertEqual(packet.evidence_index(),
                         {"ep_001": {"a"}, "ep_002": {"b"}, "ep_003": {"c"}})
        self.assertTrue(packet.validate().ok, packet.validate().as_row())
        self.assertEqual(packet.episodes[0].verifier.outcome, "TARGET_NOT_FOUND",
                         "the pass's own failure type, not an invented verdict")

    def test_an_episode_with_no_known_outcome_says_unknown_rather_than_success(self):
        """The pass groups pictures, not outcomes.  A guessed verdict would make the chain look
        complete when it is not."""
        packet = O.packet_from_clusters([{"cluster_id": "c", "members": [
            {"frame_path": "screens/a.png", "episode_id": "ep_001"}]}])
        self.assertEqual(packet.episodes[0].verifier.outcome, "UNKNOWN")
        self.assertTrue(packet.validate().ok, packet.validate().as_row())

    def test_the_report_names_its_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offline.jsonl"
            report = O.record_clusters(self._clusters(), ledger=O.OfflineLedger(path))
        self.assertEqual(report["ledger"], str(path))


class LedgerTests(unittest.TestCase):
    def test_a_candidate_row_carries_its_evidence_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = O.OfflineLedger(Path(tmp) / "offline.jsonl")
            candidate = _page_candidate()
            verdict = O.validate_candidate(candidate, packet=_packet())
            row = ledger.record_candidate(candidate, verdict=verdict, trace_id="t1")
            rows = ledger.rows()
        self.assertTrue(row["admitted"])
        self.assertEqual(rows[0]["status"], "CANDIDATE")
        self.assertEqual(rows[0]["evidence_count"], 2)
        self.assertEqual(rows[0]["evidence_refs"][0]["episode_id"], "ep_001")

    def test_a_refusal_is_recorded_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = O.OfflineLedger(Path(tmp) / "offline.jsonl")
            ledger.record_refusal(code=O.OFFLINE_NO_EVIDENCE_REFS, stage="GROUNDING",
                                  detail="no citation", trace_id="t2")
            rows = ledger.rows()
        self.assertFalse(rows[0]["admitted"])
        self.assertEqual(rows[0]["verdict"]["code"], O.OFFLINE_NO_EVIDENCE_REFS)
        self.assertEqual(rows[0]["verdict"]["family"], "OFFLINE")

    def test_the_offline_codes_fold_to_their_own_family(self):
        self.assertEqual(c.code_family(O.OFFLINE_GEOMETRY_TRANSPORTED), "OFFLINE")
        self.assertNotEqual(c.code_family(O.OFFLINE_GEOMETRY_TRANSPORTED),
                            c.code_family(c.PLAN_GEOMETRY_TRANSPORTED))

    def test_the_ledger_path_is_this_modes_own(self):
        self.assertEqual(O.OFFLINE_LEDGER_PATH.parts[0], "learning")
        self.assertNotEqual(O.OFFLINE_LEDGER_PATH, Path("learning/ui_venus_online.jsonl"))
        self.assertNotEqual(O.OFFLINE_LEDGER_PATH, Path("learning/ui_venus_repair.jsonl"))

    def test_the_three_modes_write_three_files(self):
        """Section 30's independence, as three paths that cannot collide."""
        from winter_agent_v2 import ui_venus_online, ui_venus_repair

        paths = {O.OFFLINE_LEDGER_PATH, ui_venus_online.ONLINE_LEDGER_PATH,
                 ui_venus_repair.REPAIR_LEDGER_PATH}
        self.assertEqual(len(paths), 3)
        for path in paths:
            self.assertEqual(path.parts[0], "learning")


class SchemaTests(unittest.TestCase):
    def test_the_schema_publishes_the_closed_vocabularies(self):
        schema = O.learning_schema()
        self.assertEqual(schema["properties"]["required_validation"]["items"]["enum"],
                         list(O.REQUIRED_VALIDATION_KINDS))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"],
                         ["analysis_type", "payload", "evidence_refs", "required_validation",
                          "reason"])

    def test_the_candidate_vocabulary_is_section_18s_seven(self):
        self.assertEqual(len(O.ANALYSIS_TYPES), 7)
        for name in ("CANDIDATE_PAGE", "CANDIDATE_UI_SEMANTIC", "FAILURE_PATTERN_CANDIDATE",
                     "CANDIDATE_STEP", "CANDIDATE_SKILL", "SKILL_REPAIR_CANDIDATE",
                     "NAVIGATION_EDGE_CANDIDATE"):
            self.assertIn(name, O.ANALYSIS_TYPES, name)

    def test_the_prompt_states_the_rules_the_validator_enforces(self):
        for phrase in ("ALREADY HAPPENED", "not a fact", "Your confidence is not verification",
                       "Cite your evidence", "Never output a click", "JSON only",
                       "one short sentence"):
            self.assertIn(phrase, O.SYSTEM_PROMPT, phrase)

    def test_the_prompt_does_not_offer_a_geometry_option(self):
        self.assertNotIn("candidate_bbox_norm", O.SYSTEM_PROMPT)
        self.assertNotIn("bounding box", O.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
