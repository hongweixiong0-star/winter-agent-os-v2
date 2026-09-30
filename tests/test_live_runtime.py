import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from unittest.mock import patch

from PIL import Image

from winter_agent_v2.goal_library import GoalState, GoalStatus
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
        self.backs = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.backs.append(len(self.taps))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


class ImageSequenceDevice(FakeDevice):
    def __init__(self, colors):
        super().__init__()
        self.colors = list(colors)
        self.screenshot_count = 0

    def screenshot(self, path):
        color = self.colors[min(self.screenshot_count, len(self.colors) - 1)]
        self.screenshot_count += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (720, 1280), color).save(path)
        return path


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
    def _runtime(self, goal_id, **kwargs):
        runtime = LiveRuntime(**kwargs)
        goals = () if goal_id is None else (
            GoalState(goal_id=goal_id, status=GoalStatus.READY, available_skills=("TEST_RUNTIME",)),
        )
        # These tests cover the action loop and verifiers.  Keep their goal input
        # deterministic; the separate home_to_map test exercises the real Scheduler.
        runtime.goal_library.discover = lambda _world, observations=None: goals
        return runtime

    def setUp(self):
        # Runtime tests exercise scheduler decisions as well as the UI loop.  Keep the
        # learned observations and fairness state local to each test: sharing the repo's
        # learning files lets an earlier fake screen change which goal a later test sees.
        self.learning_temp = TemporaryDirectory()
        self.addCleanup(self.learning_temp.cleanup)
        learning_root = Path(self.learning_temp.name)
        from winter_agent_v2 import control_experience, event_schedule, goal_utility, observation_store

        for module, attribute, name in (
            (control_experience, "STATE_PATH", "control_experience.json"),
            (event_schedule, "STATE_PATH", "timed_event_schedule.json"),
            (goal_utility, "STATE_PATH", "goal_fairness.json"),
            (goal_utility, "DECISIONS_PATH", "decisions.jsonl"),
            (observation_store, "STATE_PATH", "observation_state.json"),
        ):
            patcher = patch.object(module, attribute, learning_root / name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_map_to_home_uses_goal_and_semantic_button(self):
        from winter_agent_v2.brain import RuleBrain

        device = FakeDevice()
        states = [
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.HOME, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            run = self._runtime("HOME",
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
            run = self._runtime("GATHER_RESOURCE",
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
            run = self._runtime("GATHER_RESOURCE",
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
            run = self._runtime("GATHER_RESOURCE",
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
            run = self._runtime("GATHER_RESOURCE",
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

    def test_verified_live_action_writes_phase_latency(self):
        device = FakeDevice()
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            latency_path = Path(temp) / "action_latency.jsonl"
            run = self._runtime("GATHER_RESOURCE",
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp) / "captures",
                latency_trace_path=latency_path,
                sleeper=lambda _seconds: None,
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"})
            row = json.loads(latency_path.read_text(encoding="utf-8"))
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(row["skill"], "OPEN_MAP")
        self.assertEqual(row["page_before"], "HOME")
        self.assertEqual(row["page_after"], "MAP")
        self.assertTrue(row["success"])
        self.assertEqual(row["schema_version"], 2)
        for field in ("capture_ms", "ocr_ms", "parse_ms", "decision_ms", "maa_ms",
                      "settle_ms", "reobserve_ms", "verifier_ms", "episode_write_ms",
                      "total_step_ms"):
            self.assertIn(field, row)
        for duplicate in ("frame_capture_ms", "scheduler_select_ms", "maa_execute_ms", "post_action_wait_ms"):
            self.assertNotIn(duplicate, row)
        self.assertGreaterEqual(row["total_step_ms"], 0.0)
        self.assertEqual(row["settle_policy"], "PAGE_TRANSITION")
        self.assertEqual(row["settle_frame_change_fraction"], None)

    def test_unchanged_frame_gets_one_bounded_settle_retry_without_repeating_action(self):
        device = ImageSequenceDevice(["black", "black", "white"])
        states = [
            WorldState(page=Page.HOME, confidence=0.99),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        waits = []
        with TemporaryDirectory() as temp:
            run = self._runtime("GATHER_RESOURCE",
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=waits.append,
            ).run(max_actions=1, allowed_skills={"OPEN_MAP"})
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(len(device.taps), 1)
        self.assertEqual(device.screenshot_count, 3)
        self.assertEqual(waits, [0.15, 0.4])

    def test_verified_action_repeats_then_safe_stops(self):
        states = [
            ally(100, 2, 2, 0), ally(130, 1, 1, 1),
            ally(130, 1, 1, 1), ally(250, 0, 0, 2, "CLAIMED"),
            ally(250, 0, 0, 2, "CLAIMED"),
        ]
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            run = self._runtime("ALLIANCE_ROUTINE",
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=3)
        self.assertEqual(len(device.taps), 2)
        self.assertEqual(run.stop_reason, "alliance_action_not_needed")
        self.assertTrue(all(step.verification is None or step.verification.ok for step in run.steps))

    def test_dropped_claim_retries_inside_same_auto_step_with_new_location(self):
        class MovingSemantic(FakeSemantic):
            def find(self, path, semantic):
                if semantic != "BTN_ALLY_GIFT_CLAIM":
                    return super().find(path, semantic)
                point = (0.62, 0.5) if "semantic_retry" in str(path) else (0.84, 0.5)
                return type("CurrentMatch", (), {"center_norm": point})()
        device = FakeDevice()
        pending = ally(100, 2, 2, 0)
        with TemporaryDirectory() as temp:
            store = EpisodeStore(Path(temp) / "episodes.jsonl")
            runtime = self._runtime("ALLIANCE_ROUTINE", device=device,
                vision=FakeVision([pending, pending, pending, ally(130, 1, 1, 1)]),
                semantic_vision=MovingSemantic(), capture_dir=Path(temp),
                sleeper=lambda _: None, observation_retries=0, episode_store=store)
            run = runtime.run(max_actions=1)
            metrics = json.loads((Path(temp) / "semantic_click_retry_metrics.json").read_text())
            self.assertEqual(metrics["CLICK_RETRY_SUCCESS"], 1)
            episodes = [json.loads(line) for line in store.path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(episodes), 1, "a lost touch is not an extra Skill failure")
        self.assertEqual(device.taps, [(605, 640), (446, 640)])
        self.assertTrue(run.steps[0].verification.ok)
        self.assertEqual(run.steps[0].execution.detail["semantic_click"]["retries"], 1)


    def test_dropped_claim_exhausts_two_retries_then_yields(self):
        device = FakeDevice()
        pending = ally(100, 2, 2, 0)
        with TemporaryDirectory() as temp:
            runtime = self._runtime("ALLIANCE_ROUTINE", device=device,
                vision=FakeVision([pending] * 6), semantic_vision=FakeSemantic(),
                capture_dir=Path(temp), sleeper=lambda _: None, observation_retries=0)
            run = runtime.run(max_actions=1)
            metrics = json.loads((Path(temp) / "semantic_click_retry_metrics.json").read_text())
            self.assertGreaterEqual(metrics["CLICK_RETRY_EXHAUSTED"], 1)
        self.assertEqual(len(device.taps), 3)
        self.assertFalse(run.steps[0].verification.ok)
        self.assertEqual(run.steps[0].execution.detail["semantic_click"]["retries"], 2)


    def test_unknown_stops_without_click(self):
        """An unknown screen is never clicked, and still ends the run if it stays unknown.

        MASTER_RULES 7 lets the loop back out of a screen it cannot read (live
        2026-09-14: an unrecognised mission card stalled the whole intel loop),
        but backing out is the ONLY thing it may do, and if that fails the
        original reason must still be reported rather than hidden.
        """
        device = FakeDevice()
        with TemporaryDirectory() as temp:
            run = self._runtime(None,
                device=device,
                vision=FakeVision([WorldState(), WorldState(), WorldState(), WorldState()]),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=2, allowed_skills={"BACK"})
        self.assertEqual(device.taps, [], "unknown content must never be clicked")
        self.assertEqual(len(device.backs), 2, "recovery is bounded per run")
        self.assertEqual(run.stop_reason, "unknown_page")

    def test_unknown_page_recovery_resumes_the_run(self):
        """Backing out of an unreadable screen lets the run continue."""
        device = FakeDevice()
        states = [
            WorldState(),  # index 1: nothing recognised
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
            WorldState(page=Page.MAP, march_used=1, march_max=6, confidence=0.99),
        ]
        with TemporaryDirectory() as temp:
            run = self._runtime(None,
                device=device,
                vision=FakeVision(states),
                semantic_vision=FakeSemantic(),
                capture_dir=Path(temp),
                sleeper=lambda _seconds: None,
            ).run(max_actions=2, allowed_skills={"BACK"})
        self.assertEqual(len(device.backs), 1, "one back recovers, no more")
        self.assertEqual(device.taps, [])
        self.assertNotEqual(
            run.stop_reason, "unknown_page",
            "the run must survive a screen it could not read",
        )


if __name__ == "__main__":
    unittest.main()
