import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.control_panel import global_scheduler_display


class GlobalSchedulerDashboardTests(unittest.TestCase):
    def test_displays_latest_ten_global_decisions_with_switch_reasons(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "learning").mkdir()
            (root / "knowledge" / "roles").mkdir(parents=True)
            decisions = [
                {
                    "at": f"2026-09-29T11:{index:02d}:00+08:00",
                    "decision": "ROLE_REFRESH_REQUIRED" if index % 2 == 0 else "KEEP_ROLE",
                    "current_role_id": "role-a" if index % 2 == 0 else "role-b",
                    "selected_role_id": "role-b",
                    "selected_goal_id": f"GOAL_{index}",
                    "reason": f"reason_{index}",
                }
                for index in range(12)
            ]
            (root / "learning" / "global_scheduler_state.json").write_text(
                json.dumps(
                    {
                        "active_role_id": "role-b",
                        "last_decision": decisions[-1],
                        "decision_history": decisions,
                        "role_switch_count": 4,
                        "role_switch_success_count": 3,
                        "role_switch_failure_count": 1,
                        "role_switch_durations_ms": [],
                    }
                ),
                encoding="utf-8",
            )
            (root / "knowledge" / "roles" / "role_inventory.json").write_text(
                json.dumps(
                    {
                        "roles": [
                            {"role_id": "role-a", "role_key": "ROLE_A"},
                            {"role_id": "role-b", "role_key": "ROLE_B"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            view = global_scheduler_display(root)

            lines = view["timeline"].splitlines()
            self.assertEqual(len(lines), 10)
            self.assertIn("GOAL_2", lines[0])
            self.assertIn("reason_2", lines[0])
            self.assertIn("请求切换 ROLE_A→ROLE_B", lines[0])
            self.assertIn("GOAL_11", lines[-1])

    def test_missing_state_shows_an_explicit_empty_timeline(self):
        with TemporaryDirectory() as temporary:
            view = global_scheduler_display(Path(temporary))

        self.assertEqual(view["timeline"], "暂无历史决策")


if __name__ == "__main__":
    unittest.main()
