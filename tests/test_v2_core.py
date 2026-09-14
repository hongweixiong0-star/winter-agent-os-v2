from __future__ import annotations

import json
import unittest
from pathlib import Path

from winter_agent_v2.brain import RuleBrain, parse_qwen_decision
from winter_agent_v2.executor import Executor
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.scheduler import Scheduler
from winter_agent_v2.skills import p0_registry
from winter_agent_v2.verifier import verify_gathering, verify_returning
from winter_agent_v2.vision import ReplayVision


ROOT = Path(__file__).resolve().parents[1]


class V2CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = p0_registry()

    def test_unknown_safe_stops(self) -> None:
        result = Scheduler(RuleBrain(), self.registry, Executor()).tick(WorldState())
        self.assertEqual(result.decision.skill, "SAFE_STOP")
        self.assertIsNone(result.execution)

    def test_dry_run_blocks_click(self) -> None:
        world = WorldState(page=Page.MAP, march_used=2, march_max=6, confidence=0.9)
        result = Scheduler(RuleBrain(), self.registry, Executor()).tick(world)
        self.assertEqual(result.decision.skill, "SEARCH_RESOURCE")
        self.assertFalse(result.execution.executed)
        self.assertEqual(result.execution.error, "DRY_RUN_BLOCKED_DEVICE_ACTION")

    def test_gather_reserves_one_march_for_stamina_tasks(self) -> None:
        world = WorldState(page=Page.MAP, march_used=5, march_max=6, confidence=0.99)
        result = Scheduler(
            RuleBrain(current_goal="GATHER_RESOURCE", reserve_marches=1),
            self.registry,
            Executor(),
        ).tick(world)
        self.assertEqual(result.decision.skill, "SAFE_STOP")
        self.assertEqual(result.decision.reason, "reserved_march_for_stamina")
        self.assertIsNone(result.execution)

    def test_strict_qwen_json(self) -> None:
        good = json.dumps({"skill":"CHECK_MARCH","reason":"observe","confidence":0.9,"expected_result":"known"})
        self.assertEqual(parse_qwen_decision(good, self.registry).skill, "CHECK_MARCH")
        with self.assertRaisesRegex(ValueError, "REJECT"):
            parse_qwen_decision("not json", self.registry)

    def test_replay_resource_detail_verifies_gathering(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "legacy_resource_detail.png")
        result = verify_gathering(state)
        self.assertTrue(result.ok)
        self.assertEqual(state.resource_target, "WOOD")

    def test_replay_unknown_image_is_unknown(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "legacy_resource_detail.png")
        self.assertEqual(state.page, Page.RESOURCE_DETAIL)

    def test_gathering_brain_selects_verifier_only(self) -> None:
        world = WorldState(page=Page.RESOURCE_DETAIL, marches=(MarchState.GATHERING,), resource_target="WOOD", confidence=0.95)
        result = Scheduler(RuleBrain(), self.registry, Executor()).tick(world)
        self.assertEqual(result.decision.skill, "VERIFY_GATHERING")
        self.assertTrue(result.execution.executed)
        self.assertEqual(result.execution.action.kind, "OBSERVE")

    def test_replay_home_starts_with_open_map(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "legacy_home.png")
        result = Scheduler(RuleBrain(), self.registry, Executor()).tick(state)
        self.assertEqual(result.decision.skill, "OPEN_MAP")
        self.assertFalse(result.execution.executed)
        self.assertTrue(result.execution.dry_run)

    def test_live_purchase_popup_only_plans_close(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "live_current.png")
        result = Scheduler(RuleBrain(), self.registry, Executor()).tick(state)
        self.assertEqual(state.popup, "PURCHASE_POPUP")
        self.assertEqual(result.decision.skill, "CLOSE_POPUP")
        self.assertEqual(result.execution.action.target, "BTN_CLOSE")
        self.assertFalse(result.execution.executed)
        self.assertEqual(result.execution.error, "DRY_RUN_BLOCKED_DEVICE_ACTION")

    def test_replay_returning_state(self) -> None:
        vision = ReplayVision(ROOT / "tests" / "replay" / "labels.json")
        state = vision.observe(ROOT / "dataset" / "raw" / "legacy_returning.png")
        self.assertEqual(state.march_used, 4)
        self.assertTrue(verify_returning(state).ok)


if __name__ == "__main__":
    unittest.main()
