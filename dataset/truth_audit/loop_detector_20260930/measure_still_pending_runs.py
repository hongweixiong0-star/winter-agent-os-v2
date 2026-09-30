"""Measurement for #44: the run-length distribution of STILL_PENDING, and what a bound costs.

This is the measurement the task asks for *before* any change ("改变前应先测『连续 STILL_PENDING
的分布』").  Two facts from ``audit_outcome_persistence.py`` shape how it must be done:

* the outcome is not a ledger column, so it is reconstructed from the reason string, with the
  source line cited per reason (``OUTCOME_BY_REASON``);
* one reason is overloaded -- ``FISHING_RESULT_PENDING`` is emitted with either ``PROGRESS`` or
  ``STILL_PENDING`` from the same adapter line -- so the script reports a **strict** reading
  (only unambiguous reasons) and a **loose** reading (add the overloaded one).

The decision the numbers have to support is a bound on STILL_PENDING.  A bound that is too
tight converts honest waiting into a defer, so the sweep reports, for every candidate
threshold, both the stalls it catches and the *resolved* runs it would have killed.
"""
from __future__ import annotations

import json
import collections
from pathlib import Path
from typing import Any

ROOT = Path("E:/无尽冬日智能体")
STORE = ROOT / "learning/episodes.jsonl"
OUT = ROOT / "dataset/truth_audit/loop_detector_20260930/still_pending_runs.json"

#: reason (head) -> (outcome, the source line that produces it).  Never inferred from data.
OUTCOME_BY_REASON: dict[str, tuple[str, str]] = {
    "FISHING_CONTROL_SESSION_RAN": ("PROGRESS", "session_adapters.py:522"),
    "FISHING_LEVEL_ENTRY_TAPPED": ("PROGRESS", "session_adapters.py:531"),
    "FISHING_RESULT_LEFT": ("PROGRESS", "session_adapters.py:534"),
    # Overloaded: adapters:538 returns PROGRESS when the result page is up, else STILL_PENDING.
    "FISHING_RESULT_PENDING": ("OVERLOADED", "session_adapters.py:538"),
    "FISHING_CAST_VERIFIED": ("SUCCESS", "session_adapters.py:554"),
    "FISHING_NO_FRAME": ("AMBIGUOUS", "session_adapters.py:560"),
    "FISHING_LINE_VISIBLE": ("PROGRESS", "session_adapters.py:564"),
    "FISHING_WAITING_FOR_LEVEL": ("STILL_PENDING", "session_adapters.py:565"),
    "FISHING_FRAME_ADVANCED": ("PROGRESS", "session_adapters.py:566"),
    "STAMINA_STILL_UNREADABLE": ("STILL_PENDING", "session_adapters.py:883"),
    "STAMINA_NO_VERDICT": ("AMBIGUOUS", "session_adapters.py:886"),
    "STAMINA_MARCH_VERIFIED": ("SUCCESS", "session_adapters.py:890"),
    "BEAR_NO_VERDICT": ("AMBIGUOUS", "session_adapters.py:760"),
    "BEAR_STEP_VERIFIED": ("SUCCESS", "session_adapters.py:768"),
    "TRAINING_NO_VERDICT": ("AMBIGUOUS", "session_adapters.py:1058"),
    "TRAINING_CAMP_TAPPED": ("SUCCESS", "session_adapters.py:1063"),
    "SESSION_STEP_NOT_VERIFIED": ("FAILED", "session_engine.py:967"),
    "SESSION_AMBIGUOUS": ("AMBIGUOUS", "session_engine.py:1037"),
    "SESSION_NO_STEP_PRODUCED": ("STILL_PENDING", "session_engine.py:900 terminal"),
    "SESSION_DOMAIN_STUCK": ("FAILED", "session_engine.py:1006 loop handback"),
}

OVERLOADED_REASON = "FISHING_RESULT_PENDING"

#: The budgets the fishing/training routes declare, for comparing a run against its ceiling.
ROUTE_BUDGETS = {
    "FISHING_ENTER": (5, 60.0),
    "FISHING_CAST_AT_LEVEL": (10, 150.0),
    "FISHING_CAST_AT_SEA": (10, 150.0),
}


