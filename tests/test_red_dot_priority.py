"""The client's own dot, as a *priority* signal -- and only as that.

Operator directive 2026-09-23 (second document) §一-§三: a dot the client draws is a signal that
something is waiting there, it decides *order*, and it never decides *value*.  The first document's
§一 adds the binding rule -- a dot is only readable when it belongs to a concrete entry -- which is
why this file tests two things that are easy to confuse:

* **which dots may rank at all** -- the ones measured to come and go.  A badge that never read zero
  (每日/联盟 counts, 26 of 26) and a badge suspected of artwork (英雄) are constants; ranking on a
  constant is ranking on nothing, and it is also how a dot that never fires would quietly become a
  permanent +60 for whichever goal happened to sit behind it.
* **what the ranking may become** -- bounded strictly below a claim, so the dot can never outrank
  something that actually pays (§二③: an ordinary dot must not interrupt a goal at its last step).

The frames are the ones the entry-badge campaign was taken on, so the signal is proved on a real
screen rather than on a dictionary literal.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_utility  # noqa: E402
from winter_agent_v2.entry_badges import (  # noqa: E402
    ABSENT,
    PRESENT,
    UNKNOWN,
    QUICK_PANEL_ROW_GOALS,
    dots_pointing_at,
    dot_varies,
    read_all,
)
from winter_agent_v2.goal_library import (  # noqa: E402
    GOAL_ROUTES,
    CAMP_GOAL_FOR,
    GoalLibrary,
    GoalState,
    GoalStatus,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402

RUNTIME = ROOT / "dataset/raw/control_panel/runtime_auto"
MAIL_DOT_DRAWN = RUNTIME / "20260923_000206_train/20260923_000206_train_step_001_after_20260922T160220374378.png"
MAIL_NO_DOT = RUNTIME / "20260923_001936_231102/20260923_001936_231102_step_001_before_20260922T161941349297.png"


def _world(red_dots):
    """The only two fields the ranking path reads from the world for this term."""
    return SimpleNamespace(red_dots=red_dots, stamina=None, idle_marches=None)


def _records(state: WorldState, frame: Path) -> dict:
    """The ledger a real frame produces, exactly as ``ocr.observe`` writes it onto the world."""
    return {name: badge.as_record() for name, badge in read_all(state, frame).items()}


def _by_id(board) -> dict:
    """The board keyed by goal id.

    Keyed by id rather than by the ``GoalState`` itself: the dataclass is frozen, but it carries an
    ``evidence`` dict, so it is unhashable and cannot be a mapping key.  (Written the other way
    first and caught by running it.)
    """
    return {str(goal.goal_id): breakdown for goal, breakdown in board}


class TheBoundTest(unittest.TestCase):
    """§二③ as arithmetic: a dotted visit stays strictly below a claim."""

    def test_the_term_cannot_outbid_a_claim(self):
        never_read_visit = 180.0  # goal_library.SWEEP_NEVER_VALUE
        claimable_routine = 250.0
        self.assertLess(never_read_visit + goal_utility.RED_DOT_BONUS, claimable_routine)

    def test_the_term_can_outrank_ordinary_routine_work(self):
        """Otherwise it would be a term that never changes an order, which is dead code."""
        gather = 70.0  # KEEP_MARCHES_PRODUCTIVE
        fresh_sweep = 80.0  # SWEEP_BASE_VALUE
        camp_ready = 90.0  # TRAINING_CAMP_VALUE
        for ordinary in (gather, fresh_sweep, camp_ready):
            with self.subTest(ordinary=ordinary):
                self.assertGreater(ordinary + goal_utility.RED_DOT_BONUS, ordinary)

    def test_the_term_cannot_reach_what_pays(self):
        intel = 300.0 + 500.0
        bear = 1000.0 + 5000.0
        for paying in (intel, bear):
            with self.subTest(paying=paying):
                self.assertLess(180.0 + goal_utility.RED_DOT_BONUS, paying)


class TheSignalGateTest(unittest.TestCase):
    """A dot is only a signal where the measurement says it comes and goes."""

    def test_the_entries_measured_to_vary_may_rank(self):
        for entry in ("BTN_OPEN_MAIL", "TAB_EXPLORATION",
                      "QUICK_PANEL_ROW_RESEARCH", "QUICK_PANEL_ROW_SHIELD_CAMP"):
            with self.subTest(entry=entry):
                self.assertTrue(dot_varies(entry))

    def test_a_badge_that_never_reads_zero_is_not_a_signal(self):
        """每日/联盟 counts were present in 26 of 26 sampled frames; a constant decides nothing."""
        for entry in ("BTN_OPEN_DAILY", "TAB_ALLIANCE", "TAB_HERO"):
            with self.subTest(entry=entry):
                self.assertFalse(dot_varies(entry))
        ledger = {entry: {"state": PRESENT, "goal": goal}
                  for entry, goal in (("BTN_OPEN_DAILY", "DAILY_ACTIVITY_TARGET"),
                                      ("TAB_ALLIANCE", "ALLIANCE_ROUTINE"),
                                      ("TAB_HERO", "HERO_RECRUIT"))}
        self.assertEqual(dots_pointing_at(ledger), {})

    def test_an_entry_with_no_variability_record_is_not_a_signal(self):
        self.assertFalse(dot_varies("QUICK_PANEL_ROW_INVENTED_THIS_MORNING"))
        self.assertEqual(
            dots_pointing_at({"QUICK_PANEL_ROW_INVENTED_THIS_MORNING":
                              {"state": PRESENT, "goal": "MAIL_ROUTINE"}}),
            {},
        )

    def test_only_present_dots_point(self):
        for state in (ABSENT, UNKNOWN, "", "NOT_READ"):
            with self.subTest(state=state):
                ledger = {"BTN_OPEN_MAIL": {"state": state, "goal": "MAIL_ROUTINE"}}
                self.assertEqual(dots_pointing_at(ledger), {}, state)
        ledger = {"BTN_OPEN_MAIL": {"state": PRESENT, "goal": "MAIL_ROUTINE"}}
        self.assertEqual(dots_pointing_at(ledger), {"MAIL_ROUTINE": ("BTN_OPEN_MAIL",)})

    def test_a_dot_bound_to_no_goal_is_dropped_rather_than_guessed(self):
        """英雄招募 names a goal the board has none of (open issue #100)."""
        self.assertEqual(
            dots_pointing_at({"QUICK_PANEL_ROW_HERO_RECRUIT":
                              {"state": PRESENT, "goal": "HERO_RECRUIT"}}),
            {},
        )

    def test_a_malformed_ledger_is_simply_no_signal(self):
        for ledger in (None, {}, [], {"BTN_OPEN_MAIL": "PRESENT"}, {"BTN_OPEN_MAIL": None}):
            with self.subTest(ledger=ledger):
                self.assertEqual(dots_pointing_at(ledger), {})


class TheBindingTest(unittest.TestCase):
    """Every binding names a goal of the goal layer's own vocabulary, not a route domain."""

    def test_no_row_binding_is_a_route_domain_by_mistake(self):
        """Measured 2026-09-23: the 科技研究 row was bound to ``"RESEARCH"``, which is the *route
        domain* ``run_live.py --goal`` accepts -- and the row is the panel's most dotted one (9 of
        12 frames) and the only one that discriminates, so the majority of the panel's dot signal
        could never be attributed to a goal.  Pinned here so it cannot come back."""
        routes = {"HOME", "GATHER_RESOURCE", "BEAST_HUNT", "INTEL", "MAIL",
                  "EXPLORATION", "DAILY", "ALLIANCE", "RESEARCH", "TRAIN"}
        for row, goal in QUICK_PANEL_ROW_GOALS.items():
            with self.subTest(row=row):
                self.assertNotIn(goal, routes, f"{row} is bound to a route domain, not a goal")

    def test_the_research_row_names_the_research_goal(self):
        self.assertEqual(QUICK_PANEL_ROW_GOALS["RESEARCH"], "KEEP_RESEARCH_PRODUCTIVE")
        self.assertIn("KEEP_RESEARCH_PRODUCTIVE", GOAL_ROUTES)

    def test_every_binding_the_goal_layer_cannot_emit_is_known_and_named(self):
        """The one gap is stated, not discovered by a silent drop.

        ``HERO_RECRUIT`` is a goal id nothing can emit: ``goal_library`` has no route for it, no
        capability-map entry, and ``skill_factory`` records no live-loop verifier for
        ``DAILY_HERO_RECRUIT``.  Anything *else* appearing here is a new wrong binding.
        """
        known = set(GOAL_ROUTES) | set(CAMP_GOAL_FOR.values())
        unbound = {goal for goal in QUICK_PANEL_ROW_GOALS.values() if goal not in known}
        self.assertEqual(unbound, {"HERO_RECRUIT"})


class TheRankingTest(unittest.TestCase):
    """The term decides an order between two otherwise equal goals, and nothing more."""

    def _pair(self):
        research = GoalState(
            "KEEP_RESEARCH_PRODUCTIVE", GoalStatus.READY, development_value=80.0,
            available_skills=("RESEARCH",),
        )
        building = GoalState(
            "KEEP_BUILDING_PRODUCTIVE", GoalStatus.READY, development_value=80.0,
            available_skills=("BUILDING_UPGRADE",),
        )
        return research, building

    def test_without_a_dot_the_board_order_is_the_catalogue_order(self):
        research, building = self._pair()
        board = GoalLibrary().rank((research, building), _world({}))
        self.assertEqual([goal.goal_id for goal, _ in board],
                         ["KEEP_RESEARCH_PRODUCTIVE", "KEEP_BUILDING_PRODUCTIVE"])

    def test_the_dotted_goal_moves_ahead_of_an_equal_one(self):
        research, building = self._pair()
        # Reverse the board order so only the dot can explain the outcome.
        dotted = _world({"QUICK_PANEL_ROW_RESEARCH":
                         {"state": PRESENT, "goal": "KEEP_RESEARCH_PRODUCTIVE"}})
        board = GoalLibrary().rank((building, research), dotted)
        self.assertEqual([goal.goal_id for goal, _ in board],
                         ["KEEP_RESEARCH_PRODUCTIVE", "KEEP_BUILDING_PRODUCTIVE"])
        breakdown = _by_id(board)["KEEP_RESEARCH_PRODUCTIVE"]
        self.assertEqual(breakdown.red_dot, goal_utility.RED_DOT_BONUS)
        self.assertEqual(breakdown.red_dot_on, ("QUICK_PANEL_ROW_RESEARCH",))

    def test_a_goal_keeps_its_place_when_the_dot_is_absent(self):
        research, building = self._pair()
        quiet = _world({"QUICK_PANEL_ROW_RESEARCH":
                        {"state": ABSENT, "goal": "KEEP_RESEARCH_PRODUCTIVE"}})
        board = GoalLibrary().rank((building, research), quiet)
        self.assertEqual([goal.goal_id for goal, _ in board],
                         ["KEEP_BUILDING_PRODUCTIVE", "KEEP_RESEARCH_PRODUCTIVE"])

    def test_the_term_never_lands_on_a_goal_the_dot_does_not_name(self):
        research, building = self._pair()
        dotted = _world({"QUICK_PANEL_ROW_RESEARCH":
                         {"state": PRESENT, "goal": "KEEP_RESEARCH_PRODUCTIVE"}})
        board = _by_id(GoalLibrary().rank((research, building), dotted))
        self.assertEqual(board["KEEP_BUILDING_PRODUCTIVE"].red_dot, 0.0)
        self.assertEqual(board["KEEP_BUILDING_PRODUCTIVE"].red_dot_on, ())


class TheDecisionLogTest(unittest.TestCase):
    def test_the_log_names_the_entry_that_moved_the_goal(self):
        research, _ = TheRankingTest()._pair()
        dotted = _world({"QUICK_PANEL_ROW_RESEARCH":
                         {"state": PRESENT, "goal": "KEEP_RESEARCH_PRODUCTIVE"}})
        breakdown = goal_utility.utility(research, world=dotted)
        row = breakdown.as_row()
        self.assertEqual(row["red_dot"], goal_utility.RED_DOT_BONUS)
        self.assertEqual(row["red_dot_on"], ["QUICK_PANEL_ROW_RESEARCH"])
        self.assertIn("red-dot", breakdown.why())
        self.assertIn("QUICK_PANEL_ROW_RESEARCH", breakdown.why())

    def test_an_untouched_goal_says_nothing_about_dots(self):
        research, _ = TheRankingTest()._pair()
        breakdown = goal_utility.utility(research, world=_world({}))
        self.assertEqual(breakdown.red_dot, 0.0)
        self.assertNotIn("red-dot", breakdown.why())


class TheRealFrameTest(unittest.TestCase):
    """The signal, taken from the frames the campaign measured on -- not from a literal."""

    def _ledger_of(self, frame: Path) -> dict:
        state = WorldState(page=Page.HOME, quick_panel={"open": False}, confidence=0.99)
        return _records(state, frame)

    def test_a_frame_that_draws_the_mail_dot_points_at_the_mail_goal(self):
        records = self._ledger_of(MAIL_DOT_DRAWN)
        self.assertEqual(records["BTN_OPEN_MAIL"]["state"], PRESENT)
        self.assertEqual(dots_pointing_at(records), {"MAIL_ROUTINE": ("BTN_OPEN_MAIL",)})

    def test_a_frame_with_no_dot_points_at_nothing(self):
        records = self._ledger_of(MAIL_NO_DOT)
        self.assertEqual(records["BTN_OPEN_MAIL"]["state"], ABSENT)
        self.assertEqual(dots_pointing_at(records), {})

    def test_the_same_dot_moves_the_goal_it_names_on_a_real_frame(self):
        mail = GoalState("MAIL_ROUTINE", GoalStatus.READY, reward_value=250.0, daily_loss=250.0,
                         available_skills=("MAIL_CLAIM_REWARDS",))
        research = GoalState("KEEP_RESEARCH_PRODUCTIVE", GoalStatus.READY, development_value=80.0,
                             available_skills=("RESEARCH",))
        # Base prices: a claimable mail routine (500) already outranks research (80).  The dot must
        # not be what decides here -- and it must show up in the breakdown as present, on the mail
        # goal, without landing on research.
        board = _by_id(GoalLibrary().rank((research, mail), _world(self._ledger_of(MAIL_DOT_DRAWN))))
        self.assertEqual(board["MAIL_ROUTINE"].red_dot, goal_utility.RED_DOT_BONUS)
        self.assertEqual(board["KEEP_RESEARCH_PRODUCTIVE"].red_dot, 0.0)

    def test_the_ledger_the_frame_produces_carries_the_variability_it_needs(self):
        records = self._ledger_of(MAIL_DOT_DRAWN)
        table = json.loads((ROOT / "knowledge/ui/entry_badges.json").read_text(encoding="utf-8"))
        measured = set((table.get("dot_variability") or {}).get("entries") or {})
        for entry in records:
            with self.subTest(entry=entry):
                self.assertIn(entry, measured,
                              f"{entry} is read onto the world but has no variability record, so it "
                              f"can never rank -- add its measurement or it is a dead entry")


if __name__ == "__main__":
    unittest.main()
