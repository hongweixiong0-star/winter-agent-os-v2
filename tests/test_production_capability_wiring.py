import json
from pathlib import Path

from winter_agent_v2.skills import v2_registry
from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS, SkillFactory
from winter_agent_v2.goal_library import GoalLibrary, ROUTE_DOMAINS, route_for
from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.rally import RallyTarget, rally_target_for_goal
from winter_agent_v2.session_adapters import route_for as session_route_for


def _goals():
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "knowledge/goals/goal_capability_map.json").read_text(encoding="utf-8"))["goals"]


def test_stamina_rally_supports_active_start_and_existing_join():
    rally = next(c for c in _goals()["AVOID_STAMINA_WASTE"]["capabilities"]
                 if c["capability"] == "SPEND_STAMINA_ON_RALLY")
    assert rally["alternatives"] == ["START_RALLY", "JOIN_RALLY"]


def test_bear_start_and_join_are_one_alternative_not_two_required_capabilities():
    entries = _goals()["PARTICIPATE_BEAR"]["capabilities"]
    participating = [c for c in entries if "START_RALLY" in c["alternatives"]
                     or "JOIN_RALLY" in c["alternatives"]]
    assert len(participating) == 1
    assert set(participating[0]["alternatives"]) == {"START_RALLY", "JOIN_RALLY"}


def test_fishing_goal_only_maps_to_registered_normal_play():
    entries = _goals()["USE_NORMAL_FISHING_BAIT"]["capabilities"]
    assert len(entries) == 1
    assert entries[0]["alternatives"] == ["PLAY_NORMAL_FISHING_LEVEL"]
    assert v2_registry().get("PLAY_NORMAL_FISHING_LEVEL") is not None


def test_coverage_has_no_retired_polar_skill_and_does_not_require_both_bear_variants(tmp_path):
    assert 'JOIN_POLAR_TERROR_RALLY' not in GOAL_REQUIREMENTS['AVOID_STAMINA_WASTE']
    assert 'PLAY_NORMAL_FISHING_LEVEL' in GOAL_REQUIREMENTS['USE_NORMAL_FISHING_BAIT']
    requirements = SkillFactory(v2_registry(), tmp_path).coverage_requirements()
    assert len({'START_RALLY', 'JOIN_RALLY'}.intersection(requirements['PARTICIPATE_BEAR'])) == 1


def test_building_entry_uses_current_registered_navigation():
    cap = _goals()['KEEP_BUILDING_PRODUCTIVE']['capabilities'][0]
    assert 'OPEN_BUILDING' not in cap['alternatives']
    assert all(v2_registry().get(s) for s in cap['alternatives'])


def test_mobilization_icefield_goal_reuses_active_polar_route_with_explicit_target():
    world = WorldState(page=Page.HOME, events={'alliance_mobilization': {
        'recognized': True, 'status': 'ACTIVE', 'role_id': 'B',
        'tasks': [{'task_id': 'polar-1', 'task_type': 'ICEFIELD_BEAST',
                   'accepted': True, 'status': 'IN_PROGRESS', 'progress': 0, 'target': 1}]}})
    goal = next(g for g in GoalLibrary().discover(world, role_id='B')
                if g.goal_id == 'ALLIANCE_MOBILIZATION_ICEFIELD_BEAST')
    assert goal.evidence['rally_target'] == 'POLAR_TERROR'
    assert rally_target_for_goal(goal.goal_id, goal.evidence) is RallyTarget.POLAR_TERROR
    assert route_for(goal.goal_id) == 'GIANT_BEAST'
    assert route_for(goal.goal_id) in ROUTE_DOMAINS
    assert route_for('GIANT_BEAST') == 'GIANT_BEAST'
    brain = RuleBrain()
    brain.current_goal = route_for(goal.goal_id)
    brain.goal_id = goal.goal_id
    assert brain.decide(WorldState(page=Page.MAP), v2_registry()).skill == 'START_RALLY'
    assert session_route_for(goal.goal_id, 'START_RALLY').adapter == 'bear'
    assert goal.goal_id in _goals()


def test_training_commit_keeps_existing_atomic_queue_started_verifier():
    # Real 2026-09-30 episodes: the old session replaced TRAIN_TROOPS with
    # TAP_FOCUSED_* while already on Page.TRAINING, so no queue was started.
    for goal in ('SHIELD_CAMP_TRAINING', 'LANCER_CAMP_TRAINING',
                 'MARKSMAN_CAMP_TRAINING', 'KEEP_TRAINING_PRODUCTIVE'):
        assert session_route_for(goal, 'TRAIN_TROOPS') is None
        assert session_route_for(goal, 'SELECT_TRAINING_CAMP') is None
    for camp in ('SHIELD', 'LANCER', 'MARKSMAN'):
        assert session_route_for(f'{camp}_CAMP_TRAINING', f'TAP_FOCUSED_TRAINING_CAMP_{camp}') is None
