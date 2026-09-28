from __future__ import annotations

import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from winter_agent_v2.worker_recovery import retry_until_ready
from tools.control_panel import ControlPanel


class WorkerRecoveryTests(unittest.TestCase):
    def test_initial_adb_connect_timeout_is_classified_for_recovery(self):
        panel = SimpleNamespace(
            stop_requested=False,
            paused=False,
            device=SimpleNamespace(adb_path=Path("adb"), serial="127.0.0.1:7555"),
            config={"device": {"package_name": "com.gof.china"}},
        )
        timeout = subprocess.TimeoutExpired(["adb", "connect"], timeout=5)
        with patch("tools.control_panel._background_run", side_effect=timeout):
            with self.assertRaisesRegex(RuntimeError, "ADB_COMMAND_TIMEOUT"):
                ControlPanel._ensure_device(panel)

    def test_environment_failure_retries_with_bounded_backoff_then_continues(self):
        outcomes = iter([RuntimeError("DEVICE_NOT_CONNECTED"), RuntimeError("ADB_COMMAND_TIMEOUT"), None])
        delays = []
        records = []
        ticks = iter([0.0, 0.1, 0.2, 0.3, 10.3])
        def operation():
            item = next(outcomes)
            if item is not None:
                _raise(item)
        result = retry_until_ready(
            operation,
            should_stop=lambda: False,
            wait=lambda delay: delays.append(delay) or False,
            is_recoverable=lambda exc: "DEVICE_" in str(exc) or "ADB_" in str(exc),
            on_retry=lambda exc, count, delay, elapsed: records.append((str(exc), count, delay)),
            initial_delay_seconds=5,
            max_delay_seconds=8,
            clock=lambda: next(ticks),
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.retries, 2)
        self.assertEqual(delays, [5, 8])
        self.assertEqual([row[1] for row in records], [1, 2])

    def test_backoff_remains_capped_during_a_long_outage(self):
        attempts = 0
        delays = []
        def operation():
            nonlocal attempts
            attempts += 1
            if attempts <= 1100:
                _raise(RuntimeError("DEVICE_NOT_CONNECTED"))
        result = retry_until_ready(
            operation,
            should_stop=lambda: False,
            wait=lambda delay: delays.append(delay) or False,
            is_recoverable=lambda _exc: True,
            on_retry=lambda *_args: None,
            initial_delay_seconds=5,
            max_delay_seconds=60,
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.retries, 1100)
        self.assertEqual(delays[:5], [5, 10, 20, 40, 60])
        self.assertEqual(set(delays[5:]), {60})

    def test_operator_stop_interrupts_backoff_without_another_attempt(self):
        attempts = []
        result = retry_until_ready(
            lambda: (attempts.append("attempt"), _raise(RuntimeError("DEVICE_NOT_CONNECTED")))[1],
            should_stop=lambda: False,
            wait=lambda _delay: True,
            is_recoverable=lambda _exc: True,
            on_retry=lambda *_args: None,
        )
        self.assertFalse(result.ready)
        self.assertTrue(result.stopped)
        self.assertEqual(attempts, ["attempt"])

    def test_unrecoverable_worker_error_uses_crash_path(self):
        with self.assertRaisesRegex(ValueError, "programming defect"):
            retry_until_ready(
                lambda: _raise(ValueError("programming defect")),
                should_stop=lambda: False,
                wait=lambda _delay: self.fail("must not wait"),
                is_recoverable=lambda _exc: False,
                on_retry=lambda *_args: self.fail("must not record a recoverable retry"),
            )


def _raise(exc):
    raise exc


if __name__ == "__main__":
    unittest.main()
