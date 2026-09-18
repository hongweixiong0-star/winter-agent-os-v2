"""A job the gateway says is gone must settle, and must free the one concurrency slot.

Measured 2026-09-18 20:20 in production: record ``SPEND_STAMINA_ON_BEAST`` held the single
development slot with job ``d8ea0e44``; the gateway was healthy and answered
``HTTP 404 JOB_NOT_FOUND`` for it.  The old code caught that as a generic error, so the
record stayed ``WORKING`` and every escalation behind it was refused with
``CONCURRENCY_WAIT`` -- by a job that could never finish.  The queue was deadlocked by a
ghost, and the pump reported the same 404 as an error every thirty seconds.

The fold's own comment already records this shape for a *cancelled* job ("a stranded record
starves every pending escalation behind it"); this is the same failure arriving by a
different route, which is why it is tested the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    FAILED, JOB_LOST, SUBMITTED, WORKING, fold,
)

KEY = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"


def _rows(*, lost: bool) -> list[dict]:
    rows = [
        {"event": "escalation_created", "key": KEY, "capability": "SPEND_STAMINA_ON_BEAST",
         "state": "NEW", "recorded_at": "2026-09-18T09:00:00+00:00"},
        {"event": "submitted", "key": KEY, "job_id": "d8ea0e44",
         "recorded_at": "2026-09-18T09:10:00+00:00"},
        {"event": "job_state", "key": KEY, "job_id": "d8ea0e44", "state": WORKING,
         "recorded_at": "2026-09-18T09:11:00+00:00"},
    ]
    if lost:
        rows.append({"event": "job_lost", "key": KEY, "job_id": "d8ea0e44",
                     "state": FAILED, "reason": "HTTP 404 JOB_NOT_FOUND",
                     "recorded_at": "2026-09-18T09:40:00+00:00"})
    return rows


def test_a_live_job_holds_the_slot():
    """The starting position, so the change below is measured against something real."""
    snapshot = fold(_rows(lost=False))
    assert snapshot.get(KEY).state == WORKING
    assert [r.job_id for r in snapshot.active_jobs()] == ["d8ea0e44"]


def test_a_lost_job_settles_and_releases_the_slot():
    snapshot = fold(_rows(lost=True))
    record = snapshot.get(KEY)
    assert record.state == FAILED, "a job that will never report again is not in progress"
    assert record.settled_at is not None
    assert record.outcome == JOB_LOST, "the cause must survive for the next decision"
    assert snapshot.active_jobs() == (), "the single slot must be free for the next capability"
    assert any("job lost" in note for note in record.notes)


def test_lost_and_failed_are_distinguishable_after_the_fact():
    """Both are FAILED lifecycle-wise; only the outcome says whether to retry or re-submit."""
    ordinary = fold([
        {"event": "escalation_created", "key": KEY, "state": "NEW",
         "recorded_at": "2026-09-18T09:00:00+00:00"},
        {"event": "submitted", "key": KEY, "job_id": "j1",
         "recorded_at": "2026-09-18T09:10:00+00:00"},
        {"event": "job_state", "key": KEY, "job_id": "j1", "state": FAILED,
         "recorded_at": "2026-09-18T09:20:00+00:00"},
    ])
    assert ordinary.get(KEY).state == FAILED
    assert ordinary.get(KEY).outcome != JOB_LOST
    assert fold(_rows(lost=True)).get(KEY).outcome == JOB_LOST
