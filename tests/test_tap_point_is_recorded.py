"""A tap records where it landed.

Added 2026-09-20, after a run resolved OPEN_POWER_OVERVIEW's target, tapped, and the verifier
answered POWER_OVERVIEW_NOT_PROVEN.  The obvious next question -- where did the tap actually go? --
had no answer in the artifacts: the resolved point was computed inside the executor and then thrown
away.  A step could say "the target did not open" but never "and it landed here".

That matters more in this project than in most, because the standing rule is that a claim must be
provable from its artifacts.  A tap that did nothing is exactly the case where the artifact has to
carry the answer, otherwise the only recourse is to recompute the point offline against a stored
frame that need not be the frame the run was looking at.

The point is in device pixels, not normalised, because "which pixel was touched" is the fact; a
reader can normalise it but cannot recover the frame size from a ratio.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.executor import Executor  # noqa: E402
from winter_agent_v2.models import Action  # noqa: E402


class _Status:
    def __init__(self, resolution):
        self.connected = True
        self.resolution = resolution


class _Device:
    """A device that records what was tapped instead of tapping anything."""

    def __init__(self, resolution=(720, 1280)):
        self.capture_backend = "FAKE"
        self.taps: list[tuple[int, int]] = []
        self._resolution = resolution

    def status(self):
        return _Status(self._resolution)

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        pass

    def screenshot(self, path):
        path.touch()
        return path


class ATapRecordsWhereItLandedTests(unittest.TestCase):
    def _executor(self, device, resolver):
        return Executor(production=True, dry_run=False, device=device, target_resolver=resolver)

    def test_a_resolved_tap_carries_the_pixel_it_touched(self):
        device = _Device(resolution=(720, 1280))
        result = self._executor(
            device, lambda semantic: (0.5, 0.25) if semantic == "BTN_X" else None
        ).execute(Action("TAP_SEMANTIC", "BTN_X"))
        self.assertTrue(result.executed)
        self.assertEqual(result.tap_point, (360, 320), "half of 720, a quarter of 1280")
        self.assertEqual(device.taps, [(360, 320)], "and it is the pixel the device was given")

    def test_the_recorded_point_is_the_one_the_device_received(self):
        """The three values must be the same number: resolved, recorded, tapped."""
        device = _Device(resolution=(1080, 1920))
        result = self._executor(
            device, lambda _s: (0.1, 0.9)
        ).execute(Action("TAP_SEMANTIC", "BTN_Y"))
        self.assertTrue(result.executed)
        self.assertEqual(device.taps[0], result.tap_point)

    def test_an_action_with_no_point_records_none(self):
        device = _Device()
        result = self._executor(device, lambda _s: None).execute(Action("PRESS_BACK"))
        self.assertTrue(result.executed)
        self.assertIsNone(result.tap_point, "a system key has no landing point")

    def test_a_tap_that_never_resolved_records_none(self):
        device = _Device()
        result = self._executor(device, lambda _s: None).execute(Action("TAP_SEMANTIC", "BTN_MISSING"))
        self.assertFalse(result.executed)
        self.assertEqual(device.taps, [], "nothing was tapped")
        self.assertIsNone(result.tap_point)

    def test_the_field_reaches_the_episode_json(self):
        """The run prints ``asdict(result)``, so the field must exist on the dataclass itself."""
        from dataclasses import asdict

        from winter_agent_v2.models import ExecutionResult

        self.assertIn("tap_point", ExecutionResult.__dataclass_fields__)
        payload = asdict(ExecutionResult(
            executed=True, dry_run=False, action=Action("TAP_SEMANTIC", "BTN_X"),
            tap_point=(1, 2),
        ))
        self.assertEqual(payload["tap_point"], (1, 2))


if __name__ == "__main__":
    unittest.main()
