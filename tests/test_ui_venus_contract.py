"""The shared half of the UI-Venus contract, pinned.

Operator directive 2026-10-01, sections 0-3, 5, 10, 13, 23, 25, 26 and 31.  What is tested here is
the vocabulary three modes agree on, because that is the part where a change in one mode silently
changes another's meaning -- and the module exists precisely to stop that.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import context_budget
from winter_agent_v2 import ui_venus_contract as c


class BudgetTests(unittest.TestCase):
    def test_the_contracts_window_is_the_one_the_server_is_started_with(self):
        """Section 2's numbers, pinned against the single place they are configured.

        A contract that states its own window is one indirection away from disagreeing with the
        process that reads it; this fails the moment either side moves.
        """
        self.assertEqual(c.MAX_MODEL_CONTEXT, context_budget.MAX_MODEL_CONTEXT)
        self.assertEqual(c.OUTPUT_RESERVE, context_budget.OUTPUT_RESERVE)
        self.assertEqual(c.MAX_INPUT_TOKENS, context_budget.MAX_INPUT_BUDGET)

    def test_the_trimming_ladder_never_names_p0(self):
        """Section 2: "不得裁掉 P0" -- and the ladder is the place that could break it."""
        self.assertTrue(c.TRIMMING_ORDER)
        for step in c.TRIMMING_ORDER:
            self.assertNotIn("P0", step, f"{step} trims a P0 section")
        # Section 2's own order, oldest history first, and the full OCR of a *previous* frame is
        # second: the point is that the current frame's evidence is never what gets dropped.
        self.assertEqual(c.TRIMMING_ORDER[0], "P2_OLD_HISTORY")
        self.assertEqual(c.TRIMMING_ORDER[-1], "EARLIER_ACTION_HISTORY")


class ConfidenceTests(unittest.TestCase):
    def test_confirmed_outranks_observed_outranks_candidate(self):
        self.assertGreater(c.confidence_rank(c.CONFIDENCE_CONFIRMED),
                           c.confidence_rank(c.CONFIDENCE_OBSERVED))
        self.assertGreater(c.confidence_rank(c.CONFIDENCE_OBSERVED),
                           c.confidence_rank(c.CONFIDENCE_CANDIDATE))

    def test_an_unknown_level_ranks_lowest_rather_than_raising(self):
        """The failure to design against is a typo'd 'CONFIRMED' being read as a measurement."""
        self.assertEqual(c.confidence_rank("CONFIRMED!"), 0)
        self.assertEqual(c.confidence_rank(""), 0)

    def test_a_candidate_is_not_readable_as_a_game_fact(self):
        """Section 23: candidate knowledge must not be dressed as a fact in the prompt."""
        self.assertFalse(c.confidence_is_readable_as_fact(c.CONFIDENCE_CANDIDATE))
        self.assertTrue(c.confidence_is_readable_as_fact(c.CONFIDENCE_OBSERVED))
        self.assertTrue(c.confidence_is_readable_as_fact(c.CONFIDENCE_CONFIRMED))

    def test_a_knowledge_item_normalises_a_hand_written_level(self):
        item = c.KnowledgeItem(id="K1", text="x", confidence="probably")
        self.assertEqual(item.as_wire()["confidence"], c.CONFIDENCE_CANDIDATE)

    def test_bucketing_accepts_rows_objects_and_bare_levels(self):
        class Row:
            confidence = c.CONFIDENCE_OBSERVED

        buckets = c.bucket_confidence([
            c.CONFIDENCE_CONFIRMED, {"confidence": "OBSERVED"}, "CANDIDATE", Row(), "nonsense",
        ])
        self.assertEqual(buckets.as_row(), {"confirmed": 1, "observed": 2, "candidate": 2})
        self.assertEqual(buckets.total, 5)


