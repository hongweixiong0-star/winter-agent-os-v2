"""The MAA node path must name its own refusals, like the ADB path already does.

Regression under test (2026-10-02)
----------------------------------
``WB-1002-11`` gave the ledger a ``recognition_error`` column, and ``WB-1002-13`` extended it to
the registered locator -- but both only ever fire on the ADB path.  ``build_router`` binds the MAA
executor's resolver to ``lambda semantic: router.maa_resolver(semantic, skill_id)``, which never
passes through the runtime's ``resolve``, so every miss decided inside ``maa_resolver`` was thrown
away.  Measured on the day's ledger, and the split is total rather than statistical: of the 31
``SEMANTIC_TARGET_NOT_VERIFIED`` rows whose revision carried the field, the 12 with an empty reason
were exactly the skills that *have* an MAA recognition node (``OPEN_HOME`` 6,
``OPEN_BUILDING_UPGRADE`` 4, ``OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT`` 2), while the 19 that did
name a reason were node-less skills (``SELECT_RESOURCE`` 15, ``SELECT_BEAST_TARGET_MAMMOTH`` 3,
``TRY_ORDINARY_CONTROL`` 1) that fall through to ``adb_resolver`` and therefore reach the runtime's
own recorder.  Empty and non-empty divide on that one fact.

The vocabulary already existed one layer down.  ``MaaExecutorAdapter.match_template`` returns a
``RecognitionOutcome`` on a miss carrying ``error`` (``NO_MATCH`` / ``TEMPLATE_NOT_REGISTERED:<n>``
/ ``MAA_NO_RECOGNITION_NODE`` / ``NO_FRAME`` / ``MAA_RECO_FAILED:<Exc>``), the measured ``score``
of its best candidate *even when it did not hit*, and ``algorithm``.  ``maa_resolver`` held that
object in ``last_outcome`` and then read only ``center_norm()``.

Why the score and not just a name: "the template scored 0.615 against a 0.70 gate" and "the
template was never loaded" send the next reader to two different fixes, and the first also says
whether the answer is to move the threshold or to replace the crop.  A reason that omits the number
cannot tell them apart.
"""

from __future__ import annotations

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
from winter_agent_v2.maa_executor import RecognitionOutcome  # noqa: E402


class _StubDevice:
    """Minimal device: never touches a real client."""

    capture_backend = "STUB_CAPTURE"

    def status(self):
        from winter_agent_v2.device import DeviceStatus
        return DeviceStatus(True, "stub", (720, 1280), None)

    def tap(self, *_args) -> None:
        pass

    def press_back(self) -> None:
        pass

    def swipe(self, *_args, **_kwargs) -> None:
        pass


class _Adapter:
    """Just enough MAA adapter for ``maa_resolver``: a frame and a ``find``."""

    unavailable_reason = None
    capture_backend = "MAA_MUMU_EXTRAS"

    def __init__(self, *, frame="frame", outcome: RecognitionOutcome | None = None) -> None:
        self._frame = frame
        self._outcome = outcome
        self.calls = 0

    def available(self) -> bool:
        return True

    def frame(self):
        return self._frame

    def find(self, _frame, semantic, **_kw) -> RecognitionOutcome:
        self.calls += 1
        if self._outcome is not None:
            return self._outcome
        return RecognitionOutcome(False, semantic, error="NO_MATCH", score=0.615,
                                  algorithm="TemplateMatch", image_size=(720, 1280))


def _router(adapter: _Adapter, *, node: dict | None,
            delegation=(0.42, 0.58)) -> ExecutorRouter:
    entry: dict = {"preferred": MAA, "fallback": ADB}
    if node is not None:
        entry["recognition"] = {"BTN_X": node}
    return ExecutorRouter(
        adb_executor=Executor(production=True, dry_run=False, device=_StubDevice(),
                              target_resolver=None, backend=ADB),
        maa_adapter=adapter,
        routing=RoutingTable(skills={"TEST_SKILL": entry}),
        ledger=BackendLedger(path=Path(tempfile.mkdtemp()) / "l.jsonl"),
        adb_resolver=lambda _s: delegation,
    )


TEMPLATE_NODE = {"template": "BTN_X", "threshold": [0.7, 0.75]}


