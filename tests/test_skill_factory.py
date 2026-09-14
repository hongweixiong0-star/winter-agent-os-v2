import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS, PRIORS, SkillFactory
from winter_agent_v2.skills import v2_registry


class SkillFactoryTests(unittest.TestCase):
    def test_every_generated_prior_has_real_operation_and_verifier(self):
        for prior in PRIORS.values():
            self.assertTrue(prior.execute_steps)
            self.assertTrue(prior.success_conditions)
            self.assertTrue(prior.required_semantics)

    def test_factory_generates_only_missing_candidate_specs_and_coverage(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            factory = SkillFactory(v2_registry(), root / "candidate")
            written = factory.generate_candidates()
            self.assertTrue(written)
            item = json.loads(written[0].read_text(encoding="utf-8"))
            self.assertEqual(item["lifecycle"], "CANDIDATE")
            self.assertEqual(item["live_evidence"], [])
            coverage = factory.coverage_markdown()
            self.assertIn("Goal | Required | Existing", coverage)
            self.assertEqual(set(GOAL_REQUIREMENTS), {line.split(" | ")[0] for line in coverage.splitlines()[4:]})

    def test_full_audit_and_graph_expose_real_gaps(self):
        factory = SkillFactory(v2_registry(), Path("unused"))
        audit = factory.automation_audit({"OPEN_MAP"}, {"BTN_OPEN_ARENA"}, {"OPEN_MAP":3})
        self.assertEqual(audit["summary"]["total"], len(GOAL_REQUIREMENTS))
        self.assertTrue(audit["top_leverage"])
        self.assertIn("vision_missing", audit["goals"][0]["skills"][0])
        graph = factory.goal_skill_graph()
        self.assertIn("EVENT_MINIMUM_GUARANTEE", graph["skills"]["READ_EVENT_PROGRESS"])


if __name__ == "__main__": unittest.main()
