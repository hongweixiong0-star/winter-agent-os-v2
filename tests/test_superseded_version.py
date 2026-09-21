"""A trace whose version the device can no longer run must stop asking for the device.

Measured 2026-09-21, and this is the operator's §4 in its exact form.  One record --
``OPEN_TRAINING_PAGE|NO_GOAL_PROGRESS|BACK`` -- waited for version ``91e3475`` to be loaded
and run.  The tree had moved 57 commits past it.  ``validation_lease_target`` asked for the
device every two minutes for over an hour (30+ acquire/release cycles, none able to settle),
and in that whole window AUTO never completed a cycle:

    device_leases.jsonl   14:37 -> 16:09, every entry "validation run ... finished"
    runtime_snapshot      agent_state PAUSED, stop_reason device_leased_for_development,
                          steps: []
    ledger                version_active 0 times, live_verified 0 times,
                          validation_lease_requested 111 times

Two independent faults, and the fix has to cover both or neither works:

1. **The comparison was between two different shapes.**  ``record.after_version`` is written
   from ``after.head`` (a bare sha); the episode field it was compared against,
   ``repo_revision``, is ``head+digest`` for a dirty tree.  ``learning/episodes.jsonl`` has the
   same commit ``39eba75a2...`` under two digests (``e304be3180e1b369`` /
   ``e324f8791464cd4b``) because a cycle writes version-relevant files while it runs, so the
   strict form demanded that two processes agree on the contents of a tree one of them was
   still writing.  Comparing commits is what "the version the job produced" means.

2. **There was no exit for a version that can never be run again.**  The examination drives
   the working tree (``tools/control_panel.py::validation_command`` never checks a version
   out), so a record asking for a superseded commit can never be satisfied -- but
   ``validation_lease_target`` only asked whether the record was pending, so it asked forever.

Neither test below can pass on the code as it was: the first because the two strings never
matched, the second because nothing ever ended such a record.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import escalation_queue as eq  # noqa: E402
from winter_agent_v2.escalation_queue import (  # noqa: E402
    DONE, FAILED, LIVE_VERIFY_PENDING, NO_IMPROVEMENT, VERSION_ACTIVATION_PENDING,
    VERSION_ACTIVE, WORKING, EscalationLedger, EscalationQueueAdapter, RepoRevision, fold,
    commit_of,
)

KEY = "OPEN_TRAINING_PAGE|NO_GOAL_PROGRESS|BACK"
BEFORE = "a" * 40
AFTER = "b" * 40          # the commit this trace is waiting for
HEAD_NOW = "c" * 40       # the commit the device would actually run
NOW = datetime(2026, 9, 21, 16, 30, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- the comparison


def test_a_revision_token_reduces_to_its_commit():
    assert commit_of("b" * 40) == "b" * 40
    assert commit_of("b" * 40 + "+e324f8791464cd4b") == "b" * 40
    assert commit_of("") == ""
    assert commit_of(None) == ""


# --------------------------------------------------------------------------- the ledger rows


def _rows(*, after: str = AFTER) -> list[dict]:
    return [
        {"event": "escalation_created", "key": KEY, "capability": "OPEN_TRAINING_PAGE",
         "skill": "BACK", "state": "NEW", "goal": "KEEP_TRAINING_PRODUCTIVE",
         "recorded_at": "2026-09-21T07:00:00+00:00"},
        {"event": "submitted", "key": KEY, "job_id": "280d1659", "repo_head": BEFORE,
         "recorded_at": "2026-09-21T06:40:00+00:00"},
        {"event": "job_state", "key": KEY, "job_id": "280d1659", "state": WORKING,
         "recorded_at": "2026-09-21T06:41:00+00:00"},
        {"event": "reconciled", "key": KEY, "job_id": "280d1659",
         "outcome": VERSION_ACTIVATION_PENDING, "job_state": DONE, "code_changed": True,
         "capability": "OPEN_TRAINING_PAGE", "skill": "BACK",
         "before_version": BEFORE, "after_version": after,
         "recorded_at": "2026-09-21T07:10:29+00:00"},
        {"event": "live_verify_pending", "key": KEY, "job_id": "280d1659",
         "capability": "OPEN_TRAINING_PAGE", "skill": "BACK", "goal": "KEEP_TRAINING_PRODUCTIVE",
         "outcome": VERSION_ACTIVATION_PENDING, "version_since": "2026-09-21T07:10:29+00:00",
         "recorded_at": "2026-09-21T07:10:30+00:00"},
    ]


class _NoBridge:
    def status(self, job_id):  # pragma: no cover - neither pass asks the gateway
        raise AssertionError("the activation and lease passes must not need the gateway")


def _adapter(tmp_path, *, rows=None, episodes=None, head=HEAD_NOW, monkeypatch=None):
    """An adapter over a temporary ledger, with the working tree's commit stubbed.

    The commit is stubbed rather than measured because the question here is what the code
    does with the answer, and a test that depended on this repository's current HEAD would
    start passing or failing for reasons that have nothing to do with the rule.

    ``head=""`` means "no git answer available", which is what a temporary directory gives --
    and is kept as a case below because that is the conservative branch.
    """
    root = tmp_path
    (root / "learning").mkdir(parents=True, exist_ok=True)
    ledger_path = root / "learning/workbuddy_escalations.jsonl"
    ledger_path.write_text("\n".join(json.dumps(r) for r in (rows or _rows())) + "\n",
                           encoding="utf-8")
    (root / "learning/episodes.jsonl").write_text(
        "\n".join(json.dumps(e) for e in (episodes or [])) + "\n", encoding="utf-8")
    if monkeypatch is not None:
        monkeypatch.setattr(eq, "repo_revision",
                            lambda _root, **_kw: RepoRevision(head=head, dirty=0, ok=bool(head)))
    return EscalationQueueAdapter(root=root, ledger=EscalationLedger(ledger_path),
                                  bridge=_NoBridge())


def _episode(*, revision: str, episode_id: str = "ep-1",
             recorded_at: str = "2026-09-21T16:09:00+00:00") -> dict:
    return {
        "episode_id": episode_id, "capability": "OPEN_TRAINING_PAGE", "skill": "BACK",
        "trace_id": KEY, "job_id": "280d1659", "recorded_at": recorded_at,
        "repo_revision": revision, "expected_after_version": AFTER,
        "verifier_ok": True, "execution_mode": "DEVELOPMENT_VALIDATION",
        "before_screenshot": "dataset/raw/x.png", "after_screenshot": "dataset/raw/y.png",
    }


# --------------------------------------------------------------------------- fault 1


def test_an_episode_on_the_same_commit_but_a_different_digest_does_activate(tmp_path, monkeypatch):
    """The correction: the device loaded the commit; the uncommitted bytes beside it vary.

    This is what the rung demanded and could never get -- ``learning/episodes.jsonl`` really
    does carry one commit under two digests, because a cycle writes version-relevant files
    while it runs.  The capability is not credited twice over on the strength of it: an
    activation only moves the record to the *next* rung, where a real-device episode with a
    passing verifier is still owed.
    """
    adapter = _adapter(tmp_path, episodes=[_episode(revision=f"{AFTER}+e324f8791464cd4b")],
                       head=AFTER, monkeypatch=monkeypatch)
    activated = adapter._activate_pending_versions(adapter.ledger.snapshot(), NOW)
    assert len(activated) == 1, "same commit, different digest -- the digest is not the version"
    assert adapter.ledger.snapshot().get(KEY).state == VERSION_ACTIVE


def test_an_episode_on_a_different_commit_still_does_not_activate(tmp_path, monkeypatch):
    """The rule itself is unchanged.  A later tree is not the version under test."""
    adapter = _adapter(tmp_path, episodes=[_episode(revision=f"d" * 40 + "+deadbeefdeadbeef")],
                       head=AFTER, monkeypatch=monkeypatch)
    assert adapter._activate_pending_versions(adapter.ledger.snapshot(), NOW) == []
    assert adapter.ledger.snapshot().get(KEY).state != VERSION_ACTIVE


def test_with_no_commit_available_nothing_is_retired(tmp_path, monkeypatch):
    """No git answer is not the same as "the version moved on"."""
    adapter = _adapter(tmp_path, episodes=[], head="", monkeypatch=monkeypatch)
    adapter._activate_pending_versions(adapter.ledger.snapshot(), NOW)
    assert adapter.ledger.snapshot().get(KEY).state == LIVE_VERIFY_PENDING


# --------------------------------------------------------------------------- fault 2


def test_a_superseded_version_is_ended_instead_of_re_queued(tmp_path, monkeypatch):
    """§4: a finished development task may not hold the device away from gameplay forever."""
    adapter = _adapter(tmp_path, episodes=[_episode(revision=f"{HEAD_NOW}+e324f8791464cd4b")],
                       head=HEAD_NOW, monkeypatch=monkeypatch)
    events = adapter._activate_pending_versions(adapter.ledger.snapshot(), NOW)

    assert len(events) == 1
    key, message = events[0]
    assert key == KEY and "SUPERSEDED" in message

    record = adapter.ledger.snapshot().get(KEY)
    assert record.state == FAILED, "it must stop being a pending trace, or it keeps asking"
    assert record.outcome == NO_IMPROVEMENT, "ended, not verified and not blamed on the code"
    assert not eq.unfinished_trace(record), (
        "a new gap for the same capability must be allowed to open a new trace"
    )


def test_the_retirement_names_both_versions_and_admits_what_was_not_proved(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, episodes=[], head=HEAD_NOW, monkeypatch=monkeypatch)
    adapter._activate_pending_versions(adapter.ledger.snapshot(), NOW)

    row = [r for r in adapter.ledger.events()
           if r.get("event") == "reconciled" and r.get("superseded_version")][-1]
    assert row["superseded_version"] == AFTER
    assert row["superseded_by"] == HEAD_NOW
    assert row["verified_episodes"] == 0
    assert row["live_improvement"] is False, "nothing was verified here"
    assert row["repair_used"] is False, "and nothing was repaired either"
    assert "SUPERSEDED" in row["explanation"]


def test_a_pending_trace_for_the_current_commit_is_left_alone(tmp_path, monkeypatch):
    """The normal case must not be swept up: this record is waiting for something real."""
    adapter = _adapter(tmp_path, episodes=[], head=AFTER, monkeypatch=monkeypatch)
    assert adapter._activate_pending_versions(adapter.ledger.snapshot(), NOW) == []
    assert adapter.ledger.snapshot().get(KEY).state == LIVE_VERIFY_PENDING


# --------------------------------------------------------------------------- the lease lock


def test_the_device_is_not_asked_for_a_version_it_could_not_run(tmp_path, monkeypatch):
    """Second lock on the same door: a request that cannot be honoured is not made.

    ``_activate_pending_versions`` ends these records in the same drain, but the request
    must not go out even once -- one wasted request is one AUTO cycle with ``steps: []``.
    """
    adapter = _adapter(tmp_path, head=HEAD_NOW, monkeypatch=monkeypatch)
    assert adapter.validation_lease_target() is None, (
        "asking for this record could only take the device away from gameplay"
    )


def test_the_device_is_still_asked_for_when_the_commit_matches(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, head=AFTER, monkeypatch=monkeypatch)
    target = adapter.validation_lease_target()
    assert target is not None and target.key == KEY
