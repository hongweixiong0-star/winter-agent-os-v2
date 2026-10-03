"""Replay the real calendar frames and prove the COMPLETE row is now recorded.

The defect this measures was found on live revision 58dccc8b, not reasoned about: of 38
EVENT frames, 19 carried ``regular_events_hub`` and 19 did not, and the 19 that did not
all read ``entries=5`` with ``details_observed=5`` -- the branch saying the scan is
finished -- after which ``DISCOVER_EVENT_CALENDAR`` was nowhere on the board.  That is the
shape of a self-erasing cycle: navigate in, open the calendar, vanish, get carried back
out, and do it again 19 times.

A unit test could only assert that a fixture produces a COMPLETE row, which it always
did.  What had to be measured is whether the *live* frames produce one, and whether the
row now says why the goal stopped being actionable -- because "asked and answered" and
"never asked" look identical in the ledger otherwise.

So this reads the frames the device produced.  It is deliberately not a guess about what
the client will draw: the frames come from ``learning/episodes.jsonl`` and the assertion
is that the fix changes what those frames produce.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.goal_library import GoalLibrary, GoalStatus  # noqa: E402
from winter_agent_v2.models import WorldState  # noqa: E402

LEDGER = ROOT / "learning/episodes.jsonl"
CALENDAR_GOAL = "DISCOVER_EVENT_CALENDAR"


def live_event_frames(limit: int = 4000) -> tuple[list[dict], list[dict]]:
    """Real EVENT frames, split by whether the frame carried the regular-events hub.

    The split is the finding itself: the frames that keep the goal on the board and the
    frames that erase it are the same page, one perception apart.
    """
    rows: list[dict] = []
    with LEDGER.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("recorded_at"):
                rows.append(row)
    rows.sort(key=lambda r: r["recorded_at"])
    with_hub: list[dict] = []
    without_hub: list[dict] = []
    for row in rows[-limit:]:
        before = row.get("state_before")
        if not isinstance(before, dict) or before.get("page") != "EVENT":
            continue
        events = before.get("events")
        hub = events.get("regular_events_hub") if isinstance(events, dict) else None
        (with_hub if isinstance(hub, dict) else without_hub).append(before)
    return with_hub, without_hub


def _world_from(before: dict) -> WorldState:
    """A WorldState carrying exactly what the ledger recorded, and nothing invented.

    Only ``page`` and ``events`` are set, because the calendar goal reads only those two.
    Every other field keeps its dataclass default rather than being guessed, so a pass
    here cannot come from a field this replay invented.  ``known`` is a read-only
    property derived from ``page``, so it is not assigned.
    """
    from winter_agent_v2.skills import Page
    return WorldState(page=Page.EVENT, events=dict(before.get("events") or {}))


def main() -> int:
    with_hub, without_hub = live_event_frames()
    print(f"live EVENT frames: with hub {len(with_hub)}, without hub {len(without_hub)}")
    if not without_hub:
        print("FAIL: no hub-less EVENT frame in the window; nothing to prove")
        return 1

    library = GoalLibrary()
    checks: list[tuple[str, bool, str]] = []

    # 1. The hub frames must still produce an actionable goal -- the fix must not have
    #    closed the door it was supposed to keep open.
    hub_rows = []
    for before in with_hub[:20]:
        for goal in library.discover(_world_from(before)):
            if goal.goal_id == CALENDAR_GOAL:
                hub_rows.append(goal)
                break
    checks.append((
        "a hub frame still yields an actionable DISCOVER_EVENT_CALENDAR",
        bool(hub_rows) and all(g.available_skills for g in hub_rows),
        f"{len(hub_rows)} rows, skills={ {g.available_skills for g in hub_rows} }",
    ))

    # 2. The hub-less frames are the defect.  They must now produce a COMPLETE row that
    #    says why, rather than producing nothing at all.
    completed = []
    for before in without_hub:
        for goal in library.discover(_world_from(before)):
            if goal.goal_id == CALENDAR_GOAL:
                completed.append(goal)
                break
    checks.append((
        "a hub-less EVENT frame now yields a DISCOVER_EVENT_CALENDAR row at all",
        bool(completed),
        f"{len(completed)}/{len(without_hub)} frames produced a row",
    ))

    complete_rows = [g for g in completed if g.status is GoalStatus.COMPLETE]
    ready_rows = [g for g in completed if g.status is not GoalStatus.COMPLETE]
    # Not every hub-less frame is a finished scan.  Measured over the window: 203 COMPLETE,
    # 192 READY with OPEN_EVENT_CALENDAR_DETAIL (there really are details left to open), 5
    # READY with RETURN_EVENT_CALENDAR, 2 with no row.  Asserting "all COMPLETE" would be
    # asserting the bug -- a grid whose entries still need opening must stay actionable --
    # so the claim under test is the split itself: a finished scan is COMPLETE, an unfinished
    # one is still actionable, and neither disappears.
    checks.append((
        "a finished scan is COMPLETE and an unfinished one stays actionable -- the split is "
        "what makes the row honest",
        bool(complete_rows) and bool(ready_rows)
        and all(g.available_skills for g in ready_rows)
        and not any(g.available_skills for g in complete_rows),
        f"{len(complete_rows)} COMPLETE (no skills), {len(ready_rows)} still actionable",
    ))

    # 3. The load-bearing part: the row has to name the precondition that stopped
    #    holding, or "answered" stays indistinguishable from "never asked".
    served = [g for g in complete_rows if (g.evidence or {}).get("served_by")]
    unserved_ready = [g for g in ready_rows if (g.evidence or {}).get("served_by")]
    checks.append((
        "the COMPLETE row names why the goal stopped being actionable (served_by), and an "
        "unfinished row does not claim to",
        bool(served) and len(served) == len(complete_rows) and not unserved_ready,
        f"{len(served)}/{len(complete_rows)} finished rows carry served_by="
        f"{ {(g.evidence or {}).get('served_by') for g in served} }, "
        f"{len(unserved_ready)} unfinished rows wrongly claim it",
    ))

    # 4. And it must carry no price and no skills, or the agent would reopen the panel
    #    it just closed -- the reason COMPLETE is the right state in the first place.
    priced = [g for g in complete_rows if g.available_skills]
    checks.append((
        "a finished calendar scan carries no skills, so AUTO does not reopen the panel "
        "it just read",
        not priced,
        f"{len(priced)} finished rows still advertised skills",
    ))

    # 5. The defect was disappearance, so the honest measure is how many *calendar* frames
    #    still produce no row.  Two of 402 produce none, and both were checked rather than
    #    averaged away: they are 2026-10-02 frames from older revisions (f80093be, f3e5d8d5)
    #    showing a super-activity panel and the fishing tournament -- real activity pages
    #    that are not the calendar grid and correctly own no calendar goal.  Scoping the
    #    claim to frames that actually carry a calendar is the difference between measuring
    #    this defect and measuring something adjacent to it.
    calendar_frames = [
        b for b in without_hub
        if isinstance(b.get("events"), dict) and isinstance(b["events"].get("calendar"), dict)
    ]
    produced_calendar = sum(
        1 for b in calendar_frames
        if any(g.goal_id == CALENDAR_GOAL
               for g in library.discover(_world_from(b)))
    )
    checks.append((
        "every hub-less frame that carries a calendar grid produces a row (the defect was "
        "that none did)",
        produced_calendar == len(calendar_frames) and bool(calendar_frames),
        f"{produced_calendar}/{len(calendar_frames)} calendar frames produced a row; "
        f"{len(without_hub) - len(calendar_frames)} non-calendar EVENT frames excluded by name",
    ))

    width = max(len(label) for label, _, _ in checks)
    ok = True
    for label, passed, detail in checks:
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {label:<{width}}  ({detail})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
