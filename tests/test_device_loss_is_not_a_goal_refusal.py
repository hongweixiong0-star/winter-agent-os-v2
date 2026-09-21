"""A device that leaves is not a goal declining to act, and must not be handed over.

The operator drew this line for a reason that is easy to see once stated.  Every reason in
``NON_FATAL_STOPS`` is a statement about ONE goal -- "this queue is busy", "this panel has
nothing to collect" -- and the runtime answers those by handing the cycle to the next goal.
A device that has gone away says nothing about any goal: the adb endpoint dropped, MuMu was
closed, the emulator is restarting.  Handing THAT to the next goal produces a run that walks
goal to goal issuing nothing while the real problem sits unchanged underneath, and reports
each goal as merely blocked.

Measured incident, and the reason this file exists.  On 2026-09-21 eight crash reports sat in
``learning/control_panel/crashes/``, one every nineteen minutes:

    RuntimeError: DEVICE_NOT_CONNECTED
    RuntimeError: 等待 MuMu 连接超时
    classification: ENVIRONMENT

The classification was already right.  What was missing was that the capture calls inside the
run loop had no guard at all: six bare ``self.device.screenshot(...)`` calls meant a transport
that died mid-run raised straight out of ``run()``, so the run recorded nothing about where it
was standing, and the next cycle met the same screen.

What these tests pin:
  * the marker set covers what device.py actually raises, and does not swallow other errors
  * a device failure ends the run as RECOVERING with the device's own words
  * an unrelated exception is re-raised, because this is a device guard and not a blanket except
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime, _device_gone  # noqa: E402


class TheMarkerSetCoversWhatTheDeviceLayerRaises(unittest.TestCase):
    """The strings are quoted from ``device.py`` rather than invented here.

    ``DEVICE_NOT_CONNECTED`` / ``DEVICE_AMBIGUOUS`` / ``ADB_DISCOVERY_FAILED`` are literal
    ``raise RuntimeError(...)`` arguments in that module, and ``ADB_FAILED:`` is the prefix
    the adb wrapper builds from its own return code, so it is matched as a substring.
    """

    DEVICE_MESSAGES = (
        "DEVICE_NOT_CONNECTED",
        "DEVICE_AMBIGUOUS",
        "ADB_DISCOVERY_FAILED",
        "ADB_FAILED:1",
        "ADB_FAILED",
        "SCREENSHOT_NOT_PNG",
        "SCREENSHOT_DAMAGED",
        "error: device offline",
        "error: device unauthorized",
        "error: no devices/emulators found",
    )

    def test_every_device_message_is_recognised(self) -> None:
        for message in self.DEVICE_MESSAGES:
            with self.subTest(message=message):
                self.assertTrue(_device_gone(RuntimeError(message)))

    def test_ordinary_failures_are_not_claimed_as_device_failures(self) -> None:
        """The guard must not become a blanket except.

        These are the reasons the runtime already has measured recoveries for.  Claiming
        them here would replace a working recovery with a device stop.
        """
        for message in (
            "SEMANTIC_TARGET_NOT_VERIFIED",
            "SAFE_BACK_NOT_PROVEN",
            "reserved_march_for_stamina",
            "training_queue_busy",
            "",
        ):
            with self.subTest(message=message):
                self.assertFalse(_device_gone(RuntimeError(message)))


class TheGuardEndsTheRunHonestly(unittest.TestCase):
    def _runtime(self, temp: str) -> LiveRuntime:
        return LiveRuntime(
            device=object(),
            vision=object(),
            semantic_vision=object(),
            capture_dir=Path(temp),
            sleeper=lambda _seconds: None,
        )

    def test_a_dead_transport_ends_the_run_as_recovering(self) -> None:
        with TemporaryDirectory() as temp:
            runtime = self._runtime(temp)
            recorded: list[dict] = []
            with patch.object(LiveRuntime, "_runtime", lambda self, **kw: recorded.append(kw) or None):
                def dead_call(*_args):
                    raise RuntimeError("DEVICE_NOT_CONNECTED")

                self.assertTrue(runtime._device_lost(dead_call))
            self.assertEqual(runtime._device_stop_reason, "DEVICE_NOT_CONNECTED")
            self.assertEqual(recorded[-1]["agent_state"], "RECOVERING")
            self.assertEqual(recorded[-1]["stop_reason"], "DEVICE_NOT_CONNECTED")
            self.assertFalse(recorded[-1]["scheduler_loop_alive"])

    def test_the_guard_reports_which_device_message_it_saw(self) -> None:
        """``ADB_FAILED:1`` carries the adb return code; the operator needs it kept."""
        with TemporaryDirectory() as temp:
            runtime = self._runtime(temp)
            with patch.object(LiveRuntime, "_runtime", lambda self, **kw: None):
                def dead_call(*_args):
                    raise RuntimeError("ADB_FAILED:1")

                runtime._device_lost(dead_call)
            self.assertEqual(runtime._device_stop_reason, "ADB_FAILED:1")

    def test_an_unrelated_exception_is_re_raised_not_swallowed(self) -> None:
        with TemporaryDirectory() as temp:
            runtime = self._runtime(temp)

            def broken_call(*_args):
                raise ValueError("a real defect in the caller")

            with self.assertRaises(ValueError):
                runtime._device_lost(broken_call)

    def test_a_healthy_call_answers_false_and_touches_nothing(self) -> None:
        with TemporaryDirectory() as temp:
            runtime = self._runtime(temp)
            seen: list[str] = []
            self.assertFalse(runtime._device_lost(lambda value: seen.append(value), "png"))
            self.assertEqual(seen, ["png"])

    def test_the_placeholder_exists_before_any_failure(self) -> None:
        """A guard that can raise AttributeError on its own failure path is not a guard."""
        with TemporaryDirectory() as temp:
            self.assertTrue(self._runtime(temp)._device_stop_reason)


if __name__ == "__main__":
    unittest.main()
