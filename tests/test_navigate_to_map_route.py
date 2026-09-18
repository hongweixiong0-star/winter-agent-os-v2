"""NAVIGATE_TO_MAP (skill ``OPEN_MAP``): what proves it, and what still does not.

Escalation 2026-09-18 ``NAVIGATE_TO_MAP|OPEN_MAP_NOT_PROVEN|OPEN_MAP``,
condition ``UNKNOWN_UI``.

The two frames of that episode are archived under
``dataset/truth_audit/nav_to_map_20260918/key/`` and they say two different
things, which is why the escalation was unreadable:

* it *names* ``..._step_002_after_...png``, an unchanged HOME frame, and
* it *reports* ``after.page == UNKNOWN`` at confidence 0.0, which only
  ``..._step_002_after_refresh_2_...png`` produces (the client's 常规活动 ->
  护送货车 page, a page the model has no template for).

So this file pins two separate defects, one fixed and one named:

1. FIXED -- ``verify_open_map`` folded an unrelated march-counter read
   (``march_used is not None or resource_search_open``) into a navigation
   proof.  The production episode 2026-09-14T13:12:13 opened the world map
   (``after.page = MAP``, 0.99) and was still recorded as
   ``OPEN_MAP_NOT_PROVEN`` because no counter template matched that frame.  The
   regression pair below is that live pair, read through the same layer that
   produced it (``SemanticWorldVision``, i.e. ``recognition_backend: V2``); on
   that layer ``march_used`` really is ``None``.
2. FIXED -- the episode pointed at the wrong frame.  ``LiveRuntime`` kept
   ``after_path`` on the first post-action capture, so the picture and the
   recorded state could come from different moments of the same step.

What is NOT fixed, and is pinned here so it stays visible rather than looking
like a green suite: the 常规活动 / 护送货车 page has no template, so it reads as
``Page.UNKNOWN`` and the navigation fails closed.  That is correct behaviour and
also a real coverage gap.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.learning import EpisodeStore
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.verifier import verify_open_map
from winter_agent_v2.vision import SemanticWorldVision

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dataset/candidate/template_manifest.json"
KEY = ROOT / "dataset/truth_audit/nav_to_map_20260918/key"

# The production pair that failed the old verifier: the map really opened and
# the counter was unreadable on that frame.
PRODUCTION_BEFORE = KEY / "before_home__live_runtime_step_001_before_20260914T131124123677.png"
PRODUCTION_AFTER = KEY / "after_map_unreadable_counter__live_runtime_step_001_after_20260914T131135967458.png"
# The escalated episode: the tap produced nothing, and the page the client
# really ended up on is one V2 cannot name.
ESCALATION_BEFORE = KEY / "escalation_step002_before_home.png"
ESCALATION_AFTER = KEY / "escalation_step002_after_still_home.png"
ESCALATION_REFRESH = KEY / "escalation_step002_refresh2_event_page.png"
# The live-verified pair produced after the fix (episode live_runtime,
# 2026-09-17T23:46:25Z, stop_reason TARGET_SKILL_VERIFIED).
LIVE_BEFORE = KEY / "live20260918_open_map_before_home.png"
LIVE_AFTER = KEY / "live20260918_open_map_after_map.png"


def _missing(*paths: Path) -> bool:
    return any(not path.is_file() for path in paths)


class FakeMatch:
    center_norm = (0.924, 0.954)


class FakeSemantic:
    """``PAGE_MAP`` resolves; everything else refuses, as the real layer does here."""

    def find(self, _path, semantic):
        return FakeMatch() if semantic == "PAGE_MAP" else None

    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class ScriptedVision:
    """Hand back one scripted state per ``observe`` call."""

    def __init__(self, states):
        self.states = list(states)
        self.calls = 0

    def observe(self, _path):
        state = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return state


class FakeDevice:
    def __init__(self):
        self.taps = []

    def screenshot(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        pass

    def swipe(self, *_args, **_kwargs):
        pass


class TheProductionPairThatFailedTests(unittest.TestCase):
    """The live 2026-09-14 pair, read by the layer that produced the failure."""

    @classmethod
    def setUpClass(cls) -> None:
        if _missing(PRODUCTION_BEFORE, PRODUCTION_AFTER):
            raise unittest.SkipTest("archived 2026-09-14 pair not on this machine")
        cls.vision = SemanticWorldVision(MANIFEST)
        cls.before = cls.vision.observe(PRODUCTION_BEFORE)
        cls.after = cls.vision.observe(PRODUCTION_AFTER)

    def test_the_frames_really_are_home_then_map(self):
        self.assertIs(self.before.page, Page.HOME)
        self.assertIs(self.after.page, Page.MAP)
        self.assertGreaterEqual(self.after.confidence, 0.9)

    def test_the_counter_is_genuinely_unreadable_on_that_frame(self):
        # This is the whole reason the pair is the regression: if the counter
        # read, the old condition would have passed and nothing would be pinned.
        self.assertIsNone(
            self.after.march_used,
            "the 2026-09-14 after-frame carries no readable march counter - that "
            "is the defect, so a readable counter would invalidate this fixture",
        )
        self.assertFalse(self.after.resource_search_open)

    def test_the_navigation_is_now_proven(self):
        result = verify_open_map(self.before, self.after)
        self.assertTrue(result.ok, f"reason={result.reason} evidence={result.evidence}")
        self.assertEqual(result.reason, "OK")
        self.assertTrue(result.evidence["before_home"])
        self.assertTrue(result.evidence["after_map"])

    def test_the_old_condition_is_what_failed_it(self):
        """Pin the removed term, so it cannot come back by accident.

        The old rule was ``before HOME and after MAP and (march_used is not None
        or resource_search_open)``.  Written out here it must disagree with the
        verifier above on exactly this pair -- that disagreement IS the defect.
        """
        old_condition = (
            self.before.page is Page.HOME
            and self.after.page is Page.MAP
            and (self.after.march_used is not None or self.after.resource_search_open)
        )
        self.assertFalse(old_condition)
        self.assertTrue(verify_open_map(self.before, self.after).ok)


class TheEscalatedEpisodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if _missing(ESCALATION_BEFORE, ESCALATION_AFTER, ESCALATION_REFRESH):
            raise unittest.SkipTest("escalation frames not on this machine")
        cls.vision = SemanticWorldVision(MANIFEST)

    def test_the_tap_frame_is_the_unchanged_city(self):
        before = self.vision.observe(ESCALATION_BEFORE)
        after = self.vision.observe(ESCALATION_AFTER)
        self.assertIs(before.page, Page.HOME)
        self.assertIs(after.page, Page.HOME)
        self.assertFalse(verify_open_map(before, after).ok)

    def test_the_page_the_client_really_reached_is_unmodelled(self):
        state = self.vision.observe(ESCALATION_REFRESH)
        self.assertIs(
            state.page,
            Page.UNKNOWN,
            "if this page becomes readable, the coverage gap recorded for "
            "NAVIGATE_TO_MAP is closed and this test should be updated rather "
            "than deleted",
        )
        self.assertEqual(state.confidence, 0.0)

    def test_an_unreadable_page_after_the_tap_is_still_not_the_map(self):
        """Fail-closed is the point: this is the assertion the fix must NOT relax."""
        before = self.vision.observe(ESCALATION_BEFORE)
        refresh = self.vision.observe(ESCALATION_REFRESH)
        result = verify_open_map(before, refresh)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "OPEN_MAP_NOT_PROVEN")


class TheLiveVerifiedPairTests(unittest.TestCase):
    def test_the_episode_that_verified_after_the_fix(self):
        if _missing(LIVE_BEFORE, LIVE_AFTER):
            raise unittest.SkipTest("live-verified pair not on this machine")
        vision = SemanticWorldVision(MANIFEST)
        result = verify_open_map(vision.observe(LIVE_BEFORE), vision.observe(LIVE_AFTER))
        self.assertTrue(result.ok, f"reason={result.reason} evidence={result.evidence}")


class TheEpisodeNamesTheFrameItsStateCameFromTests(unittest.TestCase):
    """Evidence integrity for the step, not just for the file name.

    The escalated episode recorded ``after.page == UNKNOWN`` next to a screenshot
    of the unchanged city.  Both were true statements about the same step, taken
    from two different moments, and no auditor could tell which.  The recorded
    ``after_screenshot`` must be the frame the recorded ``after`` state was read
    from.
    """

    def _run(self, tmp: str, states):
        """Run one bounded OPEN_MAP step and return (episodes, taps issued)."""
        store = EpisodeStore(Path(tmp) / "episodes.jsonl", limit=50)
        device = FakeDevice()
        LiveRuntime(
            device=device,
            vision=ScriptedVision(states),
            semantic_vision=FakeSemantic(),
            capture_dir=Path(tmp) / "episode_0001",
            episode_store=store,
            sleeper=lambda _seconds: None,
        ).run(max_actions=1, allowed_skills={"OPEN_MAP"}, stop_after_skill="OPEN_MAP")
        episodes = Path(tmp) / "episodes.jsonl"
        rows = [json.loads(line) for line in episodes.read_text(encoding="utf-8").splitlines()
                if line.strip()] if episodes.is_file() else []
        return rows, device

    def test_a_verifier_that_only_passes_on_a_refresh_records_that_refresh(self):
        home = WorldState(page=Page.HOME, confidence=0.98)
        mapped = WorldState(page=Page.MAP, march_used=None, confidence=0.99)
        # before, after(first, still HOME), refresh_1(HOME), refresh_2(MAP)
        with TemporaryDirectory() as tmp:
            rows, device = self._run(tmp, [home, home, home, mapped])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(len(device.taps), 1, "the click is never repeated")
        self.assertTrue(row["verifier_ok"])
        self.assertEqual(row["state_after"]["page"], "MAP")
        self.assertIn("_after_refresh_", row["after_screenshot"], (
            "the episode must name the frame whose reading it reports, not the "
            "first post-action capture"
        ))

    def test_the_first_post_action_frame_is_still_used_when_it_already_verifies(self):
        home = WorldState(page=Page.HOME, confidence=0.98)
        mapped = WorldState(page=Page.MAP, march_used=0, confidence=0.99)
        with TemporaryDirectory() as tmp:
            rows, device = self._run(tmp, [home, mapped])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(device.taps), 1)
        self.assertTrue(rows[0]["verifier_ok"])
        self.assertNotIn("_after_refresh_", rows[0]["after_screenshot"])
        self.assertIn("_after_", rows[0]["after_screenshot"])


if __name__ == "__main__":
    unittest.main()
