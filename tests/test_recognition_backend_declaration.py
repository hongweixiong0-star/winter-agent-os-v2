"""A skill's declared recogniser decides who answers -- and a node may not override it.

Root cause this pins (measured 2026-09-30).  ``SEARCH_RESOURCE`` declares
``recognition_backend: "LEGACY"`` ("Its recognition is V2 semantic... which MAA
template matching does not improve on its own") yet carried a MAA recognition node
(``node_20260927``) promoted from a single frame with no A/B.  ``maa_resolver``
consulted the node unconditionally, so the node always won -- and its template is the
legacy-wilderness crop, where the map search button still wore a filled blue disc.
The current client draws the same glyph as a transparent button over the live map, so
the node scored TM_CCOEFF_NORMED 0.609 against its own 0.78 gate.  A miss in that tier
is terminal, so every ``SEARCH_RESOURCE`` tap ended as ``SEMANTIC_TARGET_NOT_VERIFIED``
on frames where the declared V2 recogniser locates the same control at pHash distance
10 <= its 12 tolerance.

These are pure-logic tests (no device).  The one live-frame test degrades to a skip
when the recorded frame, numpy or cv2 is unavailable, so the suite stays green on a
machine without the corpus.
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
    RoutingTable,
)
from winter_agent_v2.models import Action

ROUTING_PATH = ROOT / "knowledge" / "execution" / "backend_routing.json"


def _executor(device, resolver, backend: str) -> Executor:
    return Executor(production=True, dry_run=False, device=device,
                    target_resolver=resolver, backend=backend)


class _Device:
    """Minimal device: records taps, never touches a real client."""

    def __init__(self, *, capture_backend: str = "STUB_CAPTURE") -> None:
        self.taps: list[tuple[int, int]] = []
        self.capture_backend = capture_backend

    def status(self):
        from winter_agent_v2.device import DeviceStatus
        return DeviceStatus(True, "stub", (720, 1280), None)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))


class _NodeMustNotBeConsulted:
    """Adapter whose ``find`` fails the test if the node is reached."""

    unavailable_reason = None
    capture_backend = "MAA_MUMU_EXTRAS"

    def __init__(self) -> None:
        self.find_calls = 0

    def available(self) -> bool:
        return True

    def frame(self):  # pragma: no cover - only reached if the bug returns
        return "frame"

    def find(self, *_a, **_kw):  # pragma: no cover - the test asserts 0 calls
        self.find_calls += 1
        raise AssertionError("a node was consulted for a LEGACY-declared skill")


class _NodeHits:
    """Adapter whose node match succeeds, so a node-based answer is observable."""

    unavailable_reason = None
    capture_backend = "MAA_MUMU_EXTRAS"

    def __init__(self) -> None:
        self.find_calls = 0

    def available(self) -> bool:
        return True

    def frame(self):
        return "frame"

    def find(self, _frame, semantic, **_kw):
        from winter_agent_v2.maa_executor import RecognitionOutcome
        self.find_calls += 1
        return RecognitionOutcome(True, semantic, box=(100, 100, 40, 40),
                                  image_size=(720, 1280))


def _router(skills: dict, adapter, *, legacy_point=(0.42, 0.58)):
    return ExecutorRouter(
        adb_executor=_executor(_Device(), lambda _s: legacy_point, ADB),
        maa_adapter=adapter,
        routing=RoutingTable(skills=skills),
        ledger=BackendLedger(path=Path(tempfile.mkdtemp()) / "ledger.jsonl"),
        adb_resolver=lambda _s: legacy_point,
    )


class RecognitionBackendDeclarationTest(unittest.TestCase):
    def test_legacy_declared_skill_does_not_consult_a_node(self) -> None:
        """A LEGACY declaration refuses an existing node and the declared matcher answers."""
        adapter = _NodeMustNotBeConsulted()
        router = _router(
            {"SEARCH_RESOURCE": {
                "preferred": MAA, "fallback": ADB, "recognition_backend": "LEGACY",
                "recognition": {"BTN_OPEN_RESOURCE_SEARCH": {"template": "BTN_OPEN_RESOURCE_SEARCH"}},
            }},
            adapter,
        )
        point = router.maa_resolver("BTN_OPEN_RESOURCE_SEARCH", "SEARCH_RESOURCE")
        self.assertEqual(point, (0.42, 0.58),
                         "the declared LEGACY recogniser must answer, not the node")
        self.assertEqual(adapter.find_calls, 0, "the node must not be consulted at all")

    def test_maa_declared_skill_still_uses_its_node(self) -> None:
        """An explicit MAA declaration keeps the node in charge (no regression)."""
        adapter = _NodeHits()
        router = _router(
            {"OPEN_HOME": {
                "preferred": MAA, "fallback": ADB, "recognition_backend": "MAA",
                "recognition": {"BTN_OPEN_HOME": {"template": "BTN_OPEN_HOME"}},
            }},
            adapter,
            legacy_point=(0.99, 0.99),
        )
        point = router.maa_resolver("BTN_OPEN_HOME", "OPEN_HOME")
        self.assertEqual(adapter.find_calls, 1, "a MAA-declared skill must reach its node")
        self.assertNotEqual(point, (0.99, 0.99), "must not delegate when the node is entitled")

    def test_undeclared_skill_keeps_the_historical_behaviour(self) -> None:
        """No ``recognition_backend`` key means the node, if present, answers."""
        adapter = _NodeHits()
        router = _router(
            {"SOME_SKILL": {
                "preferred": MAA, "fallback": ADB,
                "recognition": {"BTN_X": {"template": "BTN_X"}},
            }},
            adapter,
            legacy_point=(0.99, 0.99),
        )
        point = router.maa_resolver("BTN_X", "SOME_SKILL")
        self.assertEqual(adapter.find_calls, 1)
        self.assertNotEqual(point, (0.99, 0.99))

    def test_legacy_declared_failed_delegation_is_named_not_left_silent(self) -> None:
        """When the declared matcher also cannot answer, the reason says so."""
        adapter = _NodeMustNotBeConsulted()
        router = _router(
            {"SEARCH_RESOURCE": {
                "preferred": MAA, "fallback": ADB, "recognition_backend": "LEGACY",
                "recognition": {"BTN_OPEN_RESOURCE_SEARCH": {"template": "BTN_OPEN_RESOURCE_SEARCH"}},
            }},
            adapter,
            legacy_point=None,
        )
        self.assertIsNone(router.maa_resolver("BTN_OPEN_RESOURCE_SEARCH", "SEARCH_RESOURCE"))
        self.assertEqual(
            router.last_recognition_error,
            "RECOGNITION_BACKEND:LEGACY:NODE_NOT_ENTITLED",
        )

    def test_successful_delegation_leaves_no_error_marker(self) -> None:
        """A resolved point proves the declaration was right, so no failure is recorded."""
        router = _router(
            {"SEARCH_RESOURCE": {
                "preferred": MAA, "fallback": ADB, "recognition_backend": "LEGACY",
                "recognition": {"BTN_OPEN_RESOURCE_SEARCH": {"template": "BTN_OPEN_RESOURCE_SEARCH"}},
            }},
            _NodeMustNotBeConsulted(),
        )
        self.assertIsNotNone(router.maa_resolver("BTN_OPEN_RESOURCE_SEARCH", "SEARCH_RESOURCE"))
        self.assertIsNone(router.last_recognition_error)

    def test_a_legacy_declared_action_is_never_double_tapped(self) -> None:
        """The router's fallback invariant still holds through the new delegation path."""
        adb_device, maa_device = _Device(), _Device(capture_backend="MAA_MUMU_EXTRAS")
        router = ExecutorRouter(
            adb_executor=_executor(adb_device, lambda _s: (0.42, 0.58), ADB),
            maa_adapter=_NodeMustNotBeConsulted(),
            routing=RoutingTable(skills={"SEARCH_RESOURCE": {
                "preferred": MAA, "fallback": ADB, "recognition_backend": "LEGACY",
                "recognition": {"BTN_OPEN_RESOURCE_SEARCH": {"template": "BTN_OPEN_RESOURCE_SEARCH"}},
            }}),
            ledger=BackendLedger(path=Path(tempfile.mkdtemp()) / "ledger.jsonl"),
            adb_resolver=lambda _s: (0.42, 0.58),
        )
        router.maa_executor = _executor(maa_device, lambda _s: (0.42, 0.58), MAA)
        result = router.execute(Action("TAP_SEMANTIC", "BTN_OPEN_RESOURCE_SEARCH"),
                                skill_id="SEARCH_RESOURCE")
        self.assertTrue(result.executed)
        self.assertEqual(result.backend, MAA)
        self.assertEqual(len(maa_device.taps), 1)
        self.assertEqual(adb_device.taps, [], "ADB must not double-tap after a MAA tap")


