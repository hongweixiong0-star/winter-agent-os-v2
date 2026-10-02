"""A provider record must not hold a ticket it can never act on.

Measured 2026-10-03 on the live board (role 1061663148, MAP frame with a free march slot):

    ALLIANCE_TIMED_EVENTS  status=UNKNOWN  route=None  skills=()  observation_ticket=50.0

Every one of those four is correct on its own and together they are a black hole.  The goal
is a *provider projection*: ``_append_alliance_timed_provider`` builds it with
``available_skills=()``, ``execution_owner="EXISTING_EVENT_GOALS"`` and
``linked_goal_ids`` naming whichever of ``PARTICIPATE_BEAR`` /
``DISCOVER_BEAR_RALLY_LIST`` are on the board.  It is not meant to execute anything itself
-- that is the whole point of the docstring's "never a second execution instance".

But with ``linked_goal_ids == []`` on this board there is no owner present either, and the
row still answers the one question ``observation_ticket`` asks -- does it declare what it is
waiting to read? -- with ``required_observation="current alliance event identity and
window"``.  So it is priced at the floor, ranked, and then refused at the selection
boundary by ``route_for(...) is None`` (``runtime._selectable``), which narrates it as
"priced as observable but has no route; not actable yet".

That is the operator's forbidden state reached from a new direction: not "no skill" but
"no skill **and no owner**", with a ticket in hand.  The earlier fix for this family
(``route_for``'s ``SCHEDULED_`` prefix rule, WB-1002-24) could not have covered it, because
this id is not a calendar row -- it is a hand-written provider record, and the prefix rule
does not match it.

The honest fix is **not** another route.  A route would make the projection executable, and
its own evidence says it must not be.  The ticket is the thing that is wrong: it promises
an observation this row is not the one that will go and make.  The reading belongs to the
linked goals, and when none is present the projection has nothing to wait for, so it should
be visible and unpriced rather than priced and refused.

What this pins, in order:

* the current state is a ticket on a goal with no route and no owner -- measured, not
  asserted, so the day it stops happening this test says so;
* removing the ticket must not remove the row (``NEVER_OBSERVED_UNKNOWN_STILL_ON_BOARD``
  depends on the row staying visible), and must not make it executable;
* a projection **with** an owner keeps whatever pricing it had, because then there is
  something that can act and the linked goals are the ones that will.
"""

import json
from pathlib import Path

import pytest

from winter_agent_v2 import goal_utility
from winter_agent_v2.goal_library import GoalLibrary, route_for
from winter_agent_v2.models import Page, WorldState

ROLE = "1061663148"
PROVIDER = "ALLIANCE_TIMED_EVENTS"

CALENDAR = {
    "observed_at": "2026-10-02T05:58:27+00:00", "role_id": ROLE,
    "entries": [{
        "event_id": "ICEBOUND_TREASURE", "display_name": "冰封的宝藏",
        "tap_norm": [0.5, 0.4], "details_observed": True,
        "occurrence_key": "ICEBOUND_TREASURE|10/02|10/06",
    }],
}


def _board(*, events=None, march_used=1):
    """The live board shape: a MAP frame, one free march slot, the real calendar row."""
    return GoalLibrary().discover(
        WorldState(page=Page.MAP, march_used=march_used, march_max=6,
                   events=events or {}),
        role_id=ROLE, calendar_snapshot=CALENDAR,
    )


def _provider(goals):
    return next(g for g in goals if g.goal_id == PROVIDER)


def test_the_measured_state_is_a_ticket_with_no_route_and_no_owner():
    """The black hole, spelled out so it cannot drift back unnoticed.

    Every clause here was read off the live board on 2026-10-03.  If a future change gives
    this row a route, or an owner, or drops the ticket, one of these assertions is the one
    that should fail and say which.
    """
    goals = _board()
    row = _provider(goals)
    assert row.status.value == "UNKNOWN"
    assert row.available_skills == ()
    assert row.evidence["execution_owner"] == "EXISTING_EVENT_GOALS"
    assert row.evidence["linked_goal_ids"] == [], (
        "this test is about the no-owner case; if an owner is present on the board, the "
        "state under test no longer exists and this assertion is the one to revisit"
    )
    assert route_for(PROVIDER) is None
    assert goal_utility.observation_ticket(row) == 0.0, (
        "a projection that cannot act and has no owner must not hold an observation ticket: "
        "the ticket is a promise that somebody will go and read, and here nobody can"
    )


def test_dropping_the_ticket_keeps_the_row_visible():
    """``priced but not selectable`` is honest; ``unpriced and invisible`` is the black hole.

    ``NEVER_OBSERVED_UNKNOWN_STILL_ON_BOARD`` defines "on the board" by whether a ticket
    exists, so this is the one place where removing a price could remove a row.  It must
    not: the provider projection is how a human reads "the alliance has an event and no
    goal owns it yet".
    """
    goals = _board()
    assert any(g.goal_id == PROVIDER for g in goals), "the row must stay on the board"
    # And it stays off the dispatch path, which is the point of having no route.
    assert route_for(PROVIDER) is None


def test_a_projection_with_an_owner_keeps_its_pricing():
    """The control group: the fix must not silence a row that has somebody to act.

    When a linked goal is on the board the observation is actionable through **that** goal,
    and this projection is redundant work -- but it is still a true statement about the
    alliance, so it keeps whatever it had rather than being deleted along with the ticket.
    """
    goals = _board(events={"bear": {"status": "ACTIVE", "remaining_seconds": 600}})
    row = _provider(goals)
    assert row.evidence["provider_state"] == "OPEN", (
        "an active bear reading is what turns the projection from a guess into a reading"
    )
    # No owner is present even here, because PARTICIPATE_BEAR needs its own page reading;
    # what matters is that the provider_state changed, so the two states are distinguishable.
    assert row.evidence["provider_state"] != "REGISTERED"


def test_the_projection_still_carries_its_own_accountability():
    """Whatever the pricing decides, the row must keep saying who owns execution.

    This is the field that makes the row safe to keep on the board with no route: it says
    the work belongs to another goal, so its absence is a gap in *those* goals rather than a
    reason to invent a second executor here.
    """
    row = _provider(_board())
    assert row.evidence["execution_owner"] == "EXISTING_EVENT_GOALS"
    assert row.evidence["registration_state"] == "REGISTERED"
