"""Classify every V2 goal and skill into A/B/C/D pipeline readiness.

Run:  python tools/pipeline_coverage.py [--json]

The four classes the operator brief asks for, applied honestly to what V2
actually has:

  A  a MAA node exists **and** the goal is routable, so AUTO can schedule it
  B  a MAA node exists but the goal cannot be reached by AUTO
  C  the control or page is known to knowledge, but no MAA node exists yet
  D  neither a node nor usable UI knowledge exists

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
from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

SEMANTIC_DICT = ROOT / "knowledge" / "ui" / "semantic_dictionary.json"
L1 = ROOT / "learning" / "l1_experiences.jsonl"


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

    skills_report: list[dict] = []
    for skill in registry.all():
        semantic = str(skill.action.target or "")
        node = node_for(table, skill.id, semantic)
        has_node = node is not None
        skills_report.append({
            "skill_id": skill.id,
            "semantic": semantic,
            "has_maa_node": has_node,
            "node_kind": (node or {}).get("kind") or ("TEMPLATE" if (node or {}).get("template") else None),
            "in_semantic_dict": semantic in semantics,
            "has_l1_experience": semantic in l1,
            "skill_state": str(getattr(skill.state, "value", skill.state)),
            "required_page": str(getattr(skill.required_page, "value", skill.required_page) or ""),
        })

    by_id = {row["skill_id"]: row for row in skills_report}

    goals: list[dict] = []
    for goal_id, required in GOAL_REQUIREMENTS.items():
        routable = goal_id in GOAL_ROUTES
        rows = [by_id.get(r) for r in required]
        present = [r for r in rows if r is not None]
        with_node = [r for r in present if r["has_maa_node"]]
        known = [r for r in present if r["in_semantic_dict"] or r["has_l1_experience"]]

        if present and with_node and routable and len(with_node) == len(present):
            cls = "A"
        elif with_node and not routable:
            cls = "B"
        elif known or present:
            cls = "C"
        else:
            cls = "D"

        missing_nodes = [r["skill_id"] for r in present if not r["has_maa_node"]]
        missing_skills = [r for r in required if r not in by_id]

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
    print(f"skills with a MAA node  : {t['skills_with_maa_node']}  <- these are the real pipelines")
    print(f"goals                   : {t['goals']}")
    print("class counts            : " + ", ".join(f"{k}={v}" for k, v in report["counts_by_class"].items()))
    print()
    print("A = node + routable | B = node, not routable | C = knowledge, no node | D = unknown")
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
