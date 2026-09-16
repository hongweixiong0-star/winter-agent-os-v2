"""Which role is logged in, read from the client instead of assumed.

The operator's product definition (2026-09-16) requires the agent to identify the
role it is logged in as before it reads that role's state: "登录谁，就读谁的状态".
The project had no role concept at all, and the corpus had already been built from
two different accounts -- 70,206,322 power with 行军 6 on 2026-09-14 against
542,443 power with 行军 2 on 2026-09-16, both on server #4298 -- so every metric
that pooled them was un-scoped.

These tests pin the read in both directions.  The negative direction is the one
that protects persisted state: a frame that is not the profile panel must not
produce an identity, because keying role state to a role nobody observed is worse
than having no identity at all.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from winter_agent_v2.ocr import (
    OCRToken,
    parse_role_identity,
    read_march_count,
    read_role_identity_rows,
)

from live_stack import production_vision

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "dataset/truth_audit/role_identity_20260916"
PROFILE_PANEL = EVIDENCE / "profile_panel_live_20260916T184004.png"
NON_PROFILE_FRAMES = (EVIDENCE / "map_before_tap.png", EVIDENCE / "map_after_back.png")

# The rows the 领主档案 panel drew, quoted from the archived live frame.  Row order
# is the panel's own layout: name first, then the labelled rows.
PANEL_ROWS = [
    "[zoe]xhw小号",
    "账号：1171757165",
    "54.2万",
    "击败：0Q",
    "联盟：zoe",
    "所在王国：4298",
]
TITLE = "领主档案"


def box(left: float, top: float, right: float, bottom: float) -> tuple[tuple[float, float], ...]:
    return ((left, top), (right, top), (right, bottom), (left, bottom))


class TheRoleIsReadFromThePanelTests(unittest.TestCase):
    def test_the_panel_yields_the_identity_it_drew(self):
        identity = parse_role_identity(TITLE, PANEL_ROWS)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.role_id, "1171757165")
        self.assertEqual(identity.role_name, "xhw小号")
        self.assertEqual(identity.alliance_tag, "zoe")
        self.assertEqual(identity.kingdom, "4298")
        self.assertEqual(identity.power_text, "54.2万")

    def test_the_alliance_tag_is_not_baked_into_the_name(self):
        # A name is what the player sees; the tag is a separate fact that changes
        # when the role changes alliance.  Merging them would make the identity
        # move for a reason unrelated to which role is logged in.
        identity = parse_role_identity(TITLE, PANEL_ROWS)
        self.assertNotIn("zoe", identity.role_name)
        self.assertNotIn("[", identity.role_name)

    def test_a_role_with_no_alliance_tag_has_none(self):
        rows = ["xhw小号", "账号：1171757165", "54.2万", "联盟：", "所在王国：4298"]
        identity = parse_role_identity(TITLE, rows)
        self.assertIsNotNone(identity)
        self.assertIsNone(identity.alliance_tag)
        self.assertEqual(identity.role_name, "xhw小号")

    def test_the_power_stays_text_because_the_panel_rounds(self):
        # The panel printed 54.2万 while the HUD on the same frame read 542,443.
        # An int would claim a precision the client never drew.
        identity = parse_role_identity(TITLE, PANEL_ROWS)
        self.assertIsInstance(identity.power_text, str)

    def test_a_label_that_is_not_a_power_total_is_not_taken_as_one(self):
        rows = ["xhw小号", "账号：1171757165", "所在王国：4298"]
        identity = parse_role_identity(TITLE, rows)
        self.assertIsNotNone(identity)
        self.assertIsNone(identity.power_text)


class NoIdentityIsInventedTests(unittest.TestCase):
    """The direction that protects every piece of role-scoped state."""

    def test_a_frame_without_the_panel_title_yields_nothing(self):
        # 账号： also appears on account-management screens, which is exactly where
        # config.risk.block_account_or_role_delete applies.  The title is the
        # second, independent fact that separates them.
        self.assertIsNone(parse_role_identity("行军队列", PANEL_ROWS))
        self.assertIsNone(parse_role_identity("", PANEL_ROWS))

    def test_a_panel_without_the_account_row_yields_nothing(self):
        rows = ["[zoe]xhw小号", "54.2万", "联盟：zoe", "所在王国：4298"]
        self.assertIsNone(parse_role_identity(TITLE, rows))

    def test_a_missing_name_row_is_not_substituted_by_a_labelled_one(self):
        # If OCR drops the name line the topmost row becomes 账号…, and reporting
        # "账号：1171757165" as the role *name* would key state to a string the
        # player never had.
        rows = ["账号：1171757165", "54.2万", "联盟：zoe", "所在王国：4298"]
        self.assertIsNone(parse_role_identity(TITLE, rows))

    def test_a_numeric_name_is_never_a_role_name(self):
        rows = ["1171757165", "账号：1171757165", "所在王国：4298"]
        self.assertIsNone(parse_role_identity(TITLE, rows))

    def test_no_rows_at_all_yields_nothing(self):
        self.assertIsNone(parse_role_identity(TITLE, []))


class RowsComeFromGeometryNotFromRectanglesTests(unittest.TestCase):
    def test_tokens_are_grouped_into_rows_then_ordered_left_to_right(self):
        tokens = (
            OCRToken("1171757165", 0.99, box(55, 50, 140, 70)),
            OCRToken("[zoe]xhw小号", 0.98, box(5, 10, 100, 30)),
            OCRToken("账号：", 0.99, box(5, 50, 50, 70)),
            OCRToken("所在王国：4298", 0.99, box(5, 175, 130, 195)),
        )
        rows = read_role_identity_rows(tokens)
        self.assertEqual(rows[0], "[zoe]xhw小号")
        self.assertEqual(rows[1], "账号： 1171757165")
        self.assertEqual(rows[2], "所在王国：4298")
        # A split account token still parses, which is why the pair is joined.
        identity = parse_role_identity(TITLE, rows)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.role_id, "1171757165")

    def test_tokens_without_boxes_are_dropped_rather_than_placed(self):
        rows = read_role_identity_rows((OCRToken("noise", 0.99, ()),))
        self.assertEqual(rows, [])


class TheMarchCounterCannotBeRewrittenByAFragmentTests(unittest.TestCase):
    def test_the_real_two_token_read_keeps_the_capacity_the_client_drew(self):
        # Measured 2026-09-16 on the frame carrying account A's counter: the ROI
        # OCR returned '3/' and '3/6', and joining them before matching let the
        # pattern read 3/ 3.  The episode recorded capacity 3 on a client that
        # said 6 -- the one number the whole dispatch path rests on.
        self.assertEqual(read_march_count("3/\n3/6"), (3, 6))

    def test_the_real_single_token_read_is_unchanged(self):
        self.assertEqual(read_march_count("1/2"), (1, 2))

    def test_a_fragment_alone_is_not_a_count(self):
        self.assertIsNone(read_march_count("3/"))
        self.assertIsNone(read_march_count(""))

    def test_two_whole_counts_are_ambiguous_rather_than_guessed(self):
        self.assertIsNone(read_march_count("3/\n3/6\n5/6"))

    def test_a_count_is_not_carved_out_of_a_longer_number(self):
        self.assertIsNone(read_march_count("200/200"))
        self.assertIsNone(read_march_count("542,443"))

    def test_a_label_and_the_count_may_share_a_line(self):
        self.assertEqual(read_march_count("行军 5/6"), (5, 6))
        self.assertEqual(read_march_count("行军\n5/6"), (5, 6))


class LivePanelReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = production_vision()
        if cls.vision is None:
            raise unittest.SkipTest("OCR runtime unavailable")
        if not PROFILE_PANEL.is_file():
            raise unittest.SkipTest("profile panel evidence missing")

    def test_the_archived_live_panel_reads_the_role(self):
        identity = self.vision.read_role_identity(PROFILE_PANEL)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.role_id, "1171757165")
        self.assertEqual(identity.role_name, "xhw小号")
        self.assertEqual(identity.alliance_tag, "zoe")
        self.assertEqual(identity.kingdom, "4298")
        self.assertGreater(identity.confidence, 0.80)

    def test_a_map_frame_never_produces_an_identity(self):
        for frame in NON_PROFILE_FRAMES:
            if not frame.is_file():
                continue
            with self.subTest(frame=frame.name):
                self.assertIsNone(self.vision.read_role_identity(frame))


if __name__ == "__main__":
    unittest.main()
