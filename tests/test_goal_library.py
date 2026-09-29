import unittest

from winter_agent_v2.goal_library import GoalLibrary, GoalState, GoalStateStore, GoalStatus, deadline_pressure
from winter_agent_v2.models import Page, WorldState


class GoalLibraryTests(unittest.TestCase):
    def test_deadline_is_dynamic_and_expired_is_not_actionable(self):
        self.assertGreater(deadline_pressure(3600), deadline_pressure(7 * 3600))
        self.assertLess(deadline_pressure(0), 0)

    def test_discovers_intel_stamina_queues_event_and_verified_rewards(self):
        world = WorldState(
            page=Page.INTEL, intel={"status": "AVAILABLE", "stamina": 80, "refresh_seconds": 1800},
            stamina={"current": 80}, training={"queue_available": True}, research={"queue_available": False},
            events={"minimum_guarantee": {"points_missing": 100, "remaining_seconds": 3500, "available_skills": ["TRAIN_TROOPS"]}},
            rewards={"verified_claimable": ["VIP"], "skills": {"VIP": ["CLAIM_VIP_FREE"]}},
        )
        goals = {goal.goal_id: goal for goal in GoalLibrary().discover(world)}
        self.assertEqual(goals["CLEAR_INTEL"].status, GoalStatus.READY)
        self.assertEqual(goals["AVOID_STAMINA_WASTE"].status, GoalStatus.READY)
        self.assertEqual(goals["KEEP_TRAINING_PRODUCTIVE"].status, GoalStatus.READY)
        # ``research={"queue_available": False}`` is a *game condition*, not a completion: this read
        # BLOCKED from 2026-09-23, when §一 separated WAITING_GAME_CONDITION from COMPLETED.  Both are
        # unrankable, so the board's choice is unchanged; what the artifact now also carries is the
        # reason, which is what §六 asks for.
        self.assertEqual(goals["KEEP_RESEARCH_PRODUCTIVE"].status, GoalStatus.BLOCKED)
        self.assertEqual(goals["EVENT_MINIMUM_GUARANTEE"].evidence["points_missing"], 100)
        self.assertIn("CLAIM_FREE_VIP", goals)

    def test_best_ignores_complete_and_blocked(self):
        goals = (
            GoalState("DONE", GoalStatus.COMPLETE, reward_value=99999, available_skills=("X",)),
            GoalState("BLOCKED", GoalStatus.BLOCKED, reward_value=99999, available_skills=("Y",)),
            GoalState("READY", GoalStatus.READY, reward_value=1, available_skills=("Z",)),
        )
        self.assertEqual(GoalLibrary().best(goals).goal_id, "READY")

    def test_mobilization_goal_provider_is_live_role_scoped_and_reuses_existing_skill(self):
        world = WorldState(
            page=Page.HOME,
            events={"alliance_mobilization": {
                "recognized": True,
                "status": "ACTIVE",
                "role_id": "ROLE_B",
                "source": "LIVE_CLIENT_OCR",
                "remaining_seconds": 3600,
                "tasks": [{
                    "task_id": "task-17",
                    "task_type": "TROOP_TRAINING_120K",
                    "status": "IN_PROGRESS",
                    "accepted": True,
                    "progress": 40000,
                    "target": 120000,
                }],
            }},
        )

        wrong_role = GoalLibrary().discover(world, role_id="ROLE_A")
        assert not any(goal.goal_id == "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K"
                       for goal in wrong_role)

        goals = GoalLibrary().discover(world, role_id="ROLE_B")
        goal = next(item for item in goals
                    if item.goal_id == "ALLIANCE_MOBILIZATION_TROOP_TRAINING_120K")
        assert goal.status is GoalStatus.READY
        assert goal.available_skills == ("TRAIN_TROOPS",)
        assert goal.evidence["role_id"] == "ROLE_B"
        assert goal.evidence["task_id"] == "task-17"
        assert goal.evidence["shared_credit_tags"] == ["ALLIANCE_MOBILIZATION"]

        # A preview or an unaccepted offer remains visible as UNKNOWN and cannot
        # be scheduled until the live client confirms task acceptance.
        waiting_world = WorldState(
            page=Page.HOME,
            events={"alliance_mobilization": {
                "recognized": True, "status": "ACTIVE", "role_id": "ROLE_B",
                "tasks": [{"task_id": "task-18", "task_type": "LARGE_GATHER",
                           "status": "AVAILABLE", "accepted": False}],
            }},
        )
        waiting = next(item for item in GoalLibrary().discover(waiting_world, role_id="ROLE_B")
                       if item.goal_id == "ALLIANCE_MOBILIZATION_LARGE_GATHER")
        assert waiting.status is GoalStatus.UNKNOWN
        assert waiting.available_skills == ()

    def test_goal_snapshot_is_atomic_and_serializable(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import json
        with TemporaryDirectory() as folder:
            path = Path(folder) / "goal_state.json"
            world = WorldState(page=Page.INTEL, intel={"status":"AVAILABLE"}, confidence=.9)
            GoalStateStore(path).write(world, GoalLibrary().discover(world))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["page"], "INTEL")
            self.assertEqual(payload["goals"][0]["status"], "READY")
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
