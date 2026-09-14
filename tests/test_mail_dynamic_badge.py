import unittest
from pathlib import Path

from winter_agent_v2.models import Page
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]

# `dataset/raw/control_panel/runtime_mail/**` 会被 retention.auto_prune 按 TTL
# 清理，历史会话目录已空，因此这里改用长期保留的引导帧。
HOME_WITH_MAIL = ROOT / "dataset/raw/live_home_after_bootstrap.png"


class MailDynamicBadgeTests(unittest.TestCase):
    def test_current_badge_19_mailbox_remains_locatable(self):
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        self.assertTrue(HOME_WITH_MAIL.is_file(), f"缺少引导帧：{HOME_WITH_MAIL}")
        self.assertIs(vision.observe(HOME_WITH_MAIL).page, Page.HOME)
        match = vision.semantic.find(HOME_WITH_MAIL, "BTN_OPEN_MAIL")
        self.assertIsNotNone(match)
        self.assertLessEqual(match.distance, 24)

    def test_current_mail_page_anchor_wins_over_home_fallback(self):
        vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")
        path = ROOT / "dataset/raw/live_mail_dynamic_badge_fix_20260909/step_001_before.png"
        self.assertIs(vision.observe(path).page, Page.MAIL)


if __name__ == "__main__": unittest.main()
