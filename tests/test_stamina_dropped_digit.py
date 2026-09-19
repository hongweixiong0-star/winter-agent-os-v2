"""A HUD stamina reading that is the leading digits of the last one is a misread.

The frames behind this are kept in ``dataset/truth_audit/stamina_hud_roi_20260919``: the HUD says
527 and the recogniser returned 52, having stopped after the second digit.

The direction is what makes it dangerous.  ``AVOID_STAMINA_WASTE`` reads this number to decide
whether anything is left to *spend*, so a dropped digit reads as "nearly empty" while stamina is
plentiful, and the goal stops spending -- the opposite of what it exists for, and silently.

Two halves are pinned here, because either without the other is useless: the rule itself, and the
fact that the runtime actually applies it to the world the brain and verifiers read (a guard that
only corrected the stored copy would leave the run acting on the bad number).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tests"))

from winter_agent_v2.ocr import looks_like_a_dropped_digit  # noqa: E402

#: ``(previous, current, is_a_dropped_digit)``.  The two ``True`` rows are the measured failure
#: and its four-digit form; every ``False`` row is a case the guard must stay quiet on, and the
#: last one is the misread this rule deliberately does NOT catch.
CASES = (
    (527, 52, True),
    (382, 38, True),
    (1000, 100, True),
    (527, 502, False),
    (382, 502, False),
    (502, 527, False),
    (552, 52, False),
    (1527, 52, False),
    (527, 527, False),
    (52, 52, False),
    (52, 527, False),
    (None, 52, False),
    (527, None, False),
)


class TheDroppedDigitRuleTests(unittest.TestCase):
    def test_the_rule(self):
        for previous, current, expected in CASES:
            with self.subTest(previous=previous, current=current):
                self.assertEqual(looks_like_a_dropped_digit(previous, current), expected)

    def test_it_can_never_suppress_a_rise(self):
        """A free claim raises stamina; the guard must not be able to hide a real gain."""
        for previous, current in ((382, 502), (52, 527), (100, 1000), (7, 77)):
            with self.subTest(previous=previous, current=current):
                self.assertFalse(looks_like_a_dropped_digit(previous, current))

    def test_the_uncatchable_misread_is_documented_as_uncatchable(self):
        """527 -> 502 differs by 25, which one frame cannot tell from a real change."""
        self.assertFalse(looks_like_a_dropped_digit(527, 502))


class TheRuntimeAppliesItTests(unittest.TestCase):
    def _runtime(self):
        from test_capability_gate import FakeDevice, FakeSemantic, FakeVision

        from winter_agent_v2.learning import EpisodeStore
        from winter_agent_v2.runtime import LiveRuntime

        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        runtime = LiveRuntime(
            device=FakeDevice(),
            vision=FakeVision([]),
            semantic_vision=FakeSemantic(),
            capture_dir=root / "captures",
            sleeper=lambda _seconds: None,
            episode_store=EpisodeStore(root / "episodes.jsonl"),
        )
        runtime._printed_deferrals = set()
        return runtime

    def _world(self, current: int):
        from winter_agent_v2.models import Page, WorldState

        return WorldState(page=Page.MAP, stamina={"current": current, "source": "MAP_HUD"},
                          confidence=0.99)

    def test_a_collapse_that_is_really_a_misread_is_refused(self):
        runtime = self._runtime()
        runtime._last_stamina_read = 527
        healed = runtime._reject_a_dropped_digit(self._world(52))
        self.assertEqual(healed.stamina["current"], 527, "the last good reading is kept")
        self.assertEqual(healed.stamina["dropped_digit_suspected"], 52,
                         "and the rejected number is kept visible as evidence")

    def test_a_real_reading_is_accepted_and_becomes_the_new_reference(self):
        runtime = self._runtime()
        runtime._last_stamina_read = 527
        # A drop of 12 is a real spend, not a dropped digit.
        accepted = runtime._reject_a_dropped_digit(self._world(515))
        self.assertEqual(accepted.stamina["current"], 515)
        self.assertNotIn("dropped_digit_suspected", accepted.stamina)
        self.assertEqual(runtime._last_stamina_read, 515, "the reference advances")

    def test_a_rise_is_accepted(self):
        runtime = self._runtime()
        runtime._last_stamina_read = 382
        accepted = runtime._reject_a_dropped_digit(self._world(502))
        self.assertEqual(accepted.stamina["current"], 502)
        self.assertEqual(runtime._last_stamina_read, 502)

    def test_a_frame_with_no_number_is_left_alone(self):
        runtime = self._runtime()
        runtime._last_stamina_read = 527
        from winter_agent_v2.models import Page, WorldState

        empty = WorldState(page=Page.MAP, confidence=0.99)
        self.assertIs(runtime._reject_a_dropped_digit(empty), empty)

    def test_the_guard_runs_at_every_observation_choke_point(self):
        """Otherwise it corrects a copy nobody acts on.

        The run decides with ``before``/``after``, and both are handed to ``_record_goals``.
        If the correction is not applied on the way there, the store gets a healed number while
        the brain spends against the broken one.
        """
        source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
        calls = re.findall(r"self\._record_goals\((before|after), frame=", source)
        guarded = re.findall(r"^\s*(before|after) = self\._reject_a_dropped_digit\(\1\)$",
                             source, re.M)
        self.assertGreaterEqual(len(calls), 5, f"the call sites moved: {calls}")
        self.assertEqual(sorted(calls), sorted(guarded),
                         f"every _record_goals site must be guarded: {calls} vs {guarded}")


if __name__ == "__main__":
    unittest.main()
