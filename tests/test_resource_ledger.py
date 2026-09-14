import json
import tempfile
import unittest
from pathlib import Path

from winter_agent_v2.learning import ResourceLedger, ResourceSpend


class ResourceLedgerTests(unittest.TestCase):
    def test_records_required_resource_spend_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resource_spend.jsonl"
            ResourceLedger(path).append_spend(ResourceSpend(
                resource="SPEEDUP",
                amount=1,
                reason="reduce_queue_time",
                expected_value="complete_training_for_event",
                before=12,
                after=11,
            ))
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(row), {"resource","amount","reason","expected_value","before","after"})


if __name__ == "__main__":
    unittest.main()
