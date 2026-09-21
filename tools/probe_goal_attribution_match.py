"""Does the goal an episode is filed under match the work that step actually did?

Operator §九 asks the run to record "which Goal was chosen and why" next to "what the step
actually did".  Those are two fields on one row, so they can be compared, and this probe
compares them on the real stream rather than on a fixture.

The suspicion it tests, and where it came from: ``runtime.py`` sets the brain's route only
while ``brain.current_goal is None`` -- that is, once per run.  The board is re-ranked every
step (``goal_library.rank`` at ``runtime.py:1482``), but a re-ranking that cannot change the
route cannot change the action.  If that matters, the evidence is a goal whose episodes are
mostly skills belonging to some other goal's route.

Read-only.  Prints counts; writes nothing.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"

#: Which route each skill belongs to, read off ``goal_library.GOAL_ROUTES`` at runtime rather
#: than hand-copied -- a second copy of that table is the drift this project already measured
#: once (every calibration run died on argparse with EXIT_2).
def _skill_routes() -> dict[str, set[str]]:
    import sys

    sys.path.insert(0, str(ROOT))
    from winter_agent_v2 import skills as skill_module  # noqa: F401

    from winter_agent_v2.goal_library import GOAL_ROUTES

    routes: dict[str, set[str]] = defaultdict(set)
    for goal_id, route in GOAL_ROUTES.items():
        routes[route].add(goal_id)
    return routes


def _route_skills() -> dict[str, set[str]]:
    """Which route each skill is used by, taken from the registry's own declarations."""
    import sys

    sys.path.insert(0, str(ROOT))
    from winter_agent_v2.skills import v2_registry

    by_route: dict[str, set[str]] = defaultdict(set)
    for skill in v2_registry().all():
        route = getattr(skill, "route", None) or getattr(skill, "goal", None)
        if route:
            by_route[str(route)].add(skill.id)
    return by_route


def main() -> int:
    rows = []
    with EPISODES.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    print(f"episodes: {len(rows)}")

    goal_routes = _skill_routes()
    print(f"route -> goal ids: { {r: len(g) for r, g in goal_routes.items()} }")

    # The question needs no route table at all if we ask it the other way round: for each
    # goal, what fraction of its steps ran a skill that *any* route claims for a different
    # goal's capability.  Simpler and stronger: bucket by goal and list the skills.
    per_goal: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        goal = str(row.get("goal_id") or "(none)")
        per_goal[goal][str(row.get("skill") or "(none)")] += 1

    for goal in ("AVOID_STAMINA_WASTE", "KEEP_TRAINING_PRODUCTIVE", "CLEAR_INTEL",
                 "KEEP_MARCHES_PRODUCTIVE", "MAIL_ROUTINE"):
        counts = per_goal.get(goal)
        if not counts:
            continue
        total = sum(counts.values())
        print(f"\n{goal}: {total} episode(s)")
        for skill, n in counts.most_common(12):
            print(f"    {n:>5}  {skill}")

    print("\n=== the training chain, by owning goal ===")
    chain = {"WAIT_FOR_CAMP_MENU", "NAVIGATE_INFANTRY_CAMP", "OPEN_POWER_OVERVIEW",
             "OPEN_POWER_DETAILS", "OPEN_INFANTRY_TRAINING", "TRAIN_TROOPS",
             "NAVIGATE_MARKSMAN_CAMP", "NAVIGATE_LANCER_CAMP"}
    owners: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        skill = str(row.get("skill") or "")
        if skill in chain:
            owners[skill][str(row.get("goal_id") or "(none)")] += 1
    for skill in sorted(owners):
        print(f"  {skill:<26} {dict(owners[skill].most_common(4))}")

    print("\n=== the beast/stamina chain, by owning goal ===")
    spend_chain = {"SEARCH_RESOURCE", "SELECT_RESOURCE", "SUBMIT_RESOURCE_SEARCH",
                   "START_GATHER", "DISPATCH_MARCH", "SCAN_MAP_FOR_BEAST",
                   "SUBMIT_BEAST_SEARCH", "OPEN_MAP"}
    owners2: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        skill = str(row.get("skill") or "")
        if skill in spend_chain:
            owners2[skill][str(row.get("goal_id") or "(none)")] += 1
    for skill in sorted(owners2):
        print(f"  {skill:<26} {dict(owners2[skill].most_common(4))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
