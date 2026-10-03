"""Does crediting a strip activity actually make the calendar converge?

The second link, and the one the first link was installed to make observable.  A strip
activity has no grid row, so ``record_calendar_snapshot`` had nowhere to put its credit,
``advertised_but_unread_activities`` never emptied, and the scan stayed due forever:
measured 2026-10-03 on live revision aab0dbb8, both roles had an EVENT_DETAIL reading of a
strip activity (``CANYON_CLASH`` for 1061663148, ``STATE_VS_STATE`` for 1063040265, both
with ``calendar_origin=None``) while the debt still listed them, and
DISCOVER_EVENT_CALENDAR was re-selected every 24 seconds.

This exercises the real store with the real reading shape and asks the question that
matters: does the debt fall, and does it stay fallen without the goal being paid for a
second time.  It writes to a temporary store, never to ``learning/``.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import event_schedule as es  # noqa: E402

ROLE = "1061663148"
NOW = es.datetime.now(es.timezone.utc)


def _state(tmp: Path, *, strip_read: bool, detail_event: str) -> Path:
    """A store shaped like the live one: two strip rows, both unread or one already read."""
    path = tmp / "schedule.json"
    payload = {
        "schema_version": "1.0",
        "roles": {},
        "calendar_observations": {
            ROLE: {
                "CALENDAR_GRID": {
                    "kind": "CALENDAR_GRID",
                    "recognized": True,
                    "observed_at": NOW.isoformat(),
                    "entries": [
                        {"event_id": "ICEBOUND_TREASURE", "tap_norm": [0.5, 0.4],
                         "details_observed": True},
                    ],
                },
                "ACTIVITY_STRIP": {
                    "kind": "ACTIVITY_STRIP",
                    "recognized": True,
                    "observed_at": NOW.isoformat(),
                    "entries": [
                        {"event_id": "CANYON_CLASH", "tap_norm": [0.74, 0.13]},
                        {"event_id": "STATE_VS_STATE", "tap_norm": [0.47, 0.13]},
                    ],
                    "read_entries": [{"event_id": "STATE_VS_STATE"}] if strip_read else [],
                },
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _record_strip_detail(path: Path, event_id: str) -> dict:
    """Exactly what the page now produces for a strip activity's detail page.

    ``calendar_origin`` is absent and ``matched_occurrence_key`` is absent, which is what a
    strip detail looks like: there is no grid row to match, and no date range was printed.
    """
    return es.record_calendar_snapshot(
        role_id=ROLE, path=path, evidence_ref="probe.png",
        observation={
            "kind": "EVENT_DETAIL",
            "recognized": True,
            "event_id": event_id,
            "display_name": "峡谷会战" if event_id == "CANYON_CLASH" else "最强王国",
            "countdown_raw": "07:53:19",
            "current_open_state": "SCHEDULED_NOT_OPEN",
        },
    ) or {}


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)

        # 1. Before: two advertised, one already read -> one owed.
        path = _state(tmp, strip_read=True, detail_event="CANYON_CLASH")
        before = es.advertised_but_unread_activities(ROLE, path)
        checks.append((
            "a strip activity that was never opened is a debt",
            before == ("CANYON_CLASH",), f"before={before}"))

        # 2. Reading its detail page is what discharges it.
        snapshot = _record_strip_detail(path, "CANYON_CLASH")
        after = es.advertised_but_unread_activities(ROLE, path)
        checks.append((
            "reading the strip activity's detail discharges its debt",
            after == (), f"after={after}"))
        checks.append((
            "and the snapshot says it credited a strip activity",
            snapshot.get("strip_activity_credited") == "CANYON_CLASH",
            f"strip_activity_credited={snapshot.get('strip_activity_credited')!r}"))

        # 3. The credit must persist rather than being recomputed each time.
        stored = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
        read_ids = {str(r.get("event_id") or "") for r in stored.get("read_entries") or ()}
        checks.append((
            "the credit is stored on the strip, not only in the returned snapshot",
            "CANYON_CLASH" in read_ids, f"read_entries={sorted(read_ids)}"))

        # 4. Re-reading must not duplicate the row -- unbounded growth would be its own bug.
        _record_strip_detail(path, "CANYON_CLASH")
        again = es.latest_calendar_snapshot(ROLE, path, kind="ACTIVITY_STRIP") or {}
        rows = [r for r in again.get("read_entries") or ()]
        checks.append((
            "re-reading does not append the same activity twice",
            len(rows) == len(read_ids), f"rows={rows}"))

        # 5. And it must be a credit, not a payment.  STATE_VS_STATE was seeded as already
        # read, so the honest assertion is that the strip is now fully discharged and that
        # this happened because CANYON_CLASH was read, not because the strip was cleared.
        other = es.advertised_but_unread_activities(ROLE, path)
        checks.append((
            "the strip is fully discharged, and it was CANYON_CLASH's own read that did it",
            other == () and snapshot.get("strip_activity_credited") == "CANYON_CLASH",
            f"still owed={other}, credited={snapshot.get('strip_activity_credited')!r}"))

    # 5b. A strip with nothing read must still show both activities as owed, which is what
    # makes the previous check a credit rather than a wipe.
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        path = _state(tmp, strip_read=False, detail_event="CANYON_CLASH")
        before = es.advertised_but_unread_activities(ROLE, path)
        _record_strip_detail(path, "CANYON_CLASH")
        after = es.advertised_but_unread_activities(ROLE, path)
        checks.append((
            "reading one of two owed activities discharges only that one",
            before == ("CANYON_CLASH", "STATE_VS_STATE") and after == ("STATE_VS_STATE",),
            f"before={before} after={after}"))

    # 6. A grid detail must still go to the row, not to the strip.
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        path = _state(tmp, strip_read=False, detail_event="ICEBOUND_TREASURE")
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
        checks.append((
            "a grid activity is credited to its row, never to the strip",
            not strip.get("read_entries"),
            f"strip read_entries={strip.get('read_entries')}"))

    width = max(len(label) for label, _, _ in checks)
    ok = True
    for label, passed, detail in checks:
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {label:<{width}}  ({detail})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
