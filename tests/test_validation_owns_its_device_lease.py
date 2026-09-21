"""A validation cycle must not yield to the lease it is itself holding.

Measured 2026-09-21, and it was the last link in a chain that kept a capability off the device
for 6.5 hours.  The window acquires the lease as ``DEVELOPMENT_VALIDATION`` and then spawns
``run_live`` as a child -- so the examining process is the child, while the lease record was
written by the parent.  The child's first iteration read that record, found an owner that was
not ``GAMEPLAY``, concluded a developer owned the device and yielded:

    {"steps": [], "stop_reason": "device_leased_for_development", "deferrals": []}

Every validation cycle exited ``EXIT_2`` with zero steps, which reads exactly like the operator's
AUTO correctly stepping aside.  It was the examination refusing to examine.  The lease was never
the obstacle; not knowing whose it was, was.

The guard itself is load-bearing and stays: an **AUTO** cycle must still yield to a real
examination, which is the operator's §19 property.  So the question had to become "does *someone
else* hold it", and the answer has two halves that must both be present -- this process is an
examination (``execution_mode``), and the holder is a ``DEVELOPMENT_VALIDATION``.

This file pins both halves, because either one alone would be a hole: dropping the mode check
would let AUTO play through an examination's lease, and dropping the owner check would let a
validation run while a *different* developer held the device.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.device_lease import (  # noqa: E402
    OWNER_DEVELOPMENT_VALIDATION,
    OWNER_GAMEPLAY,
)
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402


class _FakeVision:
    """One unbroken HOME frame, so the loop has something real to iterate on."""

    def __init__(self) -> None:
        self.state = WorldState(page=Page.HOME, confidence=0.99)

    def observe(self, _path):
        return self.state


class _FakeSemantic:
    semantic = property(lambda self: self)
    resource_tab_band = (0.0, 1.0)
    resource_level_minus = (0.5, 0.5)
    resource_tab_offset = None

    def find(self, _path, _semantic):
        return None

    def resource_cell_center_norm(self, _resource):
        return (0.5, 0.5)

    def resource_tab_swipe_for(self, _resource):
        return 0.0


class _FakeDevice:
    def __init__(self) -> None:
        self.taps: list[tuple] = []

    def screenshot(self, path):
        path.touch()
        return path

    def status(self):
        return type("Status", (), {"connected": True, "resolution": (720, 1280)})()

    def tap(self, x, y):
        self.taps.append((x, y))

    def press_back(self):
        self.taps.append(("back",))

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.taps.append(("swipe", x1, y1, x2, y2))


class _Lease:
    """A lease file that answers with one fixed holder -- the whole interface the guard uses."""

    def __init__(self, owner: str | None, capability_id: str = "OPEN_TRAINING_PAGE") -> None:
        self._owner = owner
        self._capability_id = capability_id

    def holder(self, **_kwargs):
        if self._owner is None:
            return None
        return type("Held", (), {"owner": self._owner, "capability_id": self._capability_id})()


def _runtime(*, execution_mode: str, lease_owner: str | None) -> LiveRuntime:
    return LiveRuntime(
        device=_FakeDevice(),
        vision=_FakeVision(),
        semantic_vision=_FakeSemantic(),
        capture_dir=Path(TemporaryDirectory().name),
        brain=RuleBrain(current_goal="TRAIN"),
        sleeper=lambda _seconds: None,
        device_lease=_Lease(lease_owner),
        execution_mode=execution_mode,
    )


class AValidationOwnsItsLeaseTests(unittest.TestCase):
    def test_a_validation_runs_under_the_lease_it_acquired(self):
        """The measured deadlock: this cycle must not yield to its own lock.

        Zero actions is the assertion that matters -- the guard is consulted at the top of the
        first iteration, so refusing produces ``steps: []`` and the run is over before any
        decision is made.
        """
        run = _runtime(
            execution_mode=OWNER_DEVELOPMENT_VALIDATION,
            lease_owner=OWNER_DEVELOPMENT_VALIDATION,
        ).run(max_actions=1)
        self.assertNotEqual(
            run.stop_reason, "device_leased_for_development",
            "the examination yielded to the lease it is itself holding",
        )

    def test_the_yield_reason_is_absent_from_the_result(self):
        """Stated on its own because the reason string is what the panel prints.

        The operator reads ``停止原因`` off the window; ``device_leased_for_development`` on a
        validation cycle is the sentence that made this look like correct behaviour for 6.5
        hours.
        """
        run = _runtime(
            execution_mode=OWNER_DEVELOPMENT_VALIDATION,
            lease_owner=OWNER_DEVELOPMENT_VALIDATION,
        ).run(max_actions=1)
        self.assertNotIn("device_leased_for_development", str(run.stop_reason or ""))


class ThePropertyItProtectsIsUnchangedTests(unittest.TestCase):
    def test_an_auto_cycle_still_yields_to_a_real_examination(self):
        """Operator §19, untouched: gameplay steps aside for a validation.

        This is the half that would break if the fix had simply deleted the guard.
        """
        run = _runtime(
            execution_mode="PRODUCTION",
            lease_owner=OWNER_DEVELOPMENT_VALIDATION,
        ).run(max_actions=3)
        self.assertEqual(run.stop_reason, "device_leased_for_development")
        # ``steps`` is a tuple on the result; the point is that it is empty, not its type.
        self.assertEqual(len(run.steps), 0, "AUTO must issue no action while an examination holds it")

    def test_a_validation_still_yields_to_a_different_owner(self):
        """Only a DEVELOPMENT_VALIDATION lease is *this* cycle's.

        A lease held for any other owner is somebody else's device, and an examination that ran
        through it would be a second UI owner -- the thing the lease exists to prevent.
        """
        run = _runtime(
            execution_mode=OWNER_DEVELOPMENT_VALIDATION,
            lease_owner="SOMEBODY_ELSE",
        ).run(max_actions=3)
        self.assertEqual(run.stop_reason, "device_leased_for_development")
        self.assertEqual(len(run.steps), 0)

    def test_no_lease_at_all_lets_both_modes_run(self):
        """``None`` is "gameplay owns the device", which is the state most runs are in."""
        for mode in ("PRODUCTION", OWNER_DEVELOPMENT_VALIDATION):
            run = _runtime(execution_mode=mode, lease_owner=None).run(max_actions=1)
            self.assertNotEqual(
                run.stop_reason, "device_leased_for_development",
                f"{mode} yielded although no lease is held",
            )


class TheDecisionIsTheTwoHalvesItClaimsTests(unittest.TestCase):
    """``_owns_the_lease`` in isolation, so each half is pinned rather than inferred."""

    def setUp(self) -> None:
        self.held = type("Held", (), {"owner": OWNER_DEVELOPMENT_VALIDATION, "capability_id": "x"})()

    def test_both_halves_present_is_own(self):
        runtime = _runtime(
            execution_mode=OWNER_DEVELOPMENT_VALIDATION, lease_owner=OWNER_DEVELOPMENT_VALIDATION,
        )
        self.assertTrue(runtime._owns_the_lease(self.held))

    def test_mode_alone_is_not_enough(self):
        runtime = _runtime(
            execution_mode=OWNER_DEVELOPMENT_VALIDATION, lease_owner=OWNER_DEVELOPMENT_VALIDATION,
        )
        other = type("Held", (), {"owner": OWNER_GAMEPLAY, "capability_id": "x"})()
        self.assertFalse(runtime._owns_the_lease(other))

    def test_owner_alone_is_not_enough(self):
        runtime = _runtime(execution_mode="PRODUCTION", lease_owner=OWNER_DEVELOPMENT_VALIDATION)
        self.assertFalse(runtime._owns_the_lease(self.held))

    def test_an_object_without_an_owner_answers_no(self):
        runtime = _runtime(
            execution_mode=OWNER_DEVELOPMENT_VALIDATION, lease_owner=OWNER_DEVELOPMENT_VALIDATION,
        )
        self.assertFalse(runtime._owns_the_lease(object()))


if __name__ == "__main__":
    unittest.main()
