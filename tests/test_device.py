from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from winter_agent_v2.device import ADBDevice
from winter_agent_v2.executor import Executor
from winter_agent_v2.models import Action


class DeviceTests(unittest.TestCase):
    @patch("winter_agent_v2.device.subprocess.run")
    def test_reconnect_adopts_only_unique_online_device(self, run):
        run.return_value = Mock(returncode=0, stdout=b"List of devices attached\nemulator-5554\tdevice\noffline-one\toffline\n")
        device = ADBDevice(Path("adb"), "127.0.0.1:16384")
        self.assertEqual(device.resolve_connection(), "emulator-5554")

    @patch("winter_agent_v2.device.subprocess.run")
    def test_reconnect_never_guesses_between_devices(self, run):
        run.return_value = Mock(returncode=0, stdout=b"a\tdevice\nb\tdevice\n")
        with self.assertRaisesRegex(RuntimeError, "DEVICE_AMBIGUOUS"):
            ADBDevice(Path("adb"), "missing").resolve_connection()
        self.assertEqual(ADBDevice(Path("adb"), "b").resolve_connection(), "b")

    @patch("winter_agent_v2.device.subprocess.run")
    def test_reconnect_rejects_offline_device(self, run):
        run.return_value = Mock(returncode=0, stdout=b"a\toffline\n")
        with self.assertRaisesRegex(RuntimeError, "DEVICE_NOT_CONNECTED"):
            ADBDevice(Path("adb"), "a").resolve_connection()

    @patch("winter_agent_v2.device.subprocess.run")
    def test_no_online_device_probes_emulator_ports_before_failing(self, run):
        """A wrong configured port must not kill the AUTO worker.

        MuMu only appears in `adb devices` after an explicit connect, so with a
        stale port the worker used to die with DEVICE_NOT_CONNECTED and the
        watchdog restarted it forever.
        """
        empty = Mock(returncode=0, stdout=b"List of devices attached\n")
        found = Mock(returncode=0, stdout=b"List of devices attached\n127.0.0.1:7555\tdevice\n")
        connect = Mock(returncode=0, stdout=b"connected to 127.0.0.1:7555\n")
        run.side_effect = [empty, connect, found]
        device = ADBDevice(Path("adb"), "127.0.0.1:16384")
        self.assertEqual(device.resolve_connection(), "127.0.0.1:7555")

    @patch("winter_agent_v2.device.subprocess.run")
    def test_port_probe_never_adopts_ambiguous_devices(self, run):
        empty = Mock(returncode=0, stdout=b"List of devices attached\n")
        two = Mock(returncode=0, stdout=b"a\tdevice\nb\tdevice\n")
        connect = Mock(returncode=0, stdout=b"connected\n")
        run.side_effect = [empty, connect, two]
        with self.assertRaisesRegex(RuntimeError, "DEVICE_AMBIGUOUS"):
            ADBDevice(Path("adb"), "127.0.0.1:16384").resolve_connection()

    def test_tap_is_blocked_without_production(self) -> None:
        device = ADBDevice(Path("adb"), "serial", production=False)
        with self.assertRaisesRegex(PermissionError, "DRY_RUN"):
            device.tap(1, 2)

    @patch("winter_agent_v2.device.subprocess.run")
    def test_status_parses_resolution_and_package(self, run) -> None:
        run.side_effect = [
            type("R", (), {"returncode":0,"stdout":b"Physical size: 720x1280\n","stderr":b""})(),
            type("R", (), {"returncode":0,"stdout":b"mCurrentFocus=Window{x u0 com.gof.china/com.Main}","stderr":b""})(),
        ]
        status = ADBDevice(Path("adb"), "serial").status()
        self.assertEqual(status.resolution, (720, 1280))
        self.assertEqual(status.foreground_package, "com.gof.china")

    @patch("winter_agent_v2.device.subprocess.run")
    def test_invalid_screenshot_is_rejected(self, run) -> None:
        run.return_value = type("R", (), {"returncode":0,"stdout":b"bad","stderr":b""})()
        with self.assertRaisesRegex(RuntimeError, "NOT_PNG"):
            ADBDevice(Path("adb"), "serial").screenshot(Path("unused.png"))

    @patch("winter_agent_v2.device.subprocess.run")
    def test_status_uses_android_12_activity_fallback(self, run) -> None:
        run.side_effect = [
            type("R", (), {"returncode":0,"stdout":b"Physical size: 720x1280\n","stderr":b""})(),
            type("R", (), {"returncode":0,"stdout":b"no current focus","stderr":b""})(),
            type("R", (), {"returncode":0,"stdout":b"topResumedActivity=ActivityRecord{x u0 com.gof.china/com.Main t1}","stderr":b""})(),
        ]
        status = ADBDevice(Path("adb"), "serial").status()
        self.assertEqual(status.foreground_package, "com.gof.china")

    def test_executor_maps_verified_normalized_target_at_device_boundary(self) -> None:
        device = Mock()
        device.status.return_value.connected = True
        device.status.return_value.resolution = (720, 1280)
        executor = Executor(
            production=True,
            dry_run=False,
            device=device,
            target_resolver=lambda semantic: (0.064, 0.691) if semantic == "BTN_OPEN_RESOURCE_SEARCH" else None,
        )

        result = executor.execute(Action("TAP_SEMANTIC", "BTN_OPEN_RESOURCE_SEARCH"))

        self.assertTrue(result.executed)
        device.tap.assert_called_once_with(46, 884)

    def test_executor_rejects_unverified_semantic_target(self) -> None:
        device = Mock()
        executor = Executor(
            production=True,
            dry_run=False,
            device=device,
            target_resolver=lambda semantic: None,
        )

        result = executor.execute(Action("TAP_SEMANTIC", "UNKNOWN_BUTTON"))

        self.assertFalse(result.executed)
        self.assertEqual(result.error, "SEMANTIC_TARGET_NOT_VERIFIED")
        device.tap.assert_not_called()

    def test_executor_uses_device_back_without_coordinates(self) -> None:
        device = Mock()
        device.status.return_value.connected = True
        executor = Executor(production=True, dry_run=False, device=device)

        result = executor.execute(Action("PRESS_BACK"))

        self.assertTrue(result.executed)
        device.press_back.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
