"""Executor router + backend chain: the invariants that keep MAA honest.

These are pure-logic tests (no device).  They exist because the router is the one
place where a bug can silently tap the game twice, or claim MAA ran when it did
not - both of which would corrupt the production episode stream.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.executor import Executor
from winter_agent_v2.executor_router import (
    ADB,
    MAA,
    BackendLedger,
    ExecutorRouter,
    Route,
    RoutingTable,
)
from winter_agent_v2.learning import Episode
from winter_agent_v2.models import Action, ExecutionResult
from winter_agent_v2.runtime import _executor_label


class _StubDevice:
    """Minimal device: records taps, never touches a real client."""

    def __init__(self, *, connected: bool = True, capture_backend: str = "STUB_CAPTURE") -> None:
        self.taps: list[tuple[int, int]] = []
        self.connected = connected
        self.capture_backend = capture_backend

    def status(self):
        from winter_agent_v2.device import DeviceStatus
        return DeviceStatus(self.connected, "stub", (720, 1280) if self.connected else None, None)

    def tap(self, x: int, y: int) -> None:
        if not self.connected:
            raise RuntimeError("offline")
        self.taps.append((x, y))

    def press_back(self) -> None:
        pass

    def swipe(self, *_args, **_kwargs) -> None:
        pass


def _executor(device, resolver, backend: str) -> Executor:
    return Executor(production=True, dry_run=False, device=device, target_resolver=resolver,
                    backend=backend)


class RoutingTableTests(unittest.TestCase):
    def test_unknown_skill_keeps_the_historical_adb_path(self) -> None:
        table = RoutingTable(skills={})
        route = table.route("SOME_SKILL")
        self.assertEqual((route.preferred, route.fallback), (ADB, ADB))
        self.assertEqual(route.source, "default")

    def test_promoted_skills_route_to_maa_with_adb_fallback(self) -> None:
        table = RoutingTable.load()
        promoted = {sid: entry for sid, entry in table.skills.items()
                    if entry.get("preferred") == MAA}
        # The operator asked for at least five high-frequency skills.
        self.assertGreaterEqual(len(promoted), 5, sorted(promoted))
        for skill_id, entry in promoted.items():
            self.assertEqual(entry.get("fallback"), ADB, skill_id)
            self.assertEqual(entry.get("migration_priority"), "P0", skill_id)
            # A promoted skill must carry its evidence, so it cannot be promoted
            # by accident or by optimism.
            self.assertTrue(entry.get("evidence"), skill_id)

    def test_battle_button_node_threshold_is_declared(self) -> None:
        table = RoutingTable.load()
        node = table.recognition_node("INTEL_HERO_DISPATCH", "BTN_HERO_FIGHT")
        self.assertIsNotNone(node)
        self.assertIn(0.6, node["threshold"])

    def test_not_migrated_semantics_are_recorded_with_a_reason(self) -> None:
        payload = json.loads((ROOT / "knowledge/execution/backend_routing.json")
                             .read_text(encoding="utf-8"))
        for semantic, entry in (payload.get("not_migrated") or {}).items():
            self.assertTrue(entry.get("reason"), semantic)


class FallbackInvariantTests(unittest.TestCase):
    def _router(self, ledger_path: Path, *, maa_available: bool):
        adb_device = _StubDevice()
        maa_device = _StubDevice()

        class _Adapter:
            unavailable_reason = None if maa_available else "MAA_TEST_DOWN"
            capture_backend = "MAA_MUMU_EXTRAS"

            def available(self_inner):
                return maa_available

            def frame(self_inner):
                return None

        adapter = _Adapter()
        resolver = lambda _semantic: (0.5, 0.5)  # noqa: E731
        router = ExecutorRouter(
            adb_executor=_executor(adb_device, resolver, ADB),
            maa_adapter=adapter,
            routing=RoutingTable(skills={
                "TEST_SKILL": {"preferred": MAA, "fallback": ADB, "migration_priority": "P0"},
            }),
            ledger=BackendLedger(path=ledger_path),
            adb_resolver=resolver,
        )
        router.maa_executor = _executor(maa_device, resolver, MAA)
        return router, adb_device, maa_device

    def test_unavailable_maa_falls_back_to_adb_and_records_the_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            router, adb_device, maa_device = self._router(ledger, maa_available=False)
            result = router.execute(Action("TAP_SEMANTIC", "BTN_X"), skill_id="TEST_SKILL")
            self.assertTrue(result.executed)
            self.assertEqual(result.backend, ADB)
            self.assertEqual(len(adb_device.taps), 1)
            self.assertEqual(maa_device.taps, [])
            row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["used_backend"], ADB)
            self.assertTrue(row["fallback_used"])
            self.assertEqual(row["attempts"][0]["skipped"], "MAA_TEST_DOWN")

    def test_never_falls_back_after_an_input_was_already_issued(self) -> None:
        """A tap that landed but did not verify must not be repeated on ADB."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            router, adb_device, maa_device = self._router(ledger, maa_available=True)
            # The MAA executor taps, so ``executed`` is True and the router must
            # stop there even though the verifier has not run yet.
            result = router.execute(Action("TAP_SEMANTIC", "BTN_X"), skill_id="TEST_SKILL")
            self.assertTrue(result.executed)
            self.assertEqual(result.backend, MAA)
            self.assertEqual(len(maa_device.taps), 1)
            self.assertEqual(adb_device.taps, [], "ADB must not double-tap after a MAA tap")

    def test_recognition_miss_blocks_instead_of_falling_back_to_a_blind_matcher(self) -> None:
        """A MAA recognition miss must NOT be retried on the legacy resolver.

        The legacy path resolves a target by comparing a fixed ROI, so it is
        position-blind: if MAA could not find the control, the legacy matcher
        would still hand back a coordinate and the router would tap a button that
        is not there.  "Missing button blocks" is the project's documented
        unknown-policy, so the correct outcome is a refusal, not a retry.
        """
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            adb_device = _StubDevice()
            maa_device = _StubDevice(capture_backend="MAA_MUMU_EXTRAS")

            class _Adapter:
                unavailable_reason = None
                capture_backend = "MAA_MUMU_EXTRAS"

                def available(self_inner):
                    return True

            router = ExecutorRouter(
                adb_executor=_executor(adb_device, lambda _s: (0.5, 0.5), ADB),
                maa_adapter=_Adapter(),
                routing=RoutingTable(skills={
                    "TEST_SKILL": {"preferred": MAA, "fallback": ADB},
                }),
                ledger=BackendLedger(path=ledger),
                adb_resolver=lambda _s: (0.5, 0.5),
            )
            router.maa_executor = _executor(maa_device, lambda _s: None, MAA)
            result = router.execute(Action("TAP_SEMANTIC", "BTN_X"), skill_id="TEST_SKILL")
            self.assertFalse(result.executed)
            self.assertEqual(result.error, "SEMANTIC_TARGET_NOT_VERIFIED")
            self.assertEqual(maa_device.taps, [])
            self.assertEqual(adb_device.taps, [], "a recognition miss must not become a blind tap")

    def test_backend_level_failure_does_fall_back_to_adb(self) -> None:
        """A dead backend is different from an unresolved target: retry the peer."""
        with tempfile.TemporaryDirectory() as tmp:
            adb_device = _StubDevice()
            maa_device = _StubDevice(connected=False, capture_backend="MAA_MUMU_EXTRAS")

            class _Adapter:
                unavailable_reason = None
                capture_backend = "MAA_MUMU_EXTRAS"

                def available(self_inner):
                    return True

            router = ExecutorRouter(
                adb_executor=_executor(adb_device, lambda _s: (0.5, 0.5), ADB),
                maa_adapter=_Adapter(),
                routing=RoutingTable(skills={
                    "TEST_SKILL": {"preferred": MAA, "fallback": ADB},
                }),
                ledger=BackendLedger(path=Path(tmp) / "ledger.jsonl"),
                adb_resolver=lambda _s: (0.5, 0.5),
            )
            router.maa_executor = _executor(maa_device, lambda _s: (0.5, 0.5), MAA)
            result = router.execute(Action("TAP_SEMANTIC", "BTN_X"), skill_id="TEST_SKILL")
            self.assertTrue(result.executed)
            self.assertEqual(result.backend, ADB)
            self.assertEqual(len(adb_device.taps), 1)


