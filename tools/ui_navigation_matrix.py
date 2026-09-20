"""Derive the navigation matrix from the project's own evidence -- never hand-written.

The operator asked which registered entries and navigation paths each existing Goal already has,
how many functions can be read from a shortcut panel without opening a detail page, and what is
still missing.  Those are all questions about facts the project already stores in four places, so
the answer is a projection of them rather than a new table somebody types out:

    winter_agent_v2/skills.py             the registered skills and their (page, action, target)
    LiveRuntime.VERIFIED_ATOMIC           which of those may actually be dispatched
    dataset/candidate/template_manifest   the visual evidence behind each target
    winter_agent_v2/skill_factory.py      which skills each Goal declares

Hand-writing it would create a second source of truth for facts those files own -- the same mistake
the semantics ledger avoided.  Every field the project has not measured stays UNKNOWN.

Usage:
    "E:/无尽冬日智能体/.venv/Scripts/python.exe" tools/ui_navigation_matrix.py [--json path]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime import LiveRuntime  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

UNKNOWN = "UNKNOWN"
MANIFEST = ROOT / "dataset" / "candidate" / "template_manifest.json"
CONTRACT = ROOT / "winter_agent_v2" / "skill_factory.py"

#: Destination page of a target, taken only from names whose page the project has already
#: established.  Anything else stays UNKNOWN rather than being guessed from a prefix: a wrong
#: destination is worse than an absent one, because the route reads these to decide where it is.
DESTINATION_HINTS = {
    "PAGE_MAP": "MAP",
    "PAGE_INTEL": "INTEL",
    "PAGE_MAIL": "MAIL",
    "PAGE_DAILY": "DAILY",
    "PAGE_RESEARCH": "RESEARCH",
    "PAGE_ALLIANCE_TECH": "ALLIANCE",
    "PAGE_TRAINING_INFANTRY": "TRAINING",
    "PAGE_TRAINING_LANCER": "TRAINING",
    "PAGE_TRAINING_MARKSMAN": "TRAINING",
    "PAGE_BEAST_MARCH": "MARCH",
    "POPUP_POWER_OVERVIEW": "POPUP",
    "POPUP_POWER_DETAILS": "POPUP",
}

#: Functions the operator named, as regular expressions over the project's own target names.  The
#: mapping is a *query* over identifiers the project already uses, not a new naming scheme: if a
#: function's entry is called something none of these match, it shows up as a gap rather than being
#: renamed.  Patterns rather than plain substrings because the first version of this file grouped
#: every RESEARCH target under "地图搜索栏" -- RESEARCH contains SEARCH, and a substring scan cannot
#: tell a search bar from a research lab.
OPERATOR_FUNCTIONS = {
    "城镇/野外快捷面板": r"POWER_OVERVIEW|POWER_DETAILS|POWER_TROOP_IMPROVE|POWER_RESEARCH_IMPROVE",
    "兵营/盾兵-矛兵-射手": r"TRAINING|TROOP_PLUS|INFANTRY_CAMP",
    "科技研究": r"^BTN_OPEN_RESEARCH|RESEARCH_TAB|RESEARCH_QUEUE|RESEARCH_BUILDING|"
                r"BUILDING_RESEARCH|STATUS_RESEARCH|HIGH_RISK_GEM_FINISH_RESEARCH|PAGE_RESEARCH|"
                r"BTN_POWER_RESEARCH_IMPROVE",
    "联盟捐献": r"ALLIANCE_TECH|CONTRIBUTE",
    "情报/灯塔": r"INTEL|LIGHTHOUSE",
    "地图搜索栏": r"(?<!RE)SEARCH|RESOURCE_DYNAMIC|RESOURCE_LEVEL|RESOURCE_TAB",
    "巨兽/自动加入": r"GIANT_BEAST|RALLY|AUTO_JOIN|JOIN_",
    "采集点/资源详情": r"RESOURCE_DETAIL|RESOURCE_BEAST|RESOURCE_(WOOD|MEAT|COAL|IRON)|BTN_GATHER|"
                        r"STATUS_GATHERING",
    "回城/返回": r"OPEN_HOME|RECALL|RETURNING",
    "邮件": r"MAIL",
    "活动/限时提醒": r"DAILY|EVENT|ACTIVITY",
    "体力HUD": r"STAMINA",
}


def template_index() -> dict[str, int]:
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    counts: collections.Counter[str] = collections.Counter()
    for record in payload.get("records") or ():
        semantic = str(record.get("semantic") or "")
        if semantic:
            counts[semantic] += 1
    return dict(counts)


def goal_requirements() -> dict[str, list[str]]:
    """Each Goal's declared entry skills, from the project's own contract file."""
    try:
        from winter_agent_v2.skill_factory import GOAL_REQUIREMENTS
    except Exception:  # noqa: BLE001 - a missing contract must not break the report
        return {}
    out: dict[str, list[str]] = {}
    for goal, requirement in GOAL_REQUIREMENTS.items():
        entry = requirement if isinstance(requirement, dict) else {}
        skills = entry.get("skills") or entry.get("required_skills") or ()
        out[str(goal)] = [str(s) for s in skills]
    return out


def build() -> dict:
    registry = v2_registry()
    bound = LiveRuntime.VERIFIED_ATOMIC
    templates = template_index()
    goals = goal_requirements()

    skills_by_target: dict[str, list[str]] = collections.defaultdict(list)
    for skill in registry.all():
        if skill.action.target:
            skills_by_target[str(skill.action.target)].append(skill.id)

    entries = []
    for skill in sorted(registry.all(), key=lambda s: s.id):
        target = str(skill.action.target or "")
        evidence = templates.get(target, 0) if target else 0
        kind = str(skill.action.kind)
        entries.append(
            {
                "skill": skill.id,
                "source_page": skill.required_page.value if skill.required_page else UNKNOWN,
                "action": f"{kind}:{target}" if target else kind,
                "target": target or UNKNOWN,
                "destination_page": DESTINATION_HINTS.get(target, UNKNOWN),
                "schedulable": skill.id in bound,
                "verifier": getattr(bound.get(skill.id), "__name__", UNKNOWN),
                # A template-backed target has a picture; a dynamic one is computed from the frame;
                # anything else is a fact about the code, not about the client.
                "visual_evidence": (
                    0 if not target else
                    evidence if evidence else
                    "DYNAMIC_RESOLVER" if kind in ("TAP_SEMANTIC",) else kind
                ),
                "navigation_like": bool(
                    skill.id.startswith(("OPEN_", "NAVIGATE_", "SEARCH_", "SELECT_", "SUBMIT_", "BACK"))
                    or kind in ("NAVIGATE_TO", "PRESS_BACK")
                ),
            }
        )

    by_goal = []
    for goal, declared in sorted(goals.items()):
        reached = [e for e in entries if e["skill"] in set(declared)]
        nav = [e for e in reached if e["navigation_like"]]
        by_goal.append(
            {
                "goal": goal,
                "declared_skills": declared,
                "navigation_paths": nav,
                "schedulable_path_count": sum(1 for e in nav if e["schedulable"]),
            }
        )

    orphaned = [
        {"semantic": semantic, "templates": count}
        for semantic, count in sorted(templates.items())
        if semantic not in skills_by_target
    ]

    # --- the operator's functions, answered as a query over the project's identifiers ----
    operator = []
    for label, pattern in OPERATOR_FUNCTIONS.items():
        matcher = re.compile(pattern)
        skills = sorted({e["skill"] for e in entries if matcher.search(e["target"])})
        shippable = [
            e["skill"] for e in entries
            if e["skill"] in skills and e["schedulable"]
        ]
        templates_hit = sorted(s for s in templates if matcher.search(s))
        operator.append(
            {
                "function": label,
                "registered_entry_skills": skills,
                "schedulable_entry_skills": sorted(shippable),
                "path_count": len(shippable),
                "semantics_with_templates": len(templates_hit),
                "semantics_with_templates_and_no_skill": sorted(
                    s for s in templates_hit if s not in skills_by_target
                ),
            }
        )

    return {
        "gate": "DERIVED",
        "generated_by": "tools/ui_navigation_matrix.py",
        "contract_file": CONTRACT.name,
        "counts": {
            "skills": len(entries),
            "schedulable": len(bound),
            "navigation_like_entries": sum(1 for e in entries if e["navigation_like"]),
            "schedulable_navigation_entries": sum(
                1 for e in entries if e["navigation_like"] and e["schedulable"]
            ),
            "distinct_targets": len(skills_by_target),
            "semantics_with_templates": len(templates),
            "semantics_with_templates_and_no_skill": len(orphaned),
        },
        "operator_functions": operator,
        "entries": entries,
        "goals": by_goal,
        "semantics_without_any_skill": orphaned,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=str(ROOT / "knowledge" / "ui" / "navigation_matrix.json"))
    args = parser.parse_args()
    payload = build()
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=1))
    print(f"written: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
