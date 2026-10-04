"""Replay the main AUTO path's TRUE hexad through the real ``LoopDetector``.

Why this file exists
--------------------
The handoff ``LOOP_DETECTOR_INPUT_IS_NOT_THE_FACT_20261004.md`` recorded the next step as a
*live* shadow observer in ``runtime.py``: feed the main loop's hexad into a real detector,
execute no rung, and read what it says.  The reason was that the first offline replay could
not supply ``semantic_target`` -- the episode row has no such field -- so it fell back to
``""``, and that field is a member of ``action_key``.  A replay that collapses every tap of a
skill onto one action can only *merge* distinctions, so its count is an upper bound.

Measured 2026-10-04, on the ledger itself: the hexad is already there, faithfully.

    page            <- state_after["page"]                 the *after* frame, as the engine uses
    skill           <- skill
    semantic_target <- action["target"]                     e.g. QUICK_PANEL_ROW_HERO_RECRUIT
    state_hash      <- relevant_state_hash(state_after)    reads page/popup/march_used/
                                                            march_max/normal_idle_slots
    outcome         <- result
    progress        <- goal_progress                        the measured Goal fact

So a live observer is not needed in order to *measure*, and this file is the measurement
instead of a call site on the hot path.  It runs the same detector over the same rows five
ways, which is what turns the contamination question from an argument into a number.

What it found (last 60 MB, 3990 rows, 2026-10-04)
------------------------------------------------
    control == action.target on 3990/3990 rows      the reconstruction is exact
    state_after present on 3990/3990 rows
    goal_progress measured on 3676/3990 rows (92%)

    A  progress = progress_from_outcome(result)      0 detections      <- today's rule
    B  progress = the row's goal_progress          172 detections      <- the fact
       AAA 166 / SAME_ACTION_NO_PROGRESS 2 / ABAB 4
       counters  LOOP_DETECTED 172  LOOP_RECOVERED 7  LOOP_DEFERRED 92
       fired on  HERO_RECRUIT_ADVANCED 127, AVOID_STAMINA_WASTE 41,
                 DISCOVER_EVENT_CALENDAR 3, CLEAR_INTEL 1
       goals A catches and B misses: none
    B with the fabricated target: 172 -> 172            contamination is ZERO

``LOOP_FALSE_POSITIVE`` is 0 and that is *by definition*, not a measurement: in
``_settle`` the counter moves only when the **same** action later shows progress, while an
action that simply changes is dropped as stale.  So the honest statement is not "no false
positives" but "the false-positive rate is unmeasured", and the number that says so is this
script's own probe: of the 172 claims, 106 were followed by more of the same non-progressing
action and 66 were never answered at all.

``LOOP_DEFERRED`` is 92/172 = 53%, which is the saturation the handoff predicted: the rung
index climbs once per repeat of the same ``action_key`` and is only reset by progress, so a
172-step identical run is already at ``defer_goal`` by its fourth detection.  The replay
executes no rung, so it measures *how early the flow would be noticed*, not how it would end.

Usage:  python tools/replay_loop_main_path.py [--tail-mb 60] [--json]
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from config import paths  # noqa: E402
from winter_agent_v2 import loop_watch  # noqa: E402
from winter_agent_v2.loop_detector import (  # noqa: E402
    RUNG_DEFER_GOAL,
    LoopDetector, LoopSignature, progress_from_outcome, relevant_state_hash,
)

#: The detector's own threshold, read from the detector rather than restated here.
NO_PROGRESS_REPEATS = LoopDetector.NO_PROGRESS_REPEATS
#: How far forward the corroboration probe looks.  The detector's own window is 12.
PROBE_HORIZON = LoopDetector.WINDOW


def rows(path: Path, tail_bytes: int):
    """The tail of the episode ledger, one dict per line.  Skips the half line at the seam."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - tail_bytes))
        handle.readline()
        for line in handle.read().decode("utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def action_target(row) -> str:
    """``action`` is written as a ``repr`` of the dataclass, not as JSON.

    ``literal_eval``, never ``eval``: the field is a record, and a record must not be able to
    execute anything just by being read back.
    """
    raw = row.get("action")
    if isinstance(raw, dict):
        target = raw.get("target")
    elif isinstance(raw, str) and raw.startswith("{"):
        try:
            target = ast.literal_eval(raw).get("target")
        except (ValueError, SyntaxError):
            target = None
    else:
        target = None
    return str(target or "")


def signature(row, progress, *, true_target: bool) -> LoopSignature:
    """The hexad, as the engine would have built it."""
    after = row.get("state_after")
    after = after if isinstance(after, dict) else (row.get("state_before") or {})
    return LoopSignature(
        role_id=str(row.get("role_id") or ""),
        page=str(after.get("page") or ""),
        goal_id=str(row.get("goal_id") or ""),
        skill_id=str(row.get("skill") or ""),
        semantic_target=action_target(row) if true_target else "",
        state_hash=relevant_state_hash(after),
        verifier_outcome=str(row.get("result") or ""),
        progress=progress,
    )


def outcome_rule(row):
    """Today's production rule at the engine's call site."""
    return progress_from_outcome(row.get("result"))


def goal_rule(row):
    """The measured fact the main path already computes."""
    return row.get("goal_progress")


def replay(loaded, progress_of, *, true_target: bool, per_role: bool, label: str) -> dict:
    """One pass, then an independent probe of every claim it made."""
    detectors: dict[str, LoopDetector] = {}
    single = LoopDetector()
    rows_per_goal: Counter = Counter()
    steps: list[tuple[tuple[str, ...], bool | None, bool, str]] = []

    for row in loaded:
        goal = str(row.get("goal_id") or "")
        if goal:
            rows_per_goal[goal] += 1
        sig = signature(row, progress_of(row), true_target=true_target)
        detector = detectors.setdefault(sig.role_id, LoopDetector()) if per_role else single
        verdict = detector.observe(sig)
        steps.append((sig.action_key, sig.progress, bool(verdict.detected), verdict.pattern))

    fired: Counter = Counter()
    patterns: Counter = Counter()
    corroborated = 0
    unanswered = 0
    for index, (key, _progress, detected, pattern) in enumerate(steps):
        if not detected:
            continue
        fired[str(key[1] or "")] += 1
        patterns[pattern] += 1
        repeats = 0
        progressed = False
        for later in steps[index + 1: index + 1 + PROBE_HORIZON]:
            if later[0] != key:
                break
            repeats += 1
            if later[1] is True:
                progressed = True
                break
        if repeats >= NO_PROGRESS_REPEATS and not progressed:
            corroborated += 1
        else:
            unanswered += 1

    counters: Counter = Counter()
    for detector in ([single] if not per_role else list(detectors.values())):
        for name, value in detector.counts.items():
            counters[name] += value
    return {
        "label": label,
        "detectors": len(detectors) if per_role else 1,
        "detections": sum(patterns.values()),
        "patterns": dict(patterns),
        "counters": {k: v for k, v in counters.items() if v},
        "per_goal": dict(fired),
        "rows_per_goal": dict(rows_per_goal),
        "corroborated": corroborated,
        "unanswered": unanswered,
    }


def report(result: dict, top: int = 8) -> None:
    print(f"--- {result['label']} ---")
    print(f"  detectors        : {result['detectors']}")
    print(f"  detections       : {result['detections']}")
    print(f"  patterns         : {result['patterns']}")
    print(f"  counters         : {result['counters']}")
    print(f"  independent probe: corroborated {result['corroborated']} / "
          f"unanswered {result['unanswered']}")
    print("  goals that fired :")
    if not result["per_goal"]:
        print("      (none)")
    for goal, n in sorted(result["per_goal"].items(), key=lambda kv: -kv[1])[:top]:
        print(f"      {goal:<34} {n:>4}  (rows {result['rows_per_goal'].get(goal, 0)})")
    print()


def per_run_replay(loaded) -> dict:
    """One detector per *run*, which is the one thing a 60 MB pass cannot show.

    The live runtime builds a ``LoopWatch`` at the top of ``run`` and drops it at ``finish``, so
    the detector's window -- and, far more importantly, its per-action rung index -- live for
    exactly one run.  A single detector over a 60 MB tail is not that, and the rung breakdown
    changes completely: an action key repeats across runs that a per-run detector never sees
    together, and ``_yield_to_next_goal`` answers ``False`` for a Goal that run has already held
    back.  So this pass is the one that says what the ladder would *do*.

    The remedy column is not restated here: it comes from ``loop_watch.resolve``, the same
    projection the runtime drives.  An instrument that re-implemented the projection would be a
    second opinion about what a rung means, and the two would disagree after the first edit.
    """
    detectors: dict[tuple[str, str], LoopDetector] = {}
    runs: set[str] = set()
    detections = 0
    rungs: Counter = Counter()
    intents: Counter = Counter()
    fired: Counter = Counter()
    rows_per_goal: Counter = Counter()
    would_yield: Counter = Counter()

    for row in loaded:
        after = row.get("state_after")
        after = after if isinstance(after, dict) else (row.get("state_before") or {})
        run = str(row.get("episode_id") or "")
        goal = str(row.get("goal_id") or "")
        runs.add(run)
        if goal:
            rows_per_goal[goal] += 1
        sig = LoopSignature(
            role_id=str(row.get("role_id") or ""), page=str(after.get("page") or ""),
            goal_id=goal, skill_id=str(row.get("skill") or ""),
            semantic_target=action_target(row), state_hash=relevant_state_hash(after),
            verifier_outcome=str(row.get("result") or ""), progress=row.get("goal_progress"),
        )
        detector = detectors.setdefault((run, sig.role_id), LoopDetector())
        verdict = detector.observe(sig)
        if not verdict.detected:
            continue
        detections += 1
        rungs[verdict.rung] += 1
        fired[goal] += 1
        intent, _skipped = loop_watch.resolve(verdict.rung)
        intents[intent] += 1
        if verdict.rung == RUNG_DEFER_GOAL:
            # What the run would actually *do*: ``_yield_to_next_goal`` refuses a Goal it has
            # already yielded this run, so the count of detections at this rung is an upper
            # bound on the yields, and the difference between the two is the whole reason this
            # pass exists.
            would_yield[(run, goal)] += 1

    return {
        "label": "C  the fact, TRUE target, one detector per RUN  (what the live path does)",
        "runs": len(runs),
        "detectors": len(detectors),
        "detections": detections,
        "rungs": dict(rungs),
        "intents": dict(intents),
        "per_goal": dict(fired),
        "rows_per_goal": dict(rows_per_goal),
        "yield_sites": {f"{run}/{goal}": n for (run, goal), n in would_yield.items()},
        "goals_yielded": sorted({goal for (_run, goal) in would_yield}),
        "runs_yielded": len({run for (run, _goal) in would_yield}),
    }


def report_per_run(result: dict, top: int = 8) -> None:
    print(f"--- {result['label']} ---")
    print(f"  runs             : {result['runs']}   detectors: {result['detectors']}")
    print(f"  detections       : {result['detections']}")
    print(f"  rungs            : {result['rungs']}")
    print(f"  what the run would do (from loop_watch.resolve): {result['intents']}")
    print("  goals that fired :")
    if not result["per_goal"]:
        print("      (none)")
    for goal, n in sorted(result["per_goal"].items(), key=lambda kv: -kv[1])[:top]:
        print(f"      {goal:<34} {n:>4}  (rows {result['rows_per_goal'].get(goal, 0)})")
    print(f"  Goals handed back : {result['goals_yielded']}  "
          f"in {result['runs_yielded']} run(s)")
    for site, n in sorted(result["yield_sites"].items(), key=lambda kv: -kv[1]):
        print(f"      {site:<60} {n:>4} detection(s) at defer_goal")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="replay the main path's hexad")
    parser.add_argument("--ledger", type=Path, default=paths.LOG_ROOT / "episodes.jsonl")
    parser.add_argument("--tail-mb", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    loaded = list(rows(args.ledger, args.tail_mb * 1_000_000))
    print(f"window   : last {args.tail_mb} MB of {args.ledger}")
    print(f"rows     : {len(loaded)}")
    print("roles    :", dict(Counter(str(r.get("role_id") or "") for r in loaded)))
    print()
    mismatch = sum(1 for r in loaded if action_target(r) != str(r.get("control") or ""))
    print(f"control != action.target on {mismatch} rows  (0 means one fact, two spellings)")
    print(f"state_after present on "
          f"{sum(1 for r in loaded if isinstance(r.get('state_after'), dict))} rows")
    measured = sum(1 for r in loaded if r.get("goal_progress") is not None)
    print(f"goal_progress measured on {measured} rows "
          f"({measured * 100 // max(len(loaded), 1)}%)")
    print()

    runs = [
        replay(loaded, outcome_rule, true_target=False, per_role=False,
               label="A  today's rule, fabricated target  (the first replay)"),
        replay(loaded, goal_rule, true_target=False, per_role=False,
               label="B  the fact, fabricated target       (the first replay)"),
        replay(loaded, outcome_rule, true_target=True, per_role=False,
               label="A  today's rule, TRUE target, one detector"),
        replay(loaded, goal_rule, true_target=True, per_role=False,
               label="B  the fact, TRUE target, one detector"),
        replay(loaded, goal_rule, true_target=True, per_role=True,
               label="B  the fact, TRUE target, one detector per role"),
    ]
    live = per_run_replay(loaded)
    if args.json:
        print(json.dumps({"detector": runs, "per_run": live}, ensure_ascii=False, indent=2))
        return 0
    for result in runs:
        report(result)
    report_per_run(live)

    a_old, b_old, a_true, b_true, b_role = runs
    print("contamination, measured rather than argued:")
    print(f"  A  fabricated {a_old['detections']:>4}  ->  TRUE target {a_true['detections']:>4}")
    print(f"  B  fabricated {b_old['detections']:>4}  ->  TRUE target {b_true['detections']:>4}")
    print(f"  B  one detector {b_true['detections']:>4}  ->  one per role {b_role['detections']:>4}")
    print()
    print("goals B(TRUE) catches and A(TRUE) misses:",
          sorted(set(b_true["per_goal"]) - set(a_true["per_goal"])) or "(none)")
    print("goals A(TRUE) catches and B(TRUE) misses:",
          sorted(set(a_true["per_goal"]) - set(b_true["per_goal"])) or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
