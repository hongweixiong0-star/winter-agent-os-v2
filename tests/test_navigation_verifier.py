import unittest
from pathlib import Path

from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.verifier import verify_march_page_open, verify_open_home, verify_open_map, verify_resource_found, verify_resource_search_open, verify_resource_selected, verify_safe_back, verify_wood_dispatch_from_march
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


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
        replay = ReplayVision(ROOT / "tests/replay/labels.json")
        before = replay.observe(ROOT / "dataset/raw/live_attempt8_march.png")
        after = replay.observe(ROOT / "dataset/raw/live_attempt8_marching.png")
        self.assertTrue(verify_wood_dispatch_from_march(before, after).ok)

    def test_first_live_march_is_valid_dispatch_evidence(self):
        before = WorldState(page=Page.MARCH, resource_target="WOOD", confidence=0.99)
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
