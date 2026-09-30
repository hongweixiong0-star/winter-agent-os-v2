"""FISHING POLICY V2 §3 / §14 / §15 — the fishing event may not steal the role session.

The defect these tests pin is a *ranking* one, and it is invisible in any single frame: the
client prints a countdown for every live event, ``deadline_pressure`` converts any countdown
under 24h into ``+1000 … +10000``, and the fishing tournament is open for two days.  So for
its entire length the fishing event outranks ordinary work and takes the device from the
running Role Session on nearly every frame -- which §3 ("不要为了钓鱼频繁切换角色") and §14
("禁止因为普通积分Goal频繁打断当前Role Session") both forbid.

The fix is that the fishing event's deadline comes from the bait budget instead of the
countdown, and only exists when the bait says it must.
"""

import unittest
from datetime import datetime, timedelta, timezone

from winter_agent_v2 import fishing_pressure as fp
from winter_agent_v2 import fishing_state as fs
from winter_agent_v2.goal_library import GoalLibrary, GoalStatus, deadline_pressure
from winter_agent_v2.models import Page, WorldState

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def verdict(pressure, *, remaining=None, bait=5, cap=10):
    """The shape ``fishing_pressure`` produces for one role."""
    return {
        "pressure": pressure,
        "bait_current": bait,
        "bait_cap": cap,
        "is_full": bait >= cap,
        "endgame": ({"known": True, "active": True, "remaining_seconds": remaining}
                    if remaining is not None else
                    {"known": False, "active": False, "remaining_seconds": None}),
        "reason": pressure,
        "role_key": "ROLE_A",
    }


def fishing_world(*, remaining_seconds=3500, event_id="FISHING_TOURNAMENT"):
    return WorldState(
        page=Page.EVENT,
        events={"minimum_guarantee": {
            "event_id": event_id,
            "points_missing": 100,
            "remaining_seconds": remaining_seconds,
            "available_skills": ["TRAIN_TROOPS"],
        }},
    )


def event_goal(world, pressures=None):
    goals = {g.goal_id: g for g in GoalLibrary().discover(
        world, role_id="1063040265", fishing_pressures=pressures)}
    return goals["EVENT_MINIMUM_GUARANTEE"]


class TestOnlyTheFishingEventIsTouched(unittest.TestCase):
    """A rule about one event must not silently rewrite every other event's urgency."""

    def test_another_event_keeps_its_countdown(self):
        terms = fp.event_goal_terms("BEAR_HUNT", verdict(fp.NORMAL))
        self.assertFalse(terms["is_fishing"])
        self.assertFalse(terms["applies"])
        self.assertEqual(terms["synergy_bonus"], 0.0)

    def test_another_event_still_gets_its_deadline_pressure_on_the_board(self):
        # The same big countdown that must be neutralised for fishing stays a deadline for
        # anything else -- otherwise this change would quietly slow every timed event down.
        goal = event_goal(fishing_world(remaining_seconds=3500, event_id="BEAR_HUNT"),
                          {})
        self.assertEqual(goal.remaining_seconds, 3500)
        self.assertEqual(goal.priority, 500 + 500 + deadline_pressure(3500))

    def test_the_id_match_is_case_insensitive(self):
        for spelling in ("FISHING_TOURNAMENT", "fishing_tournament", " Fishing_Tournament "):
            with self.subTest(spelling=spelling):
                self.assertTrue(fp.event_goal_terms(spelling, verdict(fp.NORMAL))["is_fishing"])


class TestOrdinaryMeansOrdinary(unittest.TestCase):
    """§3/§14: with bait in hand and time on the clock, fishing waits its turn."""

    def test_normal_bait_gets_no_deadline_and_no_bonus(self):
        terms = fp.event_goal_terms("FISHING_TOURNAMENT", verdict(fp.NORMAL))
        self.assertTrue(terms["applies"])
        self.assertIsNone(terms["remaining_seconds"])
        self.assertEqual(terms["synergy_bonus"], 0.0)

    def test_the_goal_loses_the_countdown_derived_boost(self):
        # Before the fix this goal carried ``deadline_pressure(3500) == 10000`` for no reason
        # other than that the event was open.
        goal = event_goal(fishing_world(remaining_seconds=3500), {"1063040265": verdict(fp.NORMAL)})
        self.assertIsNone(goal.remaining_seconds)
        self.assertEqual(goal.priority, 1000.0)
        self.assertLess(goal.priority, 500 + 500 + deadline_pressure(3500))

    def test_the_client_countdown_is_still_recorded_in_evidence(self):
        # Suppressing the *boost* must not delete the reading: the window still ends when the
        # client says it ends, and an audit has to be able to see both numbers.
        goal = event_goal(fishing_world(remaining_seconds=3500), {"1063040265": verdict(fp.NORMAL)})
        self.assertEqual(goal.evidence["client_remaining_seconds"], 3500)
        self.assertEqual(goal.evidence["fishing_pressure"]["pressure"], fp.NORMAL)

    def test_no_bait_is_not_an_emergency(self):
        # Nothing to spend means nothing to rush for; a preemption here would idle the run.
        terms = fp.event_goal_terms("FISHING_TOURNAMENT", verdict(fp.NO_BAIT, bait=0))
        self.assertIsNone(terms["remaining_seconds"])
        self.assertEqual(terms["synergy_bonus"], 0.0)

    def test_the_window_status_still_comes_from_the_client(self):
        # Status is about the event's window, not about how badly fishing wants the device, so
        # an open event is still READY even with its deadline neutralised.
        goal = event_goal(fishing_world(remaining_seconds=3500), {"1063040265": verdict(fp.NORMAL)})
        self.assertIs(goal.status, GoalStatus.READY)

    def test_an_expired_window_is_still_expired(self):
        goal = event_goal(fishing_world(remaining_seconds=0), {"1063040265": verdict(fp.NORMAL)})
        self.assertIs(goal.status, GoalStatus.EXPIRED)


