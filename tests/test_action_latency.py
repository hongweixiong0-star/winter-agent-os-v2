from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2.action_latency import append


class ActionLatencyTests(unittest.TestCase):
    def test_append_writes_round_trip_record_without_inventing_unmeasured_phases(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "learning" / "action_latency.jsonl"
            append(path, {
                "frame_capture_ms": 12.34567,
                "maa_execute_ms": None,
                "skill": "OPEN_HOME",
                "success": True,
            })
            row = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(row["frame_capture_ms"], 12.346)
        self.assertIsNone(row["maa_execute_ms"])
        self.assertIsNone(row["ocr_ms"])
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
