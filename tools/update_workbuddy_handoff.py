"""Refresh the cross-account handoff from real project state.

Why this exists
---------------
Any WorkBuddy account must be able to pick up this project with **no chat
history**.  Static Markdown rots the moment code changes, so the handoff is
generated: this script reads git, the live registry, the capability mapping, the
production episode stream, the runtime snapshot, the newest log and the evidence
integrity check, and rewrites the machine-owned parts of the handoff.

Division of labour
------------------
* ``.workbuddy-ai/memory``   long-term knowledge and design history (human)
* ``.workbuddy-ai/handoff``  current dev site, current progress, next action

Generated in full   01_CURRENT_TRUTH.md, 08_LIVE_METRICS.json, 09_RUNTIME_STATE.json
Generated in blocks 03_NEXT_ACTION.md, 04_OPEN_ISSUES.md, 10_LAST_HANDOFF.md
                    (only between ``<!-- AUTO:id -->`` markers; hand-written prose
                     around them is never touched)

A handoff is an *accelerator*, never the only source of truth: if the last
account died mid-sentence, everything above is still rebuildable from git,
episodes, evidence, the snapshot and the logs.

Usage
-----
    python tools/update_workbuddy_handoff.py
    python tools/update_workbuddy_handoff.py --checkpoint -m "message"
    python tools/update_workbuddy_handoff.py --mark-good      # record HEAD as last good
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HANDOFF = ROOT / ".workbuddy-ai/handoff"
MEMORY = ROOT / ".workbuddy-ai/memory"
EPISODES = ROOT / "learning/episodes.jsonl"
SNAPSHOT = ROOT / "learning/runtime_snapshot.json"
LATEST_LOG = ROOT / "learning/control_panel/latest.log"
CRASH_DIR = ROOT / "learning/control_panel/crashes"
COVERAGE = ROOT / "knowledge/goals/capability_skill_map.json"
PARITY = ROOT / "knowledge/coverage/commercial_bot_parity.json"
LAST_GOOD = HANDOFF / ".last_good_commit"
CHECKPOINT_LOG = HANDOFF / ".checkpoints.jsonl"


# --------------------------------------------------------------------- utils
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sh(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=str(ROOT), errors="replace"
    )
    return result.returncode, (result.stdout or result.stderr).strip()


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def update_auto_block(path: Path, block_id: str, body: str) -> None:
    """Replace one ``<!-- AUTO:id -->`` block, leaving human prose untouched."""
    begin, end = f"<!-- AUTO:{block_id} -->", f"<!-- /AUTO:{block_id} -->"
    replacement = f"{begin}\n{body.strip()}\n{end}"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if begin in existing and end in existing:
        head, rest = existing.split(begin, 1)
        _, tail = rest.split(end, 1)
        atomic_write(path, f"{head}{replacement}{tail}")
    else:
        joiner = "" if not existing or existing.endswith("\n\n") else ("\n" if existing else "")
        atomic_write(path, f"{existing}{joiner}{replacement}\n")


# ----------------------------------------------------------------------- git
def git_state() -> dict:
    code, _ = sh("rev-parse", "--is-inside-work-tree")
    if code != 0:
        return {
            "is_repo": False,
            "branch": None,
            "head": None,
            "head_subject": None,
            "head_time": None,
            "dirty": [],
            "dirty_count": 0,
            "last_good_commit": None,
            "commits": 0,
        }
    _, branch = sh("rev-parse", "--abbrev-ref", "HEAD")
    _, head = sh("rev-parse", "--short", "HEAD")
    _, subject = sh("log", "-1", "--pretty=%s")
    _, when = sh("log", "-1", "--pretty=%cI")
    _, porcelain = sh("status", "--porcelain")
    _, count = sh("rev-list", "--count", "HEAD")
    last_good = LAST_GOOD.read_text(encoding="utf-8").strip() if LAST_GOOD.is_file() else head
    return {
        "is_repo": True,
        "branch": branch,
        "head": head,
        "head_subject": subject,
        "head_time": when,
        "dirty": porcelain.splitlines() if porcelain else [],
        "dirty_count": len(porcelain.splitlines()) if porcelain else 0,
        "last_good_commit": last_good or None,
        "commits": int(count) if count.isdigit() else None,
    }


# ------------------------------------------------------------------- registry
def registry_state() -> dict:
    try:
        from winter_agent_v2.skills import v2_registry

        skills = v2_registry().all()
    except Exception as exc:  # noqa: BLE001 - the handoff must never fail to write
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "total": len(skills),
        "by_state": dict(Counter(skill.state.value for skill in skills)),
        "by_latency": dict(Counter(skill.latency_class.value for skill in skills)),
        "blocked": sorted(skill.id for skill in skills if skill.state.value == "BLOCKED"),
        "realtime": sorted(skill.id for skill in skills if skill.latency_class.value == "REALTIME"),
    }


def live_dispatchable() -> list[str]:
    try:
        from winter_agent_v2.runtime import LiveRuntime

        return sorted(LiveRuntime.VERIFIED_ATOMIC)
    except Exception:  # noqa: BLE001
        return []


# ------------------------------------------------------------------- episodes
def episode_state() -> dict:
    if not EPISODES.is_file():
        return {"total": 0, "success": 0, "failure": 0, "success_rate": None, "skills": {},
                "top_failures": [], "last_episode": None, "modes": {}}
    rows: list[dict] = []
    for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    modes = Counter(str(row.get("mode", "UNKNOWN")) for row in rows)
    normalised = [
        (row, str(row.get("result", "")).strip().upper(), str(row.get("mode", "")).upper())
        for row in rows
    ]
    production = [(row, result) for row, result, mode in normalised if mode == "PRODUCTION"]
    success = sum(result == "SUCCESS" for _, result in production)
    failure = sum(result == "FAILURE" for _, result in production)
    decided = success + failure

    per_skill: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "success": 0, "failure": 0, "last_seen": None})
    failures: dict[str, dict] = defaultdict(lambda: {"count": 0, "skills": Counter()})
    for row, result in production:
        skill = str(row.get("skill", ""))
        if not skill:
            continue
        entry = per_skill[skill]
        entry["attempts"] += 1
        entry["success"] += int(result == "SUCCESS")
        entry["failure"] += int(result == "FAILURE")
        seen = str(row.get("recorded_at") or "")
        if seen and (entry["last_seen"] is None or seen > entry["last_seen"]):
            entry["last_seen"] = seen
        if result == "FAILURE":
            kind = str(row.get("failure_type") or "UNCLASSIFIED")
            failures[kind]["count"] += 1
            failures[kind]["skills"][skill] += 1
    for entry in per_skill.values():
        decided_skill = entry["success"] + entry["failure"]
        entry["success_rate"] = round(entry["success"] / decided_skill, 4) if decided_skill else None
    last = production[-1][0] if production else None
    return {
        "total": len(rows),
        "production": len(production),
        "success": success,
        "failure": failure,
        "success_rate_over_decided": round(success / decided, 4) if decided else None,
        "modes": dict(modes),
        "mixed_case_rows": sum(1 for row, _, _ in normalised if str(row.get("result", "")) in {"success", "failure"}),
        "skills": dict(per_skill),
        "top_failures": sorted(
            (
                {
                    "failure_type": kind,
                    "count": data["count"],
                    "top_skills": data["skills"].most_common(3),
                }
                for kind, data in failures.items()
            ),
            key=lambda item: -item["count"],
        )[:10],
        "last_episode": {
            "skill": last.get("skill"),
            "result": last.get("result"),
            "recorded_at": last.get("recorded_at"),
            "episode_id": last.get("episode_id"),
            "before_screenshot": last.get("before_screenshot"),
            "after_screenshot": last.get("after_screenshot"),
        } if last else None,
    }


def skill_lifecycle(registry: dict, episodes: dict) -> dict:
    per_skill = episodes.get("skills", {})
    dispatchable = live_dispatchable()
    states: dict[str, str] = {}
    try:
        from winter_agent_v2.skills import v2_registry

        for skill in v2_registry().all():
            states[skill.id] = skill.state.value
    except Exception:  # noqa: BLE001
        pass
    all_ids = set(per_skill) | set(states)
    live_verified, stable, degraded, only_failed, never_executed = [], [], [], [], []
    not_dispatchable = []
    for skill_id in sorted(all_ids):
        row = per_skill.get(skill_id)
        state = states.get(skill_id)
        if row is None:
            never_executed.append({"skill_id": skill_id, "state": state})
            continue
        attempts, successes, failures = row["attempts"], row["success"], row["failure"]
        if successes == 0:
            only_failed.append({"skill_id": skill_id, "state": state, "attempts": attempts, "failure": failures})
            continue
        rate = row["success_rate"] or 0.0
        entry = {"skill_id": skill_id, "success": successes, "failure": failures, "rate": rate, "state": state}
        if successes >= 5 and rate >= 0.8:
            stable.append(entry)
        elif successes >= 5 and rate < 0.8:
            # DEGRADED means "was dependable and regressed", not "has failures".
            # The looser rule (failures >= 2 and rate < 0.8) labelled 13 skills
            # degraded and hid the fact that they still carry successful live
            # evidence.  Keep the two report paths on one definition.
            degraded.append(entry)
        else:
            live_verified.append(entry)
        if skill_id not in dispatchable:
            not_dispatchable.append({
                "skill_id": skill_id,
                "note": "has production evidence but is NOT in LiveRuntime.VERIFIED_ATOMIC, "
                        "so the live loop cannot dispatch it",
            })
    return {
        "dispatchable_skills": len(dispatchable),
        "live_verified": live_verified,
        "stable": stable,
        "degraded": degraded,
        "only_failed": only_failed,
        "never_executed": never_executed,
        "not_dispatchable_with_evidence": not_dispatchable,
        "counts": {
            "live_verified": len(live_verified),
            "stable": len(stable),
            "degraded": len(degraded),
            "only_failed": len(only_failed),
            "never_executed": len(never_executed),
        },
    }


# ------------------------------------------------------------------- coverage
def coverage_state() -> dict:
    """Rebuild the capability coverage report, then read it back."""
    script = ROOT / "tools/build_capability_coverage.py"
    if script.is_file():
        subprocess.run([sys.executable, str(script)], capture_output=True, text=True, cwd=str(ROOT))
    payload = load_json(COVERAGE, {}) or {}
    goals = payload.get("goals", [])
    return {
        "present": bool(goals),
        "summary": payload.get("summary", {}),
        "model": payload.get("model"),
        "highest_leverage": payload.get("highest_leverage", []),
        "goals": [
            {
                "goal": row["goal"],
                "status": row["status"],
                "runtime": row["runtime_goal_status"],
                "design": row["design_coverage"],
                "implementation": row["implementation_coverage"],
                "live": row["live_coverage"],
                "stable": row["stable_coverage"],
                "blocked_by": row["blocked_by"],
            }
            for row in goals
        ],
    }


def parity_state() -> dict:
    payload = load_json(PARITY)
    if not payload:
        return {"present": False}
    return {
        "present": True,
        "summary": payload.get("summary", {}),
        "without_evidence": [
            row["feature"] for row in payload.get("features", []) if not row.get("live_evidence")
        ],
    }


# -------------------------------------------------------------------- runtime
def runtime_state() -> dict:
    snapshot = load_json(SNAPSHOT, {}) or {}
    log_info = None
    if LATEST_LOG.is_file():
        stat = LATEST_LOG.stat()
        text = LATEST_LOG.read_text(encoding="utf-8", errors="replace")
        stop = None
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    stop = json.loads(line).get("stop_reason")
                except json.JSONDecodeError:
                    continue
                break
        log_info = {
            "path": str(LATEST_LOG),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "size_bytes": stat.st_size,
            "last_stop_reason": stop,
        }
    crashes = []
    if CRASH_DIR.is_dir():
        for path in sorted(CRASH_DIR.glob("*.json"))[-5:]:
            crashes.append({"path": str(path), "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return {"snapshot": snapshot, "latest_log": log_info, "recent_crash_reports": crashes}


# ------------------------------------------------------------------- evidence
def evidence_state(episodes: dict) -> dict:
    try:
        from winter_agent_v2.retention import referenced_evidence

        referenced = referenced_evidence(ROOT)
    except Exception as exc:  # noqa: BLE001
        return {"status": "UNKNOWN", "error": f"{type(exc).__name__}: {exc}"}
    existing = [path for path in referenced if path.is_file()]
    missing = [str(path) for path in referenced if not path.is_file()]
    return {
        "status": "PASS" if not missing else "FAIL",
        "referenced_screenshots": len(referenced),
        "present_on_disk": len(existing),
        "missing": missing[:10],
        "traceable_episodes": episodes.get("total", 0) and sum(
            1 for row in _raw_episodes() if row.get("before_screenshot") or row.get("after_screenshot")
        ),
        "note": "Live Verified requires production episode + verifier + screenshot evidence",
    }


def _raw_episodes() -> list[dict]:
    if not EPISODES.is_file():
        return []
    rows = []
    for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


# ------------------------------------------------------------------- markdown
def current_truth_md(state: dict) -> str:
    git, reg, ep = state["git"], state["registry"], state["episodes"]
    lc, cov = state["lifecycle"], state["coverage"]
    rt, ev, par = state["runtime"], state["evidence"], state["parity"]
    snap = rt.get("snapshot", {})
    lines = [
        "# 01 — CURRENT TRUTH",
        "",
        f"- generated_at: `{state['generated_at']}`",
        f"- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)",
        f"- commit: `{git.get('head')}` on `{git.get('branch')}`"
        + ("" if git.get("is_repo") else "  **NOT A GIT REPOSITORY — no rollback available**"),
        "",
        "> This file is regenerated. Never hand-edit it; edit the project instead.",
        "",
        "## A. Version control",
        "",
        f"- repository: {'yes' if git.get('is_repo') else 'NO'}",
        f"- last good commit: `{git.get('last_good_commit')}`",
        f"- commits: {git.get('commits')}",
        f"- HEAD: `{git.get('head')}` — {git.get('head_subject')} ({git.get('head_time')})",
        f"- working tree: {'clean' if not git.get('dirty_count') else str(git['dirty_count']) + ' dirty file(s)'}",
    ]
    for entry in git.get("dirty", [])[:20]:
        lines.append(f"  - `{entry}`")
    if not git.get("is_repo"):
        lines.append("- **Any deletion is unrecoverable. Initialise git first.**")
    lines += [
        "",
        "## B. Runtime",
        "",
        f"- agent_state: `{snap.get('agent_state', 'UNKNOWN')}`",
        f"- runtime_thread_alive: {snap.get('runtime_thread_alive')} / scheduler_loop_alive: {snap.get('scheduler_loop_alive')}",
        f"- unexpected_worker_exits: {snap.get('unexpected_worker_exits')}",
        f"- watchdog_restart_count: {snap.get('watchdog_restart_count')}",
        f"- last_fatal_error: {snap.get('last_fatal_error')}",
        f"- stop_reason: {snap.get('stop_reason')}",
        f"- page: {snap.get('page')}  march: {snap.get('march_used')}/{snap.get('march_max')}",
        f"- updated_at: {snap.get('updated_at')}",
        "",
        "## C. Episode stream",
        "",
        f"- rows: {ep['total']} (production {ep.get('production')})  modes: {ep.get('modes')}",
        f"- success / failure: {ep['success']} / {ep['failure']}",
        f"- success rate over decided: **{ep.get('success_rate_over_decided')}**",
        f"- mixed-case `result` rows (normalise on read, never rewrite): {ep.get('mixed_case_rows')}",
        f"- last episode: `{json.dumps(ep.get('last_episode'), ensure_ascii=False)}`",
        "",
        "## D. Registry and lifecycle",
        "",
        f"- registry total: {reg.get('total')}  by_state: {reg.get('by_state')}",
        f"- live dispatchable (verifier-backed): {lc.get('dispatchable_skills')}",
        f"- BLOCKED skills: {reg.get('blocked')}",
        f"- live_verified: **{lc['counts']['live_verified']}**  stable: {lc['counts']['stable']}  "
        f"degraded: {lc['counts']['degraded']}  only_failed: {lc['counts']['only_failed']}  "
        f"never_executed: {lc['counts']['never_executed']}",
        "",
        "### Never executed",
        "",
    ]
    for row in lc["never_executed"]:
        lines.append(f"- `{row['skill_id']}` ({row['state']})")
    lines += ["", "### Only ever failed", ""]
    for row in lc["only_failed"]:
        lines.append(f"- `{row['skill_id']}` attempts={row['attempts']} failure={row['failure']}")
    lines += ["", "### Stable", ""]
    lines += [f"- `{row['skill_id']}` success={row['success']} rate={row['rate']}" for row in lc["stable"]] or ["- (none)"]
    lines += ["", "### Degraded", ""]
    lines += [f"- `{row['skill_id']}` success={row['success']} failure={row['failure']} rate={row['rate']}" for row in lc["degraded"]] or ["- (none)"]
    lines += ["", "## E. Top failures", "", "Failure | Count | Top skills", "---|---:|---"]
    for row in ep["top_failures"]:
        tops = ", ".join(f"{name}({n})" for name, n in row["top_skills"])
        lines.append(f"`{row['failure_type']}` | {row['count']} | {tops}")
    lines += [
        "",
        "## F. Goal capability coverage",
        "",
        f"- model: {cov.get('model')}",
        f"- summary: {json.dumps(cov.get('summary', {}), ensure_ascii=False)}",
        "",
        "Goal | Status | Runtime | design | impl | live | stable | blocked by",
        "---|---|---|---:|---:|---:|---:|---",
    ]
    for row in cov.get("goals", []):
        blocked = ", ".join(row["blocked_by"]) or "-"
        lines.append(
            f"{row['goal']} | {row['status']} | {row['runtime']} | {row['design']:.0%} | "
            f"{row['implementation']:.0%} | {row['live']:.0%} | {row['stable']:.0%} | {blocked}"
        )
    lines += [
        "",
        "## G. Evidence integrity",
        "",
        f"- status: **{ev.get('status')}**",
        f"- referenced screenshots: {ev.get('referenced_screenshots')}  present: {ev.get('present_on_disk')}",
        f"- missing: {ev.get('missing')}",
        f"- episodes carrying screenshot references: {ev.get('traceable_episodes')}",
        "",
        "## H. Commercial bot parity",
        "",
        f"- present: {par.get('present')}",
        f"- summary: {json.dumps(par.get('summary', {}), ensure_ascii=False)}",
        f"- features without live evidence: {par.get('without_evidence')}",
        "",
        "## I. Latest runtime log",
        "",
        f"- {json.dumps(rt.get('latest_log'), ensure_ascii=False)}",
        f"- recent crash reports: {[c['path'] for c in rt.get('recent_crash_reports', [])] or '(none)'}",
        "",
    ]
    return "\n".join(lines)


def live_metrics(state: dict) -> dict:
    return {
        "generated_at": state["generated_at"],
        "source": "tools/update_workbuddy_handoff.py",
        "commit": state["git"].get("head"),
        "last_good_commit": state["git"].get("last_good_commit"),
        "dirty_count": state["git"].get("dirty_count"),
        "episodes": {
            key: state["episodes"].get(key)
            for key in ("total", "production", "success", "failure", "success_rate_over_decided", "modes", "mixed_case_rows")
        },
        "skills": {
            "registry_total": state["registry"].get("total"),
            "by_state": state["registry"].get("by_state"),
            "dispatchable": state["lifecycle"].get("dispatchable_skills"),
            "counts": state["lifecycle"]["counts"],
        },
        "top_failures": state["episodes"]["top_failures"],
        "goals": state["coverage"].get("summary", {}),
        "goal_status": {row["goal"]: row["status"] for row in state["coverage"].get("goals", [])},
        "evidence_integrity": {k: v for k, v in state["evidence"].items() if k != "missing"} | {
            "missing_count": len(state["evidence"].get("missing", []))
        },
        "commercial_parity": state["parity"].get("summary", {}),
        "runtime": {
            "agent_state": state["runtime"].get("snapshot", {}).get("agent_state"),
            "unexpected_worker_exits": state["runtime"].get("snapshot", {}).get("unexpected_worker_exits"),
            "watchdog_restart_count": state["runtime"].get("snapshot", {}).get("watchdog_restart_count"),
            "last_fatal_error": state["runtime"].get("snapshot", {}).get("last_fatal_error"),
            "stop_reason": state["runtime"].get("snapshot", {}).get("stop_reason"),
        },
    }


def runtime_state_json(state: dict) -> dict:
    return {
        "generated_at": state["generated_at"],
        "source": "tools/update_workbuddy_handoff.py",
        "commit": state["git"].get("head"),
        "snapshot_path": str(SNAPSHOT.relative_to(ROOT)),
        "snapshot": state["runtime"].get("snapshot", {}),
        "latest_log": state["runtime"].get("latest_log"),
        "recent_crash_reports": state["runtime"].get("recent_crash_reports", []),
        "process_alive_interpretation": (
            "runtime_thread_alive/scheduler_loop_alive mean the in-process worker loop is running. "
            "They do NOT mean the emulator or the game is reachable; check the device separately."
        ),
    }


NEXT_EXACT_ACTION = (
    "Implement the highest-leverage missing skill listed in "
    "`highest_leverage` inside knowledge/goals/capability_skill_map.json, then "
    "REPLAY -> LIVE -> VERIFY -> EVIDENCE."
)


NEXT_EXACT_ACTION_TEMPLATE = (
    "Add `{skill}` to winter_agent_v2/skills.py v2_registry() AND register a post-action "
    "verifier in LiveRuntime.VERIFIED_ATOMIC (a skill without a verifier is never dispatched). "
    "It unblocks: {goals}. Requirement side: knowledge/goals/goal_capability_map.json lists it "
    "as an alternative for the blocked capability. Then REPLAY -> LIVE -> VERIFY -> EVIDENCE."
)


def top_leverage(state: dict) -> dict | None:
    items = state["coverage"].get("highest_leverage") or []
    return items[0] if items else None


def next_action_block(state: dict) -> str:
    git, ep, lc = state["git"], state["episodes"], state["lifecycle"]
    cov = state["coverage"].get("summary", {})
    blocked_goals = [row["goal"] for row in state["coverage"].get("goals", []) if row["status"] == "BLOCKED"]
    never = [row["skill_id"] for row in lc["never_executed"][:12]]
    top = ep["top_failures"][0] if ep["top_failures"] else None
    item = top_leverage(state)
    if item:
        current_task = (
            f"implement `{item['skill_id']}` — missing from the registry, blocks "
            f"{item['blocked_goals']} goal(s): {item.get('goals')}"
        )
        next_action = NEXT_EXACT_ACTION_TEMPLATE.format(
            skill=item["skill_id"], goals=", ".join(item.get("goals") or [])
        )
    else:
        current_task = "no blocked capability remains; extend goal coverage"
        next_action = NEXT_EXACT_ACTION
    lines = [
        f"CURRENT PRIORITY: fill the missing skills that block {len(blocked_goals)} goal(s)",
        f"CURRENT TASK: {current_task}",
        "",
        f"WHY: {cov.get('blocked', 0)} goal(s) BLOCKED, {cov.get('partial', 0)} PARTIAL, "
        f"mean implementation coverage {cov.get('automation_coverage_mean')}. "
        "The blocked goals share one small set of never-implemented skills, so one skill "
        "purchase can move several goals at once.",
        "",
        f"CURRENT ROOT CAUSE: {top['failure_type'] + ' x' + str(top['count']) if top else 'no production failures recorded'}",
        f"LAST GOOD COMMIT: {git.get('last_good_commit')}",
        f"CURRENT DIRTY FILES: {git.get('dirty_count')}",
        f"LAST PRODUCTION EPISODE: {json.dumps(ep.get('last_episode'), ensure_ascii=False)}",
        f"TOP FAILURE: {json.dumps(top, ensure_ascii=False) if top else 'none'}",
        "",
        f"BLOCKED GOALS: {blocked_goals}",
        f"MISSING SKILLS BY LEVERAGE: "
        f"{[(x['skill_id'], x['blocked_goals']) for x in (state['coverage'].get('highest_leverage') or [])[:10]]}",
        f"NEVER EXECUTED SKILLS (first 12): {never}",
        "",
        f"NEXT EXACT ACTION: {next_action}",
        "",
        "ACCEPTANCE: production episode + passing verifier + screenshot evidence, "
        "and the named goal(s) move off BLOCKED (live coverage increases).",
        "",
        "DO NOT: re-architect, rename goals, or touch anything already live-verified "
        "without new failure evidence.",
    ]
    return "\n".join(lines)


def open_issues_block(state: dict) -> str:
    ep, lc, ev = state["episodes"], state["lifecycle"], state["evidence"]
    lines = ["Machine-detected issues (recomputed every run):", ""]
    for row in ep["top_failures"][:6]:
        tops = ", ".join(f"{name}({n})" for name, n in row["top_skills"])
        lines.append(f"- **{row['failure_type']}** x{row['count']} — {tops}")
    if ev.get("status") != "PASS":
        lines.append(f"- **EVIDENCE INTEGRITY {ev.get('status')}** — missing: {ev.get('missing')}")
    for row in lc["only_failed"]:
        lines.append(f"- `{row['skill_id']}` never succeeded (attempts={row['attempts']}, failure={row['failure']})")
    if not state["git"].get("is_repo"):
        lines.append("- **No git repository: changes cannot be rolled back.**")
    if state["git"].get("dirty_count"):
        lines.append(f"- {state['git']['dirty_count']} uncommitted file(s): {state['git']['dirty'][:5]}")
    return "\n".join(lines)


def last_handoff_block(state: dict) -> str:
    git, ep, lc, rt = state["git"], state["episodes"], state["lifecycle"], state["runtime"]
    snap = rt.get("snapshot", {})
    lines = [
        f"HANDOFF TIME: {state['generated_at']}",
        f"LAST GOOD COMMIT: {git.get('last_good_commit')}",
        f"WORKING TREE: {'clean' if not git.get('dirty_count') else str(git['dirty_count']) + ' dirty file(s)'}",
        f"  {git.get('dirty')[:10]}",
        "",
        f"WHAT FINISHED (machine-visible): {lc['counts']['live_verified']} skills live verified, "
        f"{lc['counts']['stable']} stable, {git.get('commits')} commit(s) in history",
        f"WHAT LIVE VERIFIED: see 01_CURRENT_TRUTH.md section D (skills with >=1 production success)",
        f"WHAT NOT VERIFIED: {lc['counts']['never_executed']} skills never executed, "
        f"{lc['counts']['only_failed']} never succeeded",
        "",
        f"CURRENT TASK: see 03_NEXT_ACTION.md",
        f"STOPPED AT: agent_state={snap.get('agent_state')} stop_reason={snap.get('stop_reason')}",
        f"LAST PRODUCTION EPISODE: {json.dumps(ep.get('last_episode'), ensure_ascii=False)}",
        f"TOP FAILURE: {json.dumps(ep['top_failures'][0], ensure_ascii=False) if ep['top_failures'] else 'none'}",
        f"NEXT EXACT STEP: {NEXT_EXACT_ACTION}",
        f"DIRTY FILES: {git.get('dirty_count')}",
        f"TEST STATUS: not run by this script — run `python -m pytest tests -q`",
        f"LIVE STATUS: {'PASS' if snap.get('agent_state') else 'UNKNOWN'} "
        f"(unexpected_worker_exits={snap.get('unexpected_worker_exits')})",
        "",
        "KNOWN RISKS:",
        "- Live Verified depends on screenshots that are NOT in git (see .gitignore); they are machine-local.",
        "- `unexpected_worker_exits` before 2026-09-14 has no traceback and cannot be attributed.",
        "",
        "DO NOT REPEAT:",
        "- Do not re-derive resource-tab coordinates from memory; read the bracket anchor (vision.selected_resource).",
        "- Do not assume no git history (it now exists) and never delete files by wildcard prefix.",
        "- Do not pass a changed wire format into LiveRuntime.resolve(); use the `_semantic` accessor.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------- main
def collect() -> dict:
    git = git_state()
    registry = registry_state()
    episodes = episode_state()
    return {
        "generated_at": utc_now(),
        "git": git,
        "registry": registry,
        "episodes": episodes,
        "lifecycle": skill_lifecycle(registry, episodes),
        "coverage": coverage_state(),
        "parity": parity_state(),
        "runtime": runtime_state(),
        "evidence": evidence_state(episodes),
    }


def recent_commits_block(state: dict) -> str:
    git = state["git"]
    if not git.get("is_repo"):
        return "No git repository: there is no commit history."
    _, log = sh("log", "-12", "--pretty=%h %cI %s")
    lines = ["Last 12 commits (newest first):", ""]
    lines += [f"- `{line}`" for line in log.splitlines()] or ["- (no commits)"]
    lines += [
        "",
        f"Uncommitted changes: {git.get('dirty_count')}",
        *[f"- `{entry}`" for entry in git.get("dirty", [])[:20]],
    ]
    return "\n".join(lines)


def progress_block(state: dict) -> str:
    cov, lc, ep = state["coverage"], state["lifecycle"], state["episodes"]
    summary = cov.get("summary", {})
    lines = [
        f"Machine progress at {state['generated_at']} (commit {state['git'].get('head')}):",
        "",
        f"- goals: {summary.get('total')} — FULLY_LIVE_VERIFIED {summary.get('fully_live_verified')}, "
        f"PARTIAL {summary.get('partial')}, NEVER_TRIED {summary.get('never_tried')}, "
        f"BLOCKED {summary.get('blocked')}, DEGRADED {summary.get('degraded')}",
        f"- mean implementation coverage: {summary.get('automation_coverage_mean')}",
        f"- mean live coverage: {summary.get('live_coverage_mean')}",
        f"- skills: live_verified {lc['counts']['live_verified']}, stable {lc['counts']['stable']}, "
        f"degraded {lc['counts']['degraded']}, only_failed {lc['counts']['only_failed']}, "
        f"never_executed {lc['counts']['never_executed']}",
        f"- episodes: {ep['total']} (success {ep['success']} / failure {ep['failure']}, "
        f"rate {ep.get('success_rate_over_decided')})",
        f"- evidence integrity: {state['evidence'].get('status')}",
    ]
    return "\n".join(lines)


FULL_FILES = {
    "01_CURRENT_TRUTH.md": lambda s: current_truth_md(s),
    "08_LIVE_METRICS.json": lambda s: json.dumps(live_metrics(s), ensure_ascii=False, indent=2) + "\n",
    "09_RUNTIME_STATE.json": lambda s: json.dumps(runtime_state_json(s), ensure_ascii=False, indent=2) + "\n",
}

BLOCK_FILES = {
    "02_CURRENT_PROGRESS.md": ("progress", progress_block),
    "03_NEXT_ACTION.md": ("next_action", next_action_block),
    "04_OPEN_ISSUES.md": ("open_issues", open_issues_block),
    "05_RECENT_CHANGES.md": ("recent_commits", recent_commits_block),
    "10_LAST_HANDOFF.md": ("last_handoff", last_handoff_block),
}


def evidence_index() -> dict:
    """Index every evidence artefact so conclusions can be traced without
    browsing directories (P1 of the 2026-09-14 memory architecture review)."""
    entries = []
    for base, kind in ((ROOT / "evidence", "evidence"), (ROOT / "dataset" / "truth_audit", "fixture")):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            entries.append({
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "kind": kind,
                "bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            })
    return {"generated_at": utc_now(), "count": len(entries), "entries": entries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", action="store_true", help="commit the current tree")
    parser.add_argument("-m", "--message", default="", help="checkpoint commit message")
    parser.add_argument("--mark-good", action="store_true", help="record HEAD as last_good_commit")
    args = parser.parse_args()

    HANDOFF.mkdir(parents=True, exist_ok=True)
    MEMORY.mkdir(parents=True, exist_ok=True)

    if args.checkpoint:
        if not args.message:
            parser.error("--checkpoint requires -m MESSAGE")
        state = git_state()
        if not state.get("is_repo"):
            parser.error("--checkpoint requires a git repository")
        sh("add", "-A")
        code, out = sh("commit", "-m", args.message)
        print(f"checkpoint: {out.splitlines()[0] if out else code}")
        _, head = sh("rev-parse", "--short", "HEAD")
        LAST_GOOD.write_text(head + "\n", encoding="utf-8")
        with CHECKPOINT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": utc_now(), "commit": head, "message": args.message}, ensure_ascii=False) + "\n")
        print(f"marked last good commit: {head}")

    if args.mark_good:
        _, head = sh("rev-parse", "--short", "HEAD")
        LAST_GOOD.write_text(head + "\n", encoding="utf-8")
        print(f"marked last good commit: {head}")

    state = collect()
    atomic_write(ROOT / "evidence" / "INDEX.json", json.dumps(evidence_index(), ensure_ascii=False, indent=2))
    print("wrote evidence/INDEX.json")
    for name, render in FULL_FILES.items():
        atomic_write(HANDOFF / name, render(state))
        print(f"wrote {name}")
    for name, (block_id, render) in BLOCK_FILES.items():
        path = HANDOFF / name
        if not path.is_file():
            title = name[3:-3].replace("_", " ").title()
            atomic_write(path, f"# {name[:2]} — {title}\n\n<!-- hand-written notes go here -->\n\n")
        update_auto_block(path, block_id, render(state))
        print(f"updated AUTO:{block_id} in {name}")

    print(
        f"\ncommit={state['git'].get('head')} dirty={state['git'].get('dirty_count')} "
        f"episodes={state['episodes']['total']} rate={state['episodes']['success_rate_over_decided']} "
        f"live_verified={state['lifecycle']['counts']['live_verified']} "
        f"evidence={state['evidence'].get('status')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