class RoutingFileInvariantTest(unittest.TestCase):
    """The routing file itself must not contradict its own declarations."""

    def setUp(self) -> None:
        if not ROUTING_PATH.is_file():
            self.skipTest("routing file absent")
        self.payload = json.loads(ROUTING_PATH.read_text(encoding="utf-8"))

    def test_no_skill_declares_legacy_while_carrying_a_recognition_node(self) -> None:
        offenders = [
            skill_id
            for skill_id, entry in (self.payload.get("skills") or {}).items()
            if (entry.get("recognition") or {})
            and str(entry.get("recognition_backend", "")).strip().upper() == "LEGACY"
        ]
        self.assertEqual(
            offenders, [],
            "a skill that declares LEGACY recognition must not carry a MAA node: "
            "the node would silently override the declaration",
        )

    def test_search_resource_node_is_retired_with_a_reason(self) -> None:
        entry = (self.payload.get("skills") or {}).get("SEARCH_RESOURCE") or {}
        self.assertEqual(str(entry.get("recognition_backend", "")).upper(), "LEGACY")
        self.assertFalsy(entry.get("recognition"))
        retired = (self.payload.get("not_migrated") or {}).get("SEARCH_RESOURCE_RECOGNITION") or {}
        self.assertEqual(retired.get("semantic"), "BTN_OPEN_RESOURCE_SEARCH")
        self.assertIn("TM_CCOEFF_NORMED 0.609", retired.get("reason", ""))

    # ``assertFalsy`` is not on unittest.TestCase; state it once so the intent is readable.
    def assertFalsy(self, value) -> None:
        self.assertFalse(value, f"expected an empty/falsy value, got {value!r}")


