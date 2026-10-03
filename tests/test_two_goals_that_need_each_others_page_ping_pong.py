"""Two goals that each need the other's page will ping-pong forever, and the ranking is why.

Measured 2026-10-03 on the production ledger, after ``e86d1b2`` went live.  Twenty-four
consecutive steps, all of them navigation, all ``SUCCESS``, and **all of them
``goal_progress=False``**:

    HOME -> MAP   OPEN_MAP   CLEAR_INTEL              intel_goal_requires_map
    MAP  -> HOME  OPEN_HOME  KEEP_BUILDING_PRODUCTIVE  building_goal_requires_home
    ... twelve identical round trips

Not caused by the four fixes in flight: the same pairing appears under every deployed revision
since ``d9103948`` on 2026-10-01 (64 / 28 / 24 / 24 / 15 / 13 / 12 / 11 occurrences per
revision), so it has been running for three days.

Why the ranking alternates
--------------------------
Reproduced by running the real ``GoalLibrary.discover`` and the real ``goal_utility.rank`` on
the exact ``state_before`` the ledger recorded:

    page=HOME   MAIL_ROUTINE 240.00 | KEEP_TRAINING / CLEAR_INTEL / KEEP_RESEARCH /
                             KEEP_BUILDING / DAILY / CLAIM_EXPLORATION  all 180.00, distance 1.0
    page=MAP    the same six, all 180.00, distance 1.0

Six goals with an identical ``total`` **and an identical ``distance``**.  ``rank`` breaks that
tie on board order (``scored.sort(key=(item[0], item[1]))``), and board order shifts by one
position between the two pages -- so the tie is broken differently on each page.

What makes it a *loop* rather than a wobble is the fairness term.  ``fairness_bonus`` pays for
minutes since ``last_selected_at`` and saturates at ``FAIRNESS_AGE_BONUS = 100`` after
``FAIRNESS_OVERDUE_MINUTES = 30``; these goals were last selected on 2026-09-30, so:

    CLEAR_INTEL                 waited 4329 min -> 99.31
    KEEP_BUILDING_PRODUCTIVE    waited 4135 min -> 99.28
    KEEP_TRAINING_PRODUCTIVE    waited 3673 min -> 99.19
    MAIL_ROUTINE                waited 4990 min -> 99.40

Every starved goal sits between 99.19 and 99.40.  **The term has stopped discriminating while
still deciding the winner**, and the differences it does produce are smaller than the gap it is
meant to express.  Choosing one resets its ``last_selected_at`` to now, its bonus to 0, and
hands the next step to whoever has waited longest -- which is the other one, because both are
equally starved.  That is the oscillator.

This file names the shape and pins the numbers.  It deliberately does not propose a price
change: raising these goals' totals would lift them above goals that can actually do work on
the page they are standing on, which is the same "re-pricing cannot fix a structural problem"
result the training chain produced on 2026-10-03.
"""

import datetime

import pytest

from winter_agent_v2.goal_utility import (
    FAIRNESS_AGE_BONUS,
    FAIRNESS_OVERDUE_MINUTES,
    GoalFairness,
    fairness_bonus,
)

STARVED = {
    # goal_id: (days since last selected, bonus measured on 2026-10-03)
    "CLEAR_INTEL": (3, 99.31),
    "KEEP_BUILDING_PRODUCTIVE": (3, 99.28),
    "KEEP_TRAINING_PRODUCTIVE": (3, 99.19),
    "MAIL_ROUTINE": (4, 99.40),
}


def _row(goal_id, days):
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return GoalFairness(
        goal_id=goal_id,
        last_selected_at=moment.isoformat(),
        offered=1000, selected=500, no_progress_streak=700,
    )


@pytest.mark.parametrize("goal_id", sorted(STARVED))
def test_every_starved_goal_sits_at_the_ceiling(goal_id):
    """The term has saturated: 3to 4 days of waiting all read as "99 out of 100".

    This is the measurement that makes the loop legible.  If this stops being true -- say the
    bonus grows again with age -- the oscillation it enables cannot happen this way.
    """
    _, measured = STARVED[goal_id]
    now = datetime.datetime.now(datetime.timezone.utc)
    assert fairness_bonus(_row(goal_id, STARVED[goal_id][0]), None, now=now) == pytest.approx(
        measured, abs=0.15
    ), f"{goal_id} read {measured}, expected the saturated range"
    assert measured >= FAIRNESS_AGE_BONUS * 0.99, (
        "every goal here is at the ceiling; that is the whole problem, not a detail of the value"
    )


def test_the_term_cannot_separate_the_goals_that_are_actually_competing():
    """The gap the term produces is smaller than the gap it is meant to express.

    ``total`` differences between these goals are 0.0.  The fairness spread across all four is
    0.21, and between the two that alternate it is 0.03.  So the winner of a "tie" is decided by
    a rounding-scale difference that grows purely from having been picked.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    bonuses = {
        goal_id: fairness_bonus(_row(goal_id, days), None, now=now)
        for goal_id, (days, _) in STARVED.items()
    }
    alternating = bonuses["CLEAR_INTEL"] - bonuses["KEEP_BUILDING_PRODUCTIVE"]
    spread = max(bonuses.values()) - min(bonuses.values())
    assert spread < 0.5, f"four starved goals span {spread:.2f} of a {FAIRNESS_AGE_BONUS} scale"
    assert abs(alternating) < 0.2, (
        "the two that alternate are separated by a rounding-scale difference; picking one resets "
        "its clock to zero and hands the step to the other, which is the oscillator"
    )


def test_a_goal_that_was_just_picked_loses_the_bonus_entirely():
    """The half of the loop that closes it, stated directly.

    After the step the winner's ``last_selected_at`` is now, so its bonus is 0 while the other
    is still near the ceiling.  That inversion is not a bug in the term -- §四.6/§八E wants a
    starved goal to win -- it is what makes two equally starved goals take turns.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    just_picked = fairness_bonus(_row("CLEAR_INTEL", 0), None, now=now)
    other = fairness_bonus(_row("KEEP_BUILDING_PRODUCTIVE", 3), None, now=now)
    assert just_picked == 0.0
    assert other > 99.0
    assert other - just_picked > 50.0


def test_the_saturation_threshold_is_far_shorter_than_the_wait():
    """Why nothing here is ever comparable again: 30 minutes to saturate, days to wait.

    Once ``FAIRNESS_OVERDUE_MINUTES`` is passed the bonus is 100 * overdue/(1+overdue), which
    approaches 100 without ever arriving.  A goal waiting three days scores 99.31 and one
    waiting four days scores 99.40 -- the curve is nearly flat exactly where the population
    lives.
    """
    assert FAIRNESS_OVERDUE_MINUTES == 30.0
    assert FAIRNESS_AGE_BONUS == 100.0
    now = datetime.datetime.now(datetime.timezone.utc)
    three_days = fairness_bonus(_row("X", 3), None, now=now)
    six_days = fairness_bonus(_row("X", 6), None, now=now)
    assert six_days - three_days < 1.0, (
        "doubling the wait buys almost nothing, so 'waited longer' stops meaning anything here"
    )