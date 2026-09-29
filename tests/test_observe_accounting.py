"""The observation's cost must be attributable, and setting the attention must be possible.

TASK THROUGHPUT V1 §24 ("必须能看出：时间到底浪费在哪") and §27 ("从真实耗时日志找 TOP TIME
SINKS").

Two measured facts from pin 553d8df (2026-09-30, run 20260930_032831_029636) are guarded here:

1. ``reobserve_ms`` was one number built from two observations, and the gather-formation read
   inside ``_observe`` was invisible.  A step that went MARCH -> UNKNOWN recorded
   ``reobserve_ms`` 10375 ms, while replaying those same two archived frames offline cost
   93 ms + 2270 ms.  The archive alone therefore could not attribute the cost, and any cut made
   from it would have been a guess.

2. ``_observe`` reaches for ``focus`` on ``self.vision``, but ``tools/run_live.py`` wires
   ``self.vision`` to ``HybridVision``, which defines no ``focus`` and no ``__getattr__``
   forwarding.  So ``getattr(vision, "focus", None)`` is ``None`` in production and the
   goal-driven attention documented on ``_observe`` is never set -- every map sweep runs on
   every observation.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from winter_agent_v2.brain import RuleBrain
from winter_agent_v2.models import Page, WorldState
from winter_agent_v2.runtime import LiveRuntime


class _Status:
    connected = True
    resolution = (720, 1280)


class _Device:
    capture_backend = "TEST_CAPTURE"

    def status(self) -> _Status:
        return _Status()

    def press_back(self) -> None:
        pass

    def tap(self, x: int, y: int) -> None:
        pass

    def swipe(self, *args, **kwargs) -> None:
        pass

    def screenshot(self, path: Path) -> None:
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n")


class _PlainVision:
    """The production shape: ``observe`` and nothing else, exactly like ``HybridVision``."""

    def __init__(self, state: WorldState) -> None:
        self.state = state
        self.observations = 0

    def observe(self, path: Path) -> WorldState:
        self.observations += 1
        return self.state

    def sweeps_skipped(self) -> dict[str, str]:
        return {}


class _AttentiveVision:
    """A vision that really has the attention, so the widen path can be driven."""

    def __init__(self, state: WorldState) -> None:
        self.state = state
        self.observations = 0
        self.focus_calls: list[dict] = []
        self._widen = False

    def focus(self, *, goal="", page_hint="", reason="", widen=False) -> None:
        self.focus_calls.append({"goal": goal, "page_hint": page_hint, "widen": widen})
        self._widen = bool(widen)

    def observe(self, path: Path) -> WorldState:
        self.observations += 1
        return self.state

    def sweeps_skipped(self) -> dict[str, str]:
        # A skipped sweep the observation declined to do.  The runtime widens only when the
        # focused look also failed to name the page.
        if self._widen:
            return {}
        return {"TARGET_INTEL_BEAST_MISSION": "not worth its seconds now"}


class _ResolvesAny:
    def find(self, image_path, semantic):
        return None


def _runtime(vision, **kwargs) -> LiveRuntime:
    return LiveRuntime(
        device=_Device(),
        vision=vision,
        semantic_vision=_ResolvesAny(),
        capture_dir=Path(kwargs.pop("capture_dir")),
        brain=RuleBrain(current_goal="INTEL"),
        sleeper=lambda _seconds: None,
        **kwargs,
    )


class ObserveAccountingTests(unittest.TestCase):
    def test_a_plain_vision_records_its_call_and_its_two_components(self):
        vision = _PlainVision(WorldState(page=Page.HOME, confidence=0.98))
        with TemporaryDirectory() as temp:
            runtime = _runtime(vision, capture_dir=temp)
            latency: dict[str, float] = {}
            runtime._observe(Path(temp) / "frame.png", latency=latency, phase="before")

        self.assertEqual(latency.get("observe_before_calls"), 1)
        self.assertIn("observe_before_vision_ms", latency)
        self.assertIn("observe_before_formation_ms", latency)
        self.assertEqual(vision.observations, 1)
        # The three component keys must not leak into another phase's account.
        self.assertNotIn("observe_after_calls", latency)

    def test_the_two_main_phases_do_not_share_one_bucket(self):
        vision = _PlainVision(WorldState(page=Page.HOME, confidence=0.98))
        with TemporaryDirectory() as temp:
            runtime = _runtime(vision, capture_dir=temp)
            latency: dict[str, float] = {}
            runtime._observe(Path(temp) / "a.png", latency=latency, phase="before")
            runtime._observe(Path(temp) / "b.png", latency=latency, phase="after")
            runtime._observe(Path(temp) / "c.png", latency=latency, phase="recovery")

        self.assertEqual(latency.get("observe_before_calls"), 1)
        self.assertEqual(latency.get("observe_after_calls"), 1)
        self.assertEqual(latency.get("observe_recovery_calls"), 1)
        self.assertEqual(vision.observations, 3)

    def test_accounting_is_optional_and_cannot_break_an_observation(self):
        # Six call sites observe; only the production loop passes a latency dict.  A missing one
        # must be a no-op rather than an exception on the gameplay path.
        vision = _PlainVision(WorldState(page=Page.HOME, confidence=0.98))
        with TemporaryDirectory() as temp:
            runtime = _runtime(vision, capture_dir=temp)
            state = runtime._observe(Path(temp) / "frame.png")
        self.assertIsInstance(state, WorldState)
        self.assertEqual(vision.observations, 1)

    def test_a_widening_observation_is_counted_as_two_looks(self):
        # The widen pass is the expensive path: the same frame observed again with every map
        # sweep allowed.  It must be visible as a second call, or the phase looks cheaper than
        # it is on exactly the steps that hurt.
        vision = _AttentiveVision(WorldState(page=Page.UNKNOWN, confidence=0.0))
        with TemporaryDirectory() as temp:
            runtime = _runtime(vision, capture_dir=temp)
            latency: dict[str, float] = {}
            runtime._observe(Path(temp) / "frame.png", latency=latency, phase="before")

        self.assertEqual(vision.observations, 2, "skip-then-widen is two observations")
        self.assertEqual(latency.get("observe_before_calls"), 2)
        self.assertEqual(latency.get("observe_before_widened"), 1)
        self.assertEqual([c["widen"] for c in vision.focus_calls], [False, True])

    def test_a_named_frame_is_not_widened(self):
        vision = _AttentiveVision(WorldState(page=Page.HOME, confidence=0.98))
        with TemporaryDirectory() as temp:
            runtime = _runtime(vision, capture_dir=temp)
            latency: dict[str, float] = {}
            runtime._observe(Path(temp) / "frame.png", latency=latency, phase="after")

        self.assertEqual(vision.observations, 1)
        self.assertEqual(latency.get("observe_after_widened"), None)

    def test_an_unnamed_frame_with_no_skipped_sweep_is_not_widened(self):
        # Widening is for a *narrow* look that found nothing, not for every unnamed frame.
        vision = _AttentiveVision(WorldState(page=Page.UNKNOWN, confidence=0.0))
        vision.sweeps_skipped = lambda: {}
        with TemporaryDirectory() as temp:
            runtime = _runtime(vision, capture_dir=temp)
            latency: dict[str, float] = {}
            runtime._observe(Path(temp) / "frame.png", latency=latency, phase="before")

        self.assertEqual(vision.observations, 1)
        self.assertEqual(latency.get("observe_before_widened"), None)


class ProductionVisionWiringTests(unittest.TestCase):
    """The attention is only reachable if the object the loop watches exposes it."""

    def test_hybrid_vision_does_not_expose_focus(self):
        # Documenting the defect rather than asserting the desired behaviour: this is what makes
        # ``getattr(self.vision, "focus", None)`` None in production today.  When ``HybridVision``
        # gains a forwarder this test must change with it -- see ``SemanticWorldVision.focus``,
        # which exists for exactly this reason.
        from winter_agent_v2.ocr import HybridVision

        self.assertFalse(hasattr(HybridVision, "focus"))
        self.assertFalse(hasattr(HybridVision, "__getattr__"))

    def test_the_object_that_has_focus_is_the_one_the_observation_reads(self):
        from winter_agent_v2.ocr import HybridVision, OCRService

        class _World:
            def __init__(self) -> None:
                self.focused: dict = {}

            def focus(self, **kwargs) -> None:
                self.focused = kwargs

            def observe(self, path):
                return WorldState(page=Page.HOME, confidence=0.98)

            def sweeps_skipped(self) -> dict:
                return {}

        world = _World()
        hybrid = HybridVision(world, OCRService.__new__(OCRService))
        # ``HybridVision.observe`` forwards to ``self.template_vision.observe`` and
        # ``HybridVision`` keeps no attention of its own, so the attention that governs a
        # production look is the one held by this object -- not by the wrapper the loop sees.
        self.assertIs(hybrid.template_vision, world)
        source = (Path(__file__).resolve().parents[1] / "winter_agent_v2/ocr.py").read_text(
            encoding="utf-8")
        observe_body = source[source.index("    def observe(self, image_path: Path) -> WorldState:"
                                           ):]
        self.assertIn("self.template_vision.observe(image_path)", observe_body[:2000])

    def test_run_live_wires_hybrid_vision_as_the_runtime_vision(self):
        source = (Path(__file__).resolve().parents[1] / "tools/run_live.py").read_text(encoding="utf-8")
        self.assertIn("vision=vision", source)
        self.assertIn("HybridVision(", source)
        # The semantic ROI helper goes to ``semantic_vision``; it must never be handed over as
        # ``vision``, because ``_observe`` reads the attention off ``self.vision``.
        self.assertIn("semantic_vision=template.semantic", source)
        self.assertNotIn("\n        vision=template.semantic", source)


if __name__ == "__main__":
    unittest.main()
