import json
from pathlib import Path

from winter_agent_v2.skills import v2_registry


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