class TestCapFullRaisesWithoutAClaim(unittest.TestCase):
    """§3 A: a full counter is throwing regeneration away -- raise, do not hard-preempt."""

    def test_cap_full_carries_a_bonus_not_a_deadline(self):
        terms = fp.event_goal_terms("FISHING_TOURNAMENT", verdict(fp.CAP_FULL, bait=10, cap=10))
        self.assertIsNone(terms["remaining_seconds"])
        self.assertEqual(terms["synergy_bonus"], fp.CAP_FULL_SYNERGY_BONUS)

    def test_cap_full_outranks_idle_work(self):
        goal = event_goal(fishing_world(), {"1063040265": verdict(fp.CAP_FULL, bait=10, cap=10)})
        self.assertEqual(goal.priority, 500 + 500 + fp.CAP_FULL_SYNERGY_BONUS)

    def test_cap_full_does_not_claim_a_closing_window(self):
        # ``remaining_seconds`` is not set, so the scheduler's hard-preempt (which keys on a
        # real deadline) cannot fire off a full counter.  §3 asks for a raised priority here,
        # not for the device.
        goal = event_goal(fishing_world(), {"1063040265": verdict(fp.CAP_FULL, bait=10, cap=10)})
        self.assertIsNone(goal.remaining_seconds)


class TestEndgameIsARealDeadline(unittest.TestCase):
    """§15: when the window is shorter than the bait left to spend, fishing must win."""

    def test_endgame_passes_the_measured_countdown_through(self):
        terms = fp.event_goal_terms("FISHING_TOURNAMENT", verdict(fp.ENDGAME, remaining=850))
        self.assertEqual(terms["remaining_seconds"], 850)
        self.assertEqual(terms["synergy_bonus"], 0.0)

    def test_endgame_outranks_ordinary_work(self):
        goal = event_goal(fishing_world(remaining_seconds=850),
                          {"1063040265": verdict(fp.ENDGAME, remaining=850)})
        self.assertEqual(goal.remaining_seconds, 850)
        self.assertEqual(goal.priority, 500 + 500 + deadline_pressure(850))
        self.assertGreater(goal.priority, 1000.0)

    def test_endgame_that_measured_nothing_does_not_invent_a_deadline(self):
        # ``known=False`` endgames report ``remaining_seconds=None``; a deadline must not be
        # conjured out of an unmeasured run duration.
        terms = fp.event_goal_terms("FISHING_TOURNAMENT",
                                    verdict(fp.ENDGAME, remaining=None))
        self.assertIsNone(terms["remaining_seconds"])


class TestAReadingThatIsMissingIsNotUrgency(unittest.TestCase):
    """The absence of a reading must never *increase* urgency; it restores the old behaviour."""

    def test_no_verdict_for_this_role_means_do_not_apply(self):
        terms = fp.event_goal_terms("FISHING_TOURNAMENT", None)
        self.assertFalse(terms["applies"])
        self.assertIsNone(terms["remaining_seconds"])
        self.assertEqual(terms["synergy_bonus"], 0.0)

    def test_an_unknown_pressure_is_treated_as_ordinary(self):
        terms = fp.event_goal_terms("FISHING_TOURNAMENT", verdict(fp.UNKNOWN))
        self.assertTrue(terms["applies"])
        self.assertIsNone(terms["remaining_seconds"])
        self.assertEqual(terms["synergy_bonus"], 0.0)

    def test_signal_for_role_returns_none_for_an_unread_role(self):
        pressures = {"1063040265": verdict(fp.NORMAL)}
        self.assertEqual(fp.signal_for_role(pressures, "1063040265")["pressure"], fp.NORMAL)
        self.assertIsNone(fp.signal_for_role(pressures, "1061663148"))
        self.assertIsNone(fp.signal_for_role(None, "1063040265"))

    def test_without_the_new_argument_discovery_behaves_as_before(self):
        # Backwards compatibility: a caller that has not been taught about the bait budget
        # keeps the generic behaviour rather than getting a silently different board.
        goal = event_goal(fishing_world(remaining_seconds=3500), None)
        self.assertEqual(goal.remaining_seconds, 3500)