class RiskTests(unittest.TestCase):
    def test_the_default_envelope_is_closed(self):
        """A caller that forgets to fill this in must get the restrictive envelope, not an open one."""
        env = c.RiskEnvelope()
        self.assertEqual(env.level, c.RISK_LOW)
        self.assertFalse(env.spending_allowed)
        self.assertEqual(env.authorized_actions, ())

    def test_real_money_is_never_allowed(self):
        """Section 25 makes this permanent, so it is a property rather than a field."""
        self.assertFalse(c.RiskEnvelope().real_money_allowed)
        self.assertFalse(c.RiskEnvelope(level="HIGH", spending_allowed=True).real_money_allowed)
        self.assertFalse(c.RiskEnvelope().as_wire()["real_money_allowed"])
        with self.assertRaises(TypeError):
            c.RiskEnvelope(real_money_allowed=True)  # noqa - the point is that there is no such field

    def test_a_spend_is_blocked_while_spending_is_not_allowed(self):
        allowed, code = c.RiskEnvelope().permits("CLICK_ELEMENT", identity="购买 钻石")
        self.assertFalse(allowed)
        self.assertEqual(code, c.PLAN_SPEND_BLOCKED)

    def test_a_high_risk_action_needs_the_goal_to_have_authorized_it(self):
        """Section 25's own list, and the reason is the *thing acted on* not the action's name."""
        for identity in ("攻击", "发起集结", "撤回", "加速"):
            allowed, code = c.RiskEnvelope().permits("CLICK_ELEMENT", identity=identity)
            self.assertFalse(allowed, identity)
            self.assertEqual(code, c.PLAN_ACTION_NOT_AUTHORIZED, identity)

    def test_an_authorized_high_risk_action_is_allowed(self):
        env = c.RiskEnvelope(level="HIGH", authorized_actions=("START_RALLY",))
        allowed, code = env.permits("START_RALLY", identity="发起集结")
        self.assertTrue(allowed, code)

    def test_an_ordinary_control_is_allowed_by_the_closed_default(self):
        allowed, code = c.RiskEnvelope().permits("CLICK_ELEMENT", identity="每日免费领取")
        self.assertTrue(allowed, code)

    def test_the_high_risk_vocabulary_is_the_one_learning_uses(self):
        """Two risk vocabularies are two risk rules; this is the assertion that there is one."""
        from winter_agent_v2 import unknown_learning

        self.assertEqual(c.HIGH_RISK_WORDS, unknown_learning.HIGH_RISK_WORDS)
        for action in c.HIGH_RISK_ACTIONS:
            self.assertIn(action, c.HIGH_RISK_WORDS)


class FrameIdentityTests(unittest.TestCase):
    def test_a_matching_pair_is_consistent(self):
        same = c.FrameIdentity("f1", "sha256:aa")
        self.assertEqual(c.frame_consistency(same, same), "")

    def test_a_different_hash_is_a_mismatch(self):
        """The re-capture-into-the-same-slot case, which an id-only check would miss."""
        code = c.frame_consistency(
            c.FrameIdentity("f1", "sha256:aa"), c.FrameIdentity("f1", "sha256:bb"))
        self.assertEqual(code, c.CONTEXT_FRAME_MISMATCH)

    def test_a_different_id_is_a_mismatch(self):
        code = c.frame_consistency(
            c.FrameIdentity("f1", "sha256:aa"), c.FrameIdentity("f2", "sha256:aa"))
        self.assertEqual(code, c.CONTEXT_FRAME_MISMATCH)

    def test_an_unmeasured_pair_is_refused_by_the_strict_form(self):
        """"We did not measure it" must not pass as "it matched"."""
        self.assertEqual(
            c.frame_consistency(c.FrameIdentity(), c.FrameIdentity()), c.CONTEXT_FRAME_MISMATCH)

    def test_of_digests_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.png"
            path.write_bytes(b"frame-one")
            first = c.FrameIdentity.of(path, frame_id="f1")
            self.assertTrue(first.complete)
            self.assertTrue(first.frame_hash.startswith("sha256:"))
            path.write_bytes(b"frame-two")
            self.assertNotEqual(c.FrameIdentity.of(path, frame_id="f1").frame_hash, first.frame_hash)

    def test_of_a_missing_file_is_incomplete_rather_than_wrong(self):
        identity = c.FrameIdentity.of("/nonexistent/frame.png")
        self.assertFalse(identity.complete)
        self.assertEqual(identity.frame_hash, "")


