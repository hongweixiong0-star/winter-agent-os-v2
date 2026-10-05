"""The event route must close the search panel before it goes home from the map.

Measured 2026-10-05 over the retained ledger, skill ``OPEN_HOME``: 567 episodes, **54** ended
``SEMANTIC_TARGET_NOT_VERIFIED`` -- and **every one of the 54 carried the same reason**,
``event_route_goal_needs_the_city_hud_for_an_activity_entry``, i.e. they all came from this one
branch of ``RuleBrain.decide``.  On 10-05 alone there were 31, against 2/12/9 on the three days
before, so it was getting worse.

Why they fail is visible on the frame: the branch ran on a world-map frame whose
resource-search bottom sheet is open, and that sheet covers the bar the 常规活动 / return-to-city
control is drawn on.  The frame-level probe agrees -- running the runtime's own matcher over
those very ``before_screenshot`` files finds ``BTN_OPEN_HOME`` 0 times out of 12, while the same
matcher hits 12/12 (distance 2) on the skill's successful steps.

Every sibling branch that goes home from MAP already closes the panel first.  This test pins
the one that did not, and pins that the ordinary case is untouched.
"""

import unittest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry


def _brain():
    brain = RuleBrain()
    brain.current_goal = "EVENT"
    brain.goal_id = "SCHEDULED_BROTHERS_IN_ARMS"
    return brain


def _decide(**kwargs):
    return _brain().decide(WorldState(page=Page.MAP, confidence=0.99, **kwargs),
                           registry=v2_registry())


class TheEventRouteClosesThePanelBeforeGoingHome(unittest.TestCase):
    def test_an_open_search_panel_is_closed_before_the_city_hud_is_named(self):
        decision = _decide(resource_search_open=True)
        self.assertEqual(decision.skill, "BACK")
        self.assertNotEqual(decision.skill, "OPEN_HOME")

    def test_the_panel_free_case_still_goes_home(self):
        """The measured shape the sibling test already pins must not change."""
        decision = _decide(resource_search_open=False)
        self.assertEqual(decision.skill, "OPEN_HOME")

    def test_the_panel_free_case_is_also_what_an_unmeasured_frame_gets(self):
        """``resource_search_open`` defaults to False, so a frame that did not read the
        panel keeps the old behaviour rather than gaining a new refusal."""
        decision = _decide()
        self.assertEqual(decision.skill, "OPEN_HOME")

    def test_the_branch_still_names_registered_skills_only(self):
        registry = v2_registry()
        for open_panel in (True, False):
            decision = _decide(resource_search_open=open_panel)
            self.assertIsNotNone(registry.get(decision.skill),
                                 f"{decision.skill!r} is not a registered skill")


if __name__ == "__main__":
    import unittest

    unittest.main()
