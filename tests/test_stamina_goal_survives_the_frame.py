"""The stamina goal must not disappear when the gauge is off screen.

Measured live 2026-09-19 on a healthy run: the Goal Board carried no ``AVOID_STAMINA_WASTE`` row
at all, and ``snapshot.stamina`` was ``None``.  ``discover()`` emitted the goal only when
``world.stamina["current"]`` (or the intel board's copy of it) was readable, and stamina is a HUD
reading rather than a page -- so on every frame that was not the map or the intel board, the goal
did not exist.  The operator's standing requirement is "stamina above 30 means keep spending until
it is below 30", and that requirement cannot be scheduled by a goal that is absent half the time.

So stamina is an observed domain like the panels: the last reading outlives the frame that
produced it, while it is still fresh, and the goal carries ``reused`` so a reader can tell a value
taken now from one taken minutes ago.

What these tests defend
-----------------------
* A fresh stored reading keeps the goal alive, and always above the sweep tickets -- stamina
  spending outranks browsing.
* A *stale* reading does not: claiming stamina from an old frame is the same mistake in the other
  direction, and the goal can simply come back when a frame carries the gauge.
* No reading at all is still no goal: this is not a licence to invent a number.
* The goal's meter stays "how much is left to spend", not "did one hunt happen" -- the operator's
  §一 explicitly asks for the former.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import STAMINA_FLOOR, GoalLibrary, GoalStatus  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402


def stamina_goal(world: WorldState, observations=None):
    for goal in GoalLibrary().discover(world, observations=observations):
        if goal.goal_id == "AVOID_STAMINA_WASTE":
            return goal
    return None


def stored(current: int, *, overdue: bool) -> dict:
    return {"stamina": {"reading": {"current": current},
                        "overdue": overdue, "overdue_ratio": 2.0 if overdue else 0.2}}


def test_a_fresh_reading_keeps_the_goal_alive_off_the_map():
    """The regression: on any non-map page the goal used to vanish."""
    goal = stamina_goal(WorldState(page=Page.HOME, confidence=0.99), stored(547, overdue=False))
    assert goal is not None, "the stamina requirement must not depend on which page is on screen"
    assert goal.status is GoalStatus.READY
    assert goal.evidence["reused"] is True
    assert goal.evidence["current"] == 547


def test_a_stale_reading_does_not_keep_it_alive():
    """Refusing an old number is the other half: a stale frame is not evidence of now."""
    assert stamina_goal(WorldState(page=Page.HOME), stored(547, overdue=True)) is None


def test_no_reading_anywhere_is_still_no_goal():
    assert stamina_goal(WorldState(page=Page.HOME)) is None


def test_a_live_reading_wins_and_is_not_labelled_reused():
    goal = stamina_goal(WorldState(page=Page.MAP, stamina={"current": 611}),
                        stored(547, overdue=False))
    assert goal.evidence["current"] == 611
    assert goal.evidence["reused"] is False


def test_spending_stamina_outranks_browsing_panels():
    """§一: stamina work must not be crowded out by routine sweeps.

    The world carries march data as well as stamina, because a goal that is not emitted cannot be
    compared: the first version of this test compared against ``KEEP_MARCHES_PRODUCTIVE`` in a
    world with no march reading, and it raised rather than asserting -- which is how it shipped red
    for one commit.
    """
    goals = {g.goal_id: g for g in GoalLibrary().discover(
        WorldState(page=Page.HOME, march_used=2, march_max=3),
        observations=stored(547, overdue=False))}
    assert "KEEP_MARCHES_PRODUCTIVE" in goals, "the comparison needs both goals to exist"
    assert goals["AVOID_STAMINA_WASTE"].priority > goals["MAIL_ROUTINE"].priority
    assert goals["AVOID_STAMINA_WASTE"].priority > goals["KEEP_MARCHES_PRODUCTIVE"].priority


def test_the_meter_is_how_much_is_left_to_spend():
    """§一: not "one hunt happened" -- the distance is the stamina still above the floor.

    The meter reads one point of work at the floor itself, because the requirement is
    "under 30" and 30 is not under 30.  The boundary is exclusive, so the distance is
    measured against ``STAMINA_FLOOR - 1`` rather than against the floor.
    """
    goal = stamina_goal(WorldState(page=Page.MAP, stamina={"current": 611}))
    assert goal.distance == 611 - (STAMINA_FLOOR - 1)
    spent = stamina_goal(WorldState(page=Page.MAP, stamina={"current": 551}))
    assert spent.distance == 551 - (STAMINA_FLOOR - 1), "spending must show as progress, not as completion"
    assert spent.status is GoalStatus.READY


def test_the_floor_itself_is_not_yet_satisfied():
    """The boundary the operator stated: 30 has not reached "under 30".

    It used to answer COMPLETE here, which stopped the goal one point early -- and that
    point is a whole beast dispatch, so the goal claimed to be done with work still owed.
    """
    goal = stamina_goal(WorldState(page=Page.MAP, stamina={"current": STAMINA_FLOOR}))
    assert goal.status is GoalStatus.READY
    assert goal.distance == 1.0, "one point of spending is still owed at the floor"
    assert goal.completion == 0.0


def test_below_the_floor_is_complete():
    goal = stamina_goal(WorldState(page=Page.MAP, stamina={"current": 28}))
    assert goal.status is GoalStatus.COMPLETE
    assert goal.distance == 0.0
