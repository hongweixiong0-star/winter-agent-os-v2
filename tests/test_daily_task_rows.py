from __future__ import annotations

import unittest

from winter_agent_v2.models import Page
from winter_agent_v2.ocr import OCRPageClassifier, OCRResult, OCRToken


def positioned(text: str, x: float, y: float, *, confidence: float = 0.99) -> OCRToken:
    width = max(22.0, len(text) * 12.0)
    return OCRToken(
        text,
        confidence,
        ((x, y), (x + width, y), (x + width, y + 24), (x, y + 24)),
    )


class DailyTaskRowsTests(unittest.TestCase):
    def test_classifies_visible_rows_without_assuming_fixed_row_pitch(self):
        result = OCRResult((
            positioned("每日任务", 300, 90),
            positioned("完成联盟捐献5次（3/5）", 60, 480),
            positioned("前往", 560, 552),
            positioned("研究1次科技 （0 /1)", 60, 695),
            positioned("前往", 560, 767),
            positioned("完成3次英雄招募（3/3）", 60, 905),
            # A partial preceding card has a button but no visible title. It must
            # not be attached to the first complete title below it.
            positioned("前往", 560, 430),
        ), "fake")

        state = OCRPageClassifier().classify(result, frame_size=(720, 1280))

        self.assertIs(state.page, Page.DAILY)
        rows = state.daily["tasks"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["task_id"], "DAILY_ALLIANCE_CONTRIBUTE")
        self.assertEqual(rows[0]["state"], "AVAILABLE")
        self.assertEqual(rows[0]["progress"], {"current": 3, "target": 5})
        self.assertEqual(rows[0]["action_button"]["semantic_id"], "BTN_DAILY_TASK_GO")
        self.assertEqual(rows[1]["task_id"], "DAILY_RESEARCH")
        self.assertEqual(rows[1]["state"], "AVAILABLE")
        self.assertEqual(rows[1]["progress"], {"current": 0, "target": 1})
        self.assertEqual(rows[2]["task_id"], "DAILY_HERO_RECRUIT")
        self.assertEqual(rows[2]["state"], "COMPLETED")
        self.assertNotIn("action_button", rows[2])

    def test_incomplete_row_without_current_go_button_stays_unknown(self):
        rows = OCRPageClassifier._read_daily_task_rows(
            [positioned("联盟互助20次（4/20）", 80, 600)],
            (720, 1280),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_id"], "DAILY_ALLIANCE_HELP")
        self.assertEqual(rows[0]["state"], "UNKNOWN")
        self.assertEqual(rows[0]["action_type"], "NONE")

    def test_unmapped_title_gets_a_stable_distinct_identity(self):
        one = OCRPageClassifier._read_daily_task_rows(
            [positioned("领取神秘物品（0/1）", 80, 600)], (720, 1280)
        )
        two = OCRPageClassifier._read_daily_task_rows(
            [positioned("完成限时小游戏（0/1）", 80, 600)], (720, 1280)
        )
        self.assertNotEqual(one[0]["task_id"], two[0]["task_id"])
        self.assertEqual(one[0]["semantic_id"], one[0]["task_id"])

    def test_task_identity_keeps_barracks_and_resource_variants_separate(self):
        rows = OCRPageClassifier._read_daily_task_rows(
            [
                positioned("训练30个盾兵（30/30）", 50, 400),
                positioned("训练30个矛兵（30/30）", 50, 620),
                positioned("训练30个射手（30/30）", 50, 840),
                positioned("采集250,000单位生肉（250000/250000）", 50, 1060),
            ],
            (720, 1280),
        )
        self.assertEqual(
            [row["task_id"] for row in rows],
            ["DAILY_TRAIN_SHIELD", "DAILY_TRAIN_LANCER",
             "DAILY_TRAIN_MARKSMAN", "DAILY_GATHER_MEAT"],
        )
        self.assertEqual(len({row["semantic_id"] for row in rows}), len(rows))

    def test_wounded_treatment_and_resource_specific_gathering_have_stable_ids(self):
        rows = OCRPageClassifier._read_daily_task_rows(
            [
                positioned("治疗10个伤兵（0/10）", 60, 420),
                positioned("采集10,000单位煤炭（0/10000）", 60, 680),
            ], (720, 1280),
        )
        self.assertEqual([row["task_id"] for row in rows],
                         ["DAILY_TREAT_WOUNDED", "DAILY_GATHER_COAL"])


if __name__ == "__main__":
    unittest.main()
