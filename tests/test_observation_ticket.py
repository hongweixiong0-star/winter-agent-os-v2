"""An UNKNOWN goal that says what it is waiting to learn must not vanish from the board.

Operator directive 2026-10-02 §5 ("启用Goal → UNKNOWN → priority=-inf → 永远没人再看" is
forbidden) and §11 (a goal's value must not be decided by whether a skill happens to exist).

Measured 2026-10-02 before this existed, by ``tools/invariant_review.py``:
NO_PERMANENT_UNKNOWN_BLACKHOLE = FAIL, HIGH_VALUE_UNKNOWN_NOT_STARVED = FAIL, and the §17
simulated world selected one goal out of five for a role whose work was entirely UNKNOWN.

The gate is deliberately **not** "every unknown gets a seat".  It is "an unknown that has
declared ``required_observation`` gets a seat" -- which is §5's second half, that a goal may
stay unreachable only while the system can say what it is waiting to learn.  A goal that has
declared nothing keeps the old ``-inf`` behaviour, and so does every status that observation
cannot change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import GoalState, GoalStatus  # noqa: E402
from winter_agent_v2.goal_utility import (  # noqa: E402
    OBSERVATION_TICKET_CEILING, observation_ticket, rank, utility,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402

HOME = WorldState(page=Page.HOME)


def _unknown(goal_id: str, value: float, *, observe: bool = True) -> GoalState:
    evidence = {"required_observation": "live state"} if observe else {}
    return GoalState(goal_id, GoalStatus.UNKNOWN, reward_value=value, daily_loss=value,
                     evidence=evidence)


def _known(goal_id: str, value: float) -> GoalState:
    return GoalState(goal_id, GoalStatus.READY, reward_value=value, available_skills=("S",))


def test_an_unknown_with_something_to_observe_stays_on_the_board() -> None:
    board = [_unknown("U", 1200), _known("K", 250)]

    assert "U" in [g.goal_id for g, _ in rank(board, world=HOME)]


def test_an_unknown_with_nothing_to_observe_is_still_not_offered() -> None:
    """The ticket is not a blanket amnesty: silence buys nothing."""
    assert rank([_unknown("SILENT", 1200, observe=False)], world=HOME) == ()


@pytest.mark.parametrize("status", [GoalStatus.COMPLETE, GoalStatus.BLOCKED,
                                    GoalStatus.SCHEDULED_NOT_OPEN, GoalStatus.EXPIRED])
def test_statuses_observation_cannot_change_keep_their_infinite_price(status) -> None:
    goal = GoalState("S", status, reward_value=1200,
                     evidence={"required_observation": "live state", "condition": "not now"})

    assert observation_ticket(goal) == 0.0
    assert utility(goal).base == float("-inf")


def test_the_ticket_is_bounded_and_scales_with_value() -> None:
    assert observation_ticket(_unknown("HUGE", 100_000)) == OBSERVATION_TICKET_CEILING
    assert observation_ticket(_unknown("SMALL", 100)) < observation_ticket(_unknown("BIG", 900))


def test_a_ticked_goal_does_not_hold_the_head_of_the_board_forever() -> None:
    """§9 STARVATION_FREE: the constant ticket must rotate, or routine work never runs again."""
    from datetime import datetime, timedelta, timezone

    from winter_agent_v2.goal_utility import GoalFairness

    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    ledger = {
        "TICKETED": GoalFairness(goal_id="TICKETED", last_selected_at=now.isoformat()),
        "ROUTINE": GoalFairness(goal_id="ROUTINE",
                                last_selected_at=(now - timedelta(hours=3)).isoformat()),
    }
    ranked = [g.goal_id for g, _ in rank([_unknown("TICKETED", 5000), _known("ROUTINE", 250)],
                                         world=HOME, ledger=ledger, now=now)]

    assert ranked[0] == "ROUTINE", (
        "a ticketed UNKNOWN outranked work that has been waiting for hours; the board would "
        "starve routine work on a constant"
    )
