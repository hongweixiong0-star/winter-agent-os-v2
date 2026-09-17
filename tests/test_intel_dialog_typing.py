"""CAP-A01: the Intel dialog's kind is read from its title, not from a template.

The defect this pins, measured on the archived frames (2026-09-17):

    frame              template layer before           title band OCR
    击败野兽 (beast)   INTEL_BEAST_MISSION/BEAST       击败野兽等级10
    英雄之旅 等级10    INTEL_HERO_JOURNEY             英雄之旅等级10
    英雄之旅 等级2     INTEL_BEAST_MISSION/BEAST       英雄之旅等级2   <-- wrong
    大师悬赏           INTEL_MASTER_BOUNTY             大师悬赏：20号

Why a template cannot answer it: ``TARGET_INTEL_BEAST_MISSION`` is an *anywhere*
matcher with a deliberately loose gate of 54, and it measures **d=28 on all four**
dialogs -- the beast one included.  It cannot discriminate.  The specific title
matchers could, but their crops bake in the mission level
(``POPUP_INTEL_HERO_JOURNEY_TITLE`` was cut from 英雄之旅等级10), so on a 等级2 dialog
it sat at d=16 against a threshold of 8 and lost to the generic matcher.  A hero
journey dialog therefore became a beast mission, and ``OPEN_INTEL_BEAST_TARGET`` went
looking for a beast target that was never on screen -- while the brain already had a
correct ``INTEL_HERO_JOURNEY`` route that was simply never taken.

Two rejected alternatives, so nobody re-tries them:

* a *level-free* title crop.  Cropping only 英雄之旅 and hashing at size=16 measured
  d=0 on the level-2 frame but **d=131 against the level-10 frame** and 115-126
  against the other dialogs.  The string is centred, so the level's width shifts the
  invariant part by 7-14 px, and at that crop size a dhash cell is ~2.6 px wide.  Text
  at size=16 cannot absorb that.
* registering one more instance per level.  It measures perfectly (d=0 on its own
  frame) and covers only the levels observed, which is the enumeration treadmill the
  project's own crop lesson warns about.

The tests below therefore check the shipped rule: the title text decides, an
unrecognised title leaves the template layer's answer alone, and a mission_id that
belongs to a different type is dropped rather than carried over.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.ocr import (  # noqa: E402
    INTEL_DIALOG_TITLES,
    INTEL_MISSION_ID_PREFIX,
    INTEL_TITLE_ROI,
    HybridVision,
    OCRToken,
)

BEAST = ROOT / "dataset/raw/live_beast_intel_probe.png"
HERO_L10 = ROOT / "dataset/raw/live_intel_purple_axes_probe.png"
HERO_L2 = ROOT / "dataset/raw/live_runtime/live_runtime_step_005_before_20260917T043816219622.png"
BOUNTY = ROOT / "dataset/raw/live_intel_orange_rabbit_probe.png"
REWARD = ROOT / "dataset/truth_audit/reward_popup_source_20260917/key/01_daily_reward_popup_163338.png"


class _TemplateVision:
    """Returns a fixed state, so the correction can be driven without a frame."""

    def __init__(self, state: WorldState) -> None:
        self._state = state

    def observe(self, _path: Path) -> WorldState:
        return self._state


class _StubOCR:
    def __init__(self, text: str, confidence: float = 0.99) -> None:
        self.text = text
        self.confidence = confidence
        self.calls: list[object] = []

    def recognize(self, _path: Path, roi: object = None):
        self.calls.append(roi)

        class _Result:
            tokens = (OCRToken(self.text, self.confidence),) if self.text else ()

        return _Result()


def vision_for(state: WorldState, text: str, confidence: float = 0.99) -> tuple[HybridVision, _StubOCR]:
    ocr = _StubOCR(text, confidence)
    return HybridVision(_TemplateVision(state), ocr), ocr


def beast_dialog() -> WorldState:
    return WorldState(
        page=Page.POPUP, popup="INTEL_BEAST_MISSION",
        intel={"status": "AVAILABLE", "mission_id": "INTEL_BEAST_10",
               "mission_type": "BEAST", "mission_level": 10},
    )


class TitleReadsTheKindTest(unittest.TestCase):
    def test_a_hero_journey_title_overrides_a_beast_classification(self):
        # The exact live case: the template layer said BEAST, the dialog said 英雄之旅.
        vision, _ = vision_for(beast_dialog(), "英雄之旅等级2")
        state = vision.observe(Path("ignored.png"))
        self.assertEqual(state.popup, "INTEL_HERO_JOURNEY")
        self.assertEqual(state.intel["mission_type"], "HERO_JOURNEY")

    def test_the_level_is_read_instead_of_hardcoded(self):
        # vision.py hardcodes mission_level 10 for every Intel dialog; the live dialog
        # read 等级2.  A wrong level is what makes a verifier fail for a reason that is
        # not the real one.
        for text, expected in (("英雄之旅等级2", 2), ("英雄之旅等级10", 10), ("击败野兽等级7", 7)):
            vision, _ = vision_for(beast_dialog(), text)
            self.assertEqual(vision.observe(Path("x.png")).intel["mission_level"], expected, text)

    def test_a_master_bounty_title_types_itself(self):
        vision, _ = vision_for(beast_dialog(), "大师悬赏：20号")
        state = vision.observe(Path("x.png"))
        self.assertEqual(state.popup, "INTEL_MASTER_BOUNTY")
        self.assertEqual(state.intel["mission_type"], "MASTER_BOUNTY")

    def test_the_beast_title_keeps_the_beast_reading(self):
        vision, _ = vision_for(beast_dialog(), "击败野兽等级10")
        state = vision.observe(Path("x.png"))
        self.assertEqual(state.popup, "INTEL_BEAST_MISSION")
        self.assertEqual(state.intel["mission_id"], "INTEL_BEAST_10")

    def test_a_mission_id_from_the_wrong_type_is_dropped(self):
        # INTEL_BEAST_10 attached to a hero journey is an invention of the branch that
        # got the type wrong; the verifier compares mission_id, so carrying it over
        # would let a wrong id satisfy a check it has no business satisfying.
        vision, _ = vision_for(beast_dialog(), "英雄之旅等级2")
        self.assertNotIn("mission_id", vision.observe(Path("x.png")).intel)

    def test_the_rest_of_the_reading_survives_the_correction(self):
        state = beast_dialog()
        state.intel["stamina"] = 347
        state.intel["pins"] = 6
        vision, _ = vision_for(state, "英雄之旅等级2")
        corrected = vision.observe(Path("x.png"))
        self.assertEqual(corrected.intel["stamina"], 347)
        self.assertEqual(corrected.intel["pins"], 6)
        self.assertEqual(corrected.intel["status"], "AVAILABLE")


class RefusalTest(unittest.TestCase):
    """An unknown title must change nothing: a wrong type is worse than the generic one."""

    def test_an_unrecognised_title_leaves_the_template_answer_alone(self):
        vision, _ = vision_for(beast_dialog(), "某个没见过的任务")
        self.assertEqual(vision.observe(Path("x.png")).popup, "INTEL_BEAST_MISSION")

    def test_a_frame_that_is_not_a_dialog_is_not_read_at_all(self):
        state = WorldState(page=Page.HOME)
        vision, ocr = vision_for(state, "英雄之旅等级2")
        self.assertEqual(vision.observe(Path("x.png")).page, Page.HOME)
        self.assertEqual(ocr.calls, [], "no OCR pass on a non-dialog frame")

    def test_a_dialog_with_no_readable_title_is_left_alone(self):
        vision, _ = vision_for(beast_dialog(), "", confidence=0.10)
        self.assertEqual(vision.observe(Path("x.png")).popup, "INTEL_BEAST_MISSION")

    def test_a_low_confidence_title_does_not_type_the_dialog(self):
        # 0.85 is the floor the rest of this module uses for a token it will act on.
        vision, _ = vision_for(beast_dialog(), "英雄之旅等级2", confidence=0.60)
        self.assertEqual(vision.observe(Path("x.png")).popup, "INTEL_BEAST_MISSION")


class TableShapeTest(unittest.TestCase):
    def test_only_observed_names_are_in_the_table(self):
        self.assertEqual([row[0] for row in INTEL_DIALOG_TITLES],
                         ["击败野兽", "英雄之旅", "大师悬赏"])

    def test_every_row_names_a_popup_and_a_type(self):
        for title, popup, mission_type in INTEL_DIALOG_TITLES:
            self.assertTrue(title and popup and mission_type)
            self.assertEqual(popup, f"INTEL_{mission_type}" if mission_type != "BEAST" else "INTEL_BEAST_MISSION")

    def test_the_types_with_a_mission_id_prefix_are_the_template_layers_own(self):
        self.assertEqual(set(INTEL_MISSION_ID_PREFIX), {"BEAST", "FIREBEAST", "RESCUE_SURVIVORS"})
        for mission_type in ("HERO_JOURNEY", "MASTER_BOUNTY"):
            self.assertNotIn(mission_type, INTEL_MISSION_ID_PREFIX)

    def test_the_title_band_covers_where_the_titles_were_measured(self):
        # OCR bounds on both hero journey frames: y 287..323 (level 10) and 287..323
        # (level 2); the master bounty title is at y 350..386.  All inside the band.
        y1 = INTEL_TITLE_ROI["y_norm"] * 1280
        y2 = (INTEL_TITLE_ROI["y_norm"] + INTEL_TITLE_ROI["h_norm"]) * 1280
        for top, bottom in ((287, 323), (350, 386)):
            self.assertLessEqual(y1, top, "band must start above the title")
            self.assertGreaterEqual(y2, bottom, "band must end below the title")


class LiveFrameReplayTest(unittest.TestCase):
    """The same test through the real observation path, on the archived frames."""

    @classmethod
    def setUpClass(cls):
        import json

        from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend
        from winter_agent_v2.vision import SemanticWorldVision

        try:
            config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
            cls.vision = HybridVision(
                SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json"),
                OCRService(ResilientOCRBackend(RapidOCRBackend(Path(config["ocr"]["module_path"])))),
            )
        except Exception as exc:  # noqa: BLE001 - OCR absent on a fresh clone
            raise unittest.SkipTest(f"OCR backend unavailable: {exc}")

    def _observe(self, frame: Path):
        if not frame.is_file():
            self.skipTest(f"frame rotated away: {frame.name}")
        return self.vision.observe(frame)

    def test_the_failing_frame_now_types_as_hero_journey(self):
        state = self._observe(HERO_L2)
        self.assertEqual(state.popup, "INTEL_HERO_JOURNEY")
        self.assertEqual(state.intel["mission_type"], "HERO_JOURNEY")
        self.assertEqual(state.intel["mission_level"], 2)

    def test_the_level_ten_frame_still_types_as_hero_journey(self):
        state = self._observe(HERO_L10)
        self.assertEqual(state.popup, "INTEL_HERO_JOURNEY")
        self.assertEqual(state.intel["mission_level"], 10)

    def test_the_real_beast_dialog_is_not_changed(self):
        state = self._observe(BEAST)
        self.assertEqual(state.popup, "INTEL_BEAST_MISSION")
        self.assertEqual(state.intel["mission_type"], "BEAST")
        self.assertEqual(state.intel["mission_id"], "INTEL_BEAST_10")

    def test_the_master_bounty_dialog_is_unchanged(self):
        state = self._observe(BOUNTY)
        self.assertEqual(state.popup, "INTEL_MASTER_BOUNTY")
        self.assertEqual(state.intel["mission_type"], "MASTER_BOUNTY")

    def test_a_reward_popup_is_not_touched_by_the_intel_reader(self):
        state = self._observe(REWARD)
        self.assertNotEqual(str(state.popup).startswith("INTEL_"), True)
        self.assertEqual(state.intel, {})


if __name__ == "__main__":
    unittest.main()
