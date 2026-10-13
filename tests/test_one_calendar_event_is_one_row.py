# -*- coding: utf-8 -*-
"""One calendar event must be one row on the Goal board.

Operator report, 2026-10-10: the board listed 英雄集结 twice.  Traced to two places, and only the
second one is fixed here:

* the **upstream** cause is real and is left alone: ``learning/event_schedule_state.json``'s
  ``CALENDAR_GRID`` observation holds **6 entries of which 2 carry the same**
  ``event_id`` (``DISCOVERED_EVENT_6F33C054CA``, in both role scopes).  Two grid rows really did
  carry that id, so it is evidence about the scanner and must not be erased here.
* the **board** cause is this loop: ``_append_known_activities``' second pass dedups against
  ``static_ids`` and ``reported``, and neither can see its own earlier appends -- so an id offered
  twice became two ``GoalState`` records.

The guard therefore registers each append as it happens.  A guard that only reads a set computed
before the loop passes the two-row case and fails the three-row one, which is why case 2 exists.
"""
from __future__ import annotations

from winter_agent_v2.goal_library import GoalLibrary

SYNTHETIC = "DISCOVERED_EVENT_TESTONLY0001"


def _row(event_id: str, name: str = "测试活动") -> dict:
    return {"event_id": event_id, "display_name": name, "details_observed": False}


def _scheduled_ids(goals) -> list[str]:
    return [str(goal.goal_id) for goal in goals if str(goal.goal_id).startswith("SCHEDULED_")]


def test_an_event_offered_twice_becomes_one_row():
    goals: list = []
    GoalLibrary._append_known_activities(
        goals, calendar_snapshot={"entries": [_row(SYNTHETIC), _row(SYNTHETIC)]},
    )
    assert _scheduled_ids(goals).count(f"SCHEDULED_{SYNTHETIC}") == 1


def test_an_event_offered_three_times_still_becomes_one_row():
    """The case a set computed before the loop cannot catch."""
    goals: list = []
    GoalLibrary._append_known_activities(
        goals, calendar_snapshot={"entries": [_row(SYNTHETIC), _row(SYNTHETIC), _row(SYNTHETIC)]},
    )
    assert _scheduled_ids(goals).count(f"SCHEDULED_{SYNTHETIC}") == 1


def test_two_different_events_are_still_two_rows():
    """The guard must not over-dedup: distinct events are distinct work."""
    other = "DISCOVERED_EVENT_TESTONLY0002"
    goals: list = []
    GoalLibrary._append_known_activities(
        goals, calendar_snapshot={"entries": [_row(SYNTHETIC), _row(other, "另一个活动")]},
    )
    ids = _scheduled_ids(goals)
    assert ids.count(f"SCHEDULED_{SYNTHETIC}") == 1
    assert ids.count(f"SCHEDULED_{other}") == 1


def test_no_scheduled_goal_id_is_ever_repeated():
    """The property, stated once, over a snapshot that mixes duplicates and distinct events."""
    other = "DISCOVERED_EVENT_TESTONLY0002"
    goals: list = []
    GoalLibrary._append_known_activities(goals, calendar_snapshot={"entries": [
        _row(SYNTHETIC), _row(other), _row(SYNTHETIC), _row(other), _row(SYNTHETIC),
    ]})
    ids = _scheduled_ids(goals)
    assert len(ids) == len(set(ids)), f"duplicate rows on the board: {ids}"
