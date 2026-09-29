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
                        "last_decision": {
                            **decisions[-1],
                            "candidates": [
                                {
                                    "role_id": "role-a",
                                    "goal_id": "SCHEDULED_BEAR",
                                    "hard_event": True,
                                    "score": 950,
                                    "deadline_seconds": 240,
                                }
                            ],
                        },
                        "decision_history": decisions,
                        "role_switch_count": 4,
                        "role_switch_success_count": 3,
                        "role_switch_failure_count": 1,
                        "role_switch_durations_ms": [],
                        "telemetry_since": "2026-09-29T11:00:00+08:00",
                        "global_wait_count": 2,
                        "global_wait_with_runnable_goal_count": 1,
                        "action_outcome_count": 5,
                        "shared_goal_credit_count": 3,
                        "completed_goal_count_by_role": {"role-a": 7, "role-b": 4},
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
            self.assertEqual(view["hard_event"], "ROLE_A · SCHEDULED_BEAR · 剩余 240 秒")
            self.assertIn("GLOBAL_WAIT 2 次（带可执行 Goal 1 次）", view["telemetry"])
            self.assertIn("共享 Goal credit 3 次", view["telemetry"])
            self.assertIn("ROLE_A 7 / ROLE_B 4", view["telemetry"])

    def test_missing_state_shows_an_explicit_empty_timeline(self):
        with TemporaryDirectory() as temporary:
            view = global_scheduler_display(Path(temporary))

        self.assertEqual(view["timeline"], "暂无历史决策")
        self.assertEqual(view["hard_event"], "暂无硬时间评估")
        self.assertEqual(view["telemetry"], "生产计数尚未初始化")

    def test_hard_event_displays_scheduled_start_countdown_and_phase(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "learning").mkdir()
            (root / "knowledge" / "roles").mkdir(parents=True)
            (root / "learning" / "global_scheduler_state.json").write_text(
                json.dumps({
                    "active_role_id": "role-a",
                    "last_decision": {
                        "decision": "ROLE_REFRESH_REQUIRED",
                        "selected_role_id": "role-a",
                        "candidates": [{
                            "role_id": "role-a",
                            "goal_id": "SCHEDULED_BEAR",
                            "hard_event": True,
                            "score": 900,
                            "event_starts_in_seconds": 287,
                            "event_phase": "T5",
                        }],
                    },
                }),
                encoding="utf-8",
            )
            (root / "knowledge" / "roles" / "role_inventory.json").write_text(
                json.dumps({"roles": [{"role_id": "role-a", "role_key": "ROLE_A"}]}),
                encoding="utf-8",
            )

            view = global_scheduler_display(root)

        self.assertEqual(view["hard_event"], "ROLE_A · SCHEDULED_BEAR · 距离开始 287 秒（T5）")

    def test_daily_role_boards_show_pending_work_and_exclude_unseen_from_rate(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "learning").mkdir()
            (root / "knowledge" / "roles").mkdir(parents=True)
            (root / "learning" / "global_scheduler_state.json").write_text(
                json.dumps({"active_role_id": "role-a"}), encoding="utf-8",
            )
            (root / "knowledge" / "roles" / "role_inventory.json").write_text(
                json.dumps({"roles": [
                    {"role_id": "role-a", "role_key": "ROLE_A"},
                    {"role_id": "role-b", "role_key": "ROLE_B"},
                ]}), encoding="utf-8",
            )
            (root / "learning" / "task_completion_matrix.json").write_text(
                json.dumps({"roles": {
                    "role-a": {"daily_board": {
                        "tasks": {
                            "MAIL": {"status": "READY"},
                            "BEAR": {"status": "WAITING", "reason_code": "EVENT_NOT_OPEN"},
                            "INTEL": {"status": "COMPLETE"},
                            "ARENA": {"status": "NOT_DISCOVERED"},
                        },
                        "summary": {"completed": 1, "observed": 3, "expired": 0, "not_discovered": 1},
                    }},
                    "role-b": {"daily_board": {
                        "tasks": {"RESEARCH": {"status": "BLOCKED", "reason_code": "CAPABILITY_GAP"}},
                        "summary": {"completed": 0, "observed": 1, "expired": 0, "not_discovered": 2},
                    }},
                }}), encoding="utf-8",
            )

            view = global_scheduler_display(root)

        self.assertIn("邮件 可执行", view["remaining_a"])
        self.assertIn("巨熊 等待/EVENT_NOT_OPEN", view["remaining_a"])
        self.assertIn("科研 阻塞/CAPABILITY_GAP", view["remaining_b"])
        self.assertIn("1/4（25%）", view["task_completion"])
        self.assertIn("未发现类别 3（未并入分母）", view["task_completion"])


if __name__ == "__main__":
    unittest.main()
