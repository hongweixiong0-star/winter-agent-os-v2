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


class TestUnavailableResourceDoesNotLivelock:
    """A resource with no node in range must not be selected forever.

    Measured live on 2026-09-14: MEAT completed the whole gather chain while WOOD
    returned ``RESOURCE_NOT_FOUND`` at every level from 1 to 8.  Because the
    rotation only advanced on a successful dispatch, it kept asking for WOOD and
    the goal could never progress — a livelock, not a slow path.
    """

    def test_unavailable_resource_is_skipped_and_retried_later(self, tmp_path: Path) -> None:
        store = ResourceRotationStore(tmp_path / "rotation.json", unavailable_ttl_seconds=3600)
        assert store.target() == "MEAT"
        store.completed("MEAT")
        assert store.target() == "WOOD"

        # The client reports no WOOD node in range.
        store.unavailable("WOOD")
        assert store.target() == "COAL", "an unavailable resource must not be selected again"
        store.completed("COAL")
        assert store.target() == "IRON"

    def test_all_resources_unavailable_falls_back_instead_of_deadlocking(self, tmp_path: Path) -> None:
        store = ResourceRotationStore(tmp_path / "rotation.json", unavailable_ttl_seconds=3600)
        for name in ("MEAT", "WOOD", "COAL", "IRON"):
            store.unavailable(name)
        # Excluding everything must degrade to the full set rather than raise.
        assert store.target() in {"MEAT", "WOOD", "COAL", "IRON"}

    def test_expired_cooldown_is_retried(self, tmp_path: Path) -> None:
        store = ResourceRotationStore(tmp_path / "rotation.json", unavailable_ttl_seconds=0)
        store.unavailable("MEAT")
        assert store.target() == "MEAT", "a zero TTL must not exclude anything"

    def test_successful_dispatch_clears_the_cooldown(self, tmp_path: Path) -> None:
        path = tmp_path / "rotation.json"
        store = ResourceRotationStore(path, unavailable_ttl_seconds=3600)
        store.unavailable("MEAT")
        store.completed("MEAT")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["unavailable"] == {}
        assert payload["dispatched"]["MEAT"] == 1

    def test_corrupt_state_never_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "rotation.json"
        path.write_text("{not json", encoding="utf-8")
        store = ResourceRotationStore(path)
        assert store.target() == "MEAT"
        path.write_text(json.dumps({"dispatched": {"MEAT": "x"}, "unavailable": {"WOOD": 5}}), encoding="utf-8")
        assert store.target() in {"MEAT", "WOOD", "COAL", "IRON"}
