"""Two live defects from the first long window, and the bounds that fix them.

**The hop the sweep needs.**  Measured 2026-09-19, from the episode stream:

    07:42:37 KEEP_RESEARCH_PRODUCTIVE  OPEN_ALLIANCE_GIFTS   on=ALLIANCE
    07:43:34 KEEP_RESEARCH_PRODUCTIVE  CLOSE_POPUP           on=POPUP/GENERIC_REWARD
    ... eleven more CLOSE_POPUP, one per run, ~41 seconds apart

The research goal was selected while the client stood on the ALLIANCE panel.  The four panel
routines got a "leave a page this goal does not own" hop when they were wired; these two routes
were missed, so the page-driven alliance branch ran *under a research goal* and the research page
was never once read.

**Ties are not rotation.**  `_sweep_value` used a capped ramp, so every overdue ticket sat at the
same ceiling, `best()` returned the first of the tie, and one ticket was re-selected forever --
the twelve CLOSE_POPUP runs above are what that looks like.  The age term is now an asymptote:
strictly increasing, so no two tickets with different history are ever equal and the loop rotates
to the one that has waited longest.  The ceiling stays under a real claim.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.goal_library import (  # noqa: E402
    SWEEP_BASE_VALUE,
    GoalLibrary,
    GoalStatus,
    _sweep_value,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

TICKETS = ("CLEAR_INTEL", "KEEP_TRAINING_PRODUCTIVE", "KEEP_RESEARCH_PRODUCTIVE",
           "MAIL_ROUTINE", "DAILY_ACTIVITY_TARGET", "ALLIANCE_ROUTINE",
           "CLAIM_EXPLORATION_IDLE")


def test_the_swept_goals_leave_a_panel_they_do_not_own():
    """The measured cause: a research goal running the alliance branch."""
    for goal in ("TRAIN", "RESEARCH"):
        brain = RuleBrain(current_goal=goal)
        first = brain.decide(WorldState(page=Page.ALLIANCE, confidence=0.99), v2_registry())
        assert first.skill == "BACK", f"{goal} on the alliance panel must leave it"
        assert "panel_it_does_not_own" in first.reason
        second = brain.decide(WorldState(page=Page.ALLIANCE, confidence=0.99), v2_registry())
        assert second.skill == "SAFE_STOP", "the hop happens once, so a Back that did not move ends"


def test_a_swept_goal_on_its_own_page_is_not_disturbed():
    """The hop must not shadow the real route: HOME and MAP still start the documented walk.

    Measured values, not a shape: both routes begin at the power overview from HOME and go home
    from the map, which is the entry the route notes were written against.
    """
    for goal in ("TRAIN", "RESEARCH"):
        from_home = RuleBrain(current_goal=goal).decide(
            WorldState(page=Page.HOME, confidence=0.99), v2_registry())
        assert from_home.skill == "OPEN_POWER_OVERVIEW", f"{goal} from HOME"
        from_map = RuleBrain(current_goal=goal).decide(
            WorldState(page=Page.MAP, confidence=0.99), v2_registry())
        assert from_map.skill == "OPEN_HOME", f"{goal} from MAP"


def test_the_age_term_never_ties_two_different_histories():
    """A cap creates ties, a tie is not rotation, and a tie is what hammered one ticket."""
    values = [_sweep_value(r) for r in (0, 0.25, 0.5, 1, 2, 3, 10, 50, 500)]
    assert values == sorted(values), "the price must be monotone in how overdue it is"
    assert len(set(values)) == len(values), f"two overdue ratios priced the same: {values}"


def test_the_price_stays_below_anything_that_actually_pays():
    assert _sweep_value(10_000) < 250, "a claimable routine is worth 250"


def test_seven_overdue_tickets_are_ordered_by_how_long_they_have_waited():
    """The rotation, as the scheduler actually sees it."""
    ratios = {"intel": 6.0, "training": 5.0, "research": 4.0, "mail": 3.0,
              "daily": 2.0, "alliance": 1.0, "exploration": 0.5}
    observations = {d: {"reading": {}, "overdue": True, "overdue_ratio": r}
                    for d, r in ratios.items()}
    library = GoalLibrary()
    goals = library.discover(WorldState(page=Page.MAP, march_used=2, march_max=3),
                             observations=observations)
    by_id = {g.goal_id: g for g in goals}
    waiting = sorted((g for g in goals if g.status is GoalStatus.DISCOVERED),
                     key=lambda g: -g.priority)
    assert [g.goal_id for g in waiting] == sorted(TICKETS, key=lambda t: -ratios_rank(t, ratios)), (
        "the ticket that has waited longest must be priced highest"
    )
    assert library.best(goals).goal_id == "CLEAR_INTEL"
    assert by_id["CLEAR_INTEL"].priority > by_id["KEEP_RESEARCH_PRODUCTIVE"].priority, (
        "research was the one being hammered; it must not outrank a longer wait"
    )


def ratios_rank(goal_id: str, ratios: dict[str, float]) -> float:
    field = {"CLEAR_INTEL": "intel", "KEEP_TRAINING_PRODUCTIVE": "training",
             "KEEP_RESEARCH_PRODUCTIVE": "research", "MAIL_ROUTINE": "mail",
             "DAILY_ACTIVITY_TARGET": "daily", "ALLIANCE_ROUTINE": "alliance",
             "CLAIM_EXPLORATION_IDLE": "exploration"}[goal_id]
    return ratios[field]


def test_an_unread_ticket_is_still_worth_more_than_routine_gathering():
    library = GoalLibrary()
    goals = {g.goal_id: g for g in
             library.discover(WorldState(page=Page.MAP, march_used=2, march_max=3))}
    assert goals["CLEAR_INTEL"].priority == SWEEP_BASE_VALUE
    assert goals["CLEAR_INTEL"].priority > goals["KEEP_MARCHES_PRODUCTIVE"].priority