class MeasuredFrameTest(unittest.TestCase):
    """The recorded frame that produced the failure resolves through the declared matcher."""

    FRAME = (ROOT / "dataset" / "raw" / "control_panel" / "runtime_auto"
             / "20260930_002432_782721"
             / "20260930_002432_782721_step_005_before_20260929T162544495247.png")

    def test_declared_legacy_matcher_locates_the_search_button_on_the_failure_frame(self) -> None:
        if not self.FRAME.is_file():
            self.skipTest("recorded frame absent")
        try:
            from winter_agent_v2.vision import SemanticROIVision
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"vision dependencies unavailable: {exc}")
        manifest = ROOT / "dataset" / "candidate" / "template_manifest.json"
        if not manifest.is_file():
            self.skipTest("template manifest absent")
        vision = SemanticROIVision(manifest, max_distance=8)
        match = vision.find(self.FRAME, "BTN_OPEN_RESOURCE_SEARCH")
        self.assertIsNotNone(
            match,
            "the declared recogniser must find the control the MAA node's stale template missed",
        )
        threshold = vision.semantic_max_distance.get("BTN_OPEN_RESOURCE_SEARCH", vision.max_distance)
        self.assertLessEqual(match.distance, threshold)
        x_norm, y_norm = match.center_norm
        # The magnifier sits in the lower-left HUD stack, not anywhere else on the frame.
        self.assertLess(x_norm, 0.2)
        self.assertGreater(y_norm, 0.6)


if __name__ == "__main__":
    unittest.main()
