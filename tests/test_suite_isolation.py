"""No test may write the AUTO's live control-panel files by default.

Operator directive 2026-09-22 §九: "开发测试使用独立目录，不能覆盖或回滚正式 AUTO 的学习资产".
``tests/conftest.py`` enforces that for the learning assets it lists.  These tests are the guard
for the two entries added 2026-09-30, after the pump's heartbeat was measured to be the reason
AUTO would not start:

    03:41:11  另一个实例正在运行（pid 3168）：本窗口只读，不消费队列、不启动 AUTO、不申请设备租约。
    03:42:00  不自动启动 AUTO：另一个实例（pid 3168）正在运行。本窗口只读。

``QueuePump._persist`` writes ``PUMP_STATE_PATH`` and stamps it with ``os.getpid()``.  That path
resolved to the live ``learning/control_panel/pump.json`` in a plain test process, so any test
ticking a real pump became the panel's "other instance" -- and pid 3168 was a test process that
had already exited, leaving the panel permanently refusing to start AUTO.  Sampled every 20 s
during the outage the live file named three different owners in ninety seconds (3168, then 29048
which was a running pytest, then the panel's own pid), none of them consistently the panel.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from tools import control_panel


class TheHeartbeatIsNotTheLiveFile(unittest.TestCase):
    def test_the_pump_path_is_redirected_out_of_the_live_tree(self):
        live = control_panel.ROOT / "learning/control_panel/pump.json"
        self.assertNotEqual(Path(control_panel.PUMP_STATE_PATH), live)
        self.assertFalse(
            str(control_panel.PUMP_STATE_PATH).startswith(str(control_panel.ROOT)),
            f"the pump heartbeat still points inside the live tree: {control_panel.PUMP_STATE_PATH}",
        )

    def test_a_default_pump_writes_its_heartbeat_where_the_test_session_says(self):
        # The write is the thing that did the damage, so assert on the write, not the constant.
        pump = control_panel.QueuePump(enabled=lambda: False)
        pump._persist()
        written = Path(control_panel.PUMP_STATE_PATH)
        self.assertTrue(written.exists(), "the pump wrote no heartbeat at all")
        payload = __import__("json").loads(written.read_text(encoding="utf-8"))
        self.assertEqual(
            int(payload["process"]), os.getpid(),
            "a default pump must stamp its own pid into the redirected file",
        )
        live = control_panel.ROOT / "learning/control_panel/pump.json"
        self.assertNotEqual(written, live)

    def test_the_panel_log_pid_and_probe_are_redirected_with_it(self):
        # ``panel_pid_path`` and ``gateway_probe_path`` are derived from the log path, so
        # redirecting the log is what keeps a test from writing a pid the restart tool would
        # then try to kill.
        for path in (control_panel.PANEL_LOG_PATH,
                     control_panel.panel_pid_path(),
                     control_panel.gateway_probe_path()):
            self.assertFalse(
                str(path).startswith(str(control_panel.ROOT)),
                f"still points inside the live tree: {path}",
            )


if __name__ == "__main__":
    unittest.main()