class ResolverTierTests(unittest.TestCase):
    """The resolver must delegate when a skill has no MAA node, and must not guess."""

    def _router(self, *, node: dict | None, adapter_hit: bool, delegation: float | None):
        class _Adapter:
            unavailable_reason = None
            capture_backend = "MAA_MUMU_EXTRAS"

            def available(self_inner):
                return True

            def frame(self_inner):
                return "frame"

            def find(self_inner, _frame, semantic, **_kw):
                from winter_agent_v2.maa_executor import RecognitionOutcome
                return RecognitionOutcome(
                    adapter_hit, semantic,
                    box=(100, 100, 20, 20) if adapter_hit else None,
                    image_size=(720, 1280),
                )

        entry = {"preferred": MAA, "fallback": ADB}
        if node:
            entry["recognition"] = {"BTN_X": node}
        return ExecutorRouter(
            adb_executor=_executor(_StubDevice(), None, ADB),
            maa_adapter=_Adapter(),
            routing=RoutingTable(skills={"TEST_SKILL": entry}),
            ledger=BackendLedger(path=Path(tempfile.mkdtemp()) / "l.jsonl"),
            adb_resolver=lambda _s: delegation,
        )

    def test_promoted_skill_without_a_node_keeps_the_v2_resolver(self) -> None:
        router = self._router(node=None, adapter_hit=False, delegation=(0.42, 0.58))
        self.assertEqual(router.maa_resolver("BTN_X", "TEST_SKILL"), (0.42, 0.58))

    def test_node_present_uses_maa_recognition(self) -> None:
        router = self._router(node={"template": "BTN_X", "threshold": [0.7]},
                              adapter_hit=True, delegation=(0.99, 0.99))
        centre = router.maa_resolver("BTN_X", "TEST_SKILL")
        self.assertIsNotNone(centre)
        self.assertNotEqual(centre, (0.99, 0.99), "must not delegate when a node exists")

    def test_node_that_misses_refuses_instead_of_delegating(self) -> None:
        router = self._router(node={"template": "BTN_X", "threshold": [0.7]},
                              adapter_hit=False, delegation=(0.99, 0.99))
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))


