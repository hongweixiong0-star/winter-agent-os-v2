"""One retention budget per turn, not one per call.

The host aborts a process that deletes 50 files inside one turn
(``CODEBUDDY_SAFE_DELETE_BULK_GUARD``, threshold 50, ``scope: turn``).  ``retention`` bounds a
*call* at 30, but ``ControlPanel._enforce_retention`` has two callers in the same turn -- start-up
and the round boundary -- so 30 + 30 reached 60.

Measured 2026-10-08: the abort killed the worker rather than trimming the tree.  Four
``WORKER_RESULT_MISSING: exit=1`` crashes inside 100 seconds, ``连续 Worker 异常已耗尽恢复预算``
and AUTO paused, with the guard's own line as the worker's last log entry:

    [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":50,"threshold":50,"scope":"turn", ...}
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_panel():
    """Import ``tools/control_panel.py`` by path, without letting it open a window.

    The module builds its Tk root in ``main()``, not at import, so importing it is safe; a test
    that needs an instance uses ``object.__new__`` and sets only the attributes the method reads.
    """
    path = ROOT / "tools" / "control_panel.py"
    spec = importlib.util.spec_from_file_location("control_panel_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RetentionTurnBudgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel_module = _load_panel()

    def _panel(self, calls, *, removed_per_call):
        panel = object.__new__(self.panel_module.ControlPanel)
        panel.config = {"retention": {"auto_prune": True, "max_screenshots": 500,
                                      "screenshot_ttl_days": 3}}
        panel._append = lambda *args, **kwargs: None
        panel._retention_removed_this_turn = 0
        self.panel_module.prune_runtime_screenshots = self._fake(calls, removed_per_call)
        return panel

    @staticmethod
    def _fake(calls, removed_per_call):
        def fake(root, *, max_count, ttl_days, limit=None, **kwargs):
            calls.append(limit)
            return [Path(f"/tmp/frame_{len(calls)}_{index}.png")
                    for index in range(min(removed_per_call, int(limit or 0)))]
        return fake

    def test_the_second_pass_in_one_turn_gets_no_budget(self):
        calls: list = []
        panel = self._panel(calls, removed_per_call=30)
        panel._enforce_retention()          # start-up: spends the turn's whole budget
        panel._enforce_retention()          # round boundary: same turn, must not delete again
        self.assertEqual(len(calls), 1, "a second pass in the same turn must not delete at all")
        self.assertEqual(calls[0], self.panel_module.RETENTION_DELETIONS_PER_TURN)

    def test_the_budget_is_restored_when_the_turn_ends(self):
        calls: list = []
        panel = self._panel(calls, removed_per_call=30)
        panel._enforce_retention()
        panel._retention_removed_this_turn = 0     # what the round boundary does after the call
        panel._enforce_retention()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls, [self.panel_module.RETENTION_DELETIONS_PER_TURN] * 2)

    def test_a_turn_never_exceeds_the_host_threshold(self):
        """The number the guard counts, not the number one call happens to pass."""
        calls: list = []
        panel = self._panel(calls, removed_per_call=30)
        for _ in range(5):
            panel._enforce_retention()
        self.assertLessEqual(sum(int(limit or 0) for limit in calls), 50)
        self.assertLessEqual(self.panel_module.RETENTION_DELETIONS_PER_TURN, 50)


if __name__ == "__main__":
    unittest.main()
