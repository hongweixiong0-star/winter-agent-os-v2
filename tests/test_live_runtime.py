import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


class FakeMatch:
    center_norm = (0.84, 0.50)


class FakeSemantic:
    def find(self, _path, semantic):
        return FakeMatch() if semantic in {"BTN_ALLY_GIFT_CLAIM", "PAGE_MAP", "BTN_OPEN_HOME"} else None

    # runtime now expects ``self.semantic_vision.semantic`` to expose the
    # geometric attributes and ``.find()``. Mirror that shape here so unit
    # tests keep working.  The resource strip is a relative-layout model, so
    # the fake exposes the same accessors the real vision does rather than a
    # fixed centre table.
    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, resource):
        return 0.0


class FakeVision:
    def __init__(self, states):
        self.states = iter(states)

    def observe(self, _path):
        return next(self.states)


class FakeDevice:
    def __init__(self):
        self.taps = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


def ally(progress, badge, buttons, claimed, status="CLAIMABLE"):
    return WorldState(
        page=Page.ALLIANCE,
        alliance={
            "section": "GIFTS",
            "tab": "ALLY_GIFT",
            "status": status,
            "gift_progress": progress,
            "gift_progress_target": 150000,
            "badge_count": badge,
            "visible_claim_buttons": buttons,
            "visible_claimed": claimed,
        },
        confidence=0.99,
    )


class LiveRuntimeTests(unittest.TestCase):
    def test_map_to_home_uses_goal_and_semantic_button(self):
        from winter_agent_v2.brain import RuleBrain

        device = FakeDevice()
        states = [
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                brain=RuleBrain(current_goal="HOME"),
                sleeper=lambda _seconds: None,
            ).run(max_actions=1, allowed_skills={"OPEN_HOME"})
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(len(device.taps), 1)

    def test_home_to_map_runs_through_single_scheduler(self):
        device = FakeDevice()
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"}, stop_after_skill="OPEN_MAP")
        self.assertEqual(run.stop_reason, "TARGET_SKILL_VERIFIED")
        self.assertEqual(len(device.taps), 1)
        self.assertTrue(run.steps[0].verification.ok)

    def test_unknown_transition_frame_refreshes_without_second_click(self):
        device = FakeDevice()
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"})
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(len(device.taps), 1)

    def test_known_intermediate_frame_refreshes_without_second_click(self):
        device = FakeDevice()
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"})
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(len(device.taps), 1)

    def test_verified_live_action_is_written_as_episode(self):
        device = FakeDevice()
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            episode_path = Path(temp) / "episodes.jsonl"
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                sleeper=lambda _seconds: None,
                episode_store=EpisodeStore(episode_path),
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"})
            row = json.loads(episode_path.read_text(encoding="utf-8"))
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(row["skill"], "OPEN_MAP")
        self.assertEqual(row["result"], "SUCCESS")
        self.assertEqual(row["state_before"]["page"], "HOME")
        self.assertEqual(row["state_after"]["page"], "MAP")

    def test_verified_action_repeats_then_safe_stops(self):
        states = [
            ally(100, 2, 2, 0), ally(130, 1, 1, 1),
            ally(130, 1, 1, 1), ally(250, 0, 0, 2, "CLAIMED"),
            ally(250, 0, 0, 2, "CLAIMED"),
        ]
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=5)
        self.assertEqual(len(device.taps), 2)
        self.assertEqual(run.stop_reason, "alliance_action_not_needed")
        self.assertTrue(all(step.verification is None or step.verification.ok for step in run.steps))

    def test_unknown_stops_without_click(self):
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            run = LiveRuntime(
                device=device,
                vision=FakeVision([WorldState()]),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=2)
        self.assertEqual(device.taps, [])
        self.assertEqual(run.stop_reason, "unknown_page")


if __name__ == "__main__":
    unittest.main()