class MaaFrameChannelTests(unittest.TestCase):
    """MaaFramework screencaps are BGR; this project's whole pixel path is RGB.

    Regression for 2026-09-14.  The MAA capture path handed BGR frames to both
    the matcher and the evidence writer, so the V2 vision read the live Hero
    Journey card as ``UNKNOWN / confidence 0.00`` and MAA's own matcher scored
    the matching template 0.6879 against a 0.7 threshold - just under it, which
    means colour-bearing templates fail or pass at random instead of failing
    loudly.  The card was invisible to AUTO while it sat on screen.
    """

    EVIDENCE = (
        ROOT / "dataset" / "truth_audit" / "hero_journey_card_variants_20260914"
        / "maa_captured_BGR_frame.png"
    )

    def test_bgr_capture_becomes_rgb(self) -> None:
        import numpy as np

        from winter_agent_v2.maa_executor import to_rgb_frame

        # A blue pixel as MaaFramework stores it must come out blue in RGB order.
        self.assertEqual(
            tuple(to_rgb_frame(np.array([[[222, 152, 98]]], dtype=np.uint8))[0, 0]),
            (98, 152, 222),
        )

    def test_frames_without_three_channels_pass_through(self) -> None:
        import numpy as np

        from winter_agent_v2.maa_executor import to_rgb_frame

        self.assertEqual(to_rgb_frame(np.zeros((4, 4), dtype=np.uint8)).shape, (4, 4))

    def test_evidence_frame_matches_the_rgb_template_only_after_conversion(self) -> None:
        import numpy as np
        from PIL import Image

        from winter_agent_v2.maa_executor import to_rgb_frame
        from winter_agent_v2.matchers import match_ccoeff

        if not self.EVIDENCE.is_file():
            self.skipTest("MAA evidence frame is not present on this machine")

        manifest = json.loads(
            (ROOT / "dataset" / "candidate" / "template_manifest.json").read_text(encoding="utf-8")
        )
        record = next(
            r for r in manifest["records"]
            if r.get("semantic") == "POPUP_INTEL_HERO_JOURNEY_TITLE"
        )

        as_captured = match_ccoeff(self.EVIDENCE, Path(record["template_path"]), record["roi_norm"])
        self.assertIsNotNone(as_captured)

        with tempfile.TemporaryDirectory() as temp:
            converted = Path(temp) / "rgb.png"
            with Image.open(self.EVIDENCE) as source:
                Image.fromarray(to_rgb_frame(np.asarray(source.convert("RGB")))).save(converted)
            fixed = match_ccoeff(converted, Path(record["template_path"]), record["roi_norm"])

        self.assertIsNotNone(fixed)
        # The as-captured pixels must score clearly worse than the corrected ones.
        self.assertLess(as_captured.score, fixed.score)
        self.assertGreater(fixed.score, 0.98)


