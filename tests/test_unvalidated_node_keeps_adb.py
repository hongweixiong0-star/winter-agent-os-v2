"""A route can be green in unit tests and dead in production.  This pins the route.

WB-1002-22.

The previous round answered ``BTN_SELECTED_BUILDING_UPGRADE`` from the frame itself and wrote
``tests/test_building_upgrade_entry_target.py`` for it.  Every one of those tests passes -- and the
step still failed **10 times out of 10** the next day, because the routing file declared
``preferred: MAA`` with an autogen template node while ``ExecutorRouter.execute`` tries the
preferred backend first.  ``maa_resolver`` answers a miss with ``None`` and does not fall through,
which is deliberate (see
``test_executor_router.test_recognition_miss_blocks_instead_of_falling_back_to_a_blind_matcher``): a
legacy resolver that compares a fixed ROI is position-blind, so a miss must not become a blind tap.
The runtime resolver holding this answer is not position-blind -- it reads the frame's own 升级 token
-- but nothing in the routing file said so, so it was never consulted.

The operator's rule the node never met is written in ``executor_router``'s own module docstring:

    recognition -- Migrated per semantic, only after a node is authored *and* drawn on a real frame
    for visual check, and only after an A/B shows it is not worse than the legacy matcher.
    ... The operator's rule "if MAA did not improve it, keep ADB" is enforced by the routing file.

Measured 2026-10-02 (full reasons recorded inside ``knowledge/execution/backend_routing.json``):

* 10 attempts, 0 successes for ``OPEN_BUILDING_UPGRADE``, every one
  ``SEMANTIC_TARGET_NOT_VERIFIED`` carrying ``MAA_TEMPLATE:NO_MATCH:score=0.5146:gate=0.7/0.75``;
* the node's ROI is x 335..483, y 288..432; the frame's own reading of the 升级 label is
  ``(0.4993, 0.7188)`` = px (359, 920).  The window contains snow and a wall, not the control;
* the harvested template *is* the right icon (blue hexagon, white curved arrow) -- the harvest baked
  in the ROI of the frame it was cropped from, and this control is drawn wherever the selected
  building happens to sit.

The retirement follows the file's own precedent, ``SEARCH_RESOURCE``: empty the ``recognition`` dict,
declare ``LEGACY``, and record the measurement under ``not_migrated["<SKILL>_RECOGNITION"]``.
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

from winter_agent_v2.executor import Executor  # noqa: E402
from winter_agent_v2.executor_router import (  # noqa: E402
    ADB,
    MAA,
    BackendLedger,
    ExecutorRouter,
    RoutingTable,
)
from winter_agent_v2.models import Action, Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

ROUTING = ROOT / "knowledge/execution/backend_routing.json"
SKILL = "OPEN_BUILDING_UPGRADE"
SEMANTIC = "BTN_SELECTED_BUILDING_UPGRADE"
LEGACY_KEY = f"{SKILL}_RECOGNITION"
TEMPLATE_ASSET = "dataset/candidate/autogen/btn_selected_building_upgrade__rect_300f6cc7.png"

#: The reading the live episode recorded for the frame the step failed on.
LIVE_BUILDING = {
    "id": "UNKNOWN",
    "name": "城墙",
    "level": 8,
    "target_level": 9,
    "identity_confidence": 0.9981153905391693,
    "identity_source": "FLOATING_LABEL_OCR+QUEST_BANNER",
    "upgrade_tap_norm": [0.4993, 0.7188],
}


def _payload() -> dict:
    return json.loads(ROUTING.read_text(encoding="utf-8"))


class _StubDevice:
    """Minimal device: records taps, never touches a real client."""

    def __init__(self, *, capture_backend: str = "STUB_CAPTURE") -> None:
        self.taps: list[tuple[int, int]] = []
        self.capture_backend = capture_backend

    def status(self):
        from winter_agent_v2.device import DeviceStatus

        return DeviceStatus(True, "stub", (720, 1280), None)

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def press_back(self) -> None:
        pass

    def swipe(self, *_args, **_kwargs) -> None:
        pass


class TheRouteReachesTheResolverThatAnswersTests(unittest.TestCase):
    def test_the_route_for_this_skill_does_not_prefer_the_node_that_never_answered(self) -> None:
        route = RoutingTable.load().route(SKILL)
        self.assertEqual(route.preferred, ADB, SKILL)
        self.assertEqual(route.fallback, MAA, "ADB cannot capture; the device fallback stays MAA")

    def test_the_route_and_the_resolver_together_answer_the_step_that_failed(self) -> None:
        """The whole chain, not either half of it.

        The previous round proved the resolver answers and stopped there.  This asserts the route
        that makes the resolver reachable, and then that the answer is the recorded one -- so a
        regression in either half fails here.
        """
        route = RoutingTable.load().route(SKILL)
        self.assertEqual(route.preferred, ADB)
        world = WorldState(page=Page.HOME, confidence=0.98, building=dict(LIVE_BUILDING))
        skill = v2_registry().get(SKILL)
        self.assertIsNotNone(skill)
        runtime = LiveRuntime.__new__(LiveRuntime)
        self.assertEqual(
            runtime._resolve_semantic_target(skill.action.target, world),
            (0.4993, 0.7188),
        )

    def test_the_preferred_backend_actually_runs_first(self) -> None:
        """``execute`` iterates ``[preferred, fallback]``; with ADB preferred the node is never asked.

        Pinned at the router rather than read off the file, because that is where the previous
        round's fix was lost: the file said MAA, so MAA ran, and the runtime resolver never did.
        """
        adb_device = _StubDevice()
        maa_device = _StubDevice(capture_backend="MAA_MUMU_EXTRAS")
        asked: list[str] = []

        class _Adapter:
            unavailable_reason = None
            capture_backend = "MAA_MUMU_EXTRAS"

            def available(self_inner):
                return True

        def adb_resolve(semantic: str):
            asked.append(f"ADB:{semantic}")
            return (0.4993, 0.7188)

        def maa_resolve(semantic: str):
            asked.append(f"MAA:{semantic}")
            return None

        with tempfile.TemporaryDirectory() as tmp:
            router = ExecutorRouter(
                adb_executor=Executor(production=True, dry_run=False, device=adb_device,
                                      target_resolver=adb_resolve, backend=ADB),
                maa_adapter=_Adapter(),
                routing=RoutingTable.load(),
                ledger=BackendLedger(path=Path(tmp) / "ledger.jsonl"),
                adb_resolver=adb_resolve,
            )
            router.maa_executor = Executor(production=True, dry_run=False, device=maa_device,
                                           target_resolver=maa_resolve, backend=MAA)
            result = router.execute(Action("TAP_SEMANTIC", SEMANTIC), skill_id=SKILL)

        self.assertTrue(result.executed)
        self.assertEqual(result.backend, ADB)
        self.assertEqual(len(adb_device.taps), 1)
        self.assertEqual(maa_device.taps, [], "the node that never answered must not be asked")
        self.assertEqual(asked, [f"ADB:{SEMANTIC}"])


class TheRetirementIsRecordedTests(unittest.TestCase):
    """The routing file is evidence-gated; a retirement is an evidence claim like any other."""

    def test_the_node_is_retired_the_way_this_file_retires_nodes(self) -> None:
        """Empty ``recognition`` + ``LEGACY``, exactly like ``SEARCH_RESOURCE``.

        A node left beside a LEGACY declaration is forbidden outright by
        ``test_recognition_backend_declaration`` -- the node would silently override the
        declaration -- so retiring by removal is the file's convention and not a style choice.
        """
        entry = _payload()["skills"][SKILL]
        self.assertEqual(entry["preferred"], ADB)
        self.assertEqual(entry["recognition_backend"], "LEGACY")
        self.assertFalse(entry.get("recognition"), "a retired node must not stay wired")

    def test_the_retirement_records_the_measurement_where_a_reader_looks(self) -> None:
        record = (_payload().get("not_migrated") or {}).get(LEGACY_KEY) or {}
        self.assertEqual(record.get("semantic"), SEMANTIC, "the key names the skill, the record the semantic")
        self.assertTrue(record.get("measured_at"))
        reason = record.get("reason") or ""
        # The number is what makes this checkable later: a near-miss and a window in the wrong
        # place are different fixes, and this one is the second.
        self.assertIn("0.5146", reason)
        self.assertIn("0.4993", reason)

    def test_the_asset_is_kept_so_a_remeasurement_starts_from_the_picture(self) -> None:
        entry = _payload()["skills"][SKILL]
        evidence = entry.get("evidence") or {}
        record = evidence.get("measured_record") or {}
        self.assertEqual(record.get("attempts"), 10)
        self.assertEqual(record.get("successes"), 0)
        self.assertEqual(record.get("node_roi"), [335, 288, 148, 144])
        self.assertEqual(record.get("frame_declared_control_norm"), [0.4993, 0.7188])
        self.assertEqual(record.get("template_kept_at"), TEMPLATE_ASSET)
        self.assertTrue((ROOT / TEMPLATE_ASSET).is_file(),
                        "the picture is the right icon; keep it for the re-measurement")

    def test_a_demotion_must_be_recorded_and_a_route_may_not_claim_unreachable_recognition(self) -> None:
        """Two whole-table claims, enumerated from the file rather than from this one example.

        * every skill carrying a ``demotion_reason`` must also appear in ``not_migrated`` with a
          reason -- otherwise a demotion becomes a quiet way to disable a node;
        * ``recognition_backend == "MAA"`` may never sit beside a route that is not MAA, because
          the MAA resolver is only reachable when ``preferred`` is MAA.  That is the contradiction
          this round found in ``pipeline_autogen``, and it is checkable on the data.
        """
        payload = _payload()
        not_migrated = payload.get("not_migrated") or {}
        recorded_semantics = {str(v.get("semantic") or "") for v in not_migrated.values()}

        demoted = {sid: entry for sid, entry in payload["skills"].items()
                   if (entry.get("evidence") or {}).get("demotion_reason")}
        self.assertIn(SKILL, demoted, "the case this file was written for")
        for skill_id, entry in demoted.items():
            self.assertTrue(
                any(semantic and semantic in json.dumps(entry, ensure_ascii=False)
                    for semantic in recorded_semantics),
                f"{skill_id} is demoted but no not_migrated record names its semantic",
            )

        unreachable = {sid: entry for sid, entry in payload["skills"].items()
                       if str(entry.get("recognition_backend")) == MAA
                       and entry.get("preferred") != MAA}
        self.assertEqual(unreachable, {},
                         "these skills name a recogniser their own route can never call")


if __name__ == "__main__":
    unittest.main()
