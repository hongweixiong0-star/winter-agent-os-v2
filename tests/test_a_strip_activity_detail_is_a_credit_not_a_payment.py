"""A strip activity's detail is a credit, and a credit is not a payment.

``record_calendar_snapshot`` could credit a grid row -- it matched the detail to a row and
set ``details_observed`` -- but a strip activity has no grid row, so the credit had nowhere
to land.  That is the second link in a chain whose first link was missing until aab0dbb8, and
the cost was measured: on live revision aab0dbb8 both roles carried an ``EVENT_DETAIL``
reading of a strip activity (``CANYON_CLASH`` for 1061663148, ``STATE_VS_STATE`` for
1063040265, both ``calendar_origin=None``) while ``advertised_but_unread_activities`` still
listed them, so ``calendar_scan_due`` stayed True and DISCOVER_EVENT_CALENDAR was
re-selected every 24 seconds.

The credit is deliberately an observation and nothing more.  The page also carries 商店 and
编队, and refusing to record because a spend was declined would turn "held back once" into
"due forever" -- the operator's section 7, where safety and liveness are separate.  So
these tests pin the credit, its persistence, and the fact that a grid activity still goes to
its row.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_schedule as es  # noqa: E402

ROLE = "1061663148"
NOW = datetime.now(timezone.utc)


def _state(tmp: Path, *, strip_read: bool) -> Path:
    path = tmp / "schedule.json"
    payload = {
        "schema_version": "1.0",
        "roles": {},
        "calendar_observations": {
            ROLE: {
                "CALENDAR_GRID": {
                    "kind": "CALENDAR_GRID", "recognized": True,
                    "observed_at": NOW.isoformat(),
                    "entries": [{"event_id": "ICEBOUND_TREASURE",
                                 "tap_norm": [0.5, 0.4], "details_observed": True}],
                },
                "ACTIVITY_STRIP": {
                    "kind": "ACTIVITY_STRIP", "recognized": True,
                    "observed_at": NOW.isoformat(),
                    "entries": [
                        {"event_id": "CANYON_CLASH", "tap_norm": [0.74, 0.13]},
                        {"event_id": "STATE_VS_STATE", "tap_norm": [0.47, 0.13]},
                    ],
                    "read_entries": ([{"event_id": "STATE_VS_STATE"}] if strip_read else []),
                },
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _read_strip_detail(path: Path, event_id: str, display: str) -> dict:
    """What the page produces for a strip activity: no grid row, no date range, no origin."""
    return es.record_calendar_snapshot(
        role_id=ROLE, path=path, evidence_ref="probe.png",
        observation={
            "kind": "EVENT_DETAIL", "recognized": True,
            "event_id": event_id, "display_name": display,
            "countdown_raw": "07:53:19", "current_open_state": "SCHEDULED_NOT_OPEN",
        },
    ) or {}


def test_reading_a_strip_activity_discharges_its_debt(tmp_path):
    """The whole point, stated as one behaviour: the debt falls after the page is read."""
    path = _state(tmp_path, strip_read=True)
    assert es.advertised_but_unread_activities(ROLE, path) == ("CANYON_CLASH",)
    snapshot = _read_strip_detail(path, "CANYON_CLASH", "峡谷会战")
    assert es.advertised_but_unread_activities(ROLE, path) == ()
    assert snapshot.get("strip_activity_credited") == "CANYON_CLASH"


def test_the_credit_is_stored_on_the_strip_and_does_not_grow_without_bound(tmp_path):
    """Stored, not merely returned -- and a second read must not append a second row."""
    path = _state(tmp_path, strip_read=True)
    _read_strip_detail(path, "CANYON_CLASH", "峡谷会战")
    stored = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
    first = list(stored.get("read_entries") or ())
    assert {str(r.get("event_id")) for r in first} == {"CANYON_CLASH", "STATE_VS_STATE"}
    _read_strip_detail(path, "CANYON_CLASH", "峡谷会战")
    again = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
    assert list(again.get("read_entries") or ()) == first, (
        "re-reading an activity appended another row; the strip would grow for as long as "
        "the page is open, which is its own kind of unbounded state"
    )


def test_one_activity_being_read_does_not_credit_the_other(tmp_path):
    """A credit is per activity: the one that was not read is still owed."""
    path = _state(tmp_path, strip_read=False)
    assert es.advertised_but_unread_activities(ROLE, path) == ("CANYON_CLASH", "STATE_VS_STATE")
    _read_strip_detail(path, "CANYON_CLASH", "峡谷会战")
    assert es.advertised_but_unread_activities(ROLE, path) == ("STATE_VS_STATE",), (
        "reading one activity credited the other, which would let a single look close the "
        "whole strip"
    )


def test_a_grid_activity_still_credits_its_row_and_never_the_strip(tmp_path):
    """The other direction: the new branch must not catch grid work."""
    path = _state(tmp_path, strip_read=False)
    es.record_calendar_snapshot(
        role_id=ROLE, path=path, evidence_ref="probe.png",
        observation={
            "kind": "EVENT_DETAIL", "recognized": True,
            "event_id": "ICEBOUND_TREASURE", "display_name": "冰封的宝藏",
            "matched_occurrence_key": "ICEBOUND_TREASURE|10/01|10/07",
            "calendar_origin": "GRID_ENTRY",
        },
    )
    strip = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
    assert not strip.get("read_entries"), (
        "a grid activity was credited to the strip, which would make the strip look read "
        "for activities nobody opened"
    )


def test_a_fresh_strip_reading_does_not_discard_the_credit(tmp_path):
    """The bug this file exists to pin, found on the device an hour after the first version.

    Role 1063040265's strip had **no** ``read_entries`` key while its EVENT_DETAIL carried
    ``strip_activity_credited='STATE_VS_STATE'`` -- the two contradicted each other.  The
    cause is that ``record_calendar_snapshot`` ends with ``scope[kind] = snapshot``, so every
    observation replaces the whole snapshot for its kind.  The credit had been written into
    the previous strip dict, and the next strip reading on the following calendar visit threw
    it away, which is what brought the debt back.

    What the client draws is not the list of activities a previous run opened, so a fresh
    reading cannot re-derive it; only this ledger can carry it forward.
    """
    path = _state(tmp_path, strip_read=True)
    _read_strip_detail(path, "CANYON_CLASH", "峡谷会战")
    before = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
    assert [str(r.get("event_id")) for r in before.get("read_entries") or ()] == [
        "STATE_VS_STATE", "CANYON_CLASH"]

    es.record_calendar_snapshot(
        role_id=ROLE, path=path, evidence_ref="probe2.png",
        observation={
            "kind": "ACTIVITY_STRIP", "recognized": True,
            "entries": [
                {"event_id": "CANYON_CLASH", "tap_norm": [0.74, 0.13]},
                {"event_id": "STATE_VS_STATE", "tap_norm": [0.22, 0.13]},
            ],
        },
    )
    after = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
    survived = {str(r.get("event_id")) for r in after.get("read_entries") or ()}
    assert "CANYON_CLASH" in survived, (
        "a fresh strip reading discarded the credit; the debt will come back on the next "
        f"calendar visit, which is the loop this work was to end. Survived: {survived}"
    )
    # And the debt stays discharged through the re-read, not merely recorded.
    assert "CANYON_CLASH" not in es.advertised_but_unread_activities(ROLE, path)


def test_the_live_convergence_check_still_passes():
    """Run the measurement itself rather than trusting the copy above it."""
    import subprocess

    tool = ROOT / "tools/strip_credit_convergence_check.py"
    if not tool.exists():
        pytest.skip("the convergence check is not present")
    result = subprocess.run([sys.executable, "-u", str(tool)],
                            capture_output=True, text=True, cwd=str(ROOT))
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
