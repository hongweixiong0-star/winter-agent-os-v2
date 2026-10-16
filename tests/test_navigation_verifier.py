import unittest
from dataclasses import replace
from pathlib import Path

from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.verifier import verify_march_page_open, verify_open_home, verify_open_map, verify_resource_found, verify_resource_search_open, verify_resource_selected, verify_safe_back, verify_wood_dispatch_from_march
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


def _role_scoped_wood_formation(source_frame: str, observed_at: str) -> dict:
    """The formation reading the live reader produces for an empty, current-role gather setup.

    ``verify_wood_dispatch_from_march`` has required the spent formation to be THIS role's and
    observed on THIS frame since 2026-10-02 (the WB-1002-16 refusal: a stale placeholder
    resource comparison vetoed a payable dispatch).  The replay reader does not read hero
    formations at all -- it reads ``marches``/``march_used``/the page fields -- so the state
    gets the reading the live reader would have carried, stamped with the state's OWN
    timestamp so the "observed now" clause is exact rather than accidental.  Empty slots plus
    no confirmed specialist is ``READY_EMPTY``: the safe valid fallback the contract defines.
    """
    return {
        "status": "OBSERVED",
        "page": "PAGE_FORMATION",
        "role_scope": "LIVE_OBSERVED",
        "role_id": "1061663148",
        "source_frame": source_frame,
        "observed_at": observed_at,
        "resource_source": "PAGE",
        "resource_type": "WOOD",
        "slots": [
            {"slot": 1, "state": "EMPTY"},
            {"slot": 2, "state": "EMPTY"},
            {"slot": 3, "state": "EMPTY"},
        ],
        "empty_slots": [1, 2, 3],
    }


class NavigationVerifierTests(unittest.TestCase):
    def test_live_replay_home_to_map(self):
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_back_safe_home.png")
        after = replay.observe(ROOT / "dataset/raw/live_attempt8_idle.png")
        self.assertTrue(verify_open_map(before, after).ok)

    def test_same_page_does_not_prove_navigation(self):
        home = WorldState(page=Page.HOME, confidence=0.99)
        self.assertFalse(verify_open_map(home, home).ok)

    def test_map_to_home_transition(self):
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_attempt8_idle.png")
        after = replay.observe(ROOT / "dataset/raw/live_back_safe_home.png")
        self.assertTrue(verify_open_home(before, after).ok)

    def test_resource_search_panel_transition(self):
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_attempt8_idle.png")
        after = replay.observe(ROOT / "dataset/raw/live_executor_search_open.png")
        self.assertTrue(verify_resource_search_open(before, after).ok)

    def test_safe_back_closes_search_without_leaving_map(self):
        before = WorldState(page=Page.MAP, resource_search_open=True, confidence=0.99)
        after = WorldState(page=Page.MAP, resource_search_open=False, confidence=0.99)
        self.assertTrue(verify_safe_back(before, after).ok)
        self.assertFalse(verify_safe_back(after, after).ok)

    def test_safe_back_accepts_alliance_subpage_return(self):
        before = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "TECHNOLOGY"},
            confidence=0.99,
        )
        after = WorldState(
            page=Page.ALLIANCE,
            alliance={"section": "HOME"},
            confidence=0.99,
        )

        result = verify_safe_back(before, after)

        self.assertTrue(result.ok)
        self.assertTrue(result.evidence["alliance_section_returned"])

    def test_wood_selection_transition(self):
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_runtime_search_open/step_001_after.png")
        after = replay.observe(ROOT / "dataset/raw/live_executor_search_open.png")
        self.assertTrue(verify_resource_selected(before, after).ok)

    def test_resource_search_finds_available_wood(self):
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_executor_search_open.png")
        after = replay.observe(ROOT / "dataset/raw/live_resource_attempt6.png")
        self.assertTrue(verify_resource_found(before, after).ok)

    def test_gather_opens_wood_march_page(self):
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_resource_attempt6.png")
        after = replay.observe(ROOT / "dataset/raw/live_march_attempt6.png")
        self.assertTrue(verify_march_page_open(before, after).ok)

    def test_wood_march_dispatch_transition(self):
        """The real transition, with the formation the verifier now requires (see the helper)."""
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_attempt8_march.png")
        after = replay.observe(ROOT / "dataset/raw/live_attempt8_marching.png")
        before = replace(before, hero_troop={"gather_formation": _role_scoped_wood_formation(
            "live_attempt8_march.png", str(before.timestamp))})
        self.assertTrue(verify_wood_dispatch_from_march(before, after).ok)

    def test_first_live_march_is_valid_dispatch_evidence(self):
        before = WorldState(page=Page.MARCH, resource_target="WOOD", confidence=0.99)
        before = replace(before, hero_troop={"gather_formation": _role_scoped_wood_formation(
            "live-first-march", str(before.timestamp))})
        after = WorldState(
            page=Page.MAP,
            marches=(MarchState.MARCHING,),
            march_used=1,
            march_max=6,
            resource_target="WOOD",
            confidence=0.99,
        )
        result = verify_wood_dispatch_from_march(before, after)
        self.assertTrue(result.ok)
        self.assertTrue(result.evidence["active_queue_visible"])

    def test_map_without_active_march_does_not_prove_dispatch(self):
        before = WorldState(page=Page.MARCH, resource_target="WOOD", confidence=0.99)
        after = WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99)
        self.assertFalse(verify_wood_dispatch_from_march(before, after).ok)


if __name__ == "__main__":
    unittest.main()
