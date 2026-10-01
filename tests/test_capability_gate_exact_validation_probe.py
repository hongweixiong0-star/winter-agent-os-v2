from datetime import datetime, timedelta, timezone

import pytest

from winter_agent_v2.capability_gate import (
    BLOCKED, COOLDOWN, DEVELOPMENT_PENDING, SOURCE_NO_PROGRESS, SOURCE_QUEUE,
    CapabilityGate,
)
from winter_agent_v2.goal_library import GoalComposition, GoalState, GoalStatus


NOW = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
CAMP = "MARKSMAN_CAMP_TRAINING"


def _goal(goal_id=CAMP):
    return GoalState(goal_id, GoalStatus.READY, available_skills=("OPEN_QUICK_PANEL",))


def _gate(**kwargs):
    return CapabilityGate(streaks={
        CAMP: (3, NOW - timedelta(minutes=1), "TAP_FOCUSED_TRAINING_CAMP_MARKSMAN", (0, 0, 3)),
    }, **kwargs)


def test_production_still_defers_recent_no_progress():
    blocked = _gate().blocks(_goal(), now=NOW)

    assert blocked is not None
    assert blocked.source == SOURCE_NO_PROGRESS


def test_exact_validation_goal_can_reobserve_despite_old_no_progress():
    assert _gate().blocks(
        _goal(), now=NOW, validation_goal_id=CAMP,
    ) is None


def test_validation_of_another_goal_cannot_unblock_this_camp():
    blocked = _gate().blocks(
        _goal(), now=NOW, validation_goal_id="SHIELD_CAMP_TRAINING",
    )

    assert blocked is not None
    assert blocked.source == SOURCE_NO_PROGRESS


def test_exact_validation_does_not_erase_the_production_streak():
    gate = _gate()

    assert gate.blocks(_goal(), now=NOW, validation_goal_id=CAMP) is None
    assert gate.blocks(_goal(), now=NOW).source == SOURCE_NO_PROGRESS
    assert gate.streaks[CAMP][0] == 3


@pytest.mark.parametrize("state", [BLOCKED, COOLDOWN, DEVELOPMENT_PENDING])
def test_exact_validation_preserves_capability_queue_blockers(state):
    gate = _gate(
        compositions={CAMP: GoalComposition(CAMP, "SEQUENCE", ("TRAIN_TROOPS",))},
        capabilities={"TRAIN_TROOPS": (state, "existing blocker", NOW + timedelta(hours=1))},
    )

    blocked = gate.blocks(_goal(), now=NOW, validation_goal_id=CAMP)

    assert blocked is not None
    assert blocked.source == SOURCE_QUEUE
    assert blocked.state == state


def test_exact_validation_does_not_bypass_a_pending_reload():
    blocked = _gate(reload_pending=True).blocks(
        _goal(), now=NOW, validation_goal_id=CAMP,
    )

    assert blocked is not None
    assert blocked.source == SOURCE_NO_PROGRESS
    assert "runtime reload is pending" in blocked.reason
