"""A goal whose meter is a constant can never report progress, and that is measurable.

``progress_moved`` -- the function that writes ``goal_progress_by_id`` -- compares one
number and nothing else::

    return now.distance < previous          # goal_library.py:2429

Measured over the whole production ledger, the goals that have ever reported
``goal_progress == True``:

    1366  DISCOVER_EVENT_CALENDAR
      54  CLAIM_EXPLORATION_IDLE
      53  AVOID_STAMINA_WASTE
      16  MAIL_ROUTINE
      13  DAILY_ACTIVITY_TARGET
       9  MARKSMAN_CAMP_TRAINING
       7  LANCER_CAMP_TRAINING
       6  SHIELD_CAMP_TRAINING
        0  every SCHEDULED_* goal

So the metric works -- it is not broken everywhere -- and one whole goal family is
structurally excluded from it.  Both ``_append_scheduled_activities`` branches build their
rows with a literal ``distance=1.0`` (``goal_library.py:2017`` and ``:2053``), so
``1.0 < 1.0`` is False forever.  Fifty production episodes on the new revisions carry
``goal_progress_by_id {"SCHEDULED_...": false}`` and ``goal_progress False``, and the honest
reading of each is "the action landed, the goal did not move" -- which is true, and which
was equally true before the change, because the number cannot express anything else.

Why this matters beyond the number itself: ``no_progress_streak`` is incremented on every
``False`` (``runtime.py:9734``) and feeds the fairness bonus in ``goal_utility``.  A goal
that is *structurally* unable to report progress therefore gets progressively demoted for
the one thing it is not to blame for.  The 66 ticket-driven selections measured on
2026-10-02 are what that looks like.

What this test does **not** do is hand the family a flattering meter.  Distance is a
navigation cost, and inventing one (say, 0.0, or a countdown) to make the field move would
be fabricating a measurement -- the same mistake the calendar reader avoided by refusing to
turn a preview into a battle clock.  These tests pin the two facts that are honest:

* the current state is a constant, and a constant reports "no progress" forever;
* the reading that actually distinguishes these rows -- ``calendar_observation`` appearing,
  ``availability_state`` leaving ``AWAITING_LIVE_CLIENT_READING`` -- is present in the
    evidence and is the thing a meter for this family would have to be built from.

The fix belongs where the reading is produced, not here.  What this file protects is that
nobody "solves" the flat meter by editing a number.
"""

from winter_agent_v2.goal_library import GoalLibrary, progress_moved
from winter_agent_v2.models import Page, WorldState

ROLE = "1061663148"


def _rows():
    return [
        ("ICEBOUND_TREASURE", "冰封的宝藏"),
        ("ICEBOUND_TREASURE_TRAINING", "寻宝特训"),
        ("CANYON_CLASH", "峡谷会战"),
    ]


def _snapshot(entries):
    return {
        "observed_at": "2026-10-02T05:58:27+00:00", "role_id": ROLE,
        "entries": [
            {"event_id": event_id, "display_name": name, "title_confidence": 0.99,
             "title_registered": True, "calendar_date_raw": "10/02",
             "tap_norm": [0.5, 0.4], "details_observed": True,
             "occurrence_key": f"{event_id}|10/02|10/06"}
            for event_id, name in entries
        ],
    }


def _scheduled_goals(entries):
    goals = GoalLibrary().discover(
        WorldState(page=Page.EVENT), role_id=ROLE, calendar_snapshot=_snapshot(entries),
    )
    return [g for g in goals if str(g.goal_id).startswith("SCHEDULED_")]


def test_every_scheduled_row_carries_the_same_distance():
    """The measurement, stated as a fact about the current code.

    Not a complaint about it: a constant is the honest value for a row the system cannot
    measure yet.  What matters is the consequence, which the next test pins.
    """
    goals = _scheduled_goals(_rows())
    assert goals, "the family must exist for this measurement to mean anything"
    assert {g.distance for g in goals} == {1.0}


def test_a_constant_meter_can_never_report_progress():
    """``1.0 < 1.0`` is False on every step, for every row, forever.

    This is the defect in one line, asserted through the public function so the fix cannot
    be a private helper nobody calls.  The remembered value is seeded the way the old writer
    seeded it -- the literal ``distance`` -- and the answer must be ``None`` rather than
    ``True``: a number written by the distance meter is not comparable with an observation
    reading, and "not measured" is the answer the caller already documents as distinct from
    "no progress".
    """
    goals = _scheduled_goals(_rows())
    observed = {g.goal_id: g.distance for g in goals}
    after = _scheduled_goals(_rows())
    verdicts = {g.goal_id: progress_moved(observed, after, g.goal_id) for g in after}
    assert set(verdicts.values()) == {None}, (
        f"a remembered navigation distance must not be compared with an observation rank, "
        f"got {verdicts}"
    )


def test_an_unchanged_observation_reading_is_not_progress():
    """The like-for-like case: same rank before and after answers False, not True.

    This is the check the first version of the scale guard failed.  It tested membership of
    a rank set, and a navigation distance of 1.0 is inside ``{0.0, 0.5, 1.0}`` -- so a run
    that read these goals before the meter existed had every one of them reported as progress
    on its very first step.  Found by running it, not by reading it.
    """
    from winter_agent_v2.goal_library import _METER_KINDS, _meter_for, meter_kind

    goals = _scheduled_goals(_rows())
    observed = {}
    for g in goals:
        observed[g.goal_id] = _meter_for(g)
        _METER_KINDS[g.goal_id] = meter_kind(g)
    try:
        after = _scheduled_goals(_rows())
        verdicts = {g.goal_id: progress_moved(observed, after, g.goal_id) for g in after}
        assert set(verdicts.values()) == {False}, (
            f"an unchanged reading must not report progress, got {verdicts}"
        )
    finally:
        for goal_id in list(_METER_KINDS):
            if goal_id.startswith("SCHEDULED_"):
                _METER_KINDS.pop(goal_id, None)



