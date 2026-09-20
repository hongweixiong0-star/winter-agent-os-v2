"""The training route has two stages, and Stage A must not tap the camp.

Regression under test (2026-09-17, open issue #28)
-------------------------------------------------
After ``NAVIGATE_INFANTRY_CAMP`` the client sits on HOME with the infantry camp
highlighted and a large tutorial finger over it; the radial menu is **not** drawn
yet.  The brain used to answer that state with ``SELECT_INFANTRY_CAMP`` -- tap the
camp -- and the live tap moved the client to the **map**:

    run_live --goal TRAIN, live 2026-09-17 17:45 GMT+8
      step 4 SELECT_INFANTRY_CAMP  verifier FAIL INFANTRY_CAMP_MENU_NOT_PROVEN
      after frame = the world map
      dataset/raw/control_panel/runtime_training/20260917_train_homefix/
        step_004_before...png            camp highlighted + tutorial finger
        step_004_after_refresh_2...png   the world map

So Stage A is now a no-input re-observe (``WAIT_FOR_CAMP_MENU``) and Stage B -- the
menu itself, which vision reports as ``menu_open`` -- keeps opening the training
page.  The two invariants worth pinning are that Stage A never taps, and that a
"wait" which ends on the map is never recorded as a success.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402
from winter_agent_v2.verifier import verify_camp_menu_reobserved  # noqa: E402


def decide(goal: str, world: WorldState):
    return RuleBrain(current_goal=goal).decide(world, v2_registry())


def stage_a() -> WorldState:
    return WorldState(page=Page.HOME,
                      training={"navigation": "INFANTRY_CAMP_HIGHLIGHTED", "queue_available": True},
                      confidence=0.99)


def stage_b() -> WorldState:
    return WorldState(page=Page.HOME,
                      training={"building": "INFANTRY_CAMP", "status": "IDLE",
                                "queue_available": True, "menu_open": True},
                      confidence=0.99)


class StageRoutingTest(unittest.TestCase):
    def test_stage_a_reobserves_and_never_taps_the_camp(self):
        decision = decide("TRAIN", stage_a())
        self.assertEqual(decision.skill, "WAIT_FOR_CAMP_MENU")
        self.assertEqual(decision.reason, "camp_highlight_is_stage_a_reobserve")
        self.assertNotEqual(decision.skill, "SELECT_INFANTRY_CAMP")

    def test_stage_b_opens_training(self):
        decision = decide("TRAIN", stage_b())
        self.assertEqual(decision.skill, "OPEN_INFANTRY_TRAINING")

    def test_stage_a_skill_sends_no_input(self):
        # WAIT_FOR_CAMP_MENU is still an observation and still touches nothing.  What changed
        # on 2026-09-21 is what happens *before* the wait: stage A now makes one tap at the
        # selection ring's measured centre (SELECT_INFANTRY_CAMP), because the reason for never
        # tapping -- a tutorial finger covering the camp -- was falsified, and because the frame
        # whose tap jumped to the map turned out to carry no ring at all (a 7x15 fleck of gold
        # against a real ring's 205x112), so the two states are separable after all.  The wait
        # itself is unchanged, and it is still what happens when no ring can be read.
        skill = next(s for s in v2_registry().all() if s.id == "WAIT_FOR_CAMP_MENU")
        self.assertEqual(skill.action.kind, "OBSERVE")
        self.assertEqual(skill.required_page, Page.HOME)

    def test_stage_a_skill_is_dispatchable(self):
        self.assertIn("WAIT_FOR_CAMP_MENU", LiveRuntime.VERIFIED_ATOMIC)

    def test_vision_reports_the_menu_before_the_highlight(self):
        # Order is the whole discrimination: if the highlight branch came first it
        # would shadow a drawn menu and Stage A would win forever.
        #
        # Anchored on the call rather than on `if match(...)`, because the highlight branch now
        # binds its match to a name before reading the ring out of the frame.  The property
        # being pinned is the order, not the syntax of the line.
        source = (ROOT / "winter_agent_v2/vision.py").read_text(encoding="utf-8")
        menu = source.index('if match("BTN_TRAINING_MENU_LABEL") or match("BTN_OPEN_TRAINING_FROM_CAMP")')
        highlight = source.index('match("TARGET_INFANTRY_CAMP_HIGHLIGHTED")')
        self.assertLess(menu, highlight)


class StageAVerifierTest(unittest.TestCase):
    def test_a_wait_that_stays_on_home_is_proven(self):
        result = verify_camp_menu_reobserved(stage_a(), stage_a())
        self.assertTrue(result.ok, result.reason)

    def test_a_wait_after_which_the_menu_drew_is_also_proven(self):
        result = verify_camp_menu_reobserved(stage_a(), stage_b())
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(result.evidence["menu_drawn"])

    def test_a_wait_that_ends_on_the_map_is_never_a_success(self):
        # This is the exact regression: the old path tapped in Stage A and the client
        # ended on the map.  A wait that lands there must fail loudly.
        for page in (Page.MAP, Page.TRAINING, Page.ALLIANCE, Page.MAIL):
            result = verify_camp_menu_reobserved(stage_a(), WorldState(page=page, confidence=0.99))
            self.assertFalse(result.ok, page)
            self.assertEqual(result.reason, "CAMP_MENU_REOBSERVE_NOT_PROVEN", page)

    def test_a_wait_that_did_not_start_from_stage_a_is_not_proven(self):
        result = verify_camp_menu_reobserved(stage_b(), stage_b())
        self.assertFalse(result.ok)
        self.assertFalse(result.evidence["before_highlighted"])


class TheWaitIsBoundedTest(unittest.TestCase):
    """Stage A is persistent, not transient -- so the wait must not be unbounded.

    Measured 2026-09-17 18:00 GMT+8: seven consecutive Stage A re-observations each
    returned ``menu_drawn=false`` and the run ended ``MAX_ACTIONS_REACHED``.  An
    unbounded wait spends an entire run on a state that is not converging, so after
    two waits the honest answer is a named blocker.
    """

    def test_two_waits_then_a_named_blocker(self):
        brain = RuleBrain(current_goal="TRAIN")
        skills = [brain.decide(stage_a(), v2_registry()).skill for _ in range(4)]
        self.assertEqual(skills[:2], ["WAIT_FOR_CAMP_MENU", "WAIT_FOR_CAMP_MENU"])
        self.assertEqual(skills[2:], ["SAFE_STOP", "SAFE_STOP"])

    def test_the_blocker_is_named(self):
        brain = RuleBrain(current_goal="TRAIN")
        brain.decide(stage_a(), v2_registry())
        brain.decide(stage_a(), v2_registry())
        decision = brain.decide(stage_a(), v2_registry())
        self.assertEqual(decision.reason, "camp_menu_never_drawn")

    def test_the_counter_is_per_run(self):
        first = RuleBrain(current_goal="TRAIN")
        first.decide(stage_a(), v2_registry())
        first.decide(stage_a(), v2_registry())
        fresh = RuleBrain(current_goal="TRAIN")
        self.assertEqual(fresh.decide(stage_a(), v2_registry()).skill, "WAIT_FOR_CAMP_MENU")

    def test_a_menu_that_draws_after_the_budget_is_still_acted_on(self):
        # The bound must not become a wall: vision reports the drawn menu as
        # ``menu_open`` (a different field), so a late Stage B still opens training.
        brain = RuleBrain(current_goal="TRAIN")
        brain.decide(stage_a(), v2_registry())
        brain.decide(stage_a(), v2_registry())
        self.assertEqual(brain.decide(stage_b(), v2_registry()).skill, "OPEN_INFANTRY_TRAINING")


if __name__ == "__main__":
    unittest.main()