class MaaNodeRefusalIsNamedTest(unittest.TestCase):
    def test_a_template_miss_carries_the_score_it_actually_reached(self):
        """The one number that separates 'move the gate' from 'replace the crop'."""
        router = _router(_Adapter(), node=TEMPLATE_NODE)
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        reason = str(router.last_recognition_error or "")
        self.assertTrue(reason.startswith("MAA_TEMPLATE:NO_MATCH"), reason)
        self.assertIn("score=0.6150", reason)
        self.assertIn("gate=0.7/0.75", reason)

    def test_a_miss_without_a_score_says_so_instead_of_inventing_one(self):
        router = _router(_Adapter(outcome=RecognitionOutcome(
            False, "BTN_X", error="NO_MATCH", score=None, image_size=(720, 1280))),
            node=TEMPLATE_NODE)
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        reason = str(router.last_recognition_error or "")
        self.assertIn("score=na", reason)

    def test_an_unregistered_template_is_not_reported_as_a_miss(self):
        """Two different fixes: reload the crop, or accept the control is not drawn."""
        router = _router(_Adapter(outcome=RecognitionOutcome(
            False, "BTN_X", error="TEMPLATE_NOT_REGISTERED:BTN_X", image_size=(720, 1280))),
            node=TEMPLATE_NODE)
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        reason = str(router.last_recognition_error or "")
        self.assertIn("TEMPLATE_NOT_REGISTERED", reason)
        self.assertNotIn("NO_MATCH", reason)

    def test_an_adapter_failure_keeps_its_exception_name(self):
        router = _router(_Adapter(outcome=RecognitionOutcome(
            False, "BTN_X", error="MAA_RECO_FAILED:TimeoutError")), node=TEMPLATE_NODE)
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        self.assertIn("MAA_RECO_FAILED:TimeoutError", str(router.last_recognition_error or ""))

    def test_no_frame_is_its_own_refusal(self):
        """The adapter answered without a frame: nothing was ever searched."""
        router = _router(_Adapter(frame=None), node=TEMPLATE_NODE)
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        self.assertEqual(router.last_recognition_error, "MAA_FRAME:NONE")

    def test_a_resolved_point_clears_the_reason(self):
        """A set value beside a resolved point reads as a live failure -- so it must not survive.

        This is the property the field has to have to be usable at all: ``runtime`` writes it into
        every episode row, including successful ones, so a stale code would put a failure reason on
        a step that worked.
        """
        hit = RecognitionOutcome(True, "BTN_X", box=(100, 100, 20, 20), image_size=(720, 1280))
        router = _router(_Adapter(outcome=hit), node=TEMPLATE_NODE)
        self.assertIsNotNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        self.assertIsNone(router.last_recognition_error)

    def test_a_delegated_miss_leaves_the_reason_to_the_resolver_that_owns_it(self):
        """With no node the router has nothing to say; the ADB recorder's reason must stand."""
        router = _router(_Adapter(), node=None, delegation=None)
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))
        self.assertIsNone(router.last_recognition_error)

    def test_a_delegated_hit_is_not_reported_as_a_refusal(self):
        router = _router(_Adapter(), node=None, delegation=(0.5, 0.5))
        self.assertEqual(router.maa_resolver("BTN_X", "TEST_SKILL"), (0.5, 0.5))
        self.assertIsNone(router.last_recognition_error)


class TheVerdictIsUnchangedTest(unittest.TestCase):
    """Every case above is a recorder: what the route *does* must not move."""

    def test_a_miss_is_still_a_miss_and_a_hit_still_returns_its_point(self):
        hit = RecognitionOutcome(True, "BTN_X", box=(200, 400, 20, 20), image_size=(720, 1280))
        missed = _router(_Adapter(), node=TEMPLATE_NODE).maa_resolver("BTN_X", "TEST_SKILL")
        self.assertIsNone(missed)
        point = _router(_Adapter(outcome=hit), node=TEMPLATE_NODE).maa_resolver("BTN_X", "TEST_SKILL")
        self.assertAlmostEqual(point[0], 210 / 720, places=6)
        self.assertAlmostEqual(point[1], 410 / 1280, places=6)

    def test_the_node_still_refuses_instead_of_delegating(self):
        """The tier invariant from test_executor_router must survive the recorder."""
        router = _router(_Adapter(), node=TEMPLATE_NODE, delegation=(0.99, 0.99))
        self.assertIsNone(router.maa_resolver("BTN_X", "TEST_SKILL"))


if __name__ == "__main__":
    unittest.main()
