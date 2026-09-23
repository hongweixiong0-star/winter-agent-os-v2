"""The entry-badge reading layer: three states, each bound to a measured entry.

The frames used here are the ones the measurement campaign was taken on (2026-09-23), chosen because
their own episode record says ``page=HOME`` with the 快捷面板 closed -- not because a clock said so.
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.entry_badges import (  # noqa: E402
    ABSENT,
    EntryBadge,
    PRESENT,
    UNKNOWN,
    entries,
    quick_panel_badges,
    read_all,
    read_entry_badges,
    transitions,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402

RUNTIME = ROOT / "dataset/raw/control_panel/runtime_auto"
MAIL_BADGE_DRAWN = RUNTIME / "20260923_000206_train/20260923_000206_train_step_001_after_20260922T160220374378.png"
MAIL_NO_BADGE = RUNTIME / "20260923_001936_231102/20260923_001936_231102_step_001_before_20260922T161941349297.png"
EXPLORATION_DOT = RUNTIME / "20260921_000413_168533/20260921_000413_168533_step_006_before_20260920T160517943421.png"
WORLD_MAP_FRAME = RUNTIME / "20260923_015029_train/20260923_015029_train_step_005_before_20260922T175116240696.png"


class TheMeasuredEntriesTest(unittest.TestCase):
    def test_the_mail_badge_reads_present_where_it_is_drawn(self):
        badge = read_entry_badges(MAIL_BADGE_DRAWN, "HOME", observed_at="16:02:29")["BTN_OPEN_MAIL"]
        self.assertEqual(badge.state, PRESENT)
        self.assertGreaterEqual(badge.pixels, 250)
        self.assertLessEqual(badge.pixels, 340)
        self.assertEqual(badge.goal, "MAIL_ROUTINE")
        self.assertIsNotNone(badge.box_norm)
        self.assertAlmostEqual(badge.box_norm[0], 0.943, places=2)

    def test_the_mail_badge_reads_absent_where_the_client_draws_none(self):
        badge = read_entry_badges(MAIL_NO_BADGE, "HOME", observed_at="16:20:06")["BTN_OPEN_MAIL"]
        self.assertEqual(badge.state, ABSENT)
        self.assertEqual(badge.pixels, 0)
        self.assertIn("no_red_blob_of_badge_size", badge.reason)

    def test_an_entry_whose_dot_comes_and_goes_reads_both_ways(self):
        """探险 is the entry that punished two wrong windows, so it is pinned in both directions."""
        drawn = read_entry_badges(EXPLORATION_DOT, "HOME")["TAB_EXPLORATION"]
        self.assertEqual(drawn.state, PRESENT)
        self.assertEqual(drawn.pixels, 197)
        none = read_entry_badges(MAIL_BADGE_DRAWN, "HOME")["TAB_EXPLORATION"]
        self.assertEqual(none.state, ABSENT)
        self.assertEqual(none.pixels, 0)

    def test_a_badge_that_may_be_artwork_is_never_read_as_present_or_absent(self):
        """英雄 never varied in 26 of 26 sampled frames, so a badge cannot be told from artwork yet."""
        badge = read_entry_badges(MAIL_BADGE_DRAWN, "HOME")["TAB_HERO"]
        self.assertEqual(badge.state, UNKNOWN)
        self.assertIn("artwork", badge.reason)

    def test_an_entry_that_is_not_on_this_page_is_unknown_not_absent(self):
        """The world map draws none of these entries; 'not visible' must not become 'nothing there'."""
        ledger = read_entry_badges(WORLD_MAP_FRAME, "MAP")
        self.assertTrue(ledger)
        for entry, badge in ledger.items():
            self.assertEqual(badge.state, UNKNOWN, entry)
            self.assertIn("MAP", badge.reason, entry)

    def test_a_frame_that_was_not_given_is_unknown_not_absent(self):
        """With no frame there is nothing to look at, so every entry is UNKNOWN -- and the entries
        whose badge is not trusted say so instead, because that reason is the more useful one: it
        stays true whatever frame arrives.

        An entry that lives on **another page** answers its own third reason.  That is not cosmetic:
        it is what makes ABSENT safe to refuse a goal with (2026-09-23, §一/§四), because an entry
        that is not on this screen can never be reported as "no dot here".
        """
        ledger = read_entry_badges(None, "HOME")
        for entry, badge in ledger.items():
            self.assertEqual(badge.state, UNKNOWN, entry)
            page = str(entries()[entry].get("page") or "")
            if page and page != "HOME":
                self.assertEqual(badge.reason, f"entry_is_on_{page}_not_HOME", entry)
                continue
            self.assertIn(
                badge.reason,
                ("no_frame_given", "badge_geometry_never_varies_so_it_may_be_artwork"),
                entry,
            )
        self.assertEqual(ledger["BTN_OPEN_MAIL"].reason, "no_frame_given")
        self.assertEqual(ledger["TAB_HERO"].reason, "badge_geometry_never_varies_so_it_may_be_artwork")

    def test_every_entry_in_the_table_carries_a_measured_window_and_a_goal(self):
        for entry, row in entries().items():
            with self.subTest(entry=entry):
                self.assertEqual(len(row.get("search_window_norm") or []), 4)
                self.assertTrue(row.get("goal"))
                self.assertTrue(row.get("measured_blob_norm"))

    def test_the_red_dots_with_no_measurement_are_not_readable(self):
        """The dictionary's five UNBOUND red dots must not appear here: reading them would be counting
        arbitrary red pixels, which is exactly what the operator forbade."""
        for name in ("RED_DOT_TASK", "RED_DOT_EVENT", "RED_DOT_REWARD", "RED_DOT_BUILDING", "RED_DOT_RESEARCH"):
            self.assertNotIn(name, entries())


class ThePanelRowsTest(unittest.TestCase):
    def test_a_closed_panel_makes_every_row_unknown(self):
        state = WorldState(page=Page.HOME, quick_panel={"open": False}, confidence=0.99)
        ledger = quick_panel_badges(state)
        self.assertTrue(ledger)
        for entry, badge in ledger.items():
            self.assertEqual(badge.state, UNKNOWN, entry)
            self.assertEqual(badge.reason, "quick_panel_is_closed")

    def test_a_row_that_was_not_read_is_unknown_not_absent(self):
        """The panel scrolls: a row outside the reading is one nobody looked at."""
        state = WorldState(
            page=Page.HOME,
            quick_panel={"open": True, "rows": [{"key": "SHIELD_CAMP", "badge": PRESENT, "status": "IDLE"}]},
            confidence=0.99,
        )
        ledger = quick_panel_badges(state)
        self.assertEqual(ledger["QUICK_PANEL_ROW_SHIELD_CAMP"].state, PRESENT)
        self.assertEqual(ledger["QUICK_PANEL_ROW_SHIELD_CAMP"].task_state, "IDLE")
        self.assertEqual(ledger["QUICK_PANEL_ROW_LANCER_CAMP"].state, UNKNOWN)
        self.assertEqual(ledger["QUICK_PANEL_ROW_LANCER_CAMP"].reason, "row_not_read_this_frame")

    def test_a_row_the_panel_reader_did_not_settle_is_unknown(self):
        state = WorldState(
            page=Page.HOME,
            quick_panel={"open": True, "rows": [{"key": "MY_REWARDS", "badge": None, "status": "IDLE"}]},
            confidence=0.99,
        )
        badge = quick_panel_badges(state)["QUICK_PANEL_ROW_MY_REWARDS"]
        self.assertEqual(badge.state, UNKNOWN)
        self.assertEqual(badge.reason, "panel_read_did_not_settle_this_row")

    def test_the_ledger_carries_both_families(self):
        state = WorldState(page=Page.HOME, quick_panel={"open": False}, confidence=0.99)
        ledger = read_all(state, MAIL_BADGE_DRAWN, observed_at="16:02:29")
        self.assertEqual(ledger["BTN_OPEN_MAIL"].state, PRESENT)
        self.assertEqual(ledger["QUICK_PANEL_ROW_SHIELD_CAMP"].state, UNKNOWN)
        self.assertEqual(ledger["QUICK_PANEL_ROW_SHIELD_CAMP"].goal, "SHIELD_CAMP_TRAINING")


class TheTransitionsTest(unittest.TestCase):
    def _ledger(self, mail: str, alliance: str = ABSENT):
        return {
            "BTN_OPEN_MAIL": EntryBadge("BTN_OPEN_MAIL", "HOME", mail, "t0", "MAIL_ROUTINE"),
            "TAB_ALLIANCE": EntryBadge("TAB_ALLIANCE", "HOME", alliance, "t0", "ALLIANCE_ROUTINE"),
        }

    def test_a_dot_appearing_is_a_trigger(self):
        events = transitions(self._ledger(ABSENT), self._ledger(PRESENT))
        self.assertEqual([(e["entry"], e["from"], e["to"]) for e in events], [("BTN_OPEN_MAIL", ABSENT, PRESENT)])
        self.assertEqual(events[0]["goal"], "MAIL_ROUTINE")

    def test_a_dot_that_stays_is_not_a_trigger(self):
        """The operator's §二: the same dot in consecutive frames must not re-create the same goal."""
        self.assertEqual(transitions(self._ledger(PRESENT), self._ledger(PRESENT)), [])

    def test_a_dot_going_away_is_reported_as_such(self):
        events = transitions(self._ledger(PRESENT), self._ledger(ABSENT))
        self.assertEqual([(e["from"], e["to"]) for e in events], [(PRESENT, ABSENT)])

    def test_unknown_on_either_side_is_never_a_change(self):
        self.assertEqual(transitions(self._ledger(UNKNOWN), self._ledger(PRESENT)), [])
        self.assertEqual(transitions(self._ledger(ABSENT), self._ledger(UNKNOWN)), [])

    def test_an_entry_with_no_previous_reading_is_not_a_change(self):
        self.assertEqual(transitions({}, self._ledger(PRESENT)), [])


