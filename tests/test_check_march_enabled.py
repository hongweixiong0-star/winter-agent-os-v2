"""A skill the brain may select must be executable by the live loop.

Origin (2026-09-15).  ``CHECK_MARCH`` is a ``VERIFIED`` skill on ``Page.MAP``
whose whole action is an ``OBSERVE``: the brain picks it when the march counter
could not be read (``world.idle_marches is None``), because march-dependent work
cannot be planned without it.  It had ``verifier = None`` and was therefore
absent from ``LiveRuntime.VERIFIED_ATOMIC``, and ``runtime.py`` refuses any skill
outside that map:

    if decision.skill not in allowed or decision.skill not in self.VERIFIED_ATOMIC:
        return LiveRun(tuple(steps), "SKILL_NOT_ENABLED_FOR_LIVE_LOOP")

So every run that reached this state died on step 1 citing an integration gap as
though it were the outcome of the session.  Measured live: three
``GATHER_RESOURCE`` closures in a row all stopped on step 1 with
``SKILL_NOT_ENABLED_FOR_LIVE_LOOP``, which is why ``START_GATHER`` has never
executed on MAA at all -- the gather workflow cannot even begin.

The wording is not the only cost.  The recorded reason ``march_used`` goes
missing is that an overlay hides the counter, and it becomes readable again on a
later frame; a loop that cannot survive one more frame turns a transient
occlusion into a dead run.

These tests pin the honest claim and, more importantly, the contract: the
invariant is not "CHECK_MARCH works", it is "the brain never names a skill the
loop will refuse".
"""

from __future__ import annotations

import unittest

from winter_agent_v2 import runtime
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime_snapshot import is_fatal_stop
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_march_count_readable


def _map_unreadable() -> WorldState:
    """The measured live frame: on the map, march counter not readable."""
    return WorldState(page=Page.MAP, march_used=None, march_max=6, confidence=0.98)


def _map_readable() -> WorldState:
    return WorldState(page=Page.MAP, march_used=2, march_max=6, confidence=0.99)


class TheVerifierStatesOnlyWhatItSawTests(unittest.TestCase):
    def test_a_readable_counter_on_the_map_passes(self):
        result = verify_march_count_readable(_map_unreadable(), _map_readable())
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "OK")
        self.assertEqual(result.evidence["march_used_after"], 2)

    def test_a_still_unreadable_counter_is_not_a_success(self):
        result = verify_march_count_readable(_map_unreadable(), _map_unreadable())
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "MARCH_COUNT_NOT_READ")

    def test_leaving_the_map_is_not_a_success(self):
        # The whole point is to look again *here*; wandering off is a different
        # outcome and must not be recorded as having read the counter.
        result = verify_march_count_readable(_map_unreadable(), WorldState(page=Page.HOME, march_used=2))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "MARCH_COUNT_NOT_READ")
        self.assertFalse(result.evidence["stayed_on_map"])

    def test_the_reason_is_an_ordinary_stop(self):
        self.assertFalse(is_fatal_stop("MARCH_COUNT_NOT_READ"))


class TheLoopCanActuallyRunItTests(unittest.TestCase):
    def test_check_march_is_executable_by_the_live_loop(self):
        self.assertIn("CHECK_MARCH", runtime.LiveRuntime.VERIFIED_ATOMIC)

    def test_it_is_registered_against_the_new_verifier(self):
        self.assertIs(
            runtime.LiveRuntime.VERIFIED_ATOMIC.get("CHECK_MARCH"),
            verify_march_count_readable,
        )

    def test_the_skill_still_exists_and_is_marked_verified(self):
        skill = next((s for s in v2_registry().all() if s.id == "CHECK_MARCH"), None)
        self.assertIsNotNone(skill)
        self.assertEqual(skill.required_page, Page.MAP)

    def test_the_brain_choice_is_never_one_the_loop_refuses(self):
        """The contract that failed here.

        Whatever the brain names for this state, the loop must be willing to run
        it.  Asserting the specific skill would miss the point -- the defect was
        exactly that the brain and the loop disagreed about what was runnable.
        """
        decision = RuleBrain().decide(_map_unreadable(), v2_registry())
        self.assertEqual(decision.skill, "CHECK_MARCH")
        self.assertIn(decision.skill, runtime.LiveRuntime.VERIFIED_ATOMIC)

    def test_an_observation_step_is_not_a_tap(self):
        # CHECK_MARCH must never be able to spend or move anything: it is a
        # re-read, and a version that tapped would be a different skill.
        from winter_agent_v2.skills import v2_registry as registry

        skill = next(s for s in registry().all() if s.id == "CHECK_MARCH")
        self.assertEqual(skill.action.kind, "OBSERVE")


if __name__ == "__main__":
    unittest.main()
