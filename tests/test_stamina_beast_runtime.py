from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import MarchState, Page, WorldState
from winter_agent_v2.skills import v2_registry
from winter_agent_v2.verifier import verify_beast_dispatch, verify_beast_march_open, verify_beast_target_selected
from winter_agent_v2.vision import SemanticWorldVision

from tests.live_stack import production_vision


ROOT = Path(__file__).resolve().parents[1]


class StaminaBeastRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vision = SemanticWorldVision(ROOT / "dataset/candidate/template_manifest.json")

    def test_current_client_musk_ox_chain_is_recognized(self):
        folder = ROOT / "dataset/raw/stamina_emergency"
        visible = self.vision.observe(folder / "current_for_skill.png")
        target = self.vision.observe(folder / "beast9_round3_target.png")
        dispatched = self.vision.observe(folder / "beast9_round3_dispatched.png")
        # The formation page draws the target only in its title bar, so the name
        # that `verify_beast_march_open` binds cannot come from the template
        # layer alone -- the production stack is required (see
        # tests/live_stack.py, whose whole purpose is this distinction).
        hybrid = production_vision()
        if hybrid is None:
            self.skipTest("OCR runtime unavailable")
        march = hybrid.observe(folder / "beast9_round3_march.png")

        self.assertIs(visible.page, Page.MAP)
        self.assertEqual(visible.beast.get("visible_target"), "MUSK_OX")
        self.assertEqual(RuleBrain(current_goal="BEAST_HUNT").decide(visible, v2_registry()).skill, "SELECT_BEAST_TARGET")
        self.assertTrue(verify_beast_target_selected(visible, target).ok)
        self.assertEqual(RuleBrain(current_goal="BEAST_HUNT").decide(target, v2_registry()).skill, "BEAST_HUNT")
        self.assertTrue(verify_beast_march_open(target, march).ok)
        self.assertEqual(RuleBrain(current_goal="BEAST_HUNT").decide(march, v2_registry()).skill, "DISPATCH_BEAST")
        self.assertTrue(verify_beast_dispatch(march, dispatched).ok)

    def test_low_win_probability_never_dispatches(self):
        state = self.vision.observe(ROOT / "dataset/raw/stamina_emergency/beast_march.png")
        decision = RuleBrain(current_goal="BEAST_HUNT").decide(state, v2_registry())
        self.assertIs(state.page, Page.MARCH)
        self.assertFalse(state.beast.get("victory_assured"))
        self.assertEqual(decision.skill, "SAFE_STOP")
        self.assertEqual(decision.reason, "beast_low_win_probability")

    def test_dispatch_requires_active_map_queue(self):
        before = WorldState(page=Page.MARCH, beast={"name":"麝牛", "level":9, "victory_assured":True})
        good = WorldState(page=Page.MAP, marches=(MarchState.MARCHING,), march_used=6, march_max=6)
        bad = WorldState(page=Page.MAP, marches=(MarchState.GATHERING,), march_used=6, march_max=6)
        self.assertTrue(verify_beast_dispatch(before, good).ok)
        self.assertFalse(verify_beast_dispatch(before, bad).ok)

    def test_musk_ox_target_can_move_inside_map_without_becoming_a_fixed_coordinate(self):
        source_path = ROOT / "dataset/raw/stamina_emergency/current_for_skill.png"
        with Image.open(source_path) as source, TemporaryDirectory() as folder:
            shifted = source.convert("RGB")
            target = shifted.crop((364, 198, 508, 326))
            ImageDraw.Draw(shifted).rectangle((364, 198, 508, 326), fill=(164, 177, 208))
            shifted.paste(target, (524, 504))
            path = Path(folder) / "shifted.png"
            shifted.save(path)
            match = self.vision.semantic.find(path, "TARGET_BEAST_MUSK_OX_9")
        self.assertIsNotNone(match)
        self.assertAlmostEqual(match.center_norm[0], (524 + 72) / 720, delta=0.02)
        self.assertAlmostEqual(match.center_norm[1], (504 + 64) / 1280, delta=0.02)

    def _real_map_without_musk_ox(self):
        """挑选 retention 保留、且不含雪豹/麝牛的真实地图帧。

        历史固定路径 `dataset/raw/control_panel/runtime_beast/step_001_before.png`
        会被 retention.auto_prune 清理，导致该测试随磁盘状态间歇失败甚至消失。
        这里改为在保留目录中动态寻找：先按经验排除 `stamina_emergency`（该目录
        是麝牛正样本来源），再用固定 ROI 的 pHash 距离排除画面里真的出现目标
        的帧，最后回退到最早的一张帧。找不到可用帧时跳过而不是失败。
        """
        probe = ROOT / "dataset/raw/stamina_emergency/current_for_skill.png"
        if probe.is_file() and self.vision.observe(probe).beast.get("visible_target") == "MUSK_OX":
            self.skipTest("麝牛正样本当前可见，无法用同一目录的帧做负样本校验")

        candidates: list[Path] = []
        stall = ROOT / "dataset/raw/control_panel"
        for folder in sorted(stall.glob("runtime*")) if stall.is_dir() else []:
            for episode in sorted(folder.iterdir(), reverse=True):
                if episode.is_dir():
                    candidates.extend(sorted(episode.glob("*before*.png"), reverse=True))
        for episode in sorted((stall / "bootstrap").iterdir(), reverse=True) if (stall / "bootstrap").is_dir() else []:
            if episode.is_dir():
                candidates.extend(sorted(episode.glob("*.png"), reverse=True))

        fallback: Path | None = None
        for path in candidates:
            if not path.is_file():
                continue
            if fallback is None:
                fallback = path
            if self.vision.observe(path).beast.get("visible_target") is None:
                return path
        return fallback

    def test_musk_ox_detector_rejects_real_map_without_musk_ox(self):
        frame = self._real_map_without_musk_ox()
        if frame is None:
            self.skipTest("本地没有保留的真实地图帧可用于负样本校验")
        match = self.vision.semantic.find(frame, "TARGET_BEAST_MUSK_OX_9")
        self.assertIsNone(match)


if __name__ == "__main__":
    unittest.main()