class GeometryTests(unittest.TestCase):
    def test_a_normalised_box_is_read(self):
        box, error = c.read_box([0.1, 0.2, 0.3, 0.4])
        self.assertEqual(box, (0.1, 0.2, 0.3, 0.4))
        self.assertEqual(error, "")

    def test_a_pixel_box_fails_the_range_check_by_construction(self):
        """Section 9/10: the one geometry channel cannot carry a pixel, and this is why."""
        box, error = c.read_box([340, 812, 10, 10])
        self.assertIsNone(box)
        self.assertEqual(error, c.PLAN_BOX_NOT_NORMALISED)

    def test_a_box_that_leaves_the_frame_is_refused(self):
        box, error = c.read_box([0.9, 0.9, 0.5, 0.5])
        self.assertIsNone(box)
        self.assertEqual(error, c.PLAN_BOX_OUTSIDE_FRAME)

    def test_the_named_key_form_is_tolerated_when_it_is_already_normalised(self):
        box, error = c.read_box({"x_norm": 0.0, "y_norm": 0.0, "w_norm": 0.5, "h_norm": 0.5})
        self.assertEqual(box, (0.0, 0.0, 0.5, 0.5))
        self.assertEqual(error, "")

    def test_a_forbidden_key_is_found_by_name(self):
        self.assertEqual(
            c.find_forbidden_geometry({"decision": "EXECUTE", "x": 340}), "x")
        self.assertEqual(
            c.find_forbidden_geometry({"a": {"b": {"tap": [1, 2]}}}), "a.b.tap")

    def test_the_one_allowed_key_is_skipped_by_the_recursion(self):
        """A nested {"x": ...} inside the box key is not smuggled past -- the reader refuses it."""
        self.assertEqual(
            c.find_forbidden_geometry({c.VISION_BOX_KEY: [0.1, 0.2, 0.3, 0.4]}), "")
        self.assertEqual(
            c.find_forbidden_geometry({c.VISION_BOX_KEY: {"x": 340}}), "")


class ReasonTests(unittest.TestCase):
    def test_one_short_sentence_is_fine(self):
        self.assertEqual(c.reason_violation("当前帧 E2 是可执行训练控件。"), "")

    def test_a_paragraph_is_refused(self):
        self.assertEqual(c.reason_violation("因为画面信息不足。" * 8), c.PLAN_REASON_TOO_LONG)

    def test_two_sentences_are_already_a_plan(self):
        self.assertEqual(c.reason_violation("先点这里。再看那里。"), c.PLAN_REASON_TOO_LONG)

    def test_the_cap_is_the_one_the_schema_declares(self):
        self.assertEqual(c.reason_violation("a" * (c.REASON_MAX_CHARS + 1)), c.PLAN_REASON_TOO_LONG)


