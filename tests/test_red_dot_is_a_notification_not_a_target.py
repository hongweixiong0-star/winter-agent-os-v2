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
        """The mail entry's dot decides *whether to enter*, which is the directive's own split.

        Read as source on purpose: the claim is about the *shape* of the branch -- a page decision
        behind a badge test, and no coordinate anywhere near it -- and a behavioural test cannot show
        the absence of a coordinate.  The badge test is now the three-state gate (§一/§四), so what is
        pinned is that only PRESENT reaches the page decision.
        """
        brain = (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8")
        start = brain.index('mail_gate = entry_badges.entry_gate("MAIL_ROUTINE"')
        window = brain[start:start + 900]
        self.assertIn("if mail_gate[0] != entry_badges.PRESENT:", window)
        self.assertIn('"SAFE_STOP",', window)
        self.assertIn('f"mail_entry_badge_{mail_gate[0].lower()}_this_frame"', window)
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


class TheAdviceLevelsTest(unittest.TestCase):
    """The AI's four questions, as fields -- and the boundary applied *per level*.

    The directive allows a first-time free attempt at a function nobody has a skill for
    ("不要求先写完整招募 Skill 才能首次免费招募"), and forbids acting on a page without the page
    saying so.  Both are satisfied by separating *entering* from *acting*: an ``ENTRY_CONTROL``
    answer is screened against the money list alone, a ``TASK_ACTION`` answer -- and every answer
    written before the levels existed -- against the whole list, exactly as before.
    """

    def test_the_task_boundary_did_not_move(self):
        from winter_agent_v2 import unknown_advisor as ua

        self.assertEqual(tuple(ua.SPEND_WORDS) + tuple(ua.CONTEXT_WORDS), tuple(ua.REFUSED_WORDS),
                         "the two groups must partition the old list: splitting it is the whole "
                         "change, and the TASK_ACTION reading has to be judged by the same words")
        self.assertEqual(ua.words_refused_at(None), tuple(ua.REFUSED_WORDS))
        self.assertEqual(ua.words_refused_at(""), tuple(ua.REFUSED_WORDS))
        self.assertEqual(ua.words_refused_at("NONSENSE"), tuple(ua.REFUSED_WORDS),
                         "an unknown level is not a licence: it reads as TASK_ACTION")
        self.assertEqual(ua.words_refused_at(ua.LEVEL_ENTRY), tuple(ua.SPEND_WORDS))
        for word in ("钻石", "购买", "充值", "pay", "gems"):
            self.assertIn(word, ua.SPEND_WORDS, f"{word} must be refused even when only entering")

    def test_an_answer_that_does_not_say_is_read_strictly(self):
        from winter_agent_v2 import unknown_advisor as ua

        for missing in ("", None, "whatever"):
            advice = ua.Advice(request_id="x", unknown_type="CONTROL", candidate_semantics=(),
                               proposed_action="ORDINARY_CONTROL[招募]",
                               expected_result="", uncertainty="", action_level=missing or "")
            with self.subTest(level=missing):
                self.assertEqual(ua.advice_level(advice), ua.LEVEL_TASK)

    def _answer(self, **overrides) -> dict:
        payload = {
            "unknown_type": "CONTROL",
            "candidate_semantics": ["免费招募入口"],
            "proposed_action": "ORDINARY_CONTROL[免费招募]",
            "expected_result": "招募页打开",
            "uncertainty": "medium",
        }
        payload.update(overrides)
        return payload

    def test_entering_a_function_may_name_the_function(self):
        """`免费招募` as an *entry* is allowed; the same word as a page action is not."""
        from winter_agent_v2 import unknown_advisor as ua

        entry = ua.parse_advice(self._answer(action_level="ENTRY_CONTROL",
                                             notification="英雄招募行的 免费 字样",
                                             entry="英雄招募"))
        self.assertEqual(entry.action_level, ua.LEVEL_ENTRY)
        self.assertEqual(entry.notification, "英雄招募行的 免费 字样")
        self.assertEqual(entry.entry, "英雄招募")
        self.assertEqual(entry.target_semantics, "")
        with self.assertRaises(ua.AdviceRejected) as ctx:
            ua.parse_advice(self._answer())
        self.assertIn("招募", str(ctx.exception))
        self.assertIn("ENTRY_CONTROL", str(ctx.exception),
                      "the refusal has to say how to ask for it legitimately")

    def test_money_is_refused_at_both_levels(self):
        from winter_agent_v2 import unknown_advisor as ua

        for level in ("", ua.LEVEL_ENTRY, ua.LEVEL_TASK):
            with self.subTest(level=level or "(unstated)"):
                with self.assertRaises(ua.AdviceRejected):
                    ua.parse_advice(self._answer(proposed_action="ORDINARY_CONTROL[钻石招募]",
                                                 action_level=level))

    def test_the_real_answer_on_disk_still_parses_and_is_judged_as_before(self):
        """The one answer this project has was written before the levels existed.

        It must keep working, and it must keep being judged by the full boundary -- a regression here
        would either break the only usable answer or silently loosen what it is allowed to do.
        """
        import json

        from winter_agent_v2 import unknown_advisor as ua

        path = ROOT / "learning/unknown_requests" / ua.ANSWERS_DIR / "unknown__control__b6546e80.json"
        if not path.exists():  # pragma: no cover - the file is part of the working tree
            self.skipTest("the recorded answer is not in this checkout")
        advice = ua.parse_advice(json.loads(path.read_text(encoding="utf-8")),
                                 request_id="unknown__control__b6546e80")
        self.assertEqual(ua.advice_level(advice), ua.LEVEL_TASK)
        self.assertEqual(advice.notification, "", "recorded empty, not invented")
        self.assertEqual(advice.action_level, "")
        self.assertEqual(advice.proposed_action, "ORDINARY_CONTROL[奖励入口]")

    def test_the_risk_gate_uses_the_level_it_was_given(self):
        """``_advice_risk`` is the runtime's half of the same rule, and it reads the level."""
        from winter_agent_v2 import unknown_advisor as ua
        from winter_agent_v2.runtime import LiveRuntime

        runtime = object.__new__(LiveRuntime)
        region = {"text": "免费招募"}
        for level, expected in ((ua.LEVEL_ENTRY, ""), (ua.LEVEL_TASK, "招募"), ("", "招募")):
            with self.subTest(level=level or "(unstated)"):
                advice = ua.Advice(request_id="x", unknown_type="CONTROL", candidate_semantics=(),
                                   proposed_action="ORDINARY_CONTROL[免费招募]",
                                   expected_result="", uncertainty="", action_level=level)
                verdict = runtime._advice_risk(advice, region)
                if expected:
                    self.assertIn(expected, verdict)
                    self.assertIn(ua.LEVEL_TASK, verdict, "and it names the level it judged at")
                else:
                    self.assertEqual(verdict, "")


if __name__ == "__main__":
    unittest.main()
