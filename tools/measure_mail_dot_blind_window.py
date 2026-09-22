"""Measure the mail entry's red dot against the mail reading, from production episodes.

Operator directive 2026-09-23 §二①: a *new* dot on an entry must wake the goal that entry names.
The goal layer cannot do that today for one specific reason, and this tool measures how often the
reason bites rather than assuming it:

    a fresh stored reading of the mail page that says "nothing to claim" keeps ``MAIL_ROUTINE``
    COMPLETE for the store's whole TTL (15 minutes, ``observation_store.DEFAULT_TTL_SECONDS``),
    and a dot the client draws on the mail entry during that window is not consulted at all.

So the two things worth counting, both from what production actually recorded:

A. every step whose before-frame is HOME, by ``red_dots.BTN_OPEN_MAIL.state`` -- the signal has to
   come and go for it to be a signal, so ABSENT must be observed too.  (A dot that is always
   present is artwork or a never-zero count, and the measured table already says so for the
   other entries; this is the same test applied to the one entry that claims to vary.)

B. within a single run, the gap between *the last mail page reading that said there is nothing*
   and *the next HOME frame that draws the dot* -- i.e. the blind window itself, in steps and in
   minutes.  Only runs whose steps carry a timestamp and a readable mail status can answer this;
   the count of runs that cannot answer it is reported rather than hidden.

Read-only: no device, no writes, nothing imported from the runtime.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENTRY = "BTN_OPEN_MAIL"
#: The statuses the mail page prints when there is nothing left to take.  Copied from
#: ``goal_library.PANEL_ROUTINES``' own ``done`` tuple for MAIL_ROUTINE; a second copy of the
#: vocabulary here would be one more thing to drift, so the values are asserted against the
#: module below rather than retyped from memory.
DONE_STATUSES = ("CLAIMED", "ALL_CLEAR", "NOT_AVAILABLE")
TTL_MINUTES = 15.0


def _moment(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _page_of(state: object) -> str:
    if not isinstance(state, dict):
        return ""
    page = state.get("page")
    if isinstance(page, dict):
        return str(page.get("value") or "")
    return str(page or "")


def _mail_status(state: object) -> str:
    if not isinstance(state, dict):
        return ""
    mail = state.get("mail")
    if not isinstance(mail, dict):
        return ""
    return str(mail.get("status") or "").upper()


def main() -> int:
    from winter_agent_v2.goal_library import PANEL_ROUTINES

    routine = next(r for r in PANEL_ROUTINES if r.goal_id == "MAIL_ROUTINE")
    assert set(DONE_STATUSES) == set(routine.done), (
        f"the mail done-statuses moved: goal_library says {sorted(routine.done)}, "
        f"this tool says {sorted(DONE_STATUSES)}"
    )
    assert routine.field == "mail", routine.field

    rows = []
    skipped = 0
    with EPISODES.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A malformed line is counted, not swallowed.  ``episodes.jsonl`` is appended to by
                # a live runtime, so reading it can catch a half-written tail; a skip that is
                # invisible would look exactly like a corpus that is simply smaller.
                skipped += 1

    dot_counts: Counter[str] = Counter()
    pixels: list[int] = []
    home_frames = 0
    for row in rows:
        state = row.get("state_before")
        if _page_of(state) != "HOME":
            continue
        home_frames += 1
        dots = state.get("red_dots") if isinstance(state, dict) else None
        record = (dots or {}).get(ENTRY) if isinstance(dots, dict) else None
        state_word = str((record or {}).get("state") or "NOT_READ")
        dot_counts[state_word] += 1
        if state_word == "PRESENT":
            pixels.append(int((record or {}).get("pixels") or 0))

    # ---- B: the blind window, per run, in step order -------------------------------------
    by_run: dict[str, list[dict]] = {}
    for row in rows:
        by_run.setdefault(str(row.get("episode_id") or ""), []).append(row)

    windows: list[dict] = []
    runs_unreadable = 0
    for run_id, steps in by_run.items():
        steps = [s for s in steps if _moment(s.get("recorded_at"))]
        if len(steps) < 2:
            continue
        steps.sort(key=lambda s: _moment(s.get("recorded_at")))
        if not any(_page_of(s.get("state_before")) == "MAIL" for s in steps):
            continue
        last_done: tuple[datetime, str] | None = None
        found_any = False
        for step in steps:
            state = step.get("state_before")
            page = _page_of(state)
            moment = _moment(step.get("recorded_at"))
            if page == "MAIL":
                status = _mail_status(state)
                if status in DONE_STATUSES:
                    last_done = (moment, status)
                else:
                    # A reading that is *not* "nothing there" resets the window: the goal is
                    # already awake, so there is no blindness to measure.
                    last_done = None
                continue
            if page != "HOME" or last_done is None:
                continue
            dots = state.get("red_dots") if isinstance(state, dict) else None
            record = (dots or {}).get(ENTRY) if isinstance(dots, dict) else None
            if str((record or {}).get("state") or "") != "PRESENT":
                continue
            found_any = True
            waited = (moment - last_done[0]).total_seconds() / 60.0
            windows.append({
                "run": run_id,
                "after_status": last_done[1],
                "minutes_since_reading": round(waited, 1),
                "within_ttl": waited <= TTL_MINUTES,
                "steps_since_reading": len(
                    [s for s in steps
                     if _moment(s.get("recorded_at")) <= moment]
                ) - len([s for s in steps if _moment(s.get("recorded_at")) <= last_done[0]]),
                "frame": str(step.get("before_screenshot") or ""),
                "skill_that_step": str(step.get("skill") or ""),
                "goal_that_step": str(step.get("goal_id") or ""),
            })
        if not found_any:
            runs_unreadable += 1

    print(f"episodes read           : {len(rows)}")
    print(f"lines skipped (malformed): {skipped}  (a live runtime appends to this file; "
          f"a half-written tail reads as malformed and is skipped, not treated as absent)")
    print(f"HOME before-frames      : {home_frames}")
    print(f"  mail dot states       : {dict(dot_counts)}")
    if pixels:
        print(f"  PRESENT blob pixels   : min {min(pixels)} max {max(pixels)} "
              f"(the table measured 276-302; a differing range would mean a different mark)")
    print()
    print(f"runs with a mail reading and no later dot : {runs_unreadable}")
    print(f"blind-window observations   : {len(windows)}")
    within = [w for w in windows if w["within_ttl"]]
    print(f"  ...inside the 15 min TTL  : {len(within)}")
    for w in windows[:20]:
        print(f"  after {w['after_status']:<12} +{w['minutes_since_reading']:>6.1f} min "
              f"({'INSIDE' if w['within_ttl'] else 'past  '} TTL, {w['steps_since_reading']} steps) "
              f"{w['frame'].split(chr(92))[-1] if w['frame'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