class VocabularyTests(unittest.TestCase):
    def test_a_legacy_refusal_folds_onto_the_contracts_name(self):
        """The planner predates this contract and its strings are pinned; the fold is here."""
        self.assertEqual(
            c.canonical_code("PLAN_TARGET_NOT_ON_THIS_SCREEN: 'E9'"),
            c.PLAN_TARGET_NOT_ON_THIS_FRAME)
        self.assertEqual(
            c.canonical_code("PLAN_ACTION_NOT_OFFERED: 'SCROLL'"), c.PLAN_ACTION_NOT_ALLOWED)
        self.assertEqual(
            c.canonical_code("PLAN_TRANSPORTED_GEOMETRY: x"), c.PLAN_GEOMETRY_TRANSPORTED)

    def test_a_refusal_is_grouped_by_family(self):
        self.assertEqual(c.code_family(c.PLAN_SPEND_BLOCKED), "AUTHORITY")
        self.assertEqual(c.code_family(c.PLAN_TARGET_NOT_ON_THIS_FRAME), "TARGET")
        self.assertEqual(c.code_family(c.UNKNOWN_GROUNDING_FAILED), "GROUNDING")
        self.assertEqual(c.code_family(c.CONTEXT_FRAME_MISMATCH), "FRAME")
        self.assertEqual(c.code_family("PLAN_TARGET_NOT_ON_THIS_SCREEN: x"), "TARGET")

    def test_the_three_modes_have_their_own_families(self):
        """Section 30: the refusal vocabularies stay distinguishable in one folded report."""
        self.assertEqual(c.code_family("REPAIR_NO_EVIDENCE_REFS"), "REPAIR")
        self.assertEqual(c.code_family("OFFLINE_DECISION_EXECUTE_FORBIDDEN"), "OFFLINE")

    def test_every_refusal_code_is_listed(self):
        for name in (c.PLAN_NOT_JSON, c.PLAN_SCHEMA_INVALID, c.PLAN_BBOX_UNNECESSARY,
                     c.PLAN_FRAME_STALE, c.PLAN_GOAL_SCOPE_VIOLATION, c.PLAN_SPEND_BLOCKED,
                     c.CONTEXT_FRAME_MISMATCH, c.UNKNOWN_GROUNDING_FAILED):
            self.assertIn(name, c.REFUSAL_CODES, name)

    def test_the_validation_chain_is_the_directives_order(self):
        self.assertEqual(c.VALIDATION_STAGES[0], "JSON_PARSE")
        self.assertEqual(c.VALIDATION_STAGES[-1], "GROUNDING")
        for stage in ("GOAL_SCOPE", "ROLE_SCOPE", "ALLOWED_ACTIONS", "ELEMENT_EXISTENCE",
                      "FRAME_CONSISTENCY", "RISK_SPEND"):
            self.assertIn(stage, c.VALIDATION_STAGES)

    def test_complete_is_a_claim_with_its_own_name(self):
        self.assertEqual(c.MODEL_COMPLETE_CLAIM, "MODEL_COMPLETE_CLAIM")
        self.assertIn("COMPLETE", c.DECISIONS)
        self.assertIn("COMPLETE", c.NON_TAPPING_DECISIONS)


class FunnelVocabularyTests(unittest.TestCase):
    def test_the_sixteen_layers_are_the_directives_sixteen(self):
        self.assertEqual(len(c.FUNNEL_LAYERS), 16)
        self.assertEqual(c.FUNNEL_LAYERS[0], "unknown_observed")
        self.assertEqual(c.FUNNEL_LAYERS[-1], "stable_promoted")
        for name in ("venus_called", "venus_proposed", "grounding_rejected", "risk_gate_rejected",
                     "candidate_replay_pass", "candidate_shadow_pass"):
            self.assertIn(name, c.FUNNEL_LAYERS)

    def test_every_ratio_names_two_real_layers(self):
        for numerator, denominator in c.FUNNEL_RATIOS:
            self.assertIn(numerator, c.FUNNEL_LAYERS)
            self.assertIn(denominator, c.FUNNEL_LAYERS)

    def test_a_trace_row_carries_both_ids(self):
        """Section 26 requires a trace id and the id of the layer it came from."""
        row = c.TraceRow(layer="venus_proposed", trace_id="t1", source_id="unknown-1",
                         mode=c.MODE_ONLINE, recorded_at="now").as_row()
        self.assertEqual(row["trace_id"], "t1")
        self.assertEqual(row["source_id"], "unknown-1")
        self.assertEqual(row["layer"], "venus_proposed")
        self.assertEqual(row["mode"], c.MODE_ONLINE)

    def test_a_trace_rows_code_is_folded(self):
        row = c.TraceRow(layer="grounding_rejected", trace_id="t", code="PLAN_BBOX_UNNECESSARY:")
        self.assertEqual(row.as_row()["code"], c.PLAN_BBOX_UNNECESSARY)


