"""An activity that cannot be entered must not become a permanent read debt.

Operator observed 2026-10-03: ``STATE_VS_STATE`` (最强王国) was full, so it appeared on the
activity strip and could not be entered.  The calendar's debt rule assumed every advertised
activity can eventually be opened, so this one became an unsatisfiable debt and the goal never
converged:

    STATE_VS_STATE in activity_strip.entries : 1109
    STATE_VS_STATE in activity_strip.read_entries : 0
    OPEN_EVENT_CALENDAR_DETAIL aimed at that strip : 10 attempts, all reported success,
        every one of them actually opening a different activity

so ``calendar_scan_due`` stayed True and ``DISCOVER_EVENT_CALENDAR`` was re-selected every
~24 s in a HOME -> EVENT -> SCROLL -> TAB -> BACK cycle.  Every hop was individually correct,
which is why no FAIL ever appeared in the ledger.

Both directions are pinned, because the dangerous half of a fix like this is the permissive
one: excluding an activity forever would mean it is never entered again even after it reopens,
and that is a state with no exit.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from winter_agent_v2 import event_schedule  # noqa: E402


def _registry(tmp: Path, *, marked: bool, observed_on: str) -> Path:
    """A registry carrying one unreachable activity, dated."""
    entry = {
        "event_id": "STATE_VS_STATE",
        "name": "最强王国",
        "gate": "VERIFIED",
    }
    if marked:
        entry["advertised_but_unreachable"] = True
        entry["observed_blockers"] = [{"kind": "CAPACITY_FULL", "observed_at": observed_on,
                                       "source": "OPERATOR_OBSERVED"}]
    path = tmp / "event_registry.json"
    path.write_text(json.dumps({"schema_version": "1.1", "events": [entry]},
                               ensure_ascii=False), encoding="utf-8")
    return path


def _point_at(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(event_schedule, "ACTIVITY_REGISTRY_PATH", path)


def _fresh_grid(today: str) -> dict:
    """A grid read a moment ago.

    ``observed_at`` is not decoration: ``calendar_scan_due`` answers True when the grid has no
    observation time at all, so a stub without one made the first condition fire and both this
    test and its control passed -- or failed -- for a reason unrelated to the debt.
    """
    return {"entries": [], "observed_at": today + "T00:00:00+00:00"}


def _strip_with_unread(today: str) -> dict:
    """A strip advertising the activity while nothing has read it."""
    return {"kind": "ACTIVITY_STRIP", "observed_at": today + "T00:00:00+00:00",
            "entries": [{"event_id": "STATE_VS_STATE"}, {"event_id": "CANYON_CLASH"}],
            "read_entries": [{"event_id": "CANYON_CLASH"}]}


class TheUnreachableActivityIsNotADebtTests:
    def test_an_activity_marked_today_is_excluded(self, tmp_path, monkeypatch):
        today = datetime.now(timezone.utc).date().isoformat()
        _point_at(monkeypatch, _registry(tmp_path, marked=True, observed_on=today))
        assert event_schedule._unreachable_today() == frozenset({"STATE_VS_STATE"})

    def test_the_exclusion_is_applied_to_the_debt(self, tmp_path, monkeypatch):
        """The whole point: the debt that could never clear is now clearable.

        ``calendar_scan_due`` is an OR of four conditions, so the other three are neutralised
        rather than left to fire incidentally -- otherwise this would assert on whichever
        condition happened to be true first and prove nothing about the exclusion.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        _point_at(monkeypatch, _registry(tmp_path, marked=True, observed_on=today))
        strip = _strip_with_unread(today)
        monkeypatch.setattr(event_schedule, "latest_calendar_snapshot",
                            lambda role, path=None, kind="CALENDAR_GRID": (
                                strip if kind == "ACTIVITY_STRIP" else _fresh_grid(today)))
        monkeypatch.setattr(event_schedule, "calendar_scan_pending", lambda *a, **k: False)
        monkeypatch.setattr(event_schedule, "strip_read_stale_against_grid",
                            lambda *a, **k: False)

        # The debt itself no longer names it ...
        assert event_schedule.advertised_but_unread_activities("r") == ()
        # ... and with the other three gates held false, the due answer follows the debt.
        assert event_schedule.calendar_scan_due("r") is False, (
            "an activity that cannot be entered must not keep the calendar permanently due"
        )

    def test_without_the_marker_the_same_frame_is_still_due(self, tmp_path, monkeypatch):
        """The control for the test above: the marker is what clears it, not the fixture."""
        today = datetime.now(timezone.utc).date().isoformat()
        _point_at(monkeypatch, _registry(tmp_path, marked=False, observed_on=today))
        strip = _strip_with_unread(today)
        monkeypatch.setattr(event_schedule, "latest_calendar_snapshot",
                            lambda role, path=None, kind="CALENDAR_GRID": (
                                strip if kind == "ACTIVITY_STRIP" else _fresh_grid(today)))
        monkeypatch.setattr(event_schedule, "calendar_scan_pending", lambda *a, **k: False)
        monkeypatch.setattr(event_schedule, "strip_read_stale_against_grid",
                            lambda *a, **k: False)
        assert event_schedule.advertised_but_unread_activities("r") == ("STATE_VS_STATE",)
        assert event_schedule.calendar_scan_due("r") is True

    def test_yesterday_marker_does_not_exclude_today(self, tmp_path, monkeypatch):
        """The exit.  Capacity is not permanent; a blanket ban would never re-attempt."""
        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        _point_at(monkeypatch, _registry(tmp_path, marked=True, observed_on=yesterday))
        assert event_schedule._unreachable_today() == frozenset()

    def test_an_unmarked_registry_excludes_nothing(self, tmp_path, monkeypatch):
        _point_at(monkeypatch, _registry(tmp_path, marked=False, observed_on="2026-10-03"))
        assert event_schedule._unreachable_today() == frozenset()

    def test_an_unreadable_registry_restores_the_previous_behaviour(self, tmp_path, monkeypatch):
        """Failure must be safe: no registry means no exclusion, not no calendar."""
        _point_at(monkeypatch, tmp_path / "does_not_exist.json")
        assert event_schedule._unreachable_today() == frozenset()

    def test_a_marked_activity_with_no_dated_blocker_is_still_excluded(self, tmp_path, monkeypatch):
        """Silently ignoring a deliberate marker would restore the loop it exists to end."""
        path = tmp_path / "event_registry.json"
        path.write_text(json.dumps({"events": [
            {"event_id": "STATE_VS_STATE", "advertised_but_unreachable": True}]},
            ensure_ascii=False), encoding="utf-8")
        _point_at(monkeypatch, path)
        assert event_schedule._unreachable_today() == frozenset({"STATE_VS_STATE"})


