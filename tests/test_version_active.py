"""VERSION_ACTIVE: the rung that stops a version from being credited before it ever ran.

Operator §二, and the four facts it forbids are the whole reason this file exists.  A version
becomes active when, and only when:

    job settled  +  after_version known  +  a real episode  +
    episode.repo_revision == after_version

"Files changed", "the agent said DONE" and "the tests passed" are all facts about the *tree*.
None of them is evidence that anything loaded it, and crediting one of them is exactly the
mistake the operator's earlier correction named: a certificate for a version the measuring
process had never imported.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    ACTIVE_STATES, ALL_STATES, CODE_CHANGED, DONE, LIVE_VERIFY_PENDING, REJOINED,
    TERMINAL_STATES, VERSION_ACTIVATION_PENDING, VERSION_ACTIVE, WORKING,
    EscalationLedger, EscalationQueueAdapter, fold,
)

KEY = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"
BEFORE = "a" * 40
AFTER = "b" * 40


def _reconciled(outcome: str = VERSION_ACTIVATION_PENDING) -> dict:
    return {
        "event": "reconciled", "key": KEY, "job_id": "j1", "outcome": outcome,
        "job_state": DONE, "code_changed": True,
        "before_version": BEFORE, "after_version": AFTER,
        "recorded_at": "2026-09-18T10:00:00+00:00",
    }


def _rows() -> list[dict]:
    return [
        {"event": "escalation_created", "key": KEY, "capability": "SPEND_STAMINA_ON_BEAST",
         "skill": "SCAN_MAP_FOR_BEAST", "state": "NEW",
         "recorded_at": "2026-09-18T09:00:00+00:00"},
        {"event": "submitted", "key": KEY, "job_id": "j1", "repo_head": BEFORE,
         "recorded_at": "2026-09-18T09:10:00+00:00"},
        {"event": "job_state", "key": KEY, "job_id": "j1", "state": WORKING,
         "recorded_at": "2026-09-18T09:11:00+00:00"},
        _reconciled(),
        {"event": "live_verify_pending", "key": KEY, "job_id": "j1",
         "outcome": VERSION_ACTIVATION_PENDING, "version_since": "2026-09-18T10:00:00+00:00",
         "recorded_at": "2026-09-18T10:00:30+00:00"},
    ]


def _activation_event(**over) -> dict:
    event = {
        "event": "version_active", "key": KEY, "job_id": "j1",
        "capability": "SPEND_STAMINA_ON_BEAST",
        "before_version": BEFORE, "after_version": AFTER, "active_version": AFTER,
        "activation_episode_id": "ep-1", "activated_at": "2026-09-18T10:05:00+00:00",
        "recorded_at": "2026-09-18T10:05:01+00:00",
    }
    event.update(over)
    return event


# --------------------------------------------------------------------- the state machine


def test_the_new_rungs_are_real_lifecycle_states():
    """§一: they are states in the ledger, not fields the window infers."""
    assert VERSION_ACTIVE in ALL_STATES
    assert REJOINED in ALL_STATES


def test_neither_rung_holds_the_only_development_slot():
    """One concurrency slot: a version awaiting measurement is not work in progress."""
    assert VERSION_ACTIVE not in ACTIVE_STATES
    assert REJOINED not in ACTIVE_STATES
    # ...and neither is terminal while there is still something to measure.
    assert VERSION_ACTIVE not in TERMINAL_STATES
    assert REJOINED not in TERMINAL_STATES


def test_the_versions_the_job_produced_are_folded_onto_the_record():
    """Without after_version on the record, no episode can ever be compared against it."""
    record = fold(_rows()).get(KEY)
    assert record.before_version == BEFORE
    assert record.after_version == AFTER


def test_pending_is_not_active():
    """The starting position: the job settled and nothing has proved the version loaded."""
    record = fold(_rows()).get(KEY)
    assert record.state == LIVE_VERIFY_PENDING
    assert record.outcome == VERSION_ACTIVATION_PENDING
    assert record.active_version == ""


def test_a_version_active_event_moves_the_state_and_keeps_the_cause():
    snapshot = fold(_rows() + [_activation_event()])
    record = snapshot.get(KEY)
    assert record.state == VERSION_ACTIVE
    assert record.active_version == AFTER
    assert record.activation_episode_id == "ep-1"
    assert record.activated_at is not None
    assert any("version active" in note for note in record.notes)


def test_rejoined_is_a_separate_fact_from_production_reuse():
    """§9's correction, which this test used to assert the opposite of.

    It was written before the operator split the two: ``rejoined`` means the capability has gone
    back into the production pool, and ``production_reuse`` -- a later, separate event -- is the
    only thing that may fill ``production_reuse_episode_id``.  Carrying the id on the rejoin is
    how "the exam passed" starts reading as "the capability works in play".
    """
    snapshot = fold(_rows() + [
        _activation_event(),
        {"event": "rejoined", "key": KEY, "job_id": "j1",
         "rejoined_at": "2026-09-18T10:30:00+00:00",
         "recorded_at": "2026-09-18T10:30:00+00:00"},
    ])
    record = snapshot.get(KEY)
    assert record.state == REJOINED
    assert record.rejoined_at is not None
    assert record.production_reuse_episode_id == "", (
        "re-joining is not reuse: only a later PRODUCTION episode may fill this"
    )

    done = fold(_rows() + [
        _activation_event(),
        {"event": "rejoined", "key": KEY, "job_id": "j1",
         "rejoined_at": "2026-09-18T10:30:00+00:00",
         "recorded_at": "2026-09-18T10:30:00+00:00"},
        {"event": "production_reuse", "key": KEY, "job_id": "j1",
         "production_reuse_episode_id": "ep-prod-9",
         "after_version": AFTER, "reused_at": "2026-09-18T11:00:00+00:00",
         "recorded_at": "2026-09-18T11:00:01+00:00"},
    ]).get(KEY)
    assert done.state == DONE
    assert done.production_reuse_episode_id == "ep-prod-9"


def test_tests_passing_is_not_activation():
    """§二 forbidden #3.  A green gate says the tree is fine, not that anything loaded it."""
    # Both rows that could legitimately claim the activation rung are dropped here: the point
    # is that CODE_CHANGED, on its own, never becomes VERSION_ACTIVE.  Leaving the
    # ``live_verify_pending`` row in would have made the assertion pass for the wrong reason --
    # it sets the outcome back to VERSION_ACTIVATION_PENDING by itself.
    rows = [row for row in _rows()
            if row.get("event") not in ("reconciled", "live_verify_pending")]
    rows.append(_reconciled(outcome=CODE_CHANGED))
    record = fold(rows).get(KEY)
    assert record.outcome == CODE_CHANGED
    assert record.state != VERSION_ACTIVE
    assert record.active_version == ""


