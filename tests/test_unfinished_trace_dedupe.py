"""One agent slot is not one unfinished capability (operator §0B).

Two resources, two rules, and conflating them breaks the loop in both directions:

* If ``VERSION_ACTIVE`` / ``LIVE_VERIFY_PENDING`` / ``REJOINED`` counted as *active*, the single
  WorkBuddy slot would be held by a capability that is merely waiting for a device or for
  production play -- and no other capability could ever be developed.
* If they counted as *inactive*, a new gap for the same capability would open a second job for
  work that is already in flight, which is the One-Capability-One-Job rule.

These tests pin both halves.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    ACTIVE_STATES, CODE_CHANGED, DEDUP_SKIP, FAILED, LIVE_TRIED, LIVE_VERIFIED,
    LIVE_VERIFY_PENDING, REJOINED, SUBMIT, VERSION_ACTIVE, EscalationCandidate,
    EscalationPolicy, EscalationRecord, EscalationSnapshot, FailureSignature,
    unfinished_trace, decide,
)

NOW = datetime(2026, 9, 18, 22, 0, tzinfo=timezone.utc)
POLICY = EscalationPolicy()


def _candidate(capability: str, *, skill: str, failure: str = "NO_GOAL_PROGRESS"):
    return EscalationCandidate(
        condition="REPEATED_LIVE_FAILURE",
        signature=FailureSignature(capability=capability, failure_type=failure, skill=skill),
        reason="test fixture",
    )


def _snapshot(*records: EscalationRecord) -> EscalationSnapshot:
    return EscalationSnapshot({r.key: r for r in records})


# --------------------------------------------------------------------- the resource split


def test_a_version_waiting_for_a_device_does_not_hold_the_agent_slot():
    """The first half: it must not count as an active job."""
    for state in (VERSION_ACTIVE, LIVE_VERIFY_PENDING, REJOINED):
        assert state not in ACTIVE_STATES, state


def test_all_three_still_count_as_an_unfinished_trace():
    """The second half: the same three states must still stop a second job."""
    for state in (VERSION_ACTIVE, LIVE_VERIFY_PENDING, REJOINED):
        record = EscalationRecord(key="A|F|S", capability="A", state=state)
        assert unfinished_trace(record), state


def test_a_terminal_state_with_an_open_outcome_is_still_unfinished():
    """LIVE_VERIFIED waits for re-join; LIVE_TRIED waits for proof or repair."""
    for outcome in (LIVE_VERIFIED, LIVE_TRIED):
        record = EscalationRecord(key="A|F|S", capability="A", state=FAILED, outcome=outcome)
        assert unfinished_trace(record), outcome


def test_a_finished_or_abandoned_trace_is_closed():
    """Which is what lets a genuinely new failure open a new job."""
    for state, outcome in (("DONE", "BLOCKED"), ("FAILED", CODE_CHANGED),
                           ("BLOCKED", ""), ("COOLDOWN", "")):
        record = EscalationRecord(key="A|F|S", capability="A", state=state, outcome=outcome)
        assert not unfinished_trace(record), (state, outcome)


# --------------------------------------------------------------------- through the throttle


def test_a_new_gap_for_a_capability_awaiting_validation_opens_no_second_job():
    """Operator test #9."""
    waiting = EscalationRecord(key="A|OTHER|S2", capability="A", skill="S2",
                               state=LIVE_VERIFY_PENDING, job_id="job-1")
    dispatch = decide(_candidate("A", skill="S"), _snapshot(waiting), POLICY, now=NOW)
    assert dispatch.action == DEDUP_SKIP
    assert "one capability must not have two jobs" in dispatch.reason


def test_a_different_capability_may_still_use_the_agent_slot():
    """Operator test #10: preparing in parallel is allowed, verifying is serial."""
    waiting = EscalationRecord(key="A|OTHER|S2", capability="A", skill="S2",
                               state=LIVE_VERIFY_PENDING, job_id="job-1")
    dispatch = decide(_candidate("B", skill="SB"), _snapshot(waiting), POLICY, now=NOW)
    assert dispatch.action == SUBMIT, dispatch.reason


def test_the_slot_is_free_while_a_version_awaits_its_examination():
    """A capability mid-validation must not block the slot it is deliberately not holding."""
    waiting = EscalationRecord(key="A|OTHER|S2", capability="A", skill="S2",
                               state=VERSION_ACTIVE, job_id="job-1")
    dispatch = decide(_candidate("B", skill="SB"), _snapshot(waiting), POLICY, now=NOW)
    assert dispatch.action == SUBMIT, dispatch.reason