class TestRolesAreNeverMixed(unittest.TestCase):
    """One account's bait must not steer the other account's device."""

    def setUp(self):
        self.store = fs.FishingState(path="unused.json", ledger_path="unused.jsonl")
        self.store.roles["ROLE_A"] = fs.RoleFishingState(
            role_key="ROLE_A", role_id="1063040265", name="[ioi]零氪纯盾流",
            normal_bait_current=10, bait_cap=10, regen_seconds=10800.0,
            event_end_at=NOW + timedelta(hours=20),
        )
        self.store.roles["ROLE_B"] = fs.RoleFishingState(
            role_key="ROLE_B", role_id="1061663148", name="[zoe]xhw小号",
            normal_bait_current=5, bait_cap=10, regen_seconds=10800.0,
            event_end_at=NOW + timedelta(hours=20),
        )

    def test_pressures_are_filed_under_the_roles_own_account_id(self):
        pressures = fp.pressures_by_role_id(self.store, NOW, seconds_per_run=25.0)
        self.assertEqual(set(pressures), {"1063040265", "1061663148"})
        self.assertEqual(pressures["1063040265"]["role_key"], "ROLE_A")
        self.assertEqual(pressures["1061663148"]["role_key"], "ROLE_B")

    def test_a_full_role_does_not_make_the_other_role_urgent(self):
        pressures = fp.pressures_by_role_id(self.store, NOW, seconds_per_run=25.0)
        self.assertEqual(pressures["1063040265"]["pressure"], fp.CAP_FULL)
        self.assertEqual(pressures["1061663148"]["pressure"], fp.NORMAL)

    def test_a_role_without_an_account_id_is_not_filed(self):
        self.store.roles["ROLE_C"] = fs.RoleFishingState(role_key="ROLE_C",
                                                         normal_bait_current=1, bait_cap=10)
        pressures = fp.pressures_by_role_id(self.store, NOW, seconds_per_run=25.0)
        self.assertNotIn("", pressures)
        self.assertEqual(set(pressures), {"1063040265", "1061663148"})

    def test_the_store_pressure_comes_from_the_stores_own_numbers(self):
        # Not a re-derivation: whatever the store says the counter is, that is the verdict.
        self.store.roles["ROLE_A"].normal_bait_current = 0
        pressures = fp.pressures_by_role_id(self.store, NOW, seconds_per_run=25.0)
        self.assertEqual(pressures["1063040265"]["pressure"], fp.NO_BAIT)

    def test_an_unmeasured_cadence_cannot_produce_an_endgame(self):
        # ENDGAME is only allowed to fire against a duration somebody observed (§15).  With no
        # run history and no explicit cadence, the store answers "unknown" and the role stays
        # ordinary even with the window nearly shut.
        self.store.roles["ROLE_A"].event_end_at = NOW + timedelta(seconds=60)
        pressures = fp.pressures_by_role_id(self.store, NOW)          # no seconds_per_run
        self.assertNotEqual(pressures["1063040265"]["pressure"], fp.ENDGAME)

    def test_a_measured_cadence_turns_the_same_state_into_an_endgame(self):
        self.store.roles["ROLE_A"].event_end_at = NOW + timedelta(seconds=60)
        pressures = fp.pressures_by_role_id(self.store, NOW, seconds_per_run=25.0)
        self.assertEqual(pressures["1063040265"]["pressure"], fp.ENDGAME)

    def test_a_verdict_for_another_role_does_not_rewrite_this_goals_deadline(self):
        # §3 A is about *switching* to the role whose counter is full -- it is not a licence
        # for the other role's goal to become urgent.  With no verdict filed for this role the
        # goal keeps the generic behaviour it had before this change.
        pressures = {"1061663148": verdict(fp.CAP_FULL, bait=10, cap=10)}
        goal = event_goal(fishing_world(remaining_seconds=3500), pressures)
        self.assertEqual(goal.remaining_seconds, 3500)
        recorded = goal.evidence["fishing_pressure"]
        self.assertTrue(recorded["is_fishing"])
        self.assertFalse(recorded["applies"])
        self.assertIsNone(recorded["pressure"])


class TestTheStoreSurvivesBadInput(unittest.TestCase):
    def test_an_unreadable_role_reports_unknown_rather_than_raising(self):
        class Broken:
            pass

        result = fp.role_bait_verdict(Broken(), NOW)
        self.assertEqual(result["pressure"], fp.UNKNOWN)

    def test_a_state_without_roles_yields_no_pressures(self):
        self.assertEqual(fp.pressures_by_role_id(object(), NOW), {})

    def test_every_pressure_this_module_can_return_is_declared(self):
        for name in ("NORMAL", "CAP_FULL", "ENDGAME", "NO_BAIT", "UNKNOWN"):
            with self.subTest(name=name):
                self.assertIn(getattr(fp, name), fp.BAIT_PRESSURES)
        self.assertEqual(set(fp.ORDINARY_PRESSURES) | set(fp.URGENT_PRESSURES),
                         set(fp.BAIT_PRESSURES))


if __name__ == "__main__":
    unittest.main()
