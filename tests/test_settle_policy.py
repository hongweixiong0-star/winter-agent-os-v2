from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from winter_agent_v2.settle_policy import (
    ANIMATION_HEAVY,
    NETWORK_ACTION,
    PAGE_TRANSITION,
    P0_EVENT_FAST_MODE,
    SAME_PAGE_FAST,
    FrameChangeProbe,
    choose,
)


class SettlePolicyTests(unittest.TestCase):
    def test_skill_categories_choose_expected_bounded_wait(self):
        self.assertEqual(choose("CLAIM_TRAINING"), NETWORK_ACTION)
        self.assertEqual(choose("BACK"), PAGE_TRANSITION)
        self.assertEqual(choose("NAVIGATE_TO_MAP"), PAGE_TRANSITION)
        self.assertEqual(choose("ATTACK_BEAST"), ANIMATION_HEAVY)
        self.assertEqual(choose("CLOSE_POPUP"), SAME_PAGE_FAST)

    def test_p0_bear_fast_mode_requires_matching_goal_and_live_event_evidence(self):
        self.assertEqual(
            choose("JOIN_RALLY", goal="PARTICIPATE_BEAR", bear_status="ACTIVE"),
            P0_EVENT_FAST_MODE,
        )
        self.assertEqual(
            choose("OPEN_BEAR_RALLY_LIST", goal="PARTICIPATE_BEAR", rally_list_visible=True),
            P0_EVENT_FAST_MODE,
        )
        self.assertEqual(
            choose("JOIN_RALLY", goal="PARTICIPATE_BEAR", bear_status="WAITING_WINDOW"),
            NETWORK_ACTION,
        )
        self.assertEqual(
            choose("JOIN_RALLY", goal="GATHER_RESOURCE", bear_status="ACTIVE"),
            NETWORK_ACTION,
        )

    def test_frame_probe_distinguishes_unchanged_and_changed_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            before = Path(temp) / "before.png"
            same = Path(temp) / "same.png"
            changed = Path(temp) / "changed.png"
            Image.fromarray(np.zeros((128, 72, 3), dtype=np.uint8)).save(before)
            Image.fromarray(np.zeros((128, 72, 3), dtype=np.uint8)).save(same)
            Image.fromarray(np.full((128, 72, 3), 255, dtype=np.uint8)).save(changed)
            probe = FrameChangeProbe(before)

            same_changed, same_fraction = probe.changed(same)
            changed_changed, changed_fraction = probe.changed(changed)

        self.assertFalse(same_changed)
        self.assertEqual(same_fraction, 0.0)
        self.assertTrue(changed_changed)
        self.assertGreaterEqual(changed_fraction, 0.06)

    def test_unreadable_frame_falls_through_without_extra_wait(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.png"
            changed, fraction = FrameChangeProbe(missing).changed(missing)
        self.assertTrue(changed)
        self.assertIsNone(fraction)


if __name__ == "__main__":
    unittest.main()
