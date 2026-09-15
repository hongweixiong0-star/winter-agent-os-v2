"""A non-actionable beast card is a dead end, not a stop.

Origin (2026-09-15).  A BLOCKED 大师悬赏 target card parks the client on
``Page.BEAST`` with nothing to tap.  ``brain.py`` answered ``SAFE_STOP /
beast_not_actionable`` at the first step -- but that did not stop the run, it
stranded it: nothing moved the client, so the *next* run found the same page and
stopped again, and the hourly automation produced nothing while the client sat
there.  Recorded twice, both times with ``dispatches=0 claims=0``:

    evidence/intel_pins_20260915_092119.json   (client left on the card)
    evidence/intel_pins_20260915_095605.json   3 nav cycles, each
                                               steps=1 elapsed_s=5.4, then the
                                               harness hit its own cap

The recovery presses BACK.  Where BACK goes was measured, not assumed:
``tools/probe_back_from_beast.py`` pressed it once on the live blocked card and
the client landed on **MAP** (stamina readable, 110) -- the page the INTEL goal
and the free-stamina check both start from.

Nothing here invents navigation: the assertion that the step is *verifiable* is
made against the real ``verify_safe_back``.
"""

from __future__ import annotations

import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime_snapshot import is_fatal_stop
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_safe_back

# The live card, field for field: a level-20 master bounty the account cannot
# beat, which is what parked the client.
BLOCKED_CARD = {
    "name": "大师悬赏",
    "level": 20,
    "available": False,
    "recommended_power": 189295920,
    "stamina_cost_displayed": 10,
    "blocked_reason": "POWER_BELOW_RECOMMENDED",
}


def _card(beast: dict | None = None) -> WorldState:
    return WorldState(
        page=Page.BEAST,
        beast=dict(BLOCKED_CARD if beast is None else beast),
        confidence=0.99,
    )


def _decide(world, goal="INTEL", **kwargs):
    brain = RuleBrain(current_goal=goal, **kwargs)
    return brain, brain.decide(world, v2_registry())


class TheClientCanLeaveTheDeadEndTests(unittest.TestCase):
    def test_a_blocked_card_is_left_instead_of_stranding_the_run(self):
        brain, decision = _decide(_card())
        self.assertEqual(decision.skill, "BACK")
        self.assertEqual(decision.reason, "beast_card_not_actionable_leaving_the_page")
        self.assertTrue(brain.beast_card_not_actionable_left)

    def test_a_back_that_did_not_move_the_client_is_not_repeated(self):
        # Otherwise the loop ping-pongs card -> map -> card and burns actions.
        brain, _ = _decide(_card())
        self.assertTrue(brain.beast_card_not_actionable_left)
        second = brain.decide(_card(), v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, "beast_not_actionable")

    def test_the_leave_is_an_ordinary_step_not_a_fatal_one(self):
        _, decision = _decide(_card())
        self.assertFalse(is_fatal_stop(decision.reason))

    def test_the_step_is_verifiable_by_the_real_verifier(self):
        """A recovery nobody can verify is not a recovery.

        ``verify_safe_back`` requires the before page to be neither MAP nor
        POPUP, the after page to differ, and the after page to be known --
        exactly the measured BEAST -> MAP transition.
        """
        result = verify_safe_back(_card(), WorldState(page=Page.MAP, confidence=0.99))
        self.assertTrue(result.ok, result.evidence)
        self.assertEqual(result.reason, "OK")

    def test_the_verifier_still_rejects_a_back_that_did_nothing(self):
        # Negative control for the assertion above: same page means no proof.
        result = verify_safe_back(_card(), _card())
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "SAFE_BACK_NOT_PROVEN")


class TheRecoveryDoesNotShadowRealWorkTests(unittest.TestCase):
    def test_an_actionable_intel_beast_is_still_marched_on(self):
        _, decision = _decide(
            _card({"mission_id": "INTEL_BEAST_10", "level": 22, "available": True})
        )
        self.assertEqual(decision.skill, "INTEL_BEAST_START_MARCH")

    def test_an_actionable_wilderness_beast_is_still_hunted(self):
        _, decision = _decide(
            WorldState(page=Page.BEAST, beast={"available": True}, confidence=0.99)
        )
        self.assertEqual(decision.skill, "BEAST_HUNT")

    def test_a_card_with_nothing_to_say_is_left_not_silently_ignored(self):
        # An empty beast dict on this page is not "available", so it is the same
        # dead end and gets the same way out.
        _, decision = _decide(WorldState(page=Page.BEAST, beast={"available": False}, confidence=0.99))
        self.assertEqual(decision.skill, "BACK")

    def test_other_pages_are_unaffected(self):
        _, decision = _decide(WorldState(page=Page.MAP, march_used=3, march_max=6, confidence=0.99))
        self.assertNotEqual(decision.reason, "beast_card_not_actionable_leaving_the_page")


if __name__ == "__main__":
    unittest.main()
