"""No beast in view: the beast route stops with its measured reason -- the spend handover
itself now lives in the stamina sink policy (see the re-derivation note below).

The operator's rule for this round: 如果当前没有适合的普通野兽，尝试已有可靠能力能够执行的其他耗体力任务，
例如符合条件的情报任务。

The evidence behind it: AVOID_STAMINA_WASTE is READY at priority 2585 with distance 497 (stamina 527
against a target of 30), it routes to BEAST_HUNT, and that route scans a bounded number of times and
then stops with verified_beast_target_not_visible having spent nothing -- five runs, 0 stamina, and
the two sprite templates match nothing on 23 live frames because they search bare snow.  Meanwhile
intel is AVAILABLE and LIVE_VERIFIED at 10-15 stamina per mission.

The handover is bounded on purpose, and these tests pin every bound, because an unbounded handover
would be a new way to spend stamina on a route nobody chose.

**Re-derived 2026-10-16.**  The *in-brain* handover this file was written for was retired by
``6863b779`` (2026-09-30, "Wire stamina policy to shared polar rally session and client search"):
the give-up path now stops with its own measured reason (``verified_beast_target_not_visible``)
and what happens *next* is the stamina **sink** policy's business -- ``knowledge/strategy/
stamina_routes.json`` plus the runtime's ``_stamina_sink`` / ``_stamina_route``, whose own tests
live in ``test_stamina_sink_routing.py``.  The two tests below were re-pointed to the contract
that remains on the brain's side: the route stops honestly, leaves no switch behind, and asking
twice gives the same answer.
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

    def test_after_the_budget_the_route_stops_with_its_measured_reason(self):
        """Re-derived 2026-10-16: the give-up is a stop, and the handover moved to the sink policy.

        The in-brain ``OPEN_INTEL`` handover was retired by ``6863b779``; what survives on the
        brain's side is that the beast route gives up with its own measured reason instead of
        silently rewriting its route.  Where the spend *goes* is the sink policy's decision
        (``test_stamina_sink_routing.py``), not this branch's.
        """
        brain = self._brain(goal="AVOID_STAMINA_WASTE", scans_used=SCAN_BUDGET)
        decision = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(
            decision.reason, "verified_beast_target_not_visible",
            "the stop names what was measured, not what might happen next",
        )
        self.assertFalse(brain.spend_route_switched, "the switch is not the brain's to make any more")

    def test_a_second_give_up_is_the_same_measured_stop(self):
        """Re-derived 2026-10-16: the once-per-run bound died with the handover it bounded.

        What replaces it: the give-up is a pure stop -- asking twice gives the same answer and
        touches no switch, so nothing in the brain can turn it into either a loop or a silent
        route change.  The bound on *what happens next* now lives in the sink policy
        (``test_stamina_sink_routing.py``).
        """
        brain = self._brain(goal="AVOID_STAMINA_WASTE", scans_used=SCAN_BUDGET)
        first = brain.decide(_on_map_after_search(), v2_registry())
        second = brain.decide(_on_map_after_search(), v2_registry())
        self.assertEqual(first.skill, "SAFE_STOP")
        self.assertEqual(second.skill, "SAFE_STOP")
        self.assertEqual(second.reason, first.reason, "a give-up leaves no state behind")
        self.assertFalse(brain.spend_route_switched)

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
