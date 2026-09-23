"""The numbers behind the operator's five questions about task existence and execution windows.

Operator directive 2026-09-23, final-report section:

    任务存在性与执行资格在哪一层被混淆？
    当前哪些周期活动已经能够提前准备？
    活动开放后多久开始首次有效操作？
    无红点巡检减少了多少？
    任务暂时不可执行时，AUTO 实际继续做了什么？

This tool answers each one from artifacts rather than from prose: the registry for the second, the
production corpus for the third and fifth, and ``tools/measure_red_dot_gating.py`` for the fourth (its
numbers are recomputed here so one command answers all five).

    python tools/measure_activity_windows.py
    python tools/measure_activity_windows.py --out dataset/truth_audit/activity_windows_20260923
    python tools/measure_activity_windows.py --since 2026-09-23T13:25:00+00:00

Where a question cannot be answered from what is on file, the tool says so instead of estimating.
That is the point of it: "how long after opening did work start" has no answer for an event this
project has never been present for, and a made-up number would be worse than a gap.

Read-only: no device, no clicks, no writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"

#: When the goal-layer change landed.  Defaults to the mtime of the file that carries it, because a
#: hand-written timestamp is wrong the moment the change is touched again -- and this window has to be
#: the real one or the before/after comparison means nothing.  Overridable for a re-measurement.
def _layer_landed_at() -> str:
    try:
        stamp = (ROOT / "winter_agent_v2/goal_library.py").stat().st_mtime
    except OSError:
        return "1970-01-01T00:00:00+00:00"
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()

#: The goals whose existence the goal layer decides, and the entry each one needs.  Kept here rather
#: than imported so the report still runs if the mapping is being edited.
GATED_GOALS = {"MAIL_ROUTINE": "BTN_OPEN_MAIL", "ALLIANCE_ROUTINE": "TILE_ALLIANCE_GIFTS"}

#: Goals that are activity instances rather than routines.
ACTIVITY_GOALS = ("PARTICIPATE_BEAR", "EVENT_MINIMUM_GUARANTEE")


def _rows() -> list[dict]:
    out: list[dict] = []
    try:
        handle = EPISODES.open(encoding="utf-8")
    except OSError:
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("recorded_at"):
                out.append(row)
    return out


def _page(row: dict, key: str = "state_before") -> str:
    value = (row.get(key) or {}).get("page")
    return str(value.get("value") if isinstance(value, dict) else value or "")


def _popup(row: dict, key: str = "state_before") -> str:
    return str((row.get(key) or {}).get("popup") or "")


def _window(rows: list[dict], since: str, until: str) -> list[dict]:
    """Rows in ``[since, until)``.  An empty bound means unbounded, on either side.

    The empty case has to be handled rather than compared: ``stamp < ""`` is False for every
    non-empty stamp, so comparing directly made "until the end" mean "nothing at all" -- which read
    as an empty AFTER window and is exactly the kind of silently-zero measurement this whole round is
    about.  Found by running it.
    """
    out = []
    for row in rows:
        stamp = str(row.get("recorded_at") or "")
        if since and stamp < since:
            continue
        if until and stamp >= until:
            continue
        out.append(row)
    return out


def q1_where_the_two_conflated(rows: list[dict]) -> dict:
    """Which layer, and what it looked like there -- measured with the real library, not quoted."""
    from winter_agent_v2.goal_library import GoalLibrary
    from winter_agent_v2.models import Page, WorldState

    library = GoalLibrary()

    def board(**kwargs) -> list[dict]:
        world = WorldState(page=Page.EVENT, confidence=0.99, **kwargs)
        return [{"goal_id": goal.goal_id, "status": goal.status.value,
                 "priority": None if goal.priority == float("-inf") else round(goal.priority, 1)}
                for goal in library.discover(world, observations={})]

    now = board(events={"bear": {"status": "ACTIVE", "remaining_seconds": 900}})
    later = board(events={"bear": {"seconds_to_start": 7200}})
    ended = board(events={"bear": {"status": "FINISHED"}})
    absent = board(events={})

    print("===== Q1  任务存在性与执行资格在哪一层被混淆？")
    print("      layer: GoalLibrary.discover -- both halves in the same few lines, in opposite directions")
    print("      (a) existence was read off the current frame: `world.events` is written in one place")
    print("          (ocr.py, from what the page prints), so a task nobody is standing in front of")
    print("          did not exist.  Measured over the whole corpus below.")
    print("      (b) executability ignored the window: every non-FINISHED bear phase was emitted READY,")
    print("          so a window that had not opened was priced as work.  Same library, same frame:")
    for label, rows_ in (("bear running now        ", now), ("bear opens in two hours ", later),
                         ("bear already ended     ", ended), ("no reading this frame   ", absent)):
        entry = next((r for r in rows_ if r["goal_id"] == "PARTICIPATE_BEAR"), None)
        print(f"        {label} -> {entry or '(goal absent from the board)'}")
    events_read = sum(1 for row in rows
                      if isinstance((row.get("state_before") or {}).get("events"), dict)
                      and (row.get("state_before") or {}).get("events"))
    bear_read = sum(1 for row in rows
                    if "bear" in ((row.get("state_before") or {}).get("events") or {}))
    print(f"      corpus: {len(rows)} episodes, {events_read} carry any event reading, "
          f"{bear_read} carry `bear`")
    return {"bear_active": now, "bear_in_two_hours": later, "bear_ended": ended,
            "no_reading": absent, "episodes": len(rows), "episodes_with_events": events_read,
            "episodes_with_bear": bear_read}


def q2_what_can_be_prepared() -> dict:
    from winter_agent_v2.event_goal import known_activities

    print("===== Q2  当前哪些周期活动已经能够提前准备？")
    out = {}
    activities = known_activities()
    if not activities:
        print("      (none: the registry vouches for no plannable activity)")
        return out
    for activity in activities:
        window = activity.window()
        next_open = activity.next_open_condition
        print(f"      {activity.event_id}  {activity.name}   gate={activity.gate}  "
              f"cadence={activity.cadence}  window={window.value}")
        print(f"        next open : {next_open.get('printed_cooldown') or next_open.get('printed_remaining') or '(unknown)'}"
              f"   read from {next_open.get('field')}")
        print(f"        prepare   : {len(activity.prepare)} item(s), knowledge {len(activity.knowledge)} file(s), "
              f"participation rules {len(activity.participation_conditions)}")
        print(f"        occurrence: {activity.occurrence.get('state')}")
        out[activity.event_id] = {
            "name": activity.name, "gate": activity.gate, "cadence": activity.cadence,
            "window": window.value, "next_open_condition": dict(next_open),
            "prepare": list(activity.prepare), "knowledge": list(activity.knowledge),
            "participation_conditions": list(activity.participation_conditions),
            "occurrence": dict(activity.occurrence),
            "reliable_start": activity.start, "reliable_end": activity.end,
        }
    if not any(a.time_is_known for a in activities):
        print("      note: no activity on file has a reliable start/end time, so the window is answered")
        print("            by what the client printed (next_open_condition) and never by a guess (§二).")
    return out


def q3_latency_after_opening(rows: list[dict]) -> dict:
    """How long after a window opened the first effective step happened -- or why it cannot be said."""
    print("===== Q3  活动开放后多久开始首次有效操作？")
    steps = [row for row in rows if str(row.get("goal_id")) in ACTIVITY_GOALS]
    print(f"      activity-instance steps in the corpus: {len(steps)}"
          f"   by goal {dict(Counter(str(row.get('goal_id')) for row in steps))}")
    if not steps:
        print("      NOT ANSWERABLE from what is on file: this project has never been present for an")
        print("      activity window, so there is no instance to measure a start latency against.")
        print("      The criterion for the next one is on record instead: the transition is driven by")
        print("      the client's own countdown on the frame the run is standing on")
        print("      (rally.bear_phase: 600 s -> PREPARING, 120 s -> READY), so the first effective")
        print("      step is due on the first frame after the countdown crosses it -- not on a timer.")
        return {"activity_steps": 0, "answer": "NOT_OBSERVED"}
    # The reading that opened the window is not stored per step, so report what the corpus does carry.
    first = steps[0]
    return {"activity_steps": len(steps), "first_at": first.get("recorded_at"),
            "first_status": str(first.get("result"))}


def q4_no_dot_inspections(rows: list[dict], split: str) -> dict:
    """The reduction in entry-page visits with no dot, before vs after the gate."""
    from winter_agent_v2 import entry_badges

    print("===== Q4  无红点巡检减少了多少？")
    tile_window = (entry_badges.entries().get("TILE_ALLIANCE_GIFTS") or {}).get("search_window_norm")

    def state_of(row: dict, entry: str) -> str:
        ledger = (row.get("state_before") or {}).get("red_dots")
        if isinstance(ledger, dict) and entry in ledger:
            return str((ledger.get(entry) or {}).get("state") or "UNKNOWN")
        if entry == "TILE_ALLIANCE_GIFTS" and tile_window:
            frame = Path(str(row.get("before_screenshot") or ""))
            if frame.is_file():
                try:
                    from PIL import Image
                    from winter_agent_v2.entry_badges import MIN_BLOB_PX, _largest_blob
                    image = Image.open(frame).convert("RGB")
                    width, height = image.size
                    box = (int(tile_window[0] * width), int(tile_window[1] * height),
                           int(tile_window[2] * width), int(tile_window[3] * height))
                    pixels, _ = _largest_blob(image, box)
                    return "PRESENT" if pixels >= MIN_BLOB_PX else "ABSENT"
                except (OSError, ValueError):
                    pass
        return "NO_READING"

    out = {}
    for label, since, until in (("BEFORE", "", split), ("AFTER", split, "")):
        slice_ = _window(rows, since, until)
        entry = {"steps": len(slice_),
                 "from": slice_[0].get("recorded_at") if slice_ else None,
                 "to": slice_[-1].get("recorded_at") if slice_ else None}
        for skill, name in (("OPEN_MAIL", "BTN_OPEN_MAIL"), ("OPEN_ALLIANCE_GIFTS", "TILE_ALLIANCE_GIFTS")):
            steps = [row for row in slice_ if str(row.get("skill")) == skill]
            counts = Counter(state_of(row, name) for row in steps)
            pointless = counts.get("ABSENT", 0) + counts.get("NO_READING", 0)
            entry[skill] = {"steps": len(steps), "by_entry": dict(counts), "without_a_reading": pointless}
        refusals = Counter(str(row.get("decision_reason")) for row in slice_
                           if "entry_" in str(row.get("decision_reason") or "")
                           or "refused_at_the_entry_gate" in str(row.get("decision_reason") or ""))
        entry["entry_gate_decisions"] = dict(refusals)
        out[label] = entry
        print(f"      {label:<6} steps {len(slice_):>5}   "
              f"OPEN_MAIL {len([r for r in slice_ if str(r.get('skill')) == 'OPEN_MAIL']):>3}   "
              f"OPEN_ALLIANCE_GIFTS {len([r for r in slice_ if str(r.get('skill')) == 'OPEN_ALLIANCE_GIFTS']):>3}"
              f"   gate decisions {dict(refusals) or '{}'}")
    before = out["BEFORE"]["OPEN_MAIL"]["without_a_reading"] + out["BEFORE"]["OPEN_ALLIANCE_GIFTS"]["without_a_reading"]
    after_steps = out["AFTER"]["steps"]
    print(f"      => before the gate: {before} entry-page visits taken with no dot reading at all")
    print(f"      => after: {after_steps} steps so far; "
          f"OPEN_MAIL {out['AFTER']['OPEN_MAIL']['steps']}, "
          f"OPEN_ALLIANCE_GIFTS {out['AFTER']['OPEN_ALLIANCE_GIFTS']['steps']}")
    print("      acceptance: 邮件 ABSENT/UNKNOWN → 没有 OPEN_MAIL 步；宝箱 ABSENT/UNKNOWN → 没有宝箱进入")
    return out


def q5_what_the_run_did_instead(rows: list[dict], split: str) -> dict:
    """When a task could not be run, what did the batch actually do (§六/§七.6)."""
    print("===== Q5  任务暂时不可执行时，AUTO 实际继续做了什么？")
    slice_ = _window(rows, split, "")
    by_goal = Counter(str(row.get("goal_id") or "(none)") for row in slice_)
    refused = [row for row in slice_
               if "entry_" in str(row.get("decision_reason") or "")
               or "refused_at_the_entry_gate" in str(row.get("decision_reason") or "")]

    def after_refusal(row: dict, index: int) -> dict | None:
        for follower in slice_[index + 1:index + 4]:
            if str(follower.get("episode_id")) == str(row.get("episode_id")):
                return follower
        return None

    continued = Counter()
    for index, row in enumerate(slice_):
        if row not in refused:
            continue
        follower = after_refusal(row, index)
        continued[str(follower.get("skill")) if follower else "(end of run)"] += 1
    print(f"      steps since the split: {len(slice_)}; refused at a gate: {len(refused)}")
    print(f"      what ran instead: {dict(continued) or '(no refusal in this window)'}")
    print(f"      goals the run worked on: {dict(by_goal.most_common(10))}")
    run_ids = {str(row.get("episode_id")) for row in slice_}
    print(f"      runs in the window: {len(run_ids)}")
    return {"steps": len(slice_), "refused": len(refused),
            "after_refusal": dict(continued), "by_goal": dict(by_goal.most_common(20)),
            "runs": len(run_ids)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=None,
                        help="when the goal-layer change landed (default: goal_library.py's mtime)")
    parser.add_argument("--out", type=Path, default=None, help="write the numbers as JSON here")
    args = parser.parse_args()

    rows = _rows()
    if not rows:
        print("no episodes on file")
        return 1
    rows.sort(key=lambda row: str(row.get("recorded_at")))
    split = args.since or _layer_landed_at()
    print(f"corpus: {len(rows)} steps, "
          f"{rows[0].get('recorded_at')} .. {rows[-1].get('recorded_at')}")
    print(f"split at {split}"
          + ("" if args.since else "   (goal_library.py mtime; pass --since to move it)"))
    if split > str(rows[-1].get("recorded_at") or ""):
        print("NOTE: the split is after the last step on file, so the AFTER window is empty.  That is")
        print("      the honest state while the running AUTO still holds the previous module -- a")
        print("      before/after comparison needs the new code to have actually executed.")
    print()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {"steps": len(rows), "from": rows[0].get("recorded_at"), "to": rows[-1].get("recorded_at")},
        "split": split,
        "q1": q1_where_the_two_conflated(rows),
        "q2": q2_what_can_be_prepared(),
        "q3": q3_latency_after_opening(rows),
        "q4": q4_no_dot_inspections(rows, split),
        "q5": q5_what_the_run_did_instead(rows, split),
    }

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "activity_windows.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print()
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
