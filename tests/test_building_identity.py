"""Building identity read off pixels (CAP-B01).

What went wrong, 2026-09-17/18
------------------------------
``vision.py`` answered the building-upgrade control with
``{"id": "STOREHOUSE", "level": 26, "target_level": 27}`` and none of those values was
read from a frame.  They came from
``dataset/raw/live_build_warehouse_upgrade_dialog.png`` -- a dialog that does not show
the current level at all; the only level on it is the *prerequisite* row
``大熔炉 等级 27``.  The operator's rule is that identity must never be
reverse-engineered, so the template layer no longer asserts one and this reader supplies
what the client actually draws:

    dataset/raw/live_build_quest_navigation.png, measured
      '26'                       conf=0.999  px=[285,533,322,559]
      '仓库'                     conf=0.999  px=[351,534,401,559]
      '将仓库升到27级（26/27）'   conf=0.964  px=[79,1039,347,1067]

The tests below pin the two things that make this safe rather than merely working:
spatial association (a number is a level only when it sits immediately left of the name
in the same row) and refusal (UNKNOWN, never the closest-looking building).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.building_identity import (  # noqa: E402
    BUILDING_IDS,
    UNKNOWN,
    read_building_identity,
)
from winter_agent_v2.ocr import OCRToken  # noqa: E402


def token(text: str, box: tuple[float, float, float, float], confidence: float = 0.99) -> OCRToken:
    x0, y0, x1, y1 = box
    return OCRToken(text=text, confidence=confidence,
                    box=((x0, y0), (x1, y0), (x1, y1), (x0, y1)))


def city_tokens() -> list[OCRToken]:
    """The tokens that actually matter on the live city frame, with their real boxes
    and the confidences RapidOCR actually reported."""
    return [
        token("26", (285, 533, 322, 559), 0.999),   # the level, left of the name
        token("仓库", (351, 534, 401, 559), 0.999),  # the building name
        token("112.2万", (430, 30, 520, 58)),       # HUD currency -- not a level
        token("02:37:43", (520, 300, 610, 328)),    # countdown -- not a level
        token("32/32", (200, 20, 250, 46)),         # HUD counter -- not a level
        token("详情", (276, 926, 324, 956)),        # the other action entry
        token("将仓库升到27级（26/27）", (79, 1039, 347, 1067), 0.964),
    ]


class LabelParsingTest(unittest.TestCase):
    def test_the_live_label_resolves_to_a_named_building_and_its_level(self):
        identity = read_building_identity(city_tokens())
        self.assertEqual(identity.name, "仓库")
        self.assertEqual(identity.building_id, "STOREHOUSE")
        self.assertEqual(identity.level, 26)

    def test_the_target_level_comes_from_the_quest_banner_when_it_names_the_same_building(self):
        identity = read_building_identity(city_tokens())
        self.assertEqual(identity.target_level, 27)
        self.assertEqual(identity.source, "FLOATING_LABEL_OCR+QUEST_BANNER")

    def test_the_target_falls_back_to_the_next_level_and_says_so(self):
        tokens = [token("26", (285, 533, 322, 559)), token("仓库", (351, 534, 401, 559))]
        identity = read_building_identity(tokens)
        self.assertEqual(identity.level, 26)
        self.assertEqual(identity.target_level, 27)
        self.assertEqual(identity.source, "FLOATING_LABEL_OCR+LEVEL_PLUS_ONE")

    def test_the_confidence_is_the_one_the_client_reported(self):
        identity = read_building_identity(city_tokens())
        self.assertAlmostEqual(identity.confidence, 0.999, places=3)

    def test_the_output_contract_is_exactly_the_six_keys(self):
        state = read_building_identity(city_tokens()).as_state()
        self.assertEqual(
            set(state),
            {"id", "name", "level", "target_level", "identity_confidence", "identity_source"},
        )


class SpatialAssociationTest(unittest.TestCase):
    """A number is a level only when it is *this label's* number."""

    def test_a_number_far_to_the_left_is_not_this_building_s_level(self):
        tokens = [token("187", (60, 530, 108, 556)), token("仓库", (351, 534, 401, 559))]
        identity = read_building_identity(tokens)
        self.assertIsNone(identity.level)
        self.assertEqual(identity.source, "LABEL_NAME_ONLY")

    def test_a_number_in_another_row_is_not_this_building_s_level(self):
        tokens = [token("26", (285, 700, 322, 726)), token("仓库", (351, 534, 401, 559))]
        self.assertIsNone(read_building_identity(tokens).level)

    def test_a_number_to_the_right_of_the_name_is_not_the_level(self):
        tokens = [token("26", (420, 533, 458, 559)), token("仓库", (351, 534, 401, 559))]
        self.assertIsNone(read_building_identity(tokens).level)

    def test_currency_countdown_and_hud_counters_never_become_a_level(self):
        for text in ("112.2万", "02:37:43", "50,000,000+10,000,000", "1,249", "32/32",
                     "（26/27）", "等级27", "-33.6°C"):
            with self.subTest(text=text):
                tokens = [token(text, (285, 533, 322, 559)), token("仓库", (351, 534, 401, 559))]
                self.assertIsNone(read_building_identity(tokens).level, text)

    def test_an_implausible_level_is_rejected(self):
        tokens = [token("999", (285, 533, 322, 559)), token("仓库", (351, 534, 401, 559))]
        self.assertIsNone(read_building_identity(tokens).level)


