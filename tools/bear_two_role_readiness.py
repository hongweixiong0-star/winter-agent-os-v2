"""Are both roles actually ready to join a bear rally, and is a window open right now?

The bear work has one recurring problem: the window is short (measured 2026-10-05: the only live
reading was ``status=ACTIVE, remaining_seconds=73``), so a session that starts after it closed can
only reason about it afterwards.  This tool answers the operator's actual question -- "are my two
roles ready, and is there a window?" -- from files, in one command, with each fact's source named.

It is read-only: it opens no device, takes no lease, and never taps.

Each check reports one of:
  OK      the fact is present and consistent
  WAIT    nothing is wrong; the client simply has not printed this yet (e.g. no window open)
  GAP     something the project owns is missing or contradictory -- this is actionable

usage:
    python tools/bear_two_role_readiness.py
    python tools/bear_two_role_readiness.py --role 1063040265 --role 1061663148
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

#: The two roles the operator asked about.  The registry also records a third
#: (``1171757165``), which is *not* included here: this tool answers for the two named roles, and
#: adding a third silently would be a claim about who is being driven.
DEFAULT_ROLES = ("1063040265", "1061663148")
EPISODES = ROOT / "learning/episodes.jsonl"
GOAL_STATE = ROOT / "learning/goal_state.json"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
BEAR_TARGET_WORDS = ("变异巨熊", "巨熊")


def _rows() -> list[dict]:
    out = []
    try:
        text = EPISODES.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _rally_rows_by_role(rows: list[dict]) -> dict[str, list[dict]]:
    """Every rally row any role has read, newest last, with the labels it carried."""
    found: dict[str, list[dict]] = {}
    for row in rows:
        state = row.get("state_after")
        rally = (state or {}).get("rally") if isinstance(state, dict) else None
        if not isinstance(rally, dict):
            continue
        entries = rally.get("rows")
        if not isinstance(entries, list):
            continue
        role = str(row.get("role_id") or "?")
        for entry in entries:
            if isinstance(entry, dict):
                found.setdefault(role, []).append({
                    "at": str(row.get("recorded_at") or ""),
                    "skill": str(row.get("skill") or ""),
                    "frame": str(row.get("after_screenshot") or row.get("before_screenshot") or ""),
                    "target_text": str(entry.get("target_text") or ""),
                    "target_type": str(entry.get("target_type") or ""),
                    "state": str(entry.get("state") or ""),
                    "joinable": entry.get("joinable"),
                    "capacity_used": entry.get("capacity_used"),
                    "capacity_max": entry.get("capacity_max"),
                })
    return found


def _bear_readings(rows: list[dict]) -> list[dict]:
    """Every frame that carried a live ``events.bear``, newest last."""
    out = []
    for row in rows:
        state = row.get("state_after")
        events = (state or {}).get("events") if isinstance(state, dict) else None
        bear = (events or {}).get("bear") if isinstance(events, dict) else None
        if isinstance(bear, dict) and bear:
            out.append({
                "at": str(row.get("recorded_at") or ""),
                "role_id": str(row.get("role_id") or "?"),
                "status": bear.get("status"),
                "remaining_seconds": bear.get("remaining_seconds"),
                "seconds_to_start": bear.get("seconds_to_start"),
                "source": bear.get("source"),
            })
    return out


def _label_matches_bear(text: str) -> bool:
    return any(word in text for word in BEAR_TARGET_WORDS)


def _frame_has_a_bear_label(frame: str) -> bool | None:
    """Does this recorded frame's OCR contain a bear target word **anywhere**?

    This is the distinction the first version of this tool got wrong, and it matters: a row whose
    ``target_text`` is empty has two completely different causes.

      * the client printed no bear on that frame -- normal when no window is open.  Nothing is
        broken and no code change would help.
      * the frame *does* print a bear and the reader failed to bind it to the row -- that is the
        reader's problem, and it is fixable.

    Counting both as "unreadable label" produced the false conclusion "one role cannot read a bear
    row" from three frames that contained no bear at all (measured 2026-10-05: their only beast
    label was 等级7霜鳞避役, on a 1/15 row with a 2-minute countdown).

    Returns None when the frame file or the OCR runtime is unavailable, so a missing tool reports
    "cannot tell" rather than a verdict.
    """
    path = Path(frame)
    if not frame or not path.exists():
        return None
    try:
        from winter_agent_v2.ocr import OCRService, RapidOCRBackend

        result = OCRService(RapidOCRBackend()).recognize(path)
    except Exception:  # noqa: BLE001 - a diagnostic must never be the thing that fails
        return None
    for token in getattr(result, "tokens", ()) or ():
        if _label_matches_bear(str(getattr(token, "text", ""))):
            return True
    return False


def check_role(role: str, rally: dict[str, list[dict]], *, verify_frames: int = 0) -> dict:
    """What this role can and cannot do about the bear, from the frames it produced."""
    rows = rally.get(role, [])
    labelled = [row for row in rows if row["target_text"]]
    bear_labelled = [row for row in labelled if _label_matches_bear(row["target_text"])]
    unreadable = [row for row in rows if not row["target_text"]]
    joinable_bear = [row for row in bear_labelled if row["joinable"]]

    # Optionally look at the newest label-less frames and ask whether the client printed a bear.
    verified: list[dict] = []
    for row in unreadable[-verify_frames:] if verify_frames else []:
        seen = _frame_has_a_bear_label(str(row.get("frame") or ""))
        verified.append({"at": row["at"], "frame": row.get("frame"),
                         "client_printed_a_bear": seen})
    misread = [item for item in verified if item["client_printed_a_bear"] is True]
    absent = [item for item in verified if item["client_printed_a_bear"] is False]

    if joinable_bear:
        verdict = "READY"
    elif bear_labelled:
        verdict = "SEES_BEAR_NOT_JOINABLE"
    elif misread:
        verdict = "READER_MISSED_A_PRINTED_LABEL"
    elif absent:
        verdict = "NO_BEAR_ON_THOSE_FRAMES"
    elif unreadable:
        verdict = "UNREADABLE_LABEL_UNVERIFIED"
    elif rows:
        verdict = "NO_BEAR_ON_THOSE_FRAMES"
    else:
        verdict = "NO_RALLY_FRAME_YET"

    return {
        "role_id": role,
        "rally_rows_read": len(rows),
        "rows_with_a_label": len(labelled),
        "rows_naming_the_bear": len(bear_labelled),
        "rows_with_no_readable_label": len(unreadable),
        "bear_rows_marked_joinable": len(joinable_bear),
        "frames_verified": len(verified),
        "frames_where_the_client_printed_a_bear": len(misread),
        "frames_with_no_bear_printed": len(absent),
        "verification": verified,
        "last_bear_row": bear_labelled[-1] if bear_labelled else None,
        "last_unreadable_row": unreadable[-1] if unreadable else None,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", action="append", dest="roles",
                        help="role id to report (repeatable)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verify-frames", type=int, default=0, metavar="N",
                        help="run OCR over the newest N label-less frames per role and report "
                             "whether the client actually printed a bear there (slow: loads the "
                             "OCR runtime)")
    args = parser.parse_args(argv)
    roles = tuple(args.roles) if args.roles else DEFAULT_ROLES

    rows = _rows()
    rally = _rally_rows_by_role(rows)
    readings = _bear_readings(rows)
    now = datetime.now(timezone.utc)

    report = {
        "checked_at": now.isoformat(),
        "episodes_scanned": len(rows),
        "roles": [check_role(role, rally, verify_frames=args.verify_frames) for role in roles],
        "bear_window_readings": readings[-6:],
        "window_open_now": False,
        "sources": {
            "episodes": str(EPISODES),
            "goal_state": str(GOAL_STATE),
            "snapshot": str(SNAPSHOT),
        },
    }

    # A window is "open now" only if the newest reading still has time left on it.  A reading with
    # remaining_seconds from an hour ago is history, not a window -- the countdown has run out.
    if readings:
        newest = readings[-1]
        try:
            age = (now - datetime.fromisoformat(newest["at"])).total_seconds()
        except (TypeError, ValueError):
            age = float("inf")
        remaining = newest.get("remaining_seconds")
        if isinstance(remaining, int) and age < remaining:
            report["window_open_now"] = True

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"checked at {report['checked_at'][:19]}Z  ({report['episodes_scanned']} episodes)")
        print()
        for role in report["roles"]:
            print(f"role {role['role_id']}   [{role['verdict']}]")
            print(f"   rally rows read .......... {role['rally_rows_read']}")
            print(f"   ...with a label .......... {role['rows_with_a_label']}")
            print(f"   ...naming the bear ....... {role['rows_naming_the_bear']}")
            print(f"   ...unreadable label ...... {role['rows_with_no_readable_label']}")
            print(f"   bear rows joinable ....... {role['bear_rows_marked_joinable']}")
            if role["frames_verified"]:
                print(f"   frames verified .......... {role['frames_verified']} "
                      f"(client printed a bear in {role['frames_where_the_client_printed_a_bear']}, "
                      f"no bear in {role['frames_with_no_bear_printed']})")
            if role["last_bear_row"]:
                row = role["last_bear_row"]
                print(f"   last bear row ............ {row['at'][:19]} "
                      f"{row['target_text']!r} {row['capacity_used']}/{row['capacity_max']} "
                      f"joinable={row['joinable']}")
            if role["last_unreadable_row"]:
                row = role["last_unreadable_row"]
                print(f"   last unreadable row ...... {row['at'][:19]} state={row['state']}")
            print()
        print(f"bear window readings on file: {len(readings)}")
        for reading in readings[-4:]:
            print(f"   {reading['at'][:19]}  role {reading['role_id']}  "
                  f"status={reading['status']} remaining={reading['remaining_seconds']} "
                  f"source={reading['source']}")
        print()
        print(f"WINDOW OPEN NOW: {report['window_open_now']}")
        if not readings:
            print("   (no frame has ever carried events.bear -- nothing to judge)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