class TheMailGoalTest(unittest.TestCase):
    """The first consumer of the ledger: the mail route stops re-entering a page with no badge.

    Operator directive §五.  Only a *measured* ABSENT skips the page; everything else -- PRESENT,
    UNKNOWN, or a state that carries no ledger at all -- keeps the route it already had, because a
    reading that was never made must not be allowed to look like "there is nothing there".
    """

    def _decide(self, red_dots):
        from winter_agent_v2.brain import RuleBrain
        from winter_agent_v2.skills import v2_registry

        brain = RuleBrain()
        brain.current_goal = "MAIL"
        state = WorldState(page=Page.HOME, red_dots=red_dots, confidence=0.99)
        return brain.decide(state, v2_registry())

    def test_an_absent_badge_skips_the_mail_page(self):
        decision = self._decide({"BTN_OPEN_MAIL": {"state": ABSENT, "goal": "MAIL_ROUTINE"}})
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "mail_entry_badge_absent_this_frame")
        from winter_agent_v2.runtime_snapshot import is_fatal_stop

        self.assertFalse(is_fatal_stop(decision.reason), "this must hand the cycle over, not end it")

    def test_a_present_badge_still_opens_the_mail_page(self):
        decision = self._decide({"BTN_OPEN_MAIL": {"state": PRESENT, "goal": "MAIL_ROUTINE"}})
        self.assertEqual(decision.skill, "OPEN_MAIL")

    def test_an_unknown_badge_does_not_open_the_mail_page(self):
        """Operator directive 2026-09-23 §四: UNKNOWN is not permission to go and look.

        This used to open the page, on the reasoning that "unreadable" should not change behaviour.
        For a task whose whole existence is the dot that reasoning is backwards: opening the page in
        order to find out *is* the periodic visit under another name.  The entry is drawn on HOME,
        which the loop stands on constantly, so the reading comes back for free.
        """
        decision = self._decide({"BTN_OPEN_MAIL": {"state": UNKNOWN, "reason": "entry_is_on_MAP_not_HOME"}})
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "mail_entry_badge_unknown_this_frame")
        from winter_agent_v2.runtime_snapshot import is_fatal_stop

        self.assertFalse(is_fatal_stop(decision.reason))

    def test_a_state_with_no_ledger_at_all_does_not_open_the_mail_page(self):
        """And the same rule for an older state file that predates the red-dot layer.

        The price is stated rather than hidden: a tree whose ledger is missing gets no mail goal at
        all.  That is the honest direction -- "I cannot read the entry" is not evidence that there is
        something behind it -- and it is why the guard is only safe together with the layer being
        live, which ``knowledge/ui/entry_badges.json`` is.
        """
        decision = self._decide({})
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "mail_entry_badge_unknown_this_frame")


