"""Regression tests for the backend provenance truth audit.

WB-R19-BACKEND-PROVENANCE-TRUTH.  The audit exists because field completeness is
not truth: the ledger and the episode are written by the same runtime, so their
agreement proves only self-consistency.  The audit therefore cross-checks against
the MAA framework log, which the runtime does not write.

Two rules in the audit were wrong on the first pass and both were caught by
measurement, so both are pinned here:

1. MAA events must be attributed to exactly one ledger row.  A plain "+-N seconds"
   window credited an ADB step with the next step's key press (measured
   2026-09-15T13:35: the SELECT_INTEL_PIN row at 13:35:14.866 absorbed the BACK
   row's MaaControllerPostClickKey at 13:35:17.660), which read as a double-drive
   suspicion that did not exist.
2. ``capture_backend`` in the episode and in the ledger are the SAME NAME FOR TWO
   DIFFERENT FACTS -- the observation channel versus the executor's channel.  They
   must be reported as an ambiguity, never compared as if they were one fact, and
   never made equal to silence the report (that would falsify one of them).
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools/cq_backend_truth.py"

spec = importlib.util.spec_from_file_location("cq_backend_truth", TOOL)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def _row(stamp: str, **extra: object) -> dict:
    row = {"recorded_at": stamp}
    row.update(extra)
    return row


def _event(stamp: str, kind: str, coords: tuple[int, int] | None) -> tuple:
    return (datetime.fromisoformat(stamp), kind, coords, "")


# ----------------------------------------------------------- rule 1: attribution


def test_an_event_is_credited_to_exactly_one_row() -> None:
    ledger = [
        _row("2026-09-15T13:35:14.866+00:00", skill_id="SELECT_INTEL_PIN"),
        _row("2026-09-15T13:35:17.711+00:00", skill_id="BACK"),
    ]
    events = [_event("2026-09-15T13:35:17.660+00:00", "MaaControllerPostClickKey", None)]
    assigned = audit.assign_events_to_rows(events, ledger)
    assert 1 in assigned, "the key press belongs to the row it is nearest to"
    assert 0 not in assigned, (
        "crediting the ADB step with the next step's key press invents a double-drive"
    )


def test_a_click_is_credited_to_the_step_that_issued_it() -> None:
    ledger = [
        _row("2026-09-16T02:03:55.772348+00:00", skill_id="OPEN_INTEL"),
        _row("2026-09-16T02:04:16.082229+00:00", skill_id="SELECT_INTEL_PIN"),
    ]
    events = [_event("2026-09-16T02:03:55.720+00:00", "MaaControllerPostClickV2", (666, 954))]
    assigned = audit.assign_events_to_rows(events, ledger)
    assert 0 in assigned
    assert assigned[0][0][2] == (666, 954), "the coordinates travel with the event"


def test_an_event_far_from_every_row_is_credited_to_none() -> None:
    ledger = [_row("2026-09-16T02:03:55.772348+00:00", skill_id="OPEN_INTEL")]
    events = [_event("2026-09-16T02:09:00.000000+00:00", "MaaControllerPostClickV2", (1, 1))]
    assert audit.assign_events_to_rows(events, ledger) == {}


def test_the_assignment_tolerance_is_the_documented_one() -> None:
    """One second inside is credited, one second outside is not."""
    ledger = [_row("2026-09-16T02:03:55.000000+00:00", skill_id="OPEN_INTEL")]
    inside = datetime(2026, 9, 16, 2, 3, 55, tzinfo=timezone.utc) + timedelta(
        seconds=audit.MAA_EVENT_SECONDS - 1
    )
    outside = datetime(2026, 9, 16, 2, 3, 55, tzinfo=timezone.utc) + timedelta(
        seconds=audit.MAA_EVENT_SECONDS + 1
    )
    assert audit.assign_events_to_rows([(inside, "MaaControllerPostClickV2", None, "")], ledger)
    assert not audit.assign_events_to_rows([(outside, "MaaControllerPostClickV2", None, "")], ledger)


# --------------------------------------------------- rule 2: the name collision


def test_capture_backend_is_not_compared_across_artefacts() -> None:
    """The two fields describe different facts, so equality is not the test.

    If someone later "fixes" the audit by comparing them, this fails -- which is
    the point: the values legitimately differ on every HYBRID step, and forcing
    them equal would make one of the two artefacts lie.
    """
    source = TOOL.read_text(encoding="utf-8")
    assert '("capture_backend", "capture_backend")' not in source, (
        "episode.capture_backend is the observation channel and ledger.capture_backend "
        "is the executor channel; comparing them yields a conflict on every HYBRID step"
    )
    assert "SEMANTIC_COLLISION" in source
    # The frame-provenance check that replaced it must still exist.
    assert "LEDGER_CAPTURE_UNNAMED_ON_EXECUTED_STEP" in source


def test_hybrid_steps_are_expected_to_produce_the_collision() -> None:
    """Sanity on the mechanism, stated as the audit states it.

    runtime.py writes the observation device; executor_router.py writes the device
    of the executor that ran.  With MAA observing and ADB acting they differ by
    construction.
    """
    runtime = (TOOL.parent.parent / "winter_agent_v2/runtime.py").read_text(encoding="utf-8")
    router = (TOOL.parent.parent / "winter_agent_v2/executor_router.py").read_text(encoding="utf-8")
    assert "getattr(self.device, \"capture_backend\"" in runtime
    assert "getattr(device, \"capture_backend\"" in router
