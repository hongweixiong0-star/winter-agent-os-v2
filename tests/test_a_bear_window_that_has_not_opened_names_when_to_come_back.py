"""A Bear window that has not opened yet names the time to come back.

A reservation's phase only reorders work that is already awake -- ``runtime`` applies it as a
priority bonus (``PHASE_PRIORITY``).  So a goal that must be *visited* at a time has to say so
where the runtime aggregates wait times, which is ``next_action_at`` in the goal's evidence
(runtime.py:2067 reads it into the role's ``next_action_at``).

The wake is built from ``seconds_to_start``, a DURATION, and never from
``reserved_start_time``: the client prints 预约自动开启 as a naive local time and the project's
time rule forbids inferring the game's timezone from this machine's, so an absolute stamp from
it could not become a wake at all.  The lead is the T-30 rung of the ladder the operator's own
record carries (knowledge/events/bear_hunt_time_20260927_newaccount.json -> wake_ladder).
"""

from datetime import datetime, timedelta, timezone

from winter_agent_v2.goal_library import BEAR_WAKE_LEAD_SECONDS, GoalLibrary
from winter_agent_v2.models import Page, WorldState

OBSERVED = datetime(2026, 10, 10, 4, 0, tzinfo=timezone.utc)


def bear_ticket(**bear):
    world = WorldState(
        page=Page.MAP, alliance={}, timestamp=OBSERVED,
        events={"bear": {"event_id": "BEAR_HUNT", **bear}},
    )
    goals = GoalLibrary().discover(world)
    found = [g for g in goals if g.goal_id == "PARTICIPATE_BEAR"]
    assert len(found) == 1, [g.goal_id for g in goals]
    return found[0]


def test_the_lead_is_the_operators_t_minus_30_rung():
    assert BEAR_WAKE_LEAD_SECONDS == 30 * 60


def test_a_window_two_hours_out_names_the_t_minus_30_wake():
    goal = bear_ticket(seconds_to_start=7200)
    expected = (OBSERVED + timedelta(seconds=7200 - BEAR_WAKE_LEAD_SECONDS)).isoformat()
    assert goal.evidence["next_action_at"] == expected


def test_an_open_window_is_work_now_rather_than_a_wake():
    """It already carries remaining_seconds, so bear_phase answers ACTIVE and the agent acts."""
    goal = bear_ticket(remaining_seconds=834)
    assert "next_action_at" not in goal.evidence


def test_a_window_inside_the_lead_comes_back_at_once_rather_than_never():
    goal = bear_ticket(seconds_to_start=600)          # PREPARING
    assert goal.evidence["next_action_at"] == OBSERVED.isoformat()


def test_a_window_with_no_duration_does_not_invent_a_time():
    """DISCOVERED: nothing says when. §四 -- do not convert it into a visit to find out."""
    goal = bear_ticket(status="SCHEDULED")
    assert goal.evidence["phase"] == "DISCOVERED"
    assert "next_action_at" not in goal.evidence


def test_a_finished_window_has_no_wake():
    goal = bear_ticket(status="FINISHED", remaining_seconds=0)
    assert "next_action_at" not in goal.evidence


def test_a_zero_duration_is_not_a_wake():
    goal = bear_ticket(seconds_to_start=0)
    assert "next_action_at" not in goal.evidence


def test_the_wake_is_an_instant_and_the_naive_reservation_is_not_used_for_it():
    goal = bear_ticket(seconds_to_start=7200,
                       reserved_start_time="2026-09-27T20:30:00")   # naive, no offset
    wake = goal.evidence["next_action_at"]
    assert wake.endswith("+00:00") or wake.endswith("Z")
    # The naive stamp is carried as evidence and is NOT what produced the wake.
    assert goal.evidence["reserved_start_time"] == "2026-09-27T20:30:00"
    assert not wake.startswith("2026-09-27T20:30")