def test_the_meter_changes_when_the_client_actually_answers():
    """The fix, as the ledger will see it.

    Seeded with the state a run has when the activity has been advertised but never read;
    the same goal, re-read after the calendar or the live page supplied a reading, moves
    from "not seen" to "seen".  That is a real state change produced by a current-frame
    reader, which is the only thing allowed to produce one.
    """
    unseen = _scheduled_goals([("ICEBOUND_TREASURE", "冰封的宝藏")])
    target = next(g for g in unseen if g.goal_id == "SCHEDULED_CANYON_CLASH")
    assert target.evidence.get("calendar_observation") is None

    from winter_agent_v2.goal_library import _METER_KINDS, _meter_for, meter_kind

    before = {"SCHEDULED_CANYON_CLASH": _meter_for(target)}
    assert before["SCHEDULED_CANYON_CLASH"] == 0.0, "advertised but never read"
    _METER_KINDS["SCHEDULED_CANYON_CLASH"] = meter_kind(target)
    try:
        seen = next(g for g in _scheduled_goals(
            [("CANYON_CLASH", "峡谷会战"), ("ICEBOUND_TREASURE", "冰封的宝藏")]
        ) if g.goal_id == "SCHEDULED_CANYON_CLASH")
        assert seen.evidence.get("calendar_observation") is not None

        after = _scheduled_goals(
            [("CANYON_CLASH", "峡谷会战"), ("ICEBOUND_TREASURE", "冰封的宝藏")]
        )
        assert progress_moved(before, after, "SCHEDULED_CANYON_CLASH") is True, (
            "being read for the first time is progress on a goal whose whole purpose is to "
            "be read; reporting False here is what demoted it 66 times in a day"
        )
    finally:
        _METER_KINDS.pop("SCHEDULED_CANYON_CLASH", None)


def test_a_goal_with_its_own_meter_is_untouched_by_the_new_reading():
    """The control group, and the reason the fix is scoped to one family.

    ``_meter_for`` falls back to ``distance`` for everything else, so a goal with a working
    distance keeps being measured by it.  If this fails, a second family has been drawn into
    a rule written for the first.
    """
    from winter_agent_v2.goal_library import _meter_for

    class _G:
        goal_id = "SOMETHING_ELSE"
        distance = 0.7
        evidence = {"availability_state": "AWAITING_LIVE_CLIENT_READING"}

    assert _meter_for(_G()) == 0.7
    assert progress_moved({"SOMETHING_ELSE": 0.9}, [_G()], "SOMETHING_ELSE") is True
    assert progress_moved({"SOMETHING_ELSE": 0.1}, [_G()], "SOMETHING_ELSE") is False



def test_the_reading_that_would_distinguish_them_is_in_the_evidence():
    """What a real meter would be built from, and it already exists.

    ``calendar_observation`` is the difference between "this activity is a name in a
    registry" and "this activity was seen on the client".  The strip work in 9f468b3 and
    2ee4908 produces exactly this, and ``goal_library`` already merges it into the row --
    so the information needed for progress is present and simply not wired to the meter.

    The comparison is between a row the calendar never showed and one it did.  It has to be
    two separate calls because ``_append_scheduled_activities`` looks the row up by
    ``event_id``, so an activity absent from the snapshot is precisely the one whose
    ``calendar_observation`` is ``None`` -- which is what makes the two states
    distinguishable at all.
    """
    unseen = {g.goal_id: g for g in _scheduled_goals([("ICEBOUND_TREASURE", "冰封的宝藏")])}
    absent_row = unseen["SCHEDULED_CANYON_CLASH"]
    assert absent_row.evidence.get("calendar_observation") is None, (
        "an activity the calendar never showed is the one with nothing to compare"
    )
    assert absent_row.evidence.get("availability_state") == "AWAITING_LIVE_CLIENT_READING"

    seen = {
        g.goal_id: g for g in _scheduled_goals([
            ("CANYON_CLASH", "峡谷会战"), ("ICEBOUND_TREASURE", "冰封的宝藏"),
        ])
    }
    seen_row = seen["SCHEDULED_CANYON_CLASH"]
    assert seen_row.evidence.get("calendar_observation") is not None, (
        "once the activity has been seen, the evidence says so -- this is the state change "
        "a progress meter for this family would compare"
    )
    # Same goal id, same status, same distance: the only thing that moved is the reading.
    assert seen_row.goal_id == absent_row.goal_id
    assert seen_row.status is absent_row.status
    assert seen_row.distance == absent_row.distance


def test_progress_moved_still_works_for_a_goal_with_a_moving_meter():
    """The control group: the metric itself is not broken, and must stay working.

    If this ever fails, the problem is in ``progress_moved`` rather than in the family that
    cannot feed it, and the fix belongs one layer down.
    """
    before = [type("G", (), {"goal_id": "X", "distance": 0.9})()]
    after = [type("G", (), {"goal_id": "X", "distance": 0.4})()]
    assert progress_moved({"X": 0.9}, after, "X") is True
    assert progress_moved({"X": 0.9}, before, "X") is False
    assert progress_moved({}, after, "X") is None