class TheGoalEligibilityTest(unittest.TestCase):
    """Operator directive 2026-09-23 §一/§二/§三: 红点不是加分项，是"有没有任务"的准入信号。

    The distinction this class exists to pin down: before it, ABSENT and PRESENT produced the *same*
    goal on the board and differed only by ``RED_DOT_BONUS``; and with no reading at all the goal was
    still emitted, priced by age (measured: ``MAIL_ROUTINE / DISCOVERED / ('OPEN_MAIL',)`` at 180 for
    never-read, 155 for a reading 3x past TTL).  So the clock, not the dot, decided that a mail page
    with nothing behind it outbid real work.
    """

    def _board(self, **kwargs):
        from winter_agent_v2.goal_library import GoalLibrary

        world = WorldState(page=Page.HOME, confidence=0.99, **kwargs)
        return {g.goal_id: g for g in GoalLibrary().discover(world, observations={})}

    @staticmethod
    def _dots(entry, state):
        return {entry: {"entry": entry, "state": state, "goal": "x"}}

    def test_mail_with_a_dot_is_a_ticket(self):
        board = self._board(red_dots=self._dots("BTN_OPEN_MAIL", PRESENT))
        self.assertIn("MAIL_ROUTINE", board)
        self.assertEqual(board["MAIL_ROUTINE"].available_skills, ("OPEN_MAIL",))

    def test_mail_without_a_dot_is_not_on_the_board(self):
        """ABSENT removes the goal; it does not merely demote it."""
        board = self._board(red_dots=self._dots("BTN_OPEN_MAIL", ABSENT))
        self.assertNotIn("MAIL_ROUTINE", board)

    def test_mail_with_an_unreadable_dot_is_not_on_the_board(self):
        board = self._board(red_dots=self._dots("BTN_OPEN_MAIL", UNKNOWN))
        self.assertNotIn("MAIL_ROUTINE", board)

    def test_the_gifts_goal_is_decided_by_the_tile_and_not_by_the_alliance_entry(self):
        """§三: 联盟总入口红点 != 联盟宝箱红点.

        The alliance entry (``TAB_ALLIANCE``) is a constant -- the table already records it as present
        in 26 of 26 frames -- so a dot there cannot say anything about the gift box.  What decides is
        the 联盟宝箱 tile's own badge.
        """
        entry_only = self._board(red_dots=self._dots("TAB_ALLIANCE", PRESENT))
        self.assertNotIn("ALLIANCE_ROUTINE", entry_only,
                         "a dot on the alliance entry is not evidence about the gift box")
        tile = self._board(red_dots=self._dots("TILE_ALLIANCE_GIFTS", PRESENT))
        self.assertIn("ALLIANCE_ROUTINE", tile)
        no_tile = self._board(red_dots=self._dots("TILE_ALLIANCE_GIFTS", ABSENT))
        self.assertNotIn("ALLIANCE_ROUTINE", no_tile)

    def test_a_goal_with_no_declared_entry_keeps_its_own_ticket(self):
        """The gate is a list of two, not a new rule for the whole board.

        Cleaned of the mail/daily/alliance goals, the other sweep tickets must still be emitted or the
        change would have quietly removed the bounded observation sweep itself.
        """
        board = self._board(red_dots=self._dots("BTN_OPEN_MAIL", ABSENT))
        self.assertIn("CLEAR_INTEL", board)
        self.assertEqual(board["CLEAR_INTEL"].available_skills, ("OPEN_INTEL",))


