"""A frame that has not answered the training question must go and read it.

This is the second half of the sweep fix in ``test_training_sweep_visits_the_training_page``.
Changing the ticket's ``entry_skill`` was necessary and not sufficient: ``RuleBrain.decide``
answers ``SAFE_STOP`` before the goal's step is ever consulted, so the ticket's new step never
ran.  Measured before this change, on the frame the new step is meant to act on::

    page HOME, panel open, no camps reading
      -> SAFE_STOP / training_quick_panel_entry_not_observed_so_the_known_failing_power_detour_is_skipped

The guard at ``brain.py:2193`` is not wrong.  Its question -- "did the panel already settle
this goal's state" -- is answered correctly and the two cases separate exactly as it needs::

    panel open, no camps   -> _panel_answered_this_goals_state == False
    panel open, has camps  -> _panel_answered_this_goals_state == True

and the goal layer already knows what to do in each: with a reading, ``*_CAMP_TRAINING`` is on
the board; without one, the sweep carries the ticket whose step is the training page.  What is
missing is the case in between, where the panel is open, the question is unanswered, and the
honest move is the one step that would answer it.

Why the guard's own comment is not evidence against this: it cites "100% failure, 20 of 20"
for ``OPEN_POWER_DETAILS`` -- a different page, the 加成总览, reached via
``train_goal_power_overview``.  ``OPEN_INFANTRY_TRAINING`` is a different skill on a
different page, and it has since run **57 times with 57 successes**, every after-frame
carrying the ``camps`` reading the guard was written to go and get.  So the detour the guard
warns about is not the step the sweep now takes.

These tests pin the boundary rather than the plumbing:

* unanswered training question -> the training page, not a refusal and not the power page;
* answered training question -> unchanged, and the per-camp goals own the board;
* a frame that is not on HOME at all -> the ordinary navigation back to the city, because
  the training page is reachable only from there;
* the guard still refuses the power detour it was written to refuse.
"""

import pytest

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.skills import v2_registry


def _brain():
    brain = RuleBrain()
    brain.current_goal = "TRAIN"
    brain.goal_id = "KEEP_TRAINING_PRODUCTIVE"
    return brain


def _home_panel(*, camps=None):
    panel = {
        "open": True,
        "rows": [{"key": "TRAINING", "label": "部队训练"}],
        "scroll_swipe_norm": [0.5, 0.5, 0.5, 0.6],
    }
    if camps is not None:
        panel["camps"] = camps
    return WorldState(page=Page.HOME, confidence=0.99, march_used=1, march_max=6,
                      quick_panel=panel)


CAMPS_READY = {"SHIELD_CAMP": {"troop_type": "INFANTRY", "label": "盾兵",
                               "status": "IDLE", "queue_available": True}}


def test_the_two_frames_the_guard_cares_about_stay_separated():
    """The guard's own question, asserted directly, because everything else depends on it.

    If this stops separating them, the change below would be reading a state the guard does
    not consider answered (or vice versa) and the two branches would contradict.
    """
    brain = _brain()
    assert brain._panel_answered_this_goals_state(_home_panel()) is False
    assert brain._panel_answered_this_goals_state(_home_panel(camps=CAMPS_READY)) is True


def test_an_unanswered_training_question_opens_the_training_page():
    """The one behaviour this file changes.

    Panel open, question unanswered, the sweep is the ticket on the board, and the one step
    that would answer it is the training page -- proven 57/57 with the reading in its
    after-frame.
    """
    decision = _brain().decide(_home_panel(), registry=v2_registry())
    assert decision.skill == "OPEN_INFANTRY_TRAINING", (
        f"expected the training page, got {decision.skill!r} / {decision.reason!r}"
    )


def test_the_power_detour_is_still_refused():
    """The control that matters most: this must not become a route back to 加成总览.

    The guard exists for a measured reason -- that detour failed 20 of 20 -- and relaxing the
    training branch must not reopen it.  The two are different pages, and only the training
    branch is being touched.
    """
    decision = _brain().decide(_home_panel(), registry=v2_registry())
    assert decision.skill != "OPEN_POWER_OVERVIEW"
    assert decision.skill != "OPEN_POWER_DETAILS"
    assert "power" not in decision.reason.lower()


def test_an_answered_question_is_untouched():
    """With a camps reading the behaviour must be exactly what it already was.

    The panel then describes an idle camp, so the goal layer hands the board to
    ``*_CAMP_TRAINING`` and this branch is not reached by the sweep at all.  Asserted against
    HEAD rather than against what would read as tidier: the frame answers "no usable row for
    shield camp" and the branch below answers the power-route fallback, and **that is
    pre-existing behaviour which this change does not touch** (verified by running HEAD).
    """
    brain = _brain()
    before = brain.decide(_home_panel(camps=CAMPS_READY), registry=v2_registry())
    assert before.skill == "OPEN_POWER_OVERVIEW", (
        "the answered case must keep its existing answer; if this now reads differently the "
        "change leaked into a path it was not meant to touch"
    )
    assert brain._panel_answered_this_goals_state(_home_panel(camps=CAMPS_READY)) is True



def test_off_home_the_route_is_unchanged():
    """The training page is reachable only from the city, so MAP still means go home.

    Not a behaviour change -- a boundary.  Without it, relaxing the HOME branch would be read
    as "training is now a step wherever you happen to be".
    """
    decision = _brain().decide(
        WorldState(page=Page.MAP, confidence=0.99, march_used=1, march_max=6),
        registry=v2_registry(),
    )
    assert decision.skill == "OPEN_HOME", f"got {decision.skill!r} / {decision.reason!r}"
