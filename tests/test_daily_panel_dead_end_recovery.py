"""The 任务 panel that ``OPEN_DAILY`` now opens must not become a new dead end.

Origin (2026-09-16).  ``OPEN_DAILY`` was un-blocked earlier the same day (the
``BTN_OPEN_DAILY`` template was re-registered from a live frame; the old one from
2026-09-08 scored distance 18 against a gate of 8, so the step was recorded as
``SEMANTIC_TARGET_NOT_VERIFIED``).  With the step working, the live client
reached the panel for the first time:

    step 1  OPEN_DAILY   HOME -> DAILY   verifier OK
            after.daily = {"status": "AVAILABLE", "claimable_count": 0}
    step 2  SAFE_STOP    daily_no_claimable_rewards

and the run ended **inside** the panel.  That is the ``Page.BEAST`` failure mode
again (see ``test_beast_card_dead_end_recovery``): nothing moves the client, so
every following run -- not only ``--goal DAILY`` -- stops within seconds.

What the panel actually contains was measured, not assumed
(``tools/probe_daily_tasks_tab.py``, one tap, 2026-09-16T13:46Z): the panel is
tabbed (章节任务 / 成长任务 / 每日任务) and lands on the first tab; its daily tab
showed activity 285 with the three activity chests (80/160/270) already open and
the four tasks at 16/20, 25/40, 0/10, 0/10 -- nothing claimable today.  So there
is no claim to verify yet; what can be fixed and verified now is the exit.

Where BACK goes was measured too, not assumed
(``tools/probe_back_from_beast.py`` run once from inside the panel): DAILY ->
HOME, and ``verify_safe_back`` accepts that transition, so the step is
verifiable rather than hopeful.
"""

from __future__ import annotations

import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime_snapshot import is_fatal_stop
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_safe_back

# The live panel, field for field: the 每日任务 tab with points banked and
# nothing claimable (probe_20260916_134609.json).
LIVE_EMPTY_PANEL = {"status": "AVAILABLE", "claimable_count": 0, "activity": 285}


def _panel(daily: dict | None = None) -> WorldState:
    return WorldState(
        page=Page.DAILY,
        daily=dict(LIVE_EMPTY_PANEL if daily is None else daily),
        confidence=0.99,
    )


def _decide(world, goal="DAILY", **kwargs):
    brain = RuleBrain(current_goal=goal, **kwargs)
    return brain, brain.decide(world, v2_registry())


class TheClientCanLeaveThePanelTests(unittest.TestCase):
    def test_a_panel_with_nothing_claimable_is_left_instead_of_stranding_the_run(self):
        brain, decision = _decide(_panel())
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.reason, "daily_panel_not_actionable_leaving_the_page")
        self.assertTrue(brain.daily_panel_not_actionable_left)

    def test_a_back_that_did_not_move_the_client_is_not_repeated(self):
        # Otherwise the loop ping-pongs panel -> home -> panel and burns actions.
        brain, _ = _decide(_panel())
        second = brain.decide(_panel(), v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, "daily_no_claimable_rewards")

    def test_the_goal_does_not_re_open_the_panel_it_already_judged_empty(self):
        """The half of the guard the beast card never needed.

        ``TheRecoveryDoesNotShadowRealWorkTests`` for the card can leave the
        BEAST page for good, but the panel has an entry point (``OPEN_DAILY``)
        that the DAILY goal itself calls on HOME -- so without this the run would
        end with the client back inside the panel it had just left.
        """
        brain, _ = _decide(_panel())
        home = WorldState(page=Page.HOME, confidence=0.99)
        decision = brain.decide(home, v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "daily_panel_already_read_not_actionable")

    def test_the_leave_is_an_ordinary_step_not_a_fatal_one(self):
        _, decision = _decide(_panel())
        self.assertFalse(is_fatal_stop(decision.reason))

    def test_the_step_is_verifiable_by_the_real_verifier(self):
        result = verify_safe_back(_panel(), WorldState(page=Page.HOME, confidence=0.98))
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.reason, "OK")

    def test_the_verifier_still_rejects_a_back_that_did_nothing(self):
        result = verify_safe_back(_panel(), _panel())
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "SAFE_BACK_NOT_PROVEN")

    def test_a_guardless_goal_also_leaves_the_panel(self):
        # HOME has no goal-specific block, so it reaches the page branch.
        _, decision = _decide(_panel(), goal="HOME")
        self.assertEqual(decision.skill, "BACK")


class RealWorkIsNotShadowedTests(unittest.TestCase):
    def test_a_claimable_panel_is_still_claimed(self):
        _, decision = _decide(_panel({"status": "CLAIMABLE", "claimable_count": 2,
                                      "activity": 285}))
        self.assertEqual(decision.skill, "DAILY_CLAIM_REWARDS")
        self.assertEqual(decision.reason, "daily_task_claimable")

    def test_claiming_does_not_set_the_leave_flag(self):
        brain, _ = _decide(_panel({"status": "CLAIMABLE", "claimable_count": 1}))
        self.assertFalse(brain.daily_panel_not_actionable_left)

    def test_the_first_open_of_the_run_still_happens(self):
        _, decision = _decide(WorldState(page=Page.HOME, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_DAILY")

    def test_the_map_bootstrap_still_happens(self):
        _, decision = _decide(WorldState(page=Page.MAP, confidence=0.99))
        self.assertEqual(decision.skill, "OPEN_HOME")

    def test_the_free_recruit_branch_still_outranks_the_exit(self):
        # Goal HOME reaches the page branch (there is no HOME goal block), and
        # there the free-recruit task is still chosen over leaving the panel.
        # NOTE: under goal DAILY this branch is unreachable -- the goal block
        # answers SAFE_STOP for any status that is not CLAIMABLE, both before and
        # after this change.  That is pre-existing, and ``DAILY_HERO_RECRUIT`` has
        # no verifier so the live loop could not dispatch it either way.
        _, decision = _decide(_panel({"status": "AVAILABLE", "task_id": "HERO_RECRUIT_1"}),
                              goal="HOME")
        self.assertEqual(decision.skill, "DAILY_HERO_RECRUIT")


if __name__ == "__main__":
    unittest.main()