#: Counts executor calls, at module level because the wiring checker reads ``self._X()`` as a call to
#: an undefined method when a test carries its own helper class.
class _CountingExecutor:
    calls = 0

    def execute(self, action, skill_id=None):
        type(self).calls += 1
        return None


class TheExecutorBackstopTest(unittest.TestCase):
    """§六: 增加最后一道动作出口保护.

    The goal layer and the brain both refuse without a dot now, but a decision made somewhere else --
    or made while the entry was readable and executed after the client moved on -- still reaches the
    executor.  ``Scheduler.tick`` is the one place every decision passes through, so the backstop
    lives there, and this class pins that it refuses rather than corrects: the step is settled as
    "nothing new here" and the cycle goes to another goal.
    """

    def setUp(self):
        _CountingExecutor.calls = 0

    def _tick(self, skill, state, entry, badge):
        from winter_agent_v2.brain import RuleBrain
        from winter_agent_v2.models import Decision
        from winter_agent_v2.scheduler import Scheduler
        from winter_agent_v2.skills import v2_registry

        world = WorldState(
            page=state,
            confidence=0.99,
            red_dots={} if badge is None else {entry: {"state": badge, "goal": "x"}},
        )
        scheduler = Scheduler(RuleBrain(), v2_registry(), _CountingExecutor())
        before = _CountingExecutor.calls
        result = scheduler.tick(world, Decision(skill, "forced_for_the_probe", 0.99, "x"))
        return _CountingExecutor.calls > before, result.decision

    def test_a_dotted_entry_still_reaches_the_executor(self):
        executed, decision = self._tick("OPEN_MAIL", Page.HOME, "BTN_OPEN_MAIL", PRESENT)
        self.assertTrue(executed)
        self.assertEqual(decision.skill, "OPEN_MAIL")

    def test_the_executor_is_not_reached_without_the_dot(self):
        for badge in (ABSENT, UNKNOWN, None):
            with self.subTest(badge=badge):
                executed, decision = self._tick("OPEN_MAIL", Page.HOME, "BTN_OPEN_MAIL", badge)
                self.assertFalse(executed, "the page must not be entered")
                self.assertEqual(decision.skill, "SAFE_STOP")
                self.assertIn("refused_at_the_entry_gate", decision.reason)
                from winter_agent_v2.runtime_snapshot import is_fatal_stop

                self.assertFalse(is_fatal_stop(decision.reason), "and the cycle is handed on")

    def test_the_gifts_page_is_refused_at_the_same_gate(self):
        executed, decision = self._tick(
            "OPEN_ALLIANCE_GIFTS", Page.ALLIANCE, "TILE_ALLIANCE_GIFTS", ABSENT
        )
        self.assertFalse(executed)
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertIn("ALLIANCE_ROUTINE_is_absent", decision.reason)

    def test_an_ungated_skill_is_untouched(self):
        executed, decision = self._tick("BACK", Page.ALLIANCE, "TILE_ALLIANCE_GIFTS", ABSENT)
        self.assertTrue(executed, "the backstop is a list of two entries, not a new stage")
        self.assertEqual(decision.skill, "BACK")


if __name__ == "__main__":
    unittest.main()
