from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2.action_latency import append


class ActionLatencyTests(unittest.TestCase):
    def test_append_writes_one_canonical_schema_without_inventing_unmeasured_phases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "learning" / "action_latency.jsonl"
            append(path, {
                "frame_capture_ms": 12.34567,
                "maa_execute_ms": None,
                "settle_first_wait_ms": 100.0,
                "settle_retry_wait_ms": 250.0,
                "skill": "OPEN_HOME",
                "success": True,
            })
            row = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(row["schema_version"], 2)
        self.assertEqual(row["capture_ms"], 12.346)
        self.assertIsNone(row["maa_ms"])
        self.assertIsNone(row["ocr_ms"])
        self.assertIsNone(row["parse_ms"])
        self.assertEqual(row["settle_ms"], 350.0)
        for duplicate in ("frame_capture_ms", "scheduler_select_ms", "maa_execute_ms", "post_action_wait_ms"):
            self.assertNotIn(duplicate, row)
        self.assertEqual(row["skill"], "OPEN_HOME")
        self.assertTrue(row["success"])
        self.assertTrue(row["recorded_at"])

    def test_append_does_not_raise_when_diagnostics_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as temp:
            blocker = Path(temp) / "not-a-directory"
            blocker.write_text("keep", encoding="utf-8")
            append(blocker / "child" / "action_latency.jsonl", {"skill": "OPEN_HOME"})


if __name__ == "__main__":
    unittest.main()
