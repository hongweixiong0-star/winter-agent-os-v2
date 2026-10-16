import json
from pathlib import Path

from winter_agent_v2.goal_library import GoalState, GoalStateStore, GoalStatus
from winter_agent_v2.models import Page, WorldState


def _goal(goal_id: str) -> GoalState:
    return GoalState(
        goal_id=goal_id,
        status=GoalStatus.READY,
        reward_value=100,
        available_skills=("DAILY_CLAIM_REWARDS",),
    )


def test_goal_board_keeps_role_snapshots_separate_and_preserves_legacy_active_board(tmp_path: Path):
    path = tmp_path / "goal_state.json"
    store = GoalStateStore(path)

    store.write(WorldState(page=Page.HOME, confidence=0.9), (_goal("ROLE_A_REWARD"),), role_id="A")
    store.write(WorldState(page=Page.DAILY, confidence=0.8), (_goal("ROLE_B_DAILY"),), role_id="B")
    store.write(WorldState(page=Page.MAIL, confidence=0.95), (_goal("ROLE_A_MAIL"),), role_id="A")

    roles = store.read_roles()
    active = json.loads(path.read_text(encoding="utf-8"))

    assert set(roles) == {"A", "B"}
    assert [row["goal_id"] for row in roles["A"]["goals"]] == ["ROLE_A_MAIL"]
    assert [row["goal_id"] for row in roles["B"]["goals"]] == ["ROLE_B_DAILY"]
    assert active["active_role_id"] == "A"
    assert [row["goal_id"] for row in active["goals"]] == ["ROLE_A_MAIL"]
