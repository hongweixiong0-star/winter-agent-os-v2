import json
from pathlib import Path

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.resource_rotation import ResourceRotationStore
from winter_agent_v2.skills import v2_registry


def test_persistent_four_resource_round_robin(tmp_path: Path) -> None:
    store = ResourceRotationStore(tmp_path / "rotation.json")
    assert store.target() == "MEAT"
    store.completed("MEAT")
    assert store.target() == "WOOD"
    store.completed("WOOD")
    assert store.target() == "COAL"
    store.completed("COAL")
    assert store.target() == "IRON"
    payload = json.loads((tmp_path / "rotation.json").read_text(encoding="utf-8"))
    assert payload["dispatched"] == {"MEAT": 1, "WOOD": 1, "COAL": 1, "IRON": 0}


def test_auto_discovery_preserves_stamina_march_slot() -> None:
    state = WorldState(page=Page.MAP, march_used=5, march_max=6, confidence=0.99)
    decision = RuleBrain(current_goal=None, reserve_marches=1).decide(state, v2_registry())
    assert decision.reason == "reserved_march_for_stamina"
