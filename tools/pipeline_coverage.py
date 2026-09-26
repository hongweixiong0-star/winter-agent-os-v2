"""Audit V2 Pipeline readiness from the local registry, routes and production evidence.

Run:  python tools/pipeline_coverage.py [--json]

Skill classes: A/B have a MAA node, C has UI knowledge but no node, D has
neither. STATE_ONLY and COMPOSITE do not need their own recognition node.
Goal classes use the canonical capability map's alternatives, not the old
GOAL_REQUIREMENTS strings, which do not match the live registry vocabulary.

"Has a pipeline" is judged by one thing only: whether
``knowledge/execution/backend_routing.json`` carries a recognition node for that
skill under the semantic its ``Action`` targets. V2 has no
MaaFramework ``pipeline/`` resource tree, so a node in that table *is* the
pipeline; anything else would be counting a wish as a capability.

This tool reads and reports. It changes nothing.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.executor_router import RoutingTable  # noqa: E402
from winter_agent_v2.goal_library import GOAL_ROUTES  # noqa: E402
from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

SEMANTIC_DICT = ROOT / "knowledge" / "ui" / "semantic_dictionary.json"
L1 = ROOT / "learning" / "l1_experiences.jsonl"
GOAL_MAP = ROOT / "knowledge" / "goals" / "goal_capability_map.json"
EPISODES = ROOT / "learning" / "episodes.jsonl"


def production_evidence() -> dict[str, dict[str, int]]:
    """Count distinct skills at each live evidence level, from production only."""
    counts: dict[str, dict[str, int]] = {}
    if not EPISODES.is_file():
        return counts
    with EPISODES.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("mode") != "PRODUCTION" or not row.get("skill"):
                continue
            item = counts.setdefault(str(row["skill"]), {"maa_executed": 0, "verifier_passed": 0, "goal_completed": 0})
            if row.get("recognition_backend") != "MAA" or row.get("action_backend") != "MAA":
                continue
            item["maa_executed"] += 1
            if row.get("verifier_ok") is True:
                item["verifier_passed"] += 1
                if row.get("goal_progress") is True:
                    item["goal_completed"] += 1
    return counts


def load_semantics() -> set[str]:
    try:
        payload = json.loads(SEMANTIC_DICT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    records = payload.get("records", [])
    return {str(r.get("id")) for r in records if isinstance(r, dict) and r.get("id")}


def load_l1_semantics() -> set[str]:
    ids: set[str] = set()
    if not L1.is_file():
        return ids
    for line in L1.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("semantic", "target", "action_target"):
            value = row.get(key)
            if isinstance(value, str):
                ids.add(value)
    return ids


def node_for(table: RoutingTable, skill_id: str, semantic: str) -> dict | None:
    entry = table.skills.get(skill_id)
    if not entry:
        return None
    nodes = entry.get("recognition", {}) or {}
    return nodes.get(semantic) if semantic in nodes else nodes.get("*")


def build() -> dict:
    table = RoutingTable.load()
    registry = v2_registry()
    semantics = load_semantics()
    l1 = load_l1_semantics()
    evidence = production_evidence()
    goal_map = json.loads(GOAL_MAP.read_text(encoding="utf-8"))["goals"]
    routable_skills = set(LiveRuntime.VERIFIED_ATOMIC)

    skills_report: list[dict] = []
    for skill in registry.all():
        semantic = str(skill.action.target or "")
        node = node_for(table, skill.id, semantic)
        has_node = node is not None
        kind = str(skill.action.kind)
        if kind == "OBSERVE" or kind in {"READ_TIMER", "READ_COUNTER"}:
            cls = "STATE_ONLY"
        elif kind in {"TAP_SEMANTIC", "SWIPE"}:
            cls = ("A" if skill.id in routable_skills else "B") if has_node else (
                "C" if semantic in semantics or semantic in l1 else "D")
        else:
            cls = "COMPOSITE"
        skills_report.append({
            "skill_id": skill.id,
            "class": cls,
            "auto_registered": skill.id in routable_skills,
            "action_kind": kind,
            "semantic": semantic,
            "has_maa_node": has_node,
            "node_kind": (node or {}).get("kind") or ("TEMPLATE" if (node or {}).get("template") else None),
            "in_semantic_dict": semantic in semantics,
            "has_l1_experience": semantic in l1,
            "skill_state": str(getattr(skill.state, "value", skill.state)),
            "required_page": str(getattr(skill.required_page, "value", skill.required_page) or ""),
            "production": evidence.get(skill.id, {"maa_executed": 0, "verifier_passed": 0, "goal_completed": 0}),
        })

    by_id = {row["skill_id"]: row for row in skills_report}

    goals: list[dict] = []
    for goal_id, definition in goal_map.items():
        capabilities = definition.get("capabilities", [])
        required = list(dict.fromkeys(str(alt) for cap in capabilities for alt in cap.get("alternatives", [])))
        routable = goal_id in GOAL_ROUTES
        rows = [by_id.get(r) for r in required]
        present = [r for r in rows if r is not None]
        with_node = [r for r in present if r["has_maa_node"]]
        known = [r for r in present if r["in_semantic_dict"] or r["has_l1_experience"]]

        actionable = [r for r in present if r["class"] not in {"STATE_ONLY", "COMPOSITE"}]
        capability_gaps = [str(cap.get("capability")) for cap in capabilities
                           if not any(by_id.get(str(alt)) for alt in cap.get("alternatives", []))]
        pipeline_gaps = [str(cap.get("capability")) for cap in capabilities
                         if not any(by_id.get(str(alt)) and by_id[str(alt)]["class"] in {"A", "STATE_ONLY", "COMPOSITE"}
                                    for alt in cap.get("alternatives", []))]
        if routable and not pipeline_gaps and not capability_gaps:
            cls = "A"
        elif with_node and not routable:
            cls = "B"
        elif known or any(r["has_maa_node"] for r in present):
            cls = "C"
        else:
            cls = "D"

        missing_skills = [r for r in required if r not in by_id]
        missing_nodes = [r["skill_id"] for r in actionable if not r["has_maa_node"]]

        goals.append({
            "goal": goal_id,
            "class": cls,
            "routable": routable,
            "required_skills": len(required),
            "skills_defined": len(present),
            "skills_with_node": len(with_node),
            "skills_with_knowledge": len(known),
            "missing_nodes": missing_nodes,
            "missing_skills": missing_skills,
            "capability_gaps": capability_gaps,
            "pipeline_gaps": pipeline_gaps,
        })

    goals.sort(key=lambda g: (g["class"], -g["skills_with_node"], g["goal"]))
    counts = {c: sum(1 for g in goals if g["class"] == c) for c in "ABCD"}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts_by_class": counts,
        "totals": {
            "goals": len(goals),
            "skills_defined": len(skills_report),
            "skills_with_maa_node": sum(1 for r in skills_report if r["has_maa_node"]),
            "skills_with_node_and_auto": sum(1 for r in skills_report if r["class"] == "A"),
            "skills_requiring_pipeline": sum(1 for r in skills_report if r["action_kind"] == "TAP_SEMANTIC"),
            "skills_missing_pipeline": sum(1 for r in skills_report if r["action_kind"] == "TAP_SEMANTIC" and not r["has_maa_node"]),
            "maa_executed_skills": sum(1 for r in skills_report if r["production"]["maa_executed"]),
            "maa_verifier_passed_skills": sum(1 for r in skills_report if r["production"]["verifier_passed"]),
            "maa_goal_completed_skills": sum(1 for r in skills_report if r["production"]["goal_completed"]),
        },
        "goals": goals,
        "skills": skills_report,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit raw JSON")
    ap.add_argument("--out", help="write JSON here")
    args = ap.parse_args()

    report = build()
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written -> {out}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    t = report["totals"]
    print(f"skills defined          : {t['skills_defined']}")
    print(f"tap skills needing node : {t['skills_requiring_pipeline']}")
    print(f"skills with a MAA node  : {t['skills_with_maa_node']}")
    print(f"tap skills missing node : {t['skills_missing_pipeline']}")
    print(f"MAA executed / verified / goal progress skills: {t['maa_executed_skills']} / {t['maa_verifier_passed_skills']} / {t['maa_goal_completed_skills']}")
    print(f"goals                   : {t['goals']}")
    print("class counts            : " + ", ".join(f"{k}={v}" for k, v in report["counts_by_class"].items()))
    print()
    print("Goal A = every capability has a registered node or needs no node; B = node but no AUTO route; C = known UI gap; D = UI unknown")
    print()
    print(f"{'goal':32} cls routable defined/node  missing-nodes")
    print("-" * 92)
    for g in report["goals"]:
        print(f"{g['goal']:32} {g['class']}   {'yes' if g['routable'] else 'NO ':6}"
              f"{g['skills_defined']}/{g['skills_with_node']:<10}"
              f"{','.join(g['missing_nodes'])[:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
