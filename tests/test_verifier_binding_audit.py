"""The verifier-shape audit.

Regression under test (2026-09-17)
----------------------------------
``LiveRuntime.Verifier`` is ``Callable[[WorldState, WorldState], VerificationResult]``
and the step loop calls ``VERIFIED_ATOMIC[skill](before, after)``, so a verifier
cannot receive a decision's identity.  ``verifier.py`` carries 18 verifiers written
to other shapes -- a skill parameter, an intermediate frame, or a bare state -- and
binding one raises nothing at import time and is never validated, so "cannot be
bound" is indistinguishable from "was never written" and the skill it serves sits at
BLOCKED/CANDIDATE forever.

Three of them (BUILDING_UPGRADE, TRAIN_TROOPS, RESEARCH) are dispatchable anyway
through a lambda adapter in ``runtime.py`` that injects a value read from the before
frame.  Whether that leaves the verifier meaningful has to be read per verifier: the
training and research ones compare the injected value against the *after* state (a
real cross-check), while the building one only makes its first conjunct tautological.

This session's own three wrong first guesses -- "3 args means 3 frames", "all 18 are
unbindable", "self-referential injection is fabrication" -- are why these tests pin
the *measurement* rather than a tidy story.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import verifier_binding_audit as audit  # noqa: E402


class ShapeTaxonomyTest(unittest.TestCase):
    def test_a_two_frame_verifier_is_callable(self):
        shape = audit.VerifierShape("verify_popup_closed", ("before", "after"))
        self.assertEqual(shape.kind, "TWO_FRAME")
        self.assertTrue(shape.callable_by_runtime)

    def test_a_skill_parameter_is_not_a_frame(self):
        shape = audit.VerifierShape(
            "verify_building_upgrade", ("before", "after", "building_id"))
        self.assertEqual(shape.kind, "PARAMETER")
        self.assertFalse(shape.callable_by_runtime)

    def test_an_intermediate_frame_is_its_own_family(self):
        shape = audit.VerifierShape(
            "verify_alliance_gifts_claim", ("before", "reward", "after"))
        self.assertEqual(shape.kind, "FRAME")

    def test_a_single_state_argument_is_its_own_family(self):
        self.assertEqual(audit.VerifierShape("verify_gathering", ("state",)).kind, "STATE")

    def test_a_parameter_in_first_position_is_still_a_parameter(self):
        # verify_mail_tab_selected(expected_tab, before, after): position cannot
        # classify these, only the name can.
        shape = audit.VerifierShape(
            "verify_mail_tab_selected", ("expected_tab", "before", "after"))
        self.assertEqual(shape.kind, "PARAMETER")

    def test_shapes_are_read_from_the_real_file(self):
        shapes = audit.verifier_shapes()
        self.assertEqual(shapes["verify_building_upgrade"].kind, "PARAMETER")
        self.assertEqual(shapes["verify_alliance_tech_contribution"].kind, "FRAME")
        self.assertEqual(shapes["verify_popup_closed"].kind, "TWO_FRAME")


class AdapterBindingTest(unittest.TestCase):
    def test_the_three_adapters_are_found_with_the_argument_they_inject(self):
        adapters = audit.adapter_bindings()
        self.assertEqual(
            set(adapters),
            {"BUILDING_UPGRADE", "RESEARCH", "TRAIN_TROOPS"},
        )
        for binding in adapters.values():
            self.assertTrue(binding.reads_before_frame, binding.skill)
            self.assertTrue(binding.injected.startswith("str(before."), binding.skill)

    def test_each_adapter_names_a_real_verifier(self):
        shapes = audit.verifier_shapes()
        for binding in audit.adapter_bindings().values():
            self.assertIn(binding.verifier, shapes)


class LiveHistoryTest(unittest.TestCase):
    def _run(self, rows: list[dict]) -> dict[str, tuple[int, int]]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fake = Path(directory.name) / "episodes.jsonl"
        fake.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        with patch.object(audit, "EPISODES", fake):
            return audit.live_history()

    def test_a_row_without_recorded_at_is_not_an_attempt(self):
        # This is the mistake that produced four phantom successes for
        # ALLIANCE_TECH_CONTRIBUTE.
        history = self._run([
            {"skill": "ALLIANCE_TECH_CONTRIBUTE", "result": "success"},
            {"skill": "ALLIANCE_TECH_CONTRIBUTE", "result": "success"},
        ])
        self.assertNotIn("ALLIANCE_TECH_CONTRIBUTE", history)

    def test_dated_rows_are_counted_and_success_is_case_insensitive(self):
        history = self._run([
            {"skill": "BACK", "result": "SUCCESS", "recorded_at": "2026-09-17T00:00:00Z"},
            {"skill": "BACK", "result": "success", "recorded_at": "2026-09-17T00:01:00Z"},
            {"skill": "BACK", "result": "FAILURE", "recorded_at": "2026-09-17T00:02:00Z"},
        ])
        self.assertEqual(history["BACK"], (3, 2))

    def test_a_missing_file_is_not_an_error(self):
        with patch.object(audit, "EPISODES", Path("Z:/nope/episodes.jsonl")):
            self.assertEqual(audit.live_history(), {})


class CurrentTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.shapes, cls.adapters = audit.collect()
        cls.by_skill = {r.skill: r for r in cls.rows}
        cls.families = audit.unbound_families(cls.rows, cls.shapes, cls.adapters)

    def test_every_registered_skill_gets_a_row(self):
        from winter_agent_v2.skills import v2_registry

        self.assertEqual(len(self.rows), len(v2_registry().all()))

    def test_build_train_and_research_are_dispatchable_through_an_adapter(self):
        # They were the reason this audit was written; the answer is that they are
        # *not* blocked by their verifier shape -- their shape was worked around.
        for skill in ("BUILDING_UPGRADE", "TRAIN_TROOPS", "RESEARCH"):
            row = self.by_skill[skill]
            self.assertEqual(row.binding_kind, "ADAPTER", skill)
            self.assertTrue(row.dispatchable, skill)
            self.assertTrue(row.brain_route, skill)
            self.assertNotIn("verifier", ",".join(row.missing), skill)

    def test_build_and_train_need_nothing_but_a_live_success(self):
        for skill in ("BUILDING_UPGRADE", "TRAIN_TROOPS"):
            row = self.by_skill[skill]
            self.assertTrue(row.vision_target, skill)
            self.assertEqual(row.missing, (), skill)
            self.assertEqual(row.live_success, 0, skill)

    def test_research_still_lacks_its_action_target(self):
        # BTN_START_RESEARCH has no template at all yet (2026-09-17), so RESEARCH
        # is dispatchable in shape but not in vision.
        row = self.by_skill["RESEARCH"]
        self.assertFalse(row.vision_target)
        self.assertEqual(row.missing, ("vision_target",))

    def test_the_unreachable_families_are_measured_not_assumed(self):
        # Move a name out of these sets when the runtime gains that shape.
        self.assertIn("verify_beast_hunt", self.families.get("PARAMETER", []))
        self.assertIn("verify_rally_joined", self.families.get("PARAMETER", []))
        self.assertIn("verify_alliance_tech_contribution", self.families.get("FRAME", []))
        self.assertIn("verify_gathering", self.families.get("STATE", []))

    def test_an_adapted_verifier_is_not_also_reported_unreachable(self):
        reached = set(self.families.get("PARAMETER", [])) | set(self.families.get("FRAME", []))
        for binding in self.adapters.values():
            self.assertNotIn(binding.verifier, reached, binding.skill)

    def test_ready_but_unproven_really_means_never_succeeded(self):
        for row in self.rows:
            if row.ready_but_unproven:
                self.assertGreaterEqual(row.live_success, 0)

    def test_the_group_the_operator_cares_about_is_non_empty(self):
        ready = [r for r in self.rows if r.ready_but_unproven and r.live_success == 0]
        names = {r.skill for r in ready}
        self.assertIn("BUILDING_UPGRADE", names)
        self.assertIn("TRAIN_TROOPS", names)
        self.assertTrue(len(ready) >= 10)


class CommandTest(unittest.TestCase):
    def test_json_output_parses_and_reports_adapters(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = audit.main(["--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("unreachable_verifiers", payload)
        self.assertEqual(set(payload["lambda_adapters"]),
                         {"BUILDING_UPGRADE", "RESEARCH", "TRAIN_TROOPS"})
        self.assertEqual(
            sum(len(v) for v in payload["unreachable_verifiers"].values()), 18)

    def test_the_plain_report_runs_and_names_the_adapters(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = audit.main(["--unbound-verifiers"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("verifiers no skill can reach", text)
        self.assertIn("lambda adapters already in use", text)


if __name__ == "__main__":
    unittest.main()
