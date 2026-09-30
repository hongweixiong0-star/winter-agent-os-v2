"""Report where production time actually goes, per TASK THROUGHPUT V1 §24.

Operator directive 2026-09-30 (TASK THROUGHPUT V1) §24 asks for throughput KPI rather than
success rate alone, and §27 says to cut the largest measured item first.  This tool reads the
records production already writes and prints both -- so an optimisation can be argued from
numbers instead of from a story about where the seconds must be.

Sources, all read-only:

* ``learning/action_latency.jsonl`` -- per-action phase timings (``action_latency.PHASES``);
* ``learning/episodes.jsonl``       -- per-action outcome, duration, verifier verdict;
* ``learning/global_scheduler_state.json`` -- role sessions, switches, idle counters;
* ``learning/local_gui_model_calls.jsonl`` -- local GUI model usage (UI-Venus-2-9B), which §13 wants at zero.

Usage::

    python tools/throughput_report.py                     # every recorded action
    python tools/throughput_report.py --since 2026-09-29T18:39
    python tools/throughput_report.py --commit 553d8df
    python tools/throughput_report.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The phase keys ``winter_agent_v2/action_latency.py`` writes, in the order they happen.
PHASES = (
    "capture_ms", "ocr_ms", "parse_ms", "decision_ms", "maa_ms",
    "settle_ms", "reobserve_ms", "verifier_ms", "episode_write_ms",
)

#: Navigation skills: their cost is the price of *going somewhere*, not of doing something.
NAVIGATION_PREFIXES = ("OPEN_", "NAVIGATE_", "LEAVE_", "RETURN_", "BACK")


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def _parse(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pct(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))] if ordered else 0.0


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _in_window(rows: list[dict], since: datetime | None, until: datetime | None,
               commit: str | None) -> list[dict]:
    out = []
    for row in rows:
        if commit and not str(row.get("repo_revision") or "").startswith(commit):
            continue
        stamp = _parse(row.get("recorded_at"))
        if stamp is None:
            continue
        if since and stamp < since:
            continue
        if until and stamp > until:
            continue
        out.append(row)
    return out


def collect(*, since=None, until=None, commit=None) -> dict:
    latency = _in_window(_read_jsonl(ROOT / "learning/action_latency.jsonl"),
                         since, until, commit)
    episodes = _in_window(_read_jsonl(ROOT / "learning/episodes.jsonl"),
                          since, until, commit)

    steps = len(latency)
    total_ms = [float(r["total_step_ms"]) for r in latency if r.get("total_step_ms")]
    skill_ms = [float(r["duration"]) * 1000.0 for r in episodes if r.get("duration")]
    task_hours = sum(total_ms) / 3_600_000.0 if total_ms else 0.0

    phase_total = {p: sum(float(r[p]) for r in latency if r.get(p) is not None) for p in PHASES}
    measured = sum(phase_total.values())
    wait_total = sum(float(r["inter_step_wait_ms"]) for r in latency
                     if r.get("inter_step_wait_ms") is not None)

    # ``reobserve_ms`` is one number built from two observations, and until 2026-09-30 the two
    # were indistinguishable in the trace -- as were the recovery/refresh observations, which were
    # not counted anywhere at all.  Report the split so the next cut is chosen from data.
    observation = {}
    for component in sorted({
        key for r in latency for key in r
        if key.startswith("observe_") and key.endswith("_ms")
    }):
        observation[component] = sum(float(r[component]) for r in latency if r.get(component) is not None)
        observation[component.replace("_ms", "_share")] = (
            100.0 * observation[component] / measured if measured else 0.0)
    observe_calls = sum(int(r.get("observe_before_calls") or 0) + int(r.get("observe_after_calls") or 0)
                        + int(r.get("observe_recovery_calls") or 0) + int(r.get("observe_refresh_calls") or 0)
                        for r in latency)

    navigation = [r for r in latency
                  if str(r.get("skill") or "").upper().startswith(NAVIGATION_PREFIXES)]
    navigation_ms = sum(float(r["total_step_ms"]) for r in navigation if r.get("total_step_ms"))

    passed = [r for r in latency if str(r.get("success")).lower() in {"true", "1"}]
    transitions = sum(1 for r in latency
                      if r.get("page_before") and r.get("page_after")
                      and r["page_before"] != r["page_after"])
    recovered = [r for r in episodes if r.get("recovery_result")]

    state = {}
    try:
        state = json.loads((ROOT / "learning/global_scheduler_state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass

    switches = [row for row in (state.get("role_switch_history") or [])
                if not since or (_parse(row.get("at")) or since) >= since]
    session = state.get("role_session") or {}

    # The Qwen ledger carries no repo revision, so a ``--commit`` run has to borrow the window
    # from the actions that did match; otherwise every historical call would be attributed to
    # the current pin and QWEN_CALLS_PER_TASK would be nonsense.
    qwen_since, qwen_until = since, until
    if commit and since is None and until is None:
        action_stamps = [s for s in (_parse(r.get("recorded_at")) for r in latency)
                         if s is not None]
        if action_stamps:
            qwen_since, qwen_until = min(action_stamps), max(action_stamps)
    qwen = _in_window(_read_jsonl(ROOT / "learning/local_gui_model_calls.jsonl"),
                      qwen_since, qwen_until, None)

    by_skill: dict[str, list[float]] = {}
    for row in latency:
        if row.get("total_step_ms") is not None:
            by_skill.setdefault(str(row.get("skill") or "?"), []).append(float(row["total_step_ms"]))
    failed = [r for r in episodes
              if str(r.get("result") or "").upper() == "FAILURE"
              or r.get("verifier_ok") is False]
    failure_counts = Counter(
        str(r.get("failure_type") or r.get("observed_change") or "?") for r in failed
    )

    # Wall span against summed task time: the difference is device time that produced no
    # action -- round boundaries, role switches, worker restarts, soak windows.  This is the
    # honest stand-in for §24's DEVICE_IDLE_WHILE_WORK_EXISTS, which nothing records directly.
    stamps = [s for s in (_parse(r.get("recorded_at")) for r in latency) if s is not None]
    wall_span_s = (max(stamps) - min(stamps)).total_seconds() if len(stamps) > 1 else 0.0
    task_seconds = sum(total_ms) / 1000.0

    return {
        "steps": steps,
        "episodes": len(episodes),
        "task_hours": task_hours,
        "wall_first": min((str(r.get("recorded_at")) for r in latency), default=None),
        "wall_last": max((str(r.get("recorded_at")) for r in latency), default=None),
        # Per hour of *task time*: the rate the steps would run at back to back.  Dividing by
        # the recorded span instead would fold in every operator stop and soak window.
        "steps_per_hour": steps / task_hours if task_hours else 0.0,
        "tasks_per_hour": len(passed) / task_hours if task_hours else 0.0,
        "verified_actions": len(passed),
        "verified_actions_per_hour": len(passed) / task_hours if task_hours else 0.0,
        "task_duration_p50_ms": _median(total_ms),
        "task_duration_p95_ms": _pct(total_ms, 0.95),
        "skill_duration_p50_ms": _median(skill_ms),
        "skill_duration_p95_ms": _pct(skill_ms, 0.95),
        "page_transitions": transitions,
        "page_transitions_per_task": transitions / steps if steps else 0.0,
        "ocr_calls_per_task": _mean([float(r.get("ocr_calls") or 0) for r in latency]),
        "ocr_cache_hits_per_task": _mean([float(r.get("ocr_cache_hits") or 0) for r in latency]),
        "qwen_calls_per_task": (len(qwen) / steps) if steps else 0.0,
        "role_switches": len(switches),
        "role_switches_per_hour": (len(switches) / task_hours) if task_hours else 0.0,
        "role_session_id": session.get("role_id"),
        "role_session_ratio": session.get("completion_ratio"),
        "role_session_elapsed_s": session.get("elapsed_seconds"),
        "global_wait_with_runnable_goal": state.get("global_wait_with_runnable_goal_count"),
        "wall_span_s": wall_span_s,
        "task_seconds": task_seconds,
        "idle_share": (100.0 * max(0.0, wall_span_s - task_seconds) / wall_span_s
                       if wall_span_s else 0.0),
        "device_idle_while_work_exists": state.get("device_idle_while_work_exists_count"),
        "phase_ms": phase_total,
        "phase_share": {p: (100.0 * v / measured if measured else 0.0)
                        for p, v in phase_total.items()},
        "observation": observation,
        "observe_calls": observe_calls,
        "observe_calls_per_task": (observe_calls / steps) if steps else 0.0,
        "wait_share": (100.0 * wait_total / (measured + wait_total)
                       if (measured + wait_total) else 0.0),
        "navigation_share": (100.0 * navigation_ms / sum(total_ms) if total_ms else 0.0),
        "recovery_share": (100.0 * len(recovered) / len(episodes)) if episodes else 0.0,
        "slowest_skills": sorted(
            ((_median(v), k, len(v)) for k, v in by_skill.items()), reverse=True)[:10],
        "top_failures": failure_counts.most_common(10),
        "slowest_steps": sorted(
            ((float(r["total_step_ms"]), str(r.get("skill"))) for r in latency
             if r.get("total_step_ms")), reverse=True)[:10],
    }


def render(report: dict) -> None:
    def line(label: str, value, unit: str = "") -> None:
        print("  %-42s %s%s" % (label, value, unit))

    print("== throughput ==")
    line("actions recorded", report["steps"])
    line("episodes recorded", report["episodes"])
    line("verified actions", report["verified_actions"])
    line("ACTIONS_PER_HOUR", "%.1f" % report["steps_per_hour"])
    line("TASKS_COMPLETED_PER_HOUR", "%.1f" % report["tasks_per_hour"])
    line("VERIFIED_ACTIONS_PER_HOUR", "%.1f" % report["verified_actions_per_hour"])

    print("\n== duration ==")
    line("TASK (step) P50", "%.0f" % report["task_duration_p50_ms"], " ms")
    line("TASK (step) P95", "%.0f" % report["task_duration_p95_ms"], " ms")
    line("SKILL       P50", "%.0f" % report["skill_duration_p50_ms"], " ms")
    line("SKILL       P95", "%.0f" % report["skill_duration_p95_ms"], " ms")

    print("\n== per task ==")
    line("PAGE_TRANSITIONS_PER_TASK", "%.3f" % report["page_transitions_per_task"])
    line("OCR_CALLS_PER_TASK", "%.2f" % report["ocr_calls_per_task"])
    line("OCR_CACHE_HITS_PER_TASK", "%.2f" % report["ocr_cache_hits_per_task"])
    line("QWEN_CALLS_PER_TASK", "%.4f" % report["qwen_calls_per_task"])

    print("\n== role ==")
    line("ROLE_SWITCHES", report["role_switches"])
    line("ROLE_SWITCHES_PER_HOUR", "%.2f" % report["role_switches_per_hour"])
    line("current role session", report["role_session_id"])
    line("session completion ratio", report["role_session_ratio"])

    print("\n== where the time goes (share of measured phases) ==")
    for phase, share in sorted(report["phase_share"].items(), key=lambda kv: -kv[1]):
        line(phase, "%5.1f%%" % share, "  (%.1f min)" % (report["phase_ms"][phase] / 60000.0))
    line("WAIT (inter-step gap)", "%.1f%%" % report["wait_share"])
    line("NAVIGATION (nav skills, of step time)", "%.1f%%" % report["navigation_share"])
    line("RECOVERY (episodes reporting a recovery)", "%.1f%%" % report["recovery_share"])

    if report["observation"]:
        print("\n== inside the observation (the phase that dominates) ==")
        # ``ocr_ms`` runs *inside* the observation window, so these shares overlap it by
        # construction; read them as "which part of the look", not as a partition of the step.
        for component, ms in sorted(
            ((k, v) for k, v in report["observation"].items() if k.endswith("_ms")),
            key=lambda kv: -kv[1],
        ):
            line(component, "%5.1f%%" % report["observation"][component.replace("_ms", "_share")],
                 "  (%.1f min)" % (ms / 60000.0))
        line("observe calls (all phases)", report["observe_calls"])
        line("OBSERVE_CALLS_PER_TASK", "%.2f" % report["observe_calls_per_task"])
    else:
        print("\n== inside the observation ==")
        line("(no split recorded)", "older rows predate the observe_* fields")

    print("\n== device time ==")
    line("task time (summed steps)", "%.1f" % (report["task_seconds"] / 60.0), " min")
    line("recorded wall span", "%.1f" % (report["wall_span_s"] / 60.0), " min")
    line("DEVICE_IDLE_WHILE_WORK_EXISTS (derived)", "%.1f%%" % report["idle_share"],
         "  <- round boundaries, switches, restarts")

    print("\n== slowest skills by median step ==")
    for ms, skill, n in report["slowest_skills"]:
        print("  %8.0f ms  n=%-4d %s" % (ms, n, skill))

    print("\n== slowest single steps ==")
    for ms, skill in report["slowest_steps"]:
        print("  %8.0f ms  %s" % (ms, skill))

    print("\n== safety counters ==")
    line("GLOBAL_WAIT_WITH_RUNNABLE_GOAL", report["global_wait_with_runnable_goal"])
    line("DEVICE_IDLE_WHILE_WORK_EXISTS", report["device_idle_while_work_exists"])

    if report["top_failures"]:
        print("\n== top failures ==")
        for name, count in report["top_failures"]:
            print("  %4d  %s" % (count, name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", help="ISO timestamp lower bound")
    parser.add_argument("--until", help="ISO timestamp upper bound")
    parser.add_argument("--commit", help="only rows stamped with this repo revision prefix")
    parser.add_argument("--json", help="also write the raw report here")
    args = parser.parse_args()

    report = collect(since=_parse(args.since), until=_parse(args.until), commit=args.commit)
    if args.commit:
        print("commit filter: %s" % args.commit)
    if args.since or args.until:
        print("window: %s .. %s" % (args.since or "-", args.until or "-"))
    render(report)

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print("\nwrote %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
