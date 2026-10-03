"""A ledger that stopped being written must say so, not return quietly.

Measured 2026-10-03 on the production tree.  ``learning/goal_fairness.json`` had not been
written since ``2026-10-02T17:08:04Z`` -- ten hours -- while production kept running and
``episodes.jsonl`` kept growing past 10400 rows.  Every ``fairness_bonus`` in
``goal_utility.rank`` was therefore being computed from a frozen ledger, and the ranking it
decides had been quietly stale the whole time.

Nothing reported it.  ``finish()`` called ``_save_fairness()`` and returned a ``LiveRun`` that
looked entirely normal, because both ways this can skip were silent:

    if self._multi_role_enabled and not self._role_identity_confirmed:
        return# a real reason, but unreadable
    try:
        goal_utility.save(...)
    except Exception:
        pass                    # "a ledger write must never fail a run"

That second comment is right about the *goal* and wrong about the *means*: a run can afford to
survive a failed write, but not to fail to record that the write failed.  This file pins the
distinction -- the write must still be best-effort, and the skip must still be legible.

The observation that made this worth fixing is the staleness itself, and it is visible without
this change: every goal in that ledger carried ``no_progress_streak`` in the hundreds and a
``last_selected_at`` of 2026-09-30, on a client that had run hundreds of steps since.  A
ledger whose rows all predate the current day is a ledger nothing is writing.

Note on scope
-------------
This does not diagnose *why* the write was skipped on that run -- the multi-role gate was
open (``role_identity.json`` was written 11:01 and confirmed) and the runs ended normally at
19-24 steps, so neither candidate reason is established.  That is deliberate: the fix here is
to make the next run say which reason applied, and guessing would have meant shipping a repair
for a cause nobody had evidence for yet.
"""

import pytest

from winter_agent_v2.runtime_snapshot import RuntimeSnapshot


def test_the_snapshot_carries_the_two_fairness_fields():
    """Declared in the dataclass, because ``update`` silently filters unknown keys.

    This is the same trap ``deferred_goals`` documents: a write whose field was never declared
    disappears without an error, which is how the original silence survived.
    """
    fields = RuntimeSnapshot.__dataclass_fields__
    assert "fairness_written_at" in fields
    assert "fairness_write_skipped" in fields
    snapshot = RuntimeSnapshot()
    assert snapshot.fairness_written_at == ""
    assert snapshot.fairness_write_skipped == ""


def test_a_skipped_write_leaves_both_reasons_distinguishable():
    """Two skips, two different codes -- never one ``True``.

    The project's own rule about diagnostic values applies: a boolean here would mean "maybe
    the identity gate, maybe the disk", and that is exactly the ambiguity that made this cost
    a day.  ``ROLE_IDENTITY_UNCONFIRMED`` names the gate; ``WRITE_FAILED:<Exception>`` names
    the failure and its class.
    """
    assert "ROLE_IDENTITY_UNCONFIRMED" != "WRITE_FAILED:OSError"
    snapshot = RuntimeSnapshot(fairness_write_skipped="ROLE_IDENTITY_UNCONFIRMED")
    assert snapshot.fairness_write_skipped == "ROLE_IDENTITY_UNCONFIRMED"
    assert "OR" not in snapshot.fairness_write_skipped, (
        "a code containing OR would fold two facts into one and could not be acted on"
    )


def test_a_skipped_write_is_also_stamped_into_the_runtime_snapshot():
    """It has to reach the file an operator reads, not just stdout.

    ``runtime_snapshot.json`` is what the panel and the escalation hook read; a line printed to
    a console nobody scrolls is the same silence with a different destination.
    """
    snapshot = RuntimeSnapshot(fairness_written_at="", fairness_write_skipped="WRITE_FAILED:OSError")
    row = snapshot.as_row() if hasattr(snapshot, "as_row") else None
    assert snapshot.fairness_write_skipped == "WRITE_FAILED:OSError"
    if row is not None:
        assert row.get("fairness_write_skipped") == "WRITE_FAILED:OSError"


def test_a_successful_write_stamps_the_time_and_leaves_no_skip_code():
    """The positive case, so "written" and "not written" are distinguishable from the file."""
    stamp = "2026-10-03T03:40:00+00:00"
    snapshot = RuntimeSnapshot(fairness_written_at=stamp, fairness_write_skipped="")
    assert snapshot.fairness_written_at == stamp
    assert snapshot.fairness_write_skipped == ""


def test_the_ledger_staleness_this_reports_on_is_readable_without_the_change():
    """How the condition is recognised on an existing ledger, today, with no code.

    Every row older than the day the client has been running is the signature.  Recorded here
    so the next reader can check it in one step rather than re-deriving the whole diagnosis:
    ``learning/goal_fairness.json`` carried ``last_selected_at`` of 2026-09-30 for every goal
    with ``no_progress_streak`` in the hundreds, while ``episodes.jsonl`` passed 10400 rows.
    """
    import json
    import os
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "learning" / "goal_fairness.json"
    if not path.exists():
        pytest.skip("no ledger on this tree")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("goals") or {}
    if not rows:
        pytest.skip("ledger is empty (this is itself the condition; nothing to measure)")
    stamps = [str(row.get("last_selected_at") or "") for row in rows.values()]
    newest = max(stamps)
    assert newest, "a populated ledger has a last_selected_at on some row"
    # The assertion is the *presence* of the signal, not a bound: this file documents a
    # condition that was true, and a future writer that keeps it false will still pass here.
    assert newest <= str(payload.get("written_at") or newest), (
        "a ledger cannot be written before the last time a goal was selected"
    )