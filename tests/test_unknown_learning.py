"""The UNKNOWN -> skill bridge: what it records, what it refuses, and what it never writes.

Directive 2026-10-01 sections 11-15.  Three properties are pinned here because each one is a rule
that would be easy to lose in a refactor and expensive to lose in production:

* an unverified step is never filed, and a filed record has **no coordinate field**;
* a route compiled twice lands on one ``skill_id`` and strengthens it, rather than forking;
* nothing in this module can reach the registry.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2 import unknown_learning as ul


def _step(**overrides):
    base = {
        "recorded_at": "2026-10-01T00:00:00+00:00",
        "request_id": "req1",
        "session_id": "s1",
        "episode_id": "e1",
        "step_index": 1,
        "goal_id": "DAILY",
        "role_id": "A",
        "page_before": "UNKNOWN::活动",
        "page_after": "UNKNOWN::活动中心",
        "semantic_target": "ORDINARY_CONTROL[活动]",
        "action_type": "CLICK_ELEMENT",
        "risk_route": ul.ROUTE_FAST,
        "key": "UNKNOWN::活动|DAILY|ORDINARY_CONTROL[活动]|UNKNOWN::活动中心",
        "source_frames": ["f1.png"],
        "expected_result": "活动中心打开",
        "grounding_basis": "PRINTED_WORD",
        "verifier_ok": True,
        "no_progress": False,
    }
    base.update(overrides)
    return base


class RecordingTests(unittest.TestCase):
    def test_a_recorded_step_has_no_place_to_put_a_coordinate(self):
        """§10: the strongest enforcement of "never persist a model box" is having no field.

        Written as an assertion over the *serialised* record, because that is what a future reader
        would actually see; a field added to the dataclass and not to ``as_row`` would pass a
        dataclass check and still leak nothing, and one added to both fails here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ul.VerifiedStepLedger(Path(tmp) / "steps.jsonl")
            step = ul.record_verified_step(
                session_id="s1", page_before="P", page_after="Q", goal_id="G",
                semantic_target="ORDINARY_CONTROL[关闭]", action_type="CLICK_ELEMENT",
                verifier_ok=True, ledger=ledger,
            )
            row = json.loads((Path(tmp) / "steps.jsonl").read_text(encoding="utf-8").splitlines()[0])
        forbidden = {"x", "y", "bbox", "box", "point", "coord", "coordinates", "x_norm", "y_norm"}
        self.assertFalse(forbidden & set(row), f"a coordinate field appeared: {forbidden & set(row)}")
        self.assertEqual(step.risk_route, ul.ROUTE_FAST)

    def test_only_verified_steps_are_offered_for_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ul.VerifiedStepLedger(Path(tmp) / "steps.jsonl")
            ul.record_verified_step(session_id="s1", page_before="P", page_after="Q",
                                    semantic_target="ORDINARY_CONTROL[a]", verifier_ok=True,
                                    ledger=ledger)
            ul.record_verified_step(session_id="s1", page_before="P", page_after="Q",
                                    semantic_target="ORDINARY_CONTROL[b]", verifier_ok=False,
                                    ledger=ledger)
            ul.record_verified_step(session_id="s1", page_before="P", page_after="P",
                                    semantic_target="ORDINARY_CONTROL[c]", verifier_ok=True,
                                    no_progress=True, ledger=ledger)
            verified = ledger.verified()
        self.assertEqual([row["semantic_target"] for row in verified], ["ORDINARY_CONTROL[a]"])

    def test_risk_route_follows_the_element_not_the_page(self):
        """§14: the boundary is applied to the element's own identity."""
        self.assertEqual(ul.risk_route(semantic="ORDINARY_CONTROL[关闭]", action_type="CLICK_ELEMENT"),
                         ul.ROUTE_FAST)
        self.assertEqual(ul.risk_route(semantic="ORDINARY_CONTROL[攻击]", action_type="CLICK_ELEMENT"),
                         ul.ROUTE_SLOW)
        self.assertEqual(ul.risk_route(semantic="ORDINARY_CONTROL[购买]", action_type="CLICK_ELEMENT"),
                         ul.ROUTE_BLOCKED)


