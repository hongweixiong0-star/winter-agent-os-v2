# -*- coding: utf-8 -*-
"""Record one activity's printed reservation, from frames already captured off the client.

Why this exists

    The wake chain is complete in code -- the printed line is read (event_calendar.
    read_printed_reservation), the duration is computed from the client's own clock
    (event_schedule.seconds_until_a_printed_reservation), and the reservation is written
    (runtime._record_live_event_reservation -> record_live_countdown).  What is missing is a
    GOAL that would take the agent onto the page where the line is printed, so the runtime's own
    loop never feeds it.  Measured 2026-10-10: both active roles' BEAR_HUNT reserved_start were
    None, so tomorrow's window would have had no wake behind it.

    So this records the reading once, by hand, the way this project has always recorded a live
    read it did not automate yet -- bear_hunt_time_20260927_newaccount.json was written from a
    V2 session and bear_hunt_time_20260928.json from the operator.  It uses no new arithmetic and
    no new store.

What it does NOT do

    It does not invent a time.  The reservation and the clock are both read off frames with the
    production readers; the difference is taken with the tested helper; and the source string
    says exactly what happened so a later reader can tell this from an AUTO-loop observation.

Usage
    python tools/record_a_printed_reservation_from_a_frame.py \
        --reservation-frame <bear page png> --clock-frame <calendar png> \
        --activity BEAR_HUNT --role 1063040265 --role 1061663148
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = "RECORDED_FROM_CAPTURED_LIVE_FRAMES_BY_TOOL"


def _tokens(path: Path):
    import numpy as np
    from PIL import Image

    from winter_agent_v2.executor_router import _rapid_ocr_results
    from winter_agent_v2.ocr import OCRToken

    raw = _rapid_ocr_results(np.asarray(Image.open(path).convert("RGB")), None, [])
    return [OCRToken(t["text"], t["score"], ((t["box"][0], t["box"][1]),
                                              (t["box"][0] + t["box"][2], t["box"][1]),
                                              (t["box"][0] + t["box"][2], t["box"][1] + t["box"][3]),
                                              (t["box"][0], t["box"][1] + t["box"][3])))
            for t in raw]


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reservation-frame", required=True, type=Path)
    ap.add_argument("--clock-frame", required=True, type=Path)
    ap.add_argument("--activity", default="BEAR_HUNT")
    ap.add_argument("--role", action="append", required=True)
    ap.add_argument("--clock-frame-age-seconds", type=float, default=0.0,
                    help="how long ago --clock-frame was captured, if it was not just now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv[1:])

    from winter_agent_v2 import event_calendar, event_schedule

    reservation = event_calendar.read_printed_reservation(_tokens(args.reservation_frame))
    if reservation is None:
        print(json.dumps({"refused": "the reservation frame prints no 预约自动开启 line"},
                         ensure_ascii=False))
        return 2
    calendar = event_calendar.read_event_calendar(
        _tokens(args.clock_frame), frame_size=(720, 1280), frame_path=args.clock_frame)
    clock = (calendar or {}).get("current_game_datetime_raw")
    if not clock:
        print(json.dumps({"refused": "the clock frame prints no client clock "
                                     "(read_event_calendar.current_game_datetime_raw is empty)"},
                         ensure_ascii=False))
        return 2

    lead = event_schedule.seconds_until_a_printed_reservation(
        reservation["reserved_start_time"], clock,
        client_now_age_seconds=args.clock_frame_age_seconds)
    ledger = {
        "activity": args.activity, "roles": args.role,
        "reserved_local_from_the_client": reservation["reserved_start_time"],
        "client_clock_from_the_client": clock,
        "clock_frame_age_seconds": args.clock_frame_age_seconds,
        "lead_seconds": lead, "source": SOURCE,
        "reservation_frame": str(args.reservation_frame), "clock_frame": str(args.clock_frame),
    }
    if lead is None:
        ledger["refused"] = "the two stamps do not give a positive lead"
        print(json.dumps(ledger, ensure_ascii=False, indent=1))
        return 2

    now = datetime.now(timezone.utc)
    if not args.dry_run:
        schedules = event_schedule.load()
        for role in args.role:
            event_schedule.record_live_countdown(
                schedules, role_id=role, event_id=args.activity, seconds_to_start=lead,
                source=SOURCE, role="AUTO", alliance=None, now=now)
        event_schedule.save(schedules)
        ledger["written_at"] = now.isoformat()
        ledger["reserved_start"] = (now + __import__("datetime").timedelta(seconds=lead)).isoformat()
    print(json.dumps(ledger, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