# --------------------------------------------------------------------- the detector


class _NoBridge:
    def status(self, job_id):  # pragma: no cover - the activation pass never asks the gateway
        raise AssertionError("activation must not need the gateway")


def _adapter(tmp_path, *, episodes: list[dict]) -> EscalationQueueAdapter:
    root = tmp_path
    (root / "learning").mkdir(parents=True, exist_ok=True)
    ledger_path = root / "learning/workbuddy_escalations.jsonl"
    # Trailing newline on purpose.  A jsonl seed written without one makes the next ``append``
    # concatenate onto the unterminated last line, so the ledger silently loses the two rows
    # that matter -- measured here: the record read back as DONE and the activation looked
    # like it had never been written.
    ledger_path.write_text("\n".join(json.dumps(r) for r in _rows()) + "\n", encoding="utf-8")
    (root / "learning/episodes.jsonl").write_text(
        "\n".join(json.dumps(e) for e in episodes) + "\n", encoding="utf-8"
    )
    return EscalationQueueAdapter(
        root=root, ledger=EscalationLedger(ledger_path), bridge=_NoBridge(),
    )


def _episode(*, revision: str, episode_id: str = "ep-1",
             recorded_at: str = "2026-09-18T10:05:00+00:00") -> dict:
    return {
        "episode_id": episode_id, "capability": "SPEND_STAMINA_ON_BEAST",
        "skill": "SCAN_MAP_FOR_BEAST", "recorded_at": recorded_at,
        "repo_revision": revision, "verifier_ok": True, "mode": "PRODUCTION",
        "before_screenshot": "dataset/raw/x.png", "after_screenshot": "dataset/raw/y.png",
    }


def test_an_episode_that_ran_a_different_tree_does_not_activate(tmp_path):
    """The episode must be the *new* version, not merely a later one."""
    adapter = _adapter(tmp_path, episodes=[_episode(revision="c" * 40)])
    activated = adapter._activate_pending_versions(adapter.ledger.snapshot(),
                                                  __import__("datetime").datetime.now(
                                                      __import__("datetime").timezone.utc))
    assert activated == []