class RefusalTest(unittest.TestCase):
    """UNKNOWN, never the closest-looking building."""

    def test_no_name_token_is_unknown_with_a_reason(self):
        identity = read_building_identity([token("26", (285, 533, 322, 559))])
        self.assertEqual(identity.building_id, UNKNOWN)
        self.assertIsNone(identity.level)
        self.assertEqual(identity.source, "NO_BUILDING_NAME_TOKEN")

    def test_a_name_outside_the_table_keeps_the_name_and_the_level_but_refuses_the_id(self):
        # The operator's contract: an unlisted building is still reported by name, with
        # building.id = UNKNOWN.  The level is a real observation (26 sits immediately
        # left of the name), so it is kept; the *identity* is what is refused.
        tokens = [token("26", (285, 533, 322, 559)), token("兵工厂", (351, 534, 401, 559))]
        identity = read_building_identity(tokens)
        self.assertEqual(identity.name, "兵工厂")
        self.assertEqual(identity.level, 26)
        self.assertEqual(identity.building_id, UNKNOWN)

    def test_a_misspelt_name_is_not_fuzzy_matched(self):
        # 仓厍 is one character off 仓库; treating it as 仓库 would be exactly the
        # "closest-building" guess that is forbidden.  The label is still readable, so
        # the name and level are reported -- only the id is refused.
        tokens = [token("26", (285, 533, 322, 559)), token("仓厍", (351, 534, 401, 559))]
        identity = read_building_identity(tokens)
        self.assertEqual(identity.name, "仓厍")
        self.assertEqual(identity.building_id, UNKNOWN)

    def test_a_known_label_wins_over_an_unlisted_one(self):
        # Precedence, not ambiguity: when one candidate is a building we can name, that is
        # the answer -- an unlisted 兵工厂 elsewhere on the frame does not make the read
        # ambiguous.
        tokens = [
            token("26", (285, 533, 322, 559)), token("仓库", (351, 534, 401, 559)),
            token("12", (285, 700, 322, 726)), token("兵工厂", (351, 701, 401, 726)),
        ]
        identity = read_building_identity(tokens)
        self.assertEqual(identity.name, "仓库")
        self.assertEqual(identity.building_id, "STOREHOUSE")
        self.assertEqual(identity.level, 26)

    def test_two_unlisted_labels_refuse_rather_than_pick_one(self):
        tokens = [
            token("26", (285, 533, 322, 559)), token("兵工厂", (351, 534, 401, 559)),
            token("12", (285, 700, 322, 726)), token("铁匠铺", (351, 701, 401, 726)),
        ]
        identity = read_building_identity(tokens)
        self.assertEqual(identity.building_id, UNKNOWN)
        self.assertEqual(identity.source, "NO_BUILDING_NAME_TOKEN")

    def test_a_low_confidence_name_is_refused(self):
        tokens = [token("仓库", (351, 534, 401, 559), 0.55), token("26", (285, 533, 322, 559))]
        identity = read_building_identity(tokens)
        self.assertEqual(identity.building_id, UNKNOWN)
        self.assertEqual(identity.source, "NO_BUILDING_NAME_TOKEN")

    def test_a_name_without_a_level_still_reports_the_name_but_not_a_level(self):
        identity = read_building_identity([token("仓库", (351, 534, 401, 559))])
        self.assertEqual(identity.building_id, "STOREHOUSE")
        self.assertIsNone(identity.level)
        self.assertEqual(identity.source, "LABEL_NAME_ONLY")


