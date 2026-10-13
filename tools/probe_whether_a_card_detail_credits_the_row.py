# -*- coding: utf-8 -*-
"""Does a detail whose OWN id is a different hash still credit the row by its date window?

The first version of this probe built the card observation from field names I guessed
(``activity_open_start_raw``), and the rebinding did not fire -- which proves nothing, because
the rebinding may read different fields.  The real observation the run stored for another
activity uses ``preview_start_raw`` / ``preview_end_raw`` instead.

So this version takes a REAL detail observation out of the live store and changes **only its
event_id**, leaving every other field exactly as the reader wrote it.  If the debt still falls,
the credit is date-driven and the id mismatch does not matter.  If it does not fall, the id
mismatch is what blocks the credit -- and since the debt on file is keyed on the grid frame's
ids, that is the reason the loop cannot end.

Runs on a temporary store.  Never writes to ``learning/``.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from winter_agent_v2 import event_schedule as es  # noqa: E402

ROLE = "1063040265"          # a real role, so the live store has observations for it
NOW = datetime.now(timezone.utc)
BOGUS_ID = "DISCOVERED_EVENT_1C9F9BD8F5"   # sha1("除雪小分队") -- what a card frame would mint


def real_observations() -> tuple[dict, dict]:
    """The live grid snapshot and one real detail_observation, read from the store."""
    grid = es.latest_calendar_snapshot(ROLE) or {}
    detail = None
    for row in grid.get("entries") or ():
        if isinstance(row, dict) and isinstance(row.get("detail_observation"), dict):
            detail = row["detail_observation"]
            break
    return grid, detail or {}


def main() -> int:
    live_grid, live_detail = real_observations()
    if not live_grid or not live_detail:
        print("PROBLEMS: the live store carries no grid entry with a detail_observation,")
        print("so this probe cannot build a faithful fixture.  Refusing to guess one.")
        return 2

    # An unobserved row to be credited: its window is what the detail must fall inside.
    target = next((r for r in (live_grid.get("entries") or ())
                   if isinstance(r, dict) and r.get("details_observed") is not True
                   and r.get("tap_norm")), None)
    if target is None:
        print("PROBLEMS: no unobserved row with a tap point in the live grid.")
        return 2

    print("real detail observation taken from the live store:")
    print(f"  event_id          = {live_detail.get('event_id')!r}")
    print(f"  display_name      = {live_detail.get('display_name')!r}")
    print(f"  preview window    = {live_detail.get('preview_start_raw')!r} .. "
          f"{live_detail.get('preview_end_raw')!r}")
    print(f"  calendar_origin   = {live_detail.get('calendar_origin')!r}")
    print()
    print("row to credit (unobserved, taken from the live grid):")
    print(f"  display_name      = {target.get('display_name')!r}")
    print(f"  event_id          = {target.get('event_id')!r}")
    print(f"  dates             = {target.get('calendar_dates_raw')!r}")
    print()

    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "schedule.json"
        es.STATE_PATH = store
        es.record_calendar_snapshot(
            role_id=ROLE, observation={"recognized": True, "entries": [copy.deepcopy(target)]},
            observed_at=NOW, path=store,
        )
        before = es.advertised_but_unread_activities(ROLE, store)
        print(f"debt after the grid reading : {before}")

        # The SAME real observation, with only the identity swapped for a mismatched hash,
        # and its window moved onto the target row's dates so the date match is possible.
        perturbed = copy.deepcopy(live_detail)
        for key in ("event_id", "matched_event_id"):
            if key in perturbed:
                perturbed[key] = BOGUS_ID
        perturbed.pop("matched_occurrence_key", None)      # a fresh reading would not carry one
        target_dates = target.get("calendar_dates_raw") or []
        if target_dates:
            perturbed["preview_start_raw"] = f"2026-{target_dates[0].replace('/', '-')} 00:00"
            perturbed["preview_end_raw"] = f"2026-{target_dates[-1].replace('/', '-')} 24:00"
        print(f"perturbed detail window     : {perturbed.get('preview_start_raw')!r} .. "
              f"{perturbed.get('preview_end_raw')!r}  id={BOGUS_ID}")

        credited = es.record_calendar_detail(
            role_id=ROLE, observation=perturbed, observed_at=NOW + timedelta(seconds=5), path=store,
        )
        after = es.advertised_but_unread_activities(ROLE, store)
        print(f"debt after the detail        : {after}")
        print(f"  matched_occurrence_key = {(credited or {}).get('matched_occurrence_key')!r}")
        print(f"  strip_activity_credited= {(credited or {}).get('strip_activity_credited')!r}")
        print()

    fell = len(after) < len(before)
    print("=" * 88)
    if fell:
        print("ANSWER: the debt fell -- a card whose id is a different hash still credits the")
        print("row it belongs to, on the date evidence alone.  Before the date-window fallback")
        print("was added this printed (1 -> 1) with matched_occurrence_key=None, which is what")
        print("kept the calendar goal re-selected every few minutes.")
        return 0
    print("ANSWER: the debt did NOT fall.  The credit refused a differently-hashed id, so a")
    print("reading taken on a frame that read the label differently credits nothing -- the")
    print("state this probe was written to catch.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
