"""A red dot is a notification, never a click target (operator directive 2026-09-23).

The directive separates three things that a screenshot makes look like one, and it separates them
because collapsing them is how an agent ends up tapping a badge and calling it work:

    NOTIFICATION   which entry or task row carries the dot, in what state, about what matter
    ENTRY_CONTROL  the real interactive control that enters that function
    TASK_ACTION    what to do once inside, decided from the page's own information, not from the
                   notification

The reading layer already has this shape -- ``EntryBadge`` is a property *of an entry* and carries no
coordinate a caller could tap -- but "already has this shape" is not a guarantee, so the shape is
pinned here.  What this file defends against is concrete: a future change that reaches for the dot's
box as a point, or that starts consuming the ledger somewhere new, would make
"点击红点附近" pass for "红点任务已处理".
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import entry_badges  # noqa: E402
from winter_agent_v2.entry_badges import EntryBadge, entries, PRESENT  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

#: Fields that would make a dot something a caller can aim at.  ``box_norm`` is deliberately not
#: one: it is the evidence for the reading (``pixels`` counts the same region), and the directive's
#: point is that evidence is not a target.
TARGET_LIKE = ("point", "centre", "center", "tap", "click", "target_point", "hit")


class TheNotificationLayerIsNotATargetTest(unittest.TestCase):
    def test_a_badge_carries_no_coordinate_a_caller_could_tap(self):
        fields = tuple(EntryBadge.__dataclass_fields__)
        for name in fields:
            with self.subTest(field=name):
                self.assertFalse(
                    any(word in name.lower() for word in TARGET_LIKE),
                    f"EntryBadge.{name} looks like a tap target; a dot is a notification, and the "
                    f"control that enters the entry is a separate, named thing",
                )
        self.assertIn("box_norm", fields, "the reading's evidence is kept -- as evidence")
        self.assertIn("task_state", fields, "and so is the state the directive asks to separate")

    def test_the_reader_answers_with_badges_and_nothing_else(self):
        """``read_entry_badges`` returns ``{entry: EntryBadge}`` -- there is no second value."""
        import inspect

        source = inspect.getsource(entry_badges.read_entry_badges)
        self.assertIn("EntryBadge", source)
        for word in ("tap", "click", "press("):
            self.assertNotIn(word, source.lower(),
                             f"the reading layer must not {word}; it reads, it does not act")

    def test_the_only_consumer_of_the_ledger_is_the_scoring_layer(self):
        """One declared consumer per level, and this test is what keeps the list short.

        Measured 2026-09-23: the whole package consumes the dots in exactly two places -- the ranking
        term in ``goal_utility`` (a *score*) and the mail entry's decision to open its page at all (a
        *branch*).  Neither is a coordinate.  A third consumer appearing means somebody is using the
        notification for something else, and the directive wants that stated rather than assumed.
        """
        found: dict[str, list[str]] = {}
        for path in sorted((ROOT / "winter_agent_v2").glob("*.py")):
            if path.name == "entry_badges.py":
                continue  # the module that defines it is not a consumer of it
            text = path.read_text(encoding="utf-8")
            hits = [line.strip() for line in text.splitlines()
                    if "dots_pointing_at(" in line and not line.strip().startswith("#")]
            if hits:
                found[path.name] = hits
        self.assertEqual(sorted(found), ["goal_utility.py"],
                         f"a new consumer of the dots appeared: {found}")
        self.assertTrue(any("RED_DOT_BONUS" in h or "red_dot" in h for h in found["goal_utility.py"]),
                        "and it is the scoring path, not a locator")

    def test_the_branch_on_the_notification_is_a_branch_not_a_tap(self):
        """The mail entry's dot decides *whether to enter*, which is the directive's own split."""
        brain = (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8")
        start = brain.index('mail_badge = str(((world.red_dots or {})')
        window = brain[start:start + 700]
        self.assertIn('Decision("SAFE_STOP", "mail_entry_has_no_badge_this_frame"', window)
        self.assertIn('Decision("OPEN_MAIL"', window,
                      "the dot produces a page decision; the tap is OPEN_MAIL's own business")
        self.assertNotIn("tap(", window)
        self.assertNotIn("point", window.lower().replace("entry_point", ""),
                         "no coordinate may be derived from the notification here")


class TheEntryControlLayerTest(unittest.TestCase):
    """Every entry the ledger reads must have a *named* way in, or be recorded as a gap.

    This is the middle level of the directive: the notification says "there is something here", and
    entering is a separate control with its own name, its own verifier and its own evidence.  A table
    row with no way in is a gap to register (``knowledge/ui/entry_badges.json``), not a licence to
    tap the dot.
    """

    #: The panel rows whose entry is a per-row skill, and the ones whose entry is the shared power
    #: overview path (measured 2026-09-23: the three barracks rows are entered through
    #: OPEN_POWER_OVERVIEW -> NAVIGATE_*_CAMP -> OPEN_*_TRAINING, which is why no per-row skill
    #: exists for them; that path is live-verified and is not a gap).
    CAMP_ROWS_ENTERED_BY_THE_POWER_ROUTE = frozenset({"SHIELD_CAMP", "LANCER_CAMP", "MARKSMAN_CAMP"})

    def test_every_panel_row_has_a_named_entry_control(self):
        ids = {skill.id for skill in v2_registry().all()}
        for row in sorted(entry_badges.QUICK_PANEL_ROW_GOALS):
            with self.subTest(row=row):
                if row in self.CAMP_ROWS_ENTERED_BY_THE_POWER_ROUTE:
                    self.assertIn("OPEN_POWER_OVERVIEW", ids)
                    continue
                self.assertIn(f"OPEN_TASK_FROM_QUICK_PANEL_{row}", ids,
                              f"{row} has a notification binding but no named control to enter it")

    def test_every_table_entry_names_its_goal_or_is_declared_unbound(self):
        table = entry_badges.table()
        declared_unbound = set((table.get("not_measured") or []) if False else [])
        for name, row in sorted(entries().items()):
            with self.subTest(entry=name):
                goal = str(row.get("goal") or "")
                if goal:
                    self.assertTrue(goal.isupper(), f"{name}: {goal!r} is not a goal id")
                else:
                    self.assertTrue(
                        declared_unbound or row.get("status"),
                        f"{name} names no goal and is not marked -- an entry with no matter to "
                        f"advance has nothing for a dot to notify about",
                    )

    def test_a_row_nobody_could_read_is_unknown_and_never_absent(self):
        """§三: "面板关闭、行未显示、视觉识别失败" must not read as "this entry has no dot".

        ABSENT is a measurement -- the client drew no dot in a window that was read.  With no frame
        there is no window, so the honest answer is UNKNOWN, and that is what keeps a row the client
        is drawing (免费招募 / 可捐献 / 已完成待领取) from being written off as "nothing here".
        """
        from winter_agent_v2.models import WorldState, Page

        ledger = entry_badges.read_all(WorldState(page=Page.HOME, confidence=0.99), None)
        self.assertTrue(ledger, "the table's entries are still reported without a frame")
        for name, badge in ledger.items():
            with self.subTest(entry=name):
                self.assertEqual(badge.state, entry_badges.UNKNOWN,
                                 f"{name} claims a measurement it does not have")

    def test_the_three_states_are_distinct_and_carry_the_state_apart(self):
        """PRESENT is not "has pixels", and ABSENT is not "could not read"."""
        states = {entry_badges.PRESENT, entry_badges.ABSENT, entry_badges.UNKNOWN}
        self.assertEqual(len(states), 3)
        self.assertIn("task_state", EntryBadge.__dataclass_fields__,
                      "the client's own state word (空闲中/免费招募/可捐献/已完成待领取) is what §三 "
                      "lets a goal act on when the dot is UNKNOWN")


if __name__ == "__main__":
    unittest.main()