def test_an_episode_recorded_before_the_job_settled_does_not_activate(tmp_path):
    """A cycle that started before the job finished was running the old code."""
    adapter = _adapter(tmp_path, episodes=[_episode(revision=AFTER,
                                                   recorded_at="2026-09-18T09:30:00+00:00")])
    import datetime as _dt
    activated = adapter._activate_pending_versions(
        adapter.ledger.snapshot(), _dt.datetime(2026, 9, 18, 10, 10, tzinfo=_dt.timezone.utc))
    assert activated == []


def test_the_matching_episode_activates_and_records_the_chain(tmp_path):
    """The positive case, with the causal fields §三 asks for written into the ledger."""
    adapter = _adapter(tmp_path, episodes=[_episode(revision=AFTER)])
    import datetime as _dt
    activated = adapter._activate_pending_versions(
        adapter.ledger.snapshot(), _dt.datetime(2026, 9, 18, 10, 10, tzinfo=_dt.timezone.utc))
    assert len(activated) == 1
    key, message = activated[0]
    assert key == KEY and "VERSION_ACTIVE" in message

    record = adapter.ledger.snapshot().get(KEY)
    assert record.state == VERSION_ACTIVE
    assert record.active_version == AFTER
    assert record.activation_episode_id == "ep-1"

    rows = adapter.ledger.events()
    event = [r for r in rows if r.get("event") == "version_active"][-1]
    for field in ("key", "job_id", "capability", "before_version", "after_version",
                  "active_version", "activation_episode_id", "activated_at"):
        assert event.get(field), field


# --------------------------------------------------------------------- §一 the driver


def _adapter_at(tmp_path, rows, *, episodes=None):
    root = tmp_path
    (root / "learning").mkdir(parents=True, exist_ok=True)
    ledger_path = root / "learning/workbuddy_escalations.jsonl"
    ledger_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (root / "learning/episodes.jsonl").write_text(
        "\n".join(json.dumps(e) for e in (episodes or [])) + "\n", encoding="utf-8")
    return EscalationQueueAdapter(
        root=root, ledger=EscalationLedger(ledger_path), bridge=_NoBridge())


def _activated_rows():
    return _rows() + [_activation_event()]


def test_an_active_version_is_sent_for_validation_by_the_queue_itself(tmp_path):
    """§一: no click, no second trigger -- the pump requests the examination."""
    import datetime as _dt
    adapter = _adapter_at(tmp_path, _activated_rows())
    requested = adapter._request_validation(
        adapter.ledger.snapshot(), _dt.datetime(2026, 9, 18, 10, 20, tzinfo=_dt.timezone.utc))
    assert len(requested) == 1
    record = adapter.ledger.snapshot().get(KEY)
    assert record.state == LIVE_VERIFY_PENDING
    assert record.outcome == VERSION_ACTIVE

    event = [r for r in adapter.ledger.events()
             if r.get("event") == "live_verify_pending" and r.get("outcome") == VERSION_ACTIVE][-1]
    for field in ("key", "job_id", "capability", "skill", "goal",
                  "before_version", "after_version", "active_version",
                  "activation_episode_id", "requested_at"):
        assert event.get(field) is not None, field


def test_the_request_is_idempotent(tmp_path):
    """A second pass must not re-request what is already owed."""
    import datetime as _dt
    when = _dt.datetime(2026, 9, 18, 10, 20, tzinfo=_dt.timezone.utc)
    adapter = _adapter_at(tmp_path, _activated_rows())
    adapter._request_validation(adapter.ledger.snapshot(), when)
    before = len(adapter.ledger.events())
    again = adapter._request_validation(adapter.ledger.snapshot(), when)
    assert again == []
    assert len(adapter.ledger.events()) == before


def test_a_version_that_is_not_the_one_under_test_is_not_sent(tmp_path):
    """Asking for validation of the wrong code would credit the right capability."""
    import datetime as _dt
    rows = _rows() + [_activation_event(active_version="f" * 40, after_version=AFTER)]
    adapter = _adapter_at(tmp_path, rows)
    requested = adapter._request_validation(
        adapter.ledger.snapshot(), _dt.datetime(2026, 9, 18, 10, 20, tzinfo=_dt.timezone.utc))
    assert requested == []