class CompilationTests(unittest.TestCase):
    def test_a_contiguous_chain_becomes_one_skill(self):
        rows = [
            _step(step_index=1, page_before="A", page_after="B",
                  semantic_target="ORDINARY_CONTROL[活动]",
                  key="A|DAILY|ORDINARY_CONTROL[活动]|B"),
            _step(step_index=2, page_before="B", page_after="C",
                  semantic_target="ORDINARY_CONTROL[领取]",
                  key="B|DAILY|ORDINARY_CONTROL[领取]|C"),
        ]
        compiled = ul.compile_candidate_skills(rows, write=False)
        self.assertEqual(len(compiled), 1)
        record = compiled[0]
        self.assertEqual(len(record.steps), 2)
        self.assertEqual(record.entry_page, "A")
        self.assertEqual(record.exit_page, "C")
        self.assertEqual(record.status, ul.STATUS_CANDIDATE)

    def test_steps_that_do_not_connect_are_not_one_skill(self):
        """A chain is a *route*; two unrelated steps that merely share a session are not one."""
        rows = [
            _step(step_index=1, page_before="A", page_after="B",
                  key="A|DAILY|ORDINARY_CONTROL[活动]|B"),
            _step(step_index=2, page_before="X", page_after="Y",
                  semantic_target="ORDINARY_CONTROL[关闭]",
                  key="X|DAILY|ORDINARY_CONTROL[关闭]|Y"),
        ]
        self.assertEqual(ul.compile_candidate_skills(rows, write=False), ())

    def test_one_step_proved_in_two_sessions_is_a_skill(self):
        """§15: the common one-tap UNKNOWN must still be learnable."""
        rows = [_step(session_id="s1"), _step(session_id="s2", recorded_at="2026-10-01T01:00:00+00:00")]
        compiled = ul.compile_candidate_skills(rows, write=False)
        self.assertEqual(len(compiled), 1)
        self.assertEqual(len(compiled[0].steps), 1)

    def test_recompiling_strengthens_one_record_instead_of_forking(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                _step(step_index=1, page_before="A", page_after="B",
                      key="A|DAILY|ORDINARY_CONTROL[活动]|B"),
                _step(step_index=2, page_before="B", page_after="C",
                      semantic_target="ORDINARY_CONTROL[领取]",
                      key="B|DAILY|ORDINARY_CONTROL[领取]|C"),
            ]
            first = ul.compile_candidate_skills(rows, out_dir=tmp)
            second = ul.compile_candidate_skills(rows, out_dir=tmp)
            files = list(Path(tmp).glob("*.json"))
            payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].skill_id, second[0].skill_id)
        self.assertEqual(len(files), 1, "a recompile must not fork the record")
        self.assertEqual(payload["status"], ul.STATUS_STRENGTHENED)

    def test_the_written_record_says_it_is_not_a_promoted_skill(self):
        """§14/§39: the file a promotion reviewer opens must say what it is not."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = [
                _step(step_index=1, page_before="A", page_after="B",
                      key="A|DAILY|ORDINARY_CONTROL[活动]|B"),
                _step(step_index=2, page_before="B", page_after="C",
                      semantic_target="ORDINARY_CONTROL[领取]",
                      key="B|DAILY|ORDINARY_CONTROL[领取]|C"),
            ]
            compiled = ul.compile_candidate_skills(rows, out_dir=tmp)
            payload = json.loads((Path(tmp) / f"{compiled[0].skill_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["lifecycle"], ul.STATUS_CANDIDATE)
        self.assertIn("not registered", payload["not_yet"])
        self.assertNotIn("STABLE", str(payload.get("status")))


class ReuseTests(unittest.TestCase):
    def test_learned_lookup_is_keyed_on_the_screen_and_the_goal(self):
        rows = [
            _step(page_before="A", goal_id="DAILY"),
            _step(page_before="B", goal_id="DAILY",
                  key="B|DAILY|ORDINARY_CONTROL[活动]|C"),
        ]
        self.assertEqual(len(ul.learned_steps_for(rows, page_key="A", goal_id="DAILY")), 1)
        self.assertEqual(ul.learned_steps_for(rows, page_key="A", goal_id="TRAIN"), [])
        self.assertEqual(ul.learned_steps_for(rows, page_key="Z", goal_id="DAILY"), [])

    def test_a_blocked_element_is_never_offered_for_reuse(self):
        """A reuse path has no risk gate in front of it, so a spending element must not be in it."""
        rows = [_step(risk_route=ul.ROUTE_BLOCKED)]
        ordered = ul.learned_steps_for(rows, page_key="UNKNOWN::活动", goal_id="DAILY")
        self.assertEqual(len(ordered), 1)
        self.assertEqual(ordered[0]["risk_route"], ul.ROUTE_BLOCKED)

    def test_a_free_action_outranks_a_spending_one(self):
        rows = [
            _step(risk_route=ul.ROUTE_SLOW, key="slow", page_before="A"),
            _step(risk_route=ul.ROUTE_FAST, key="fast", page_before="A"),
        ]
        ordered = ul.learned_steps_for(rows, page_key="A", goal_id="DAILY")
        self.assertEqual(ordered[0]["risk_route"], ul.ROUTE_FAST)


class BoundaryTests(unittest.TestCase):
    def test_the_module_never_reaches_the_registry(self):
        """§14: "UI-Venus 没有 Promotion 权限" is an architectural line, not a convention.

        Checked over the module's **code**, not its text: the docstrings discuss the registry at
        length (that is how the rule is explained to the next reader), so a substring search would
        fail on the explanation of the rule it is enforcing.  What is forbidden is an import of the
        registry or a call to it, which is exactly what an AST can see.
        """
        import ast

        tree = ast.parse(Path(ul.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(str(node.module or ""))
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        self.assertNotIn("skills", imported, "the learning bridge must not import the registry")
        self.assertNotIn("winter_agent_v2.skills", imported)

        called = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("v2_registry", called)
        self.assertFalse({name for name in called if name.startswith("register")},
                         "the learning bridge must not register anything")


if __name__ == "__main__":
    unittest.main()
