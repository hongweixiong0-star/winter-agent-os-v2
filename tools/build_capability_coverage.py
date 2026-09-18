"""Rebuild the capability coverage report from the live registry.

Usage:
    PYTHONPATH=. python tools/build_capability_coverage.py

Reads the canonical mapping at ``knowledge/goals/goal_capability_map.json`` and
writes ``knowledge/goals/capability_skill_map.json`` (machine readable) plus
``docs/CAPABILITY_COVERAGE.md`` (review copy).

Two things this deliberately keeps separate:

* ``implementation_coverage`` — a registered, verifier-backed skill can perform
  the capability.  Code existing is not evidence that it works.
* ``live_coverage`` — the production episode stream contains a success for it.
  Only ``PRODUCTION`` rows with a passed verifier count, and the episode record
  carries the screenshot paths that make the claim auditable.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.capability_coverage import CapabilityCoverage  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402


def episode_stats(path: Path) -> dict[str, dict]:
    """Per-skill attempts / success / failure from the PRODUCTION stream.

    Result values are compared case-insensitively: 35 historical rows were
    written in lower case by an older writer, and counting only ``SUCCESS``
    silently dropped them from every statistic.
    """
    stats: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "success": 0, "failure": 0})
    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("mode", "")).upper() != "PRODUCTION":
            continue
        skill = str(row.get("skill", ""))
        if not skill:
            continue
        result = str(row.get("result", "")).upper()
        stats[skill]["attempts"] += 1
        if result == "SUCCESS":
            stats[skill]["success"] += 1
        elif result == "FAILURE":
            stats[skill]["failure"] += 1
    return dict(stats)


def _markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        "# Capability Coverage",
        "",
        "Model: **Goal -> Canonical Capability -> Registered Skill -> Production Evidence**.",
        "",
        "`design` = the capability is named at all; `implementation` = a registered, "
        "verifier-backed skill performs it; `live` = the production episode stream "
        "proves a verified success; `stable` = enough live successes for a dependable rate.",
        "",
        f"- goals: {summary['total']}",
        f"- FULLY_LIVE_VERIFIED: {summary['fully_live_verified']}",
        f"- PARTIAL: {summary['partial']}",
        f"- NEVER_TRIED: {summary['never_tried']}",
        f"- BLOCKED: {summary['blocked']}",
        f"- DEGRADED: {summary['degraded']}",
        f"- mean implementation coverage: {summary['automation_coverage_mean']:.1%}",
        f"- mean live coverage: {summary['live_coverage_mean']:.1%}",
        "",
        "Goal | Composition | Status | Runtime | design | impl | live | stable",
        "---|---|---|---|---:|---:|---:|---:",
    ]
    for row in payload["goals"]:
        lines.append(
            f"{row['goal']} | {row['composition']} | {row['status']} | {row['runtime_goal_status']} | "
            f"{row['design_coverage']:.0%} | {row['implementation_coverage']:.0%} | "
            f"{row['live_coverage']:.0%} | {row['stable_coverage']:.0%}"
        )
    referenced = []
    lines += ["", "## Capabilities", "", "Goal | Capability | Status | Implemented By | Live | Attempts | Success", "---|---|---|---|---|---:|---:"]
    for row in payload["goals"]:
        for capability in row["capabilities"]:
            lines.append(
                f"{row['goal']} | {capability['capability']} | {capability['status']} | "
                f"{capability['implemented_by'] or '-'} | {capability['live_verified_by'] or '-'} | "
                f"{capability['attempts']} | {capability['successes']}"
            )
            if capability.get("evidence"):
                referenced.append((row["goal"], capability["capability"], capability["evidence"]))
    lines += ["", "## Highest-Leverage Blockers", "", "Skill | Blocked Goals | Never-Tried Goals", "---|---:|---:"]
    for item in payload["highest_leverage"]:
        lines.append(f"{item['skill_id']} | {item['blocked_goals']} | {item['never_tried_goals']}")
    if referenced:
        # Every "LIVE_VERIFIED" / "STABLE" in the table above is a claim that some
        # frame on disk shows the page transition.  Name the frame here so the
        # claim can be checked instead of trusted.  Empty means no evidence set
        # has been published yet, not that no episode exists.
        lines += [
            "",
            "## Published Evidence Sets",
            "",
            "Each path below holds the archived frames behind a capability's live claim; "
            "the directory's `report.json` records what was measured and what stayed unproven.",
            "",
            "Goal | Capability | Evidence",
            "---|---|---",
        ]
        for goal, capability, evidence in referenced:
            lines.append(f"{goal} | {capability} | `{evidence}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    registry = v2_registry()
    map_path = ROOT / "knowledge" / "goals" / "goal_capability_map.json"
    coverage = CapabilityCoverage(
        registry,
        verifier_skills=set(LiveRuntime.VERIFIED_ATOMIC),
        map_path=map_path,
    )
    payload = coverage.build(episode_stats(ROOT / "learning" / "episodes.jsonl"))
    out_json = ROOT / "knowledge" / "goals" / "capability_skill_map.json"
    CapabilityCoverage.write(payload, out_json)
    out_md = ROOT / "docs" / "CAPABILITY_COVERAGE.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(_markdown(payload), encoding="utf-8")
    summary = payload["summary"]
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")
    print(
        "total={total} fully_live_verified={fully_live_verified} partial={partial} "
        "never_tried={never_tried} blocked={blocked} degraded={degraded} missing={missing}".format(**summary)
    )


if __name__ == "__main__":
    main()