class BackendChainTests(unittest.TestCase):
    def test_recognition_backend_is_v2_when_the_skill_has_no_maa_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adb_device = _StubDevice()
            maa_device = _StubDevice(capture_backend="MAA_MUMU_EXTRAS")

            class _Adapter:
                unavailable_reason = None
                capture_backend = "MAA_MUMU_EXTRAS"

                def available(self_inner):
                    return True

            table = RoutingTable(skills={
                "TEST_SKILL": {"preferred": MAA, "fallback": ADB},
            })
            router = ExecutorRouter(
                adb_executor=_executor(adb_device, None, ADB),
                maa_adapter=_Adapter(),
                routing=table,
                ledger=BackendLedger(path=Path(tmp) / "l.jsonl"),
                adb_resolver=lambda _s: (0.5, 0.5),
            )
            router.maa_executor = _executor(maa_device, lambda _s: (0.4, 0.4), MAA)
            result = router.execute(Action("TAP_SEMANTIC", "BTN_X"), skill_id="TEST_SKILL")
            self.assertEqual(result.backend, MAA)
            self.assertEqual(result.recognition_backend, "V2")
            self.assertEqual(result.capture_backend, "MAA_MUMU_EXTRAS")
            # MAA drove the screen, V2 found the target: that is HYBRID, not MAA.
            self.assertEqual(_executor_label(result), "HYBRID")

    def test_executor_label_classifies_all_four_chains(self) -> None:
        cases = {
            ("MAA", "MAA"): "MAA",
            ("MAA", "NONE"): "MAA",
            ("MAA", "V2"): "HYBRID",
            ("ADB", "V2"): "ADB",
        }
        for (backend, recognition), expected in cases.items():
            result = ExecutionResult(True, False, Action("TAP_SEMANTIC", "X"), None,
                                     backend=backend, recognition_backend=recognition)
            self.assertEqual(_executor_label(result), expected, (backend, recognition))

    def test_nothing_issued_credits_no_backend(self) -> None:
        self.assertEqual(_executor_label(None), "")
        self.assertEqual(
            _executor_label(ExecutionResult(False, False, Action("TAP_SEMANTIC", "X"), "NO")), ""
        )

    def test_episode_carries_the_whole_chain(self) -> None:
        fields = Episode.__dataclass_fields__
        for name in ("executor_backend", "capture_backend", "recognition_backend", "action_backend"):
            self.assertIn(name, fields)
        self.assertIsInstance(Episode("S", {}, {}, {}, "SUCCESS", None, 0.0, "PRODUCTION").capture_backend, str)


if __name__ == "__main__":
    unittest.main()
