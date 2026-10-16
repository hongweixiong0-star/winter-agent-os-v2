import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from winter_agent_v2.vision import SemanticMatch, SemanticROIVision


class TemplateLifecyclePrecedenceTests(unittest.TestCase):
    def _vision(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manifest = Path(temporary.name) / "manifest.json"
        manifest.write_text(json.dumps({"records": []}), encoding="utf-8")
        vision = SemanticROIVision(manifest)
        vision.records = [
            {"semantic": "TEST_CONTROL", "status": "CANDIDATE", "template_path": "candidate"},
            {"semantic": "TEST_CONTROL", "status": "VERIFIED", "template_path": "verified"},
            {"semantic": "TEST_CONTROL", "status": "STABLE", "template_path": "stable"},
        ]
        return vision

    def test_stable_template_wins_even_when_candidate_is_listed_first(self):
        vision = self._vision()
        frame = Path("synthetic-frame.png")
        stable = SemanticMatch("TEST_CONTROL", 5, {"x_norm": 0.1, "y_norm": 0.1, "w_norm": 0.1, "h_norm": 0.1})

        def find_tier(_path, rows, _semantic):
            if rows[0]["status"] == "STABLE":
                return stable
            self.fail("lower-priority tier should not be searched after a stable match")

        with patch.object(vision, "_find_in_roi", side_effect=find_tier):
            self.assertIs(vision.find(frame, "TEST_CONTROL"), stable)

    def test_candidate_remains_fallback_when_verified_tier_has_no_match(self):
        vision = self._vision()
        frame = Path("synthetic-frame.png")
        candidate = SemanticMatch("TEST_CONTROL", 3, {"x_norm": 0.6, "y_norm": 0.4, "w_norm": 0.1, "h_norm": 0.1})
        visited = []

        def find_tier(_path, rows, _semantic):
            visited.append(rows[0]["status"])
            return candidate if rows[0]["status"] == "CANDIDATE" else None

        with patch.object(vision, "_find_in_roi", side_effect=find_tier):
            self.assertIs(vision.find(frame, "TEST_CONTROL"), candidate)
        self.assertEqual(visited, ["STABLE", "VERIFIED", "CANDIDATE"])


if __name__ == "__main__":
    unittest.main()