class QuestBannerTest(unittest.TestCase):
    def test_a_banner_about_another_building_is_not_borrowed(self):
        tokens = [token("26", (285, 533, 322, 559)), token("仓库", (351, 534, 401, 559)),
                  token("将大熔炉升到30级（29/30）", (79, 1039, 347, 1067), 0.96)]
        identity = read_building_identity(tokens, quest_texts=["将大熔炉升到30级（29/30）"])
        self.assertEqual(identity.target_level, 27, "must fall back to level+1")
        self.assertEqual(identity.source, "FLOATING_LABEL_OCR+LEVEL_PLUS_ONE")

    def test_a_banner_whose_current_level_contradicts_the_label_loses_its_target(self):
        # Same name, different current level: the two readings disagree, so the target is
        # dropped and the confidence drops with it rather than the disagreement hidden.
        tokens = [token("26", (285, 533, 322, 559)), token("仓库", (351, 534, 401, 559)),
                  token("将仓库升到31级（30/31）", (79, 1039, 347, 1067), 0.96)]
        identity = read_building_identity(tokens, quest_texts=["将仓库升到31级（30/31）"])
        self.assertEqual(identity.target_level, 27)
        self.assertLessEqual(identity.confidence, 0.5)

    def test_a_matching_banner_current_level_keeps_full_confidence(self):
        identity = read_building_identity(city_tokens())
        self.assertGreater(identity.confidence, 0.9)


class TablePolicyTest(unittest.TestCase):
    def test_every_entry_maps_to_a_plausible_id(self):
        for name, building_id in BUILDING_IDS.items():
            self.assertTrue(name.strip(), name)
            self.assertTrue(building_id.isupper(), building_id)
            self.assertNotEqual(building_id, UNKNOWN)

    def test_the_table_has_no_duplicate_ids(self):
        ids = list(BUILDING_IDS.values())
        self.assertEqual(len(ids), len(set(ids)))


class LiveFrameReplayTest(unittest.TestCase):
    """Replay the measurements this reader was built from, on the real frames."""

    FRAME = ROOT / "dataset/raw/live_build_quest_navigation.png"
    CAMP_FRAME = (ROOT / "dataset/truth_audit/power_route_20260917"
                  "/build_live2_20260917_115113_01_after_tap_280_640.png")

    @staticmethod
    def _read(frame: Path):
        import json

        from winter_agent_v2.ocr import OCRService, RapidOCRBackend, ResilientOCRBackend

        config = json.loads((ROOT / "config/v2.json").read_text(encoding="utf-8"))
        service = OCRService(ResilientOCRBackend(
            RapidOCRBackend(Path(config["ocr"]["module_path"]))))
        tokens = [t for t in service.recognize(frame).tokens if t.confidence >= 0.80]
        return read_building_identity(tokens, quest_texts=[t.text for t in tokens])

    def test_the_real_frame_yields_the_measured_identity(self):
        if not self.FRAME.is_file():
            self.skipTest("parent frame rotated away by retention")
        identity = self._read(self.FRAME)
        self.assertEqual(identity.name, "仓库")
        self.assertEqual(identity.building_id, "STOREHOUSE")
        self.assertEqual(identity.level, 26)
        self.assertEqual(identity.target_level, 27)
        self.assertEqual(identity.source, "FLOATING_LABEL_OCR+QUEST_BANNER")

    def test_a_live_camp_frame_reports_its_name_and_level_but_refuses_an_unlisted_id(self):
        # Live 2026-09-17 19:51 GMT+8, a selected 盾兵营.  The frame also carries 467, 27,
        # 113.1万, 01:12:50 and 32/32; the level must come from the 12 beside the name.
        if not self.CAMP_FRAME.is_file():
            self.skipTest("camp frame rotated away by retention")
        identity = self._read(self.CAMP_FRAME)
        self.assertEqual(identity.name, "盾兵营")
        self.assertEqual(identity.level, 12)
        self.assertEqual(identity.building_id, UNKNOWN)
        self.assertEqual(identity.target_level, 13)
        self.assertEqual(identity.source, "FLOATING_LABEL_OCR+LEVEL_PLUS_ONE")


if __name__ == "__main__":
    unittest.main()
