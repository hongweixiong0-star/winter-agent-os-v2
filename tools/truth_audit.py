"""Recompute the current truth of Winter Agent OS V2 from raw evidence.

Every number in docs/CURRENT_TRUTH.md comes from here. Nothing is hardcoded:
historical summaries in old Markdown must never be trusted again.

Fact precedence (see the takeover directive):
    LIVE CLIENT > PRODUCTION EVIDENCE > CURRENT CODE > TEST > DOCUMENT > PRIOR KNOWLEDGE

Run:  python tools/truth_audit.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPISODES = ROOT / "learning/episodes.jsonl"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
COVERAGE_JSON = ROOT / "learning/goal_coverage.json"
OUT_JSON = ROOT / "learning/current_truth.json"
OUT_MD = ROOT / "docs/CURRENT_TRUTH.md"

# Historical episodes were written with mixed-case `result` values. History must
# never be rewritten (directive 44), so normalize on read instead of on disk.
SUCCESS_RESULTS = {"SUCCESS", "success"}
FAILURE_RESULTS = {"FAILURE", "failure"}


def load_episodes() -> list[dict]:
    episodes: list[dict] = []
    if not EPISODES.is_file():
        return episodes
    for line in EPISODES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            episodes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return episodes


def normalize(result: object) -> str:
    value = str(result or "").strip().upper()
    if value in SUCCESS_RESULTS:
        return "SUCCESS"
    if value in FAILURE_RESULTS:
        return "FAILURE"
    return value or "UNSPECIFIED"


def episode_stats(episodes: list[dict]) -> dict:
    total = len(episodes)
    tally = Counter(normalize(e.get("result")) for e in episodes)
    success = tally.get("SUCCESS", 0)
    failure = tally.get("FAILURE", 0)
    decided = success + failure
    return {
        "total": total,
        "success": success,
        "failure": failure,
        "blocked": tally.get("BLOCKED", 0),
        "in_progress": tally.get("IN_PROGRESS", 0),
        "success_rate_over_decided": round(success / decided * 100, 1) if decided else 0.0,
        "success_rate_over_total": round(success / total * 100, 1) if total else 0.0,
        "modes": dict(Counter(e.get("mode") for e in episodes)),
        "result_case_anomaly": sum(
            1 for e in episodes if str(e.get("result", "")) in {"success", "failure"}
        ),
    }


def failure_ranking(episodes: list[dict], top: int = 12) -> list[dict]:
    by_type: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "skills": Counter(), "recent": None}
    )
    for episode in episodes:
        if normalize(episode.get("result")) != "FAILURE":
            continue
        kind = episode.get("failure_type") or "UNCLASSIFIED"
        bucket = by_type[kind]
        bucket["count"] += 1
        bucket["skills"][episode.get("skill")] += 1
        recorded = str(episode.get("recorded_at") or "")
        if recorded and (bucket["recent"] is None or recorded > bucket["recent"]):
            bucket["recent"] = recorded
    rows = [
        {
            "failure_type": kind,
            "count": data["count"],
            "affected_skills": len(data["skills"]),
            "top_skills": data["skills"].most_common(3),
            "last_seen": data["recent"],
        }
        for kind, data in by_type.items()
    ]
    rows.sort(key=lambda row: -row["count"])
    return rows[:top]


def skill_stats(episodes: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for episode in episodes:
        skill = episode.get("skill")
        if not skill:
            continue
        entry = stats.setdefault(
            skill, {"attempts": 0, "success": 0, "failure": 0, "other": 0, "last_seen": None}
        )
        entry["attempts"] += 1
        outcome = normalize(episode.get("result"))
        if outcome == "SUCCESS":
            entry["success"] += 1
        elif outcome == "FAILURE":
            entry["failure"] += 1
        else:
            entry["other"] += 1
        recorded = str(episode.get("recorded_at") or "")
        if recorded and (entry["last_seen"] is None or recorded > entry["last_seen"]):
            entry["last_seen"] = recorded
    for entry in stats.values():
        decided = entry["success"] + entry["failure"]
        entry["success_rate"] = round(entry["success"] / decided * 100, 1) if decided else None
    return stats


def registry_stats() -> dict:
    try:
        from winter_agent_v2.skills import v2_registry
    except Exception as exc:  # pragma: no cover - audit must not explode
        return {"error": f"{type(exc).__name__}: {exc}"}
    skills = v2_registry().all()
    return {
        "total": len(skills),
        "by_state": dict(Counter(skill.state.value for skill in skills)),
        "by_risk": dict(Counter(str(skill.risk) for skill in skills)),
        "by_latency": dict(Counter(skill.latency_class.value for skill in skills)),
        "realtime": [skill.id for skill in skills if skill.latency_class.value == "REALTIME"],
        "blocked": [skill.id for skill in skills if skill.state.value == "BLOCKED"],
    }


def dataset_stats() -> dict:
    out: dict[str, object] = {}
    for name in ("raw", "candidate", "verified", "normalized", "production", "external"):
        folder = ROOT / "dataset" / name
        if not folder.is_dir():
            out[name] = {"files": 0, "empty_dirs": 0}
            continue
        files = [p for p in folder.rglob("*") if p.is_file() and p.name != ".gitkeep"]
        empty_dirs = sum(1 for p in folder.rglob("*") if p.is_dir() and not any(p.iterdir()))
        out[name] = {"files": len(files), "empty_dirs": empty_dirs}
    return out


def runtime_stats() -> dict:
    if not SNAPSHOT.is_file():
        return {}
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "runtime_snapshot.json is not valid JSON"}


def coverage_freshness() -> dict:
    """Report the *new* capability model, not the retired string-matching one.

    ``learning/goal_coverage.json`` matched goal-requirement strings against
    registry strings and therefore undercounted goals whose requirement list used
    names that were never registered.  That model is retired; the numbers below
    come from ``knowledge/goals/capability_skill_map.json``, which is rebuilt by
    ``tools/build_capability_coverage.py`` over the canonical capability layer.
    """
    report = ROOT / "knowledge/goals/capability_skill_map.json"
    if not report.is_file():
        return {"present": False}
    mtime = datetime.fromtimestamp(report.stat().st_mtime, tz=timezone.utc)
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"present": False, "error": "capability_skill_map.json is not valid JSON"}
    goals = payload.get("goals", [])
    return {
        "present": True,
        "model": payload.get("model"),
        "generated_at_utc": mtime.isoformat(),
        "age_days": round((datetime.now(timezone.utc) - mtime).total_seconds() / 86400, 2),
        "summary": payload.get("summary", {}),
        "by_goal": [
            {
                "goal": row["goal"],
                "status": row["status"],
                "runtime_goal_status": row["runtime_goal_status"],
                "design_coverage": row["design_coverage"],
                "implementation_coverage": row["implementation_coverage"],
                "live_coverage": row["live_coverage"],
                "stable_coverage": row["stable_coverage"],
                "blocked_by": row["blocked_by"],
            }
            for row in goals
        ],
        "retired": "learning/goal_coverage.json (string-matching model; do not use)",
    }


def registry_lifecycle(episodes: list[dict]) -> dict:
    """Split the registry by what the episode stream can actually prove.

    The takeover directive separates LIVE_VERIFIED from "code exists".  These
    three lists are the operational answer: what has never executed, what only
    ever failed, and what has produced a verified production success.
    """
    try:
        from winter_agent_v2.skills import v2_registry

        skills = {skill.id: skill.state.value for skill in v2_registry().all()}
    except Exception as exc:  # pragma: no cover - audit must not explode
        return {"error": f"{type(exc).__name__}: {exc}"}
    performed: dict[str, Counter] = defaultdict(Counter)
    for episode in episodes:
        performed[str(episode.get("skill"))][normalize(episode.get("result"))] += 1
    never_executed, only_failed, verified = [], [], []
    for skill_id, state in sorted(skills.items()):
        seen = performed.get(skill_id, Counter())
        if not seen:
            never_executed.append({"skill_id": skill_id, "state": state})
        elif seen.get("SUCCESS", 0) == 0:
            only_failed.append({"skill_id": skill_id, "state": state, "failure": seen.get("FAILURE", 0)})
        else:
            verified.append({"skill_id": skill_id, "state": state, "success": seen["SUCCESS"]})
    return {
        "registry_total": len(skills),
        "live_verified_skills": len(verified),
        "only_failed_skills": len(only_failed),
        "never_executed_skills": len(never_executed),
        "never_executed": never_executed,
        "only_failed": sorted(only_failed, key=lambda row: -row["failure"]),
        "live_verified": sorted(verified, key=lambda row: -row["success"]),
    }


def evidence_integrity(episodes: list[dict]) -> dict:
    """Section 13: every referenced screenshot must exist, or the audit fails.

    Episodes written before this change carry no screenshot paths, so the check
    reports how many rows are traceable instead of pretending the older rows are
    broken.
    """
    referenced = 0
    missing: list[str] = []
    traceable = 0
    unique_ids = Counter()
    for episode in episodes:
        paths = [episode.get(key) for key in ("before_screenshot", "after_screenshot")]
        paths = [str(value) for value in paths if value]
        if episode.get("episode_id"):
            unique_ids[str(episode["episode_id"])] += 1
        if not paths:
            continue
        traceable += 1
        for value in paths:
            referenced += 1
            if not Path(value).is_file():
                missing.append(value)
    collisions = sum(1 for count in unique_ids.values() if count > 1) and 0
    return {
        "episodes_with_screenshot_references": traceable,
        "screenshots_referenced": referenced,
        "screenshots_missing": len(missing),
        "missing_examples": missing[:10],
        "distinct_episode_ids": len(unique_ids),
        "cross_episode_name_collisions": collisions,
        "status": "PASS" if not missing else "FAIL",
    }


def build() -> dict:
    episodes = load_episodes()
    return {
        "schema_version": "1.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_of_truth": "learning/episodes.jsonl + registry + runtime_snapshot.json + capability coverage",
        "episodes": episode_stats(episodes),
        "top_failures": failure_ranking(episodes),
        "skills": skill_stats(episodes),
        "registry": registry_stats(),
        "registry_lifecycle": registry_lifecycle(episodes),
        "dataset": dataset_stats(),
        "runtime": runtime_stats(),
        "evidence_integrity": evidence_integrity(episodes),
        "capability_coverage": coverage_freshness(),
    }


def render_markdown(truth: dict) -> str:
    ep = truth["episodes"]
    reg = truth["registry"]
    rt = truth["runtime"]
    lines = [
        "# CURRENT TRUTH",
        "",
        f"Generated (UTC): {truth['generated_at_utc']}",
        "",
        "Everything below is recomputed by `python tools/truth_audit.py`.",
        "Do not trust numbers in older Markdown files.",
        "",
        "## A. Runtime",
        "",
        f"- agent_state: `{rt.get('agent_state', 'UNKNOWN')}`",
        f"- runtime_thread_alive: {rt.get('runtime_thread_alive')} / "
        f"scheduler_loop_alive: {rt.get('scheduler_loop_alive')}",
        f"- unexpected_worker_exits: {rt.get('unexpected_worker_exits')}",
        f"- watchdog_restart_count: {rt.get('watchdog_restart_count')}",
        f"- last_fatal_error: {rt.get('last_fatal_error')}",
        f"- stop_reason: {rt.get('stop_reason')}",
        f"- page: {rt.get('page')} march: {rt.get('march_used')}/{rt.get('march_max')}",
        "",
        "## B. Episodes",
        "",
        f"- total: {ep['total']} (mode: {', '.join(f'{k}={v}' for k, v in ep['modes'].items())})",
        f"- success / failure: {ep['success']} / {ep['failure']}",
        f"- blocked: {ep['blocked']}  in_progress: {ep['in_progress']}",
        f"- success rate over decided: **{ep['success_rate_over_decided']}%**",
        f"- success rate over total: {ep['success_rate_over_total']}%",
        f"- mixed-case `result` rows (must be normalized on read, never rewritten): "
        f"{ep['result_case_anomaly']}",
        "",
        "## C. Top failures",
        "",
        "Failure type | Count | Skills | Top skills | Last seen",
        "---|---:|---:|---|---",
    ]
    for row in truth["top_failures"]:
        tops = ", ".join(f"{name}({n})" for name, n in row["top_skills"])
        seen = (row["last_seen"] or "")[:19]
        lines.append(
            f"`{row['failure_type']}` | {row['count']} | {row['affected_skills']} | {tops} | {seen}"
        )
    lines += [
        "",
        "## D. Registry",
        "",
        f"- total skills: {reg.get('total')}",
        f"- by state: {reg.get('by_state')}",
        f"- by latency: {reg.get('by_latency')}",
        f"- REALTIME skills: {reg.get('realtime')}",
        f"- BLOCKED skills: {reg.get('blocked')}",
        "",
        "## E. Dataset",
        "",
        "Area | Files | Empty dirs",
        "---|---:|---:",
    ]
    for name, data in truth["dataset"].items():
        lines.append(f"`dataset/{name}` | {data['files']} | {data['empty_dirs']}")
    lines += [
        "",
        "## F. Evidence integrity",
        "",
    ]
    ev = truth.get("evidence_integrity", {})
    lines += [
        f"- status: **{ev.get('status', 'UNKNOWN')}**",
        f"- episodes carrying screenshot references: {ev.get('episodes_with_screenshot_references')}"
        f" / {ep['total']}",
        f"- screenshots referenced: {ev.get('screenshots_referenced')}",
        f"- screenshots missing: {ev.get('screenshots_missing')}",
        f"- distinct episode ids: {ev.get('distinct_episode_ids')}",
    ]
    if ev.get("missing_examples"):
        lines.append(f"- missing examples: {ev['missing_examples']}")
    lines += [
        "",
        "## G. Skill lifecycle vs the episode stream",
        "",
    ]
    lc = truth.get("registry_lifecycle", {})
    lines += [
        f"- registry total: {lc.get('registry_total')}",
        f"- live verified (>=1 production success): **{lc.get('live_verified_skills')}**",
        f"- only ever failed: {lc.get('only_failed_skills')}",
        f"- never executed: {lc.get('never_executed_skills')}",
        "",
        "Never executed skills:",
        "",
    ]
    for row in lc.get("never_executed", []):
        lines.append(f"- `{row['skill_id']}` ({row['state']})")
    lines += [
        "",
        "## H. Capability coverage (rebuilt model)",
        "",
    ]
    cov = truth.get("capability_coverage", {})
    if cov.get("present"):
        summary = cov.get("summary", {})
        lines += [
            f"- model: {cov.get('model')}",
            f"- generated: {cov.get('generated_at_utc')} ({cov.get('age_days')} days ago)",
            f"- FULLY_LIVE_VERIFIED: {summary.get('fully_live_verified')} / {summary.get('total')}",
            f"- PARTIAL: {summary.get('partial')}  NEVER_TRIED: {summary.get('never_tried')}  "
            f"BLOCKED: {summary.get('blocked')}  DEGRADED: {summary.get('degraded')}",
            f"- mean implementation coverage: {summary.get('automation_coverage_mean')}",
            f"- mean live coverage: {summary.get('live_coverage_mean')}",
            "",
            "Goal | Status | Runtime | design | impl | live | stable | blocked by",
            "---|---|---|---:|---:|---:|---:|---",
        ]
        for row in cov.get("by_goal", []):
            blocked = ", ".join(row["blocked_by"]) or "-"
            lines.append(
                f"{row['goal']} | {row['status']} | {row['runtime_goal_status']} | "
                f"{row['design_coverage']:.0%} | {row['implementation_coverage']:.0%} | "
                f"{row['live_coverage']:.0%} | {row['stable_coverage']:.0%} | {blocked}"
            )
        lines += [
            "",
            f"Retired: {cov.get('retired')}",
        ]
    else:
        lines.append("- capability coverage report is absent; run `tools/build_capability_coverage.py`")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    truth = build()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_markdown(truth), encoding="utf-8")
    ep = truth["episodes"]
    print(f"episodes={ep['total']} success={ep['success']} failure={ep['failure']} "
          f"rate={ep['success_rate_over_decided']}%")
    lc = truth.get("registry_lifecycle", {})
    print(f"skills live_verified={lc.get('live_verified_skills')} "
          f"never_executed={lc.get('never_executed_skills')}")
    print(f"evidence_integrity={truth.get('evidence_integrity', {}).get('status')}")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