class TheRealRegistryCarriesTheOperatorsObservationTests:
    """Live check against the tree, not a fixture: the observation must be recorded."""

    def test_the_operator_observation_is_in_the_registry(self):
        payload = json.loads(
            (Path(__file__).resolve().parents[1] / "knowledge/events/event_registry.json")
            .read_text(encoding="utf-8"))
        entry = next((e for e in payload.get("events") or ()
                      if e.get("event_id") == "STATE_VS_STATE"), None)
        assert entry is not None, "STATE_VS_STATE must stay in the registry"
        assert entry.get("advertised_but_unreachable") is True, (
            "the operator's 2026-10-03 observation (人数满了所以进不去) is what tells the debt "
            "rule this activity cannot be entered; losing it restores the loop"
        )
        kinds = [b.get("kind") for b in entry.get("observed_blockers") or ()]
        assert "CAPACITY_FULL" in kinds, kinds
        assert entry.get("gate") == "VERIFIED", (
            "recording a blocker must not demote the activity's own gate"
        )

    def test_a_non_loopback_address_is_still_external_unrelated_guard(self):
        """Sanity anchor for the neighbouring rule: this file's fix touches no network path."""
        from tools.research_gate import _endpoints_in, _LOOPBACK_MARKERS

        eps = _endpoints_in('U = "https://api.example.com"')
        assert [e for e in eps if not any(m in e for m in _LOOPBACK_MARKERS)]