class LedgerTests(unittest.TestCase):
    def test_a_ledger_appends_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = c.Ledger(Path(tmp) / "l.jsonl")
            self.assertTrue(ledger.append({"a": 1}))
            self.assertTrue(ledger.append({"b": "中文"}))
            rows = ledger.rows()
        self.assertEqual([row.get("a") for row in rows], [1, None])
        self.assertEqual(rows[1]["b"], "中文")

    def test_a_ledger_keeps_the_newest_rows_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = c.Ledger(Path(tmp) / "l.jsonl", limit=3)
            for index in range(6):
                ledger.append({"i": index})
            rows = ledger.rows()
        self.assertEqual([row["i"] for row in rows], [3, 4, 5])

    def test_something_unserialisable_is_refused_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = c.Ledger(Path(tmp) / "l.jsonl")
            self.assertTrue(ledger.append({"ok": 1}))
            self.assertFalse(c.append_row(Path(tmp) / "bad" / "l.jsonl", None), "not a mapping")
            self.assertEqual(len(ledger.rows()), 1)

    def test_unreadable_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.jsonl"
            path.write_text('{"a": 1}\nnot json\n\n{"b": 2}\n', encoding="utf-8")
            rows = c.read_rows(path)
        self.assertEqual(len(rows), 2)

    def test_a_missing_file_reads_as_empty(self):
        self.assertEqual(c.read_rows("/nonexistent/ledger.jsonl"), [])

    def test_each_mode_has_its_own_path(self):
        """Section 30: three independent ledgers, which is a fact about the paths."""
        from winter_agent_v2 import ui_venus_offline, ui_venus_online, ui_venus_repair

        paths = {ui_venus_online.ONLINE_LEDGER_PATH, ui_venus_repair.REPAIR_LEDGER_PATH,
                 ui_venus_offline.OFFLINE_LEDGER_PATH}
        self.assertEqual(len(paths), 3)
        for path in paths:
            self.assertEqual(path.parts[0], "learning", str(path))


class GateTests(unittest.TestCase):
    def test_a_gate_record_is_not_verified_by_default(self):
        self.assertFalse(c.GateRecord().verified)

    def test_a_projector_alone_is_not_evidence(self):
        record = c.GateRecord(backend="llama.cpp", mmproj_loaded=True,
                              with_image_reply="the count reads 62,795,625",
                              text_only_reply="the count reads 62,795,625")
        self.assertFalse(record.verified, "an identical answer proves nothing about the picture")

    def test_an_answer_that_differs_with_the_picture_is_evidence(self):
        record = c.GateRecord(
            backend="llama.cpp", model="UI-Venus-2-9B", quantization="Q4_K_M",
            mmproj_loaded=True, image_resolution="720x1280",
            image_encoding="data-url/base64/png", latency_ms=5774.7, ram_mb=1234.0, vram_mb=4096.0,
            text_only_reply="the largest text is Play Now",
            with_image_reply="the largest readable text is 62,795,625",
        )
        self.assertTrue(record.verified)
        row = record.as_row()
        self.assertTrue(row[c.SCREENSHOT_INPUT_VERIFIED])
        self.assertEqual(row["unmeasured_fields"], [])

    def test_the_record_says_which_fields_it_could_not_measure(self):
        """Section 31 lists the fields; a record that silently omitted one would be an overclaim."""
        row = c.GateRecord(mmproj_loaded=True, with_image_reply="a",
                           text_only_reply="b").as_row()
        self.assertIn("vram_mb", row["unmeasured_fields"])
        self.assertIn("quantization", row["unmeasured_fields"])


class SerialisationTests(unittest.TestCase):
    def test_json_keeps_the_clients_own_script_readable(self):
        self.assertIn("领取", c.to_json({"text": "领取"}))

    def test_a_digest_is_stable_and_order_independent(self):
        self.assertEqual(c.digest_of({"a": 1, "b": 2}), c.digest_of({"b": 2, "a": 1}))
        self.assertNotEqual(c.digest_of({"a": 1}), c.digest_of({"a": 2}))

    def test_a_world_state_is_bounded(self):
        state = {"page": "P", "confidence": 0.9, "junk": "x" * 500,
                 "resources": list(range(50)), "unknown_field": 1}
        out = c.compact_state(state, ("page", "confidence", "junk", "resources"))
        self.assertEqual(out["page"], "P")
        self.assertLessEqual(len(out["junk"]), 200)
        self.assertEqual(len(out["resources"]), 8)
        self.assertNotIn("unknown_field", out)


if __name__ == "__main__":
    unittest.main()
