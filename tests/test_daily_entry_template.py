"""The daily entry point resolves on the live city frame -- and only there.

Origin (2026-09-16).  ``OPEN_DAILY`` (HOME -> DAILY) is the entry point of the whole
daily-mission family and it had never worked under the auditable episode schema.
The first live attempt of the day recorded

    skill OPEN_DAILY   action TAP_SEMANTIC BTN_OPEN_DAILY
    executed=false     error SEMANTIC_TARGET_NOT_VERIFIED

``BTN_OPEN_DAILY`` was a single record cut on 2026-09-08, and measured against
today's live frame it scored **distance 18 against a gate of 8** while the city's
other buttons still hit (exploration d=0, alliance d=8, mail d=8..20 under its own
gate of 24).  Between the two dates the red claimable badge left the icon and the
city behind it changed.

The replacement was chosen by measurement, not by loosening the gate
(``tools/probe_daily_entry_gate.py``, all 3480 frames of ``dataset/raw``, using the
city/HUD bottom-nav button as the recall proxy):

    candidate                recall(hud, n=1104)   hits outside   old-parent frame
    existing (2026-09-08)         24  ( 2.2%)            0            d=2
    full_circle                   41  ( 3.7%)            0            d=16  (miss)
    lower_band                   587  (53.2%)            0            d=2
    left_half                   1054  (95.5%)            1            d=6   (hit)

``left_half`` -- the left 2/3 of the icon circle, which excludes the badge -- is the
only candidate that covers **both** states of the control, so one record serves the
claimable and the claimed client.  The old record is kept (``find`` takes the
minimum over records), so nothing that used to resolve stops resolving.

The exact same fix is also what ``test_daily_panel_dead_end_recovery`` builds on:
once the step worked, the run reached the panel and had to be given a way out.

These frames are archived under ``dataset/truth_audit/`` rather than read out of
``dataset/raw``: the raw tree is rotated by the retention pass, and
``test_evidence_integrity`` fails the suite for tests that depend on it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.models import Page
from winter_agent_v2.vision import SemanticROIVision, SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"

# The live city frame the replacement was cut from (2026-09-16T13:10:40Z).
LIVE_CITY = (ROOT / "dataset" / "truth_audit" / "daily_entry_template_20260916"
             / "00_live_home_20260916T131040Z.png")

# The panel the fixed step lands on.  It is a negative control for the semantic:
# the entry icon is not drawn there, so the tap target must not resolve -- the
# panel would otherwise be tapped through.
PANEL = (ROOT / "dataset" / "truth_audit" / "daily_tasks_tab_20260916"
         / "01_before_20260916_134609.png")

SEMANTIC = "BTN_OPEN_DAILY"

# Measured on the live frame (tools/register_daily_entry_template.py prints it):
# the icon circle is centred on (42,1052) px with a radius of about 32 px.
ICON_CENTER = (42 / 720, 1052 / 1280)
ICON_RADIUS_X = 34 / 720
ICON_RADIUS_Y = 34 / 1280


def _vision() -> SemanticROIVision:
    return SemanticROIVision(MANIFEST)


class TheEntryResolvesOnTheLiveCityFrameTests(unittest.TestCase):
    def test_the_city_frame_still_classifies_as_home(self):
        # If the frame were not HOME the semantic would never be asked for.
        self.assertIs(SemanticWorldVision(MANIFEST).observe(LIVE_CITY).page, Page.HOME)

    def test_the_entry_resolves_where_it_used_to_be_rejected(self):
        match = _vision().find(LIVE_CITY, SEMANTIC)
        self.assertIsNotNone(match, "BTN_OPEN_DAILY no longer resolves on the live "
                                    "city frame -- the regression this test exists for")
        self.assertLessEqual(match.distance, 8)

    def test_the_record_that_resolves_is_the_2026_09_16_one(self):
        """Pin the identity of the winning record, not just that something won.

        An accidental hit from another record would produce a tap in the wrong
        place while still satisfying "it resolved".
        """
        match = _vision().find(LIVE_CITY, SEMANTIC)
        self.assertIsNotNone(match)
        self.assertAlmostEqual(match.roi["x_norm"], 12 / 720, places=4)
        self.assertAlmostEqual(match.roi["y_norm"], 1026 / 1280, places=4)

    def test_the_tap_point_lands_on_the_icon(self):
        match = _vision().find(LIVE_CITY, SEMANTIC)
        self.assertIsNotNone(match)
        cx, cy = match.center_norm
        self.assertLess(abs(cx - ICON_CENTER[0]), ICON_RADIUS_X)
        self.assertLess(abs(cy - ICON_CENTER[1]), ICON_RADIUS_Y)


class TheTargetDoesNotResolveWhereItIsNotDrawnTests(unittest.TestCase):
    def test_the_panel_frame_rejects_the_semantic(self):
        # NOTE: the production stack reads this frame as ``Page.DAILY`` through
        # its OCR layer (the panel's 章节任务 title strip); the semantic-only
        # vision reports UNKNOWN for it.  What this test pins is the part that
        # matters for a tap target: the entry icon is not drawn inside the panel,
        # so nothing can resolve there.  Observed live: the panel frame resolves
        # ``BTN_OPEN_DAILY`` to human eye as "the same scroll icon" only on the
        # city/map HUD, never here.
        self.assertIsNot(SemanticWorldVision(MANIFEST).observe(PANEL).page, Page.HOME)
        self.assertIsNone(_vision().find(PANEL, SEMANTIC))

    def test_a_frame_the_production_stack_calls_daily_still_rejects_it(self):
        """Same claim, on a frame the semantic-only layer agrees is DAILY.

        The panel the fixed step lands on is the one that matters, and both layers
        call that one DAILY; the archived frame next to it is the reward popup-free
        after-tap frame from the same probe.
        """
        after = (ROOT / "dataset" / "truth_audit" / "daily_tasks_tab_20260916"
                 / "02_after_tap_20260916_134609.png")
        self.assertIs(SemanticWorldVision(MANIFEST).observe(after).page, Page.DAILY)
        self.assertIsNone(_vision().find(after, SEMANTIC))


if __name__ == "__main__":
    unittest.main()