def rows():
    with STORE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def session_step(row: dict) -> tuple[str, str] | None:
    reason = str(row.get("decision_reason") or "")
    if not reason.startswith("session:"):
        return None
    parts = reason.split(":", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def outcome_of(reason: str, *, loose: bool) -> tuple[str, str]:
    head = reason.split(":", 1)[0]
    entry = OUTCOME_BY_REASON.get(head)
    if entry is None:
        return "UNKNOWN", "unknown"
    outcome, _cite = entry
    if outcome == "OVERLOADED":
        return ("STILL_PENDING", "loose") if loose else ("UNKNOWN", "unknown")
    return outcome, "strict"


def maximal_runs(sequence: list[str]) -> list[tuple[int, int]]:
    """-> [(start_index, length)] for every maximal run of STILL_PENDING."""
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(sequence):
        if sequence[index] != "STILL_PENDING":
            index += 1
            continue
        start = index
        while index < len(sequence) and sequence[index] == "STILL_PENDING":
            index += 1
        runs.append((start, index - start))
    return runs


def analyse(loose: bool) -> dict[str, Any]:
    sessions: dict[str, list[tuple[str, dict]]] = collections.OrderedDict()
    for row in rows():
        parsed = session_step(row)
        if parsed is None:
            continue
        sessions.setdefault(parsed[0], []).append((parsed[1], row))

    all_runs: list[int] = []
    per_session: dict[str, Any] = {}
    for sid, seq in sessions.items():
        outcomes = [outcome_of(reason, loose=loose)[0] for reason, _ in seq]
        runs = maximal_runs(outcomes)
        for start, length in runs:
            all_runs.append(length)
        if runs:
            per_session[sid] = {
                "steps": len(seq),
                "runs": [length for _, length in runs],
                "outcomes": outcomes,
            }

    histogram = collections.Counter(all_runs)

    # ---- what each run ended on: another verdict, or the end of the session (the budget)
    anatomy: list[dict[str, Any]] = []
    for sid, seq in sessions.items():
        outcomes = [outcome_of(reason, loose=loose)[0] for reason, _ in seq]
        for start, length in maximal_runs(outcomes):
            ends_at_session_end = (start + length) >= len(seq)
            anatomy.append({
                "session_id": sid,
                "start": start,
                "length": length,
                "ended_by": "session_end" if ends_at_session_end else "another_verdict",
                "next_reason": ("" if ends_at_session_end
                                else seq[start + length][0].split(":", 1)[0]),
                "step_count_after_the_run": len(seq) - (start + length),
            })

    resolved = [item for item in anatomy if item["ended_by"] == "another_verdict"]
    budget = [item for item in anatomy if item["ended_by"] == "session_end"]

    # ---- threshold sweep, counting the cost of a false positive
    sweep = []
    for threshold in range(2, 9):
        tripping = [item for item in anatomy if item["length"] >= threshold]
        tripping_resolved = [item for item in tripping if item["ended_by"] == "another_verdict"]
        sweep.append({
            "threshold": threshold,
            "sessions_tripped": len({item["session_id"] for item in tripping}),
            "runs_tripped": len(tripping),
            "runs_tripped_that_resolved": len(tripping_resolved),
            "false_positive_rate": (round(len(tripping_resolved) / len(tripping), 3)
                                    if tripping else None),
            "longest_run_left_alone": max((item["length"] for item in anatomy
                                           if item["length"] < threshold), default=0),
        })

    # ---- wall time: is the run a wait honouring a clock, or a busy spin?
    wall = []
    for item in anatomy:
        total = sum(float(item_row.get("duration") or 0.0)
                    for item_row in seq_durations(sessions[item["session_id"]],
                                                  item["start"], item["length"]))
        wall.append({"session_id": item["session_id"], "length": item["length"],
                     "seconds_in_the_run": round(total, 3),
                     "seconds_per_step": round(total / item["length"], 4)})

    return {
        "reading": "loose" if loose else "strict",
        "sessions_with_a_run": len(per_session),
        "still_pending_steps": sum(all_runs),
        "runs": len(all_runs),
        "histogram": {str(k): v for k, v in sorted(histogram.items())},
        "longest_run": max(all_runs) if all_runs else 0,
        "mean_run_length": (round(sum(all_runs) / len(all_runs), 2) if all_runs else None),
        "per_session": per_session,
        "run_anatomy": anatomy,
        "runs_that_resolved": len(resolved),
        "runs_that_ended_at_the_session_end": len(budget),
        "threshold_sweep": sweep,
        "run_wall_time": wall,
    }


def seq_durations(seq: list[tuple[str, dict]], start: int, length: int):
    return [row for _, row in seq[start:start + length]]


def main() -> None:
    strict = analyse(loose=False)
    loose = analyse(loose=True)

    # The ledger is appended to by the live AUTO while this runs, so a count without the size
    # it was taken at is not reproducible.  Recorded here for the same reason ``code_revision``
    # is recorded on the replay: a number detached from its snapshot is not evidence.
    ledger_rows = sum(1 for _ in rows())

    report = {
        "ledger_rows_at_measurement": ledger_rows,
        "what_this_measures": (
            "The run-length distribution of consecutive STILL_PENDING session steps, and the "
            "false-positive cost of each candidate bound."
        ),
        "why_two_readings": (
            "FISHING_RESULT_PENDING is the only STILL_PENDING-shaped reason that actually occurs, "
            "and it is emitted with PROGRESS or STILL_PENDING from the same line, so it cannot be "
            "resolved from the record. STRICT counts only reasons that name one outcome; LOOSE "
            "adds the overloaded one."
        ),
        "outcome_by_reason": {k: list(v) for k, v in OUTCOME_BY_REASON.items()},
        "strict": strict,
        "loose": loose,
        "finding": {},
        "limitations": [
            "The outcome is reconstructed from the reason string, never from a ledger column: "
            "see audit_outcome_persistence.py. One reason is overloaded, hence two readings.",
            "The corpus contains no unambiguous STILL_PENDING step at all, so the strict reading "
            "is empty and every number here rests on the overloaded reason.",
            "`step_budget` is a ceiling, and the run that reaches it is invisible in the ledger: "
            "the budget terminal is a SessionResult, and finish() writes no episode row.",
        ],
    }

    wall_all = loose["run_wall_time"]
    per_step = [item["seconds_per_step"] for item in wall_all if item["length"]]
    report["finding"] = {
        "strict_reading_is_empty": strict["runs"] == 0,
        "runs_are_at_most": loose["longest_run"],
        "longest_run_equals_budget_minus_two": loose["longest_run"] == 10 - 2,
        "runs_that_resolved": loose["runs_that_resolved"],
        "runs_that_died_at_the_session_end": loose["runs_that_ended_at_the_session_end"],
        "seconds_per_step_median": (round(sorted(per_step)[len(per_step) // 2], 4)
                                    if per_step else None),
        "the_run_is_a_busy_spin_not_a_wait": all(value < 0.1 for value in per_step),
        "clean_step_threshold": next(
            (item["threshold"] for item in loose["threshold_sweep"]
             if item["runs_tripped_that_resolved"] == 0
             and item["sessions_tripped"] > 0), None),
        "threshold_that_would_kill_most_sessions": next(
            (item["threshold"] for item in loose["threshold_sweep"]
             if item["sessions_tripped"] >= 10), None),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for label, block in (("STRICT", strict), ("LOOSE", loose)):
        print(f"== {label} ==")
        print(f"  sessions with a run : {block['sessions_with_a_run']}")
        print(f"  STILL_PENDING steps : {block['still_pending_steps']}")
        print(f"  runs                : {block['runs']}")
        print(f"  histogram           : {block['histogram']}")
        print(f"  longest run         : {block['longest_run']}")
        print(f"  resolved / budget   : {block['runs_that_resolved']} / "
              f"{block['runs_that_ended_at_the_session_end']}")
        print("  threshold sweep:")
        print("      N  sessions  runs  of_which_resolved  false_pos_rate  longest_left_alone")
        for item in block["threshold_sweep"]:
            print(f"      {item['threshold']}  {item['sessions_tripped']:>8d}  "
                  f"{item['runs_tripped']:>4d}  {item['runs_tripped_that_resolved']:>17d}  "
                  f"{str(item['false_positive_rate']):>14s}  {item['longest_run_left_alone']:>17d}")
        print()

    print("== wall time inside a run (loose reading) ==")
    for item in wall_all:
        print(f"  {item['session_id']}  len={item['length']:2d}  "
              f"{item['seconds_in_the_run']:>7.3f}s total  "
              f"{item['seconds_per_step']:.4f}s/step")
    print()

    print("== finding ==")
    for key, value in report["finding"].items():
        print(f"  {key:46s} = {value!r}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
