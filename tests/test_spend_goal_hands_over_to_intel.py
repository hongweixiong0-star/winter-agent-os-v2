"""No beast in view: the spend goal hands over to the intel flow instead of stopping.

The operator's rule for this round: 如果当前没有适合的普通野兽，尝试已有可靠能力能够执行的其他耗体力任务，
例如符合条件的情报任务。

The evidence behind it: AVOID_STAMINA_WASTE is READY at priority 2585 with distance 497 (stamina 527
against a target of 30), it routes to BEAST_HUNT, and that route scans a bounded number of times and
then stops with verified_beast_target_not_visible having spent nothing -- five runs, 0 stamina, and
the two sprite templates match nothing on 23 live frames because they search bare snow.  Meanwhile
intel is AVAILABLE and LIVE_VERIFIED at 10-15 stamina per mission.

The handover is bounded on purpose, and these tests pin every bound, because an unbounded handover
would be a new way to spend stamina on a route nobody chose.
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
from winter_agent_v2.skills import v2_registry  # noqa: E402


def _on_map() -> WorldState:
    return WorldState(page=Page.MAP, stamina={"current": 527}, march_used=1, march_max=6,
                      confidence=0.99)


def _on_map_search_panel() -> WorldState:
    """The search panel open on the beast tab: where 搜索 is issued from."""
    return WorldState(page=Page.MAP, stamina={"current": 527}, march_used=1, march_max=6,
                      resource_search_open=True, resource_beast_tab=True, confidence=0.99)


def _on_map_after_search() -> WorldState:
    """The state the handover is decided in: bare map, both tickets spent.

    Since 2026-09-21 the beast route asks the client's own search for a target
    before it pans the map, and 搜索 leaves the panel up -- so the route leaves
    the panel with one Back before its pan budget applies.  A handover cannot be
    reached while the route is still standing on that panel, which is why this
    helper is the bare map rather than the panel.
    """
    return WorldState(page=Page.MAP, stamina={"current": 527}, march_used=1, march_max=6,
                      confidence=0.99)


class TheSpendGoalHandsOverToIntelTests(unittest.TestCase):
    def _brain(self, *, goal: str, scans_used: int, route: str = "BEAST_HUNT"):
        brain = RuleBrain()
        brain.current_goal = route
        brain.goal_id = goal
        brain.beast_scans_used = scans_used
        # Both of the route's own methods are spent: the search ticket is part of
        # the route's turn, and the panel has already been left.  The tests below
        # pin that both really do come first.
        brain.beast_search_used = True
        brain.beast_search_panel_left = True
        return brain

    def test_the_beast_route_still_gets_its_whole_scan_budget_first(self):
        """The handover must not pre-empt the route it is replacing."""
        brain = self._brain(goal="AVOID_STAMINA_WASTE", scans_used=0)
        decision = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(decision.skill, "SCAN_MAP_FOR_BEAST")
        self.assertFalse(brain.spend_route_switched, "the switch must wait for the budget")

    def test_the_search_is_part_of_the_turn_not_a_shortcut(self):
        """The un-spent search ticket is tried before any handover.

        A brain that has spent its pan budget but never asked the client to
        search has not finished the route: the search is the convergence the pan
        lacked, so handing over to intel while it is still unspent would abandon
        the route's best method.
        """
        brain = RuleBrain()
        brain.current_goal = "BEAST_HUNT"
        brain.goal_id = "AVOID_STAMINA_WASTE"
        brain.beast_scans_used = SCAN_BUDGET
        brain.beast_search_used = False
        decision = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(
            decision.skill, "SEARCH_RESOURCE",
            "the un-spent search is tried before the handover",
        )
        self.assertFalse(brain.spend_route_switched)

    def test_the_panel_is_left_before_the_pan_budget_applies(self):
        """搜索 leaves the panel up, so one Back is what reaches the bare map.

        Without this hop the route would pan while the panel still covers the map,
        and the pan would be a gesture on a panel rather than on the world.
        """
        brain = RuleBrain()
        brain.current_goal = "BEAST_HUNT"
        brain.goal_id = "AVOID_STAMINA_WASTE"
        brain.beast_scans_used = 0
        brain.beast_search_used = True
        brain.beast_search_panel_left = False
        decision = brain.decide(_on_map_search_panel(), v2_registry())
        self.assertEqual(decision.skill, "BACK")
        self.assertTrue(brain.beast_search_panel_left)

    def test_after_the_budget_it_opens_the_intel_flow_instead_of_stopping(self):
        brain = self._brain(goal="AVOID_STAMINA_WASTE", scans_used=SCAN_BUDGET)
        decision = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(
            decision.skill, "OPEN_INTEL",
            "no beast in view means another verified stamina task, not a safe stop",
        )
        self.assertEqual(brain.current_goal, "SPEND_STAMINA", "the route hands over")
        self.assertTrue(brain.spend_route_switched)

    def test_the_handover_happens_once_per_run(self):
        """The bound: a *second* give-up on the beast route is a stop, not another handover.

        After the first handover the run is legitimately on the spend route, so it opens intel on
        its own -- that is the route working, not the handover repeating.  What must not happen is
        the beast route giving up twice and switching twice, so the second give-up is asserted
        with the run put back on BEAST_HUNT.
        """
        brain = self._brain(goal="AVOID_STAMINA_WASTE", scans_used=SCAN_BUDGET)
        brain.decide(_on_map_after_search(), v2_registry())
        self.assertTrue(brain.spend_route_switched)

        brain.current_goal = "BEAST_HUNT"      # as if the run were back on the beast route
        brain.goal_id = "AVOID_STAMINA_WASTE"
        second = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(second.skill, "SAFE_STOP",
                         "the handover is once per run; a second give-up is a stop")

    def test_another_goal_is_untouched_by_this_rule(self):
        """Only the goal whose purpose is to spend may be handed over.

        A hunting run that finds nothing is not a failure -- it is a hunt that found nothing --
        and turning it into an intel run would change a route the operator chose.
        """
        brain = self._brain(goal="", route="BEAST_HUNT", scans_used=SCAN_BUDGET)
        decision = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertFalse(brain.spend_route_switched)


#: The scan budget, read off a brain rather than hard-coded here.
SCAN_BUDGET = RuleBrain().max_beast_scans


if __name__ == "__main__":
    unittest.main()
