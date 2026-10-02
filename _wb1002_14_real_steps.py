"""Acceptance on production inputs: replay the 10 real OPEN_HOME failures.

Each of these rows is a real step the runtime took, carrying the exact ``state_before``
that the decision was made from.  Rebuilding that WorldState and asking the *new* brain
is the closest thing to a re-run that costs no stamina: the decision is a pure function
of the frame, so the same frame must now answer differently.

Run with either tree:

    .venv/Scripts/python.exe _wb1002_14_real_steps.py
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.goal_library import route_for  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

FIELDS = {f.name for f in dataclasses.fields(WorldState)}


def failing_rows():
    path = ROOT / "learning" / "episodes.jsonl"
    size = os.path.getsize(path)
    with path.open("rb") as stream:
        stream.seek(max(0, size - 25_000_000))
        blob = stream.read().decode("utf-8", "replace")
    rows = []
    for line in blob.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if (
            str(row.get("recorded_at") or "").startswith("2026-10-02")
            and row.get("skill") == "OPEN_HOME"
            and row.get("result") == "FAILURE"
        ):
            rows.append(row)
    return rows


def rebuild(state_before: dict) -> WorldState:
    """Rebuild the frame the decision was made from.

    ``page`` is stored as the enum's *value* (``"MAP"``) in the ledger, and every branch in
    ``RuleBrain`` compares with ``is Page.MAP``.  Passing the string straight through makes
    every page branch false and silently sends the decision down its fallback -- so the
    conversion is not cosmetic, it is the difference between replaying the step and replaying
    some other step.
    """
    fields = {k: v for k, v in state_before.items() if k in FIELDS}
    if isinstance(fields.get("page"), str):
        fields["page"] = Page(fields["page"])
    return WorldState(**fields)


def main() -> int:
    registry = v2_registry()
    rows = failing_rows()
    print(f"real OPEN_HOME failures today: {len(rows)}")
    print()
    print(
        "%-9s %-8s %-30s %-22s %-6s  %s"
        % ("time", "goal_id", "decision_reason", "route", "panel", "new decision")
    )
    changed = 0
    for row in rows:
        world = rebuild(row.get("state_before") or {})
        # The row names the attached goal; the brain reads the route off ``current_goal``,
        # so ask the goal layer the same question the runtime asks (see ``_goal_route``).
        route = route_for(str(row.get("goal_id") or "")) or str(row.get("goal_id") or "")
        brain = RuleBrain(current_goal=route)
        # ``goal_id`` is set by the runtime after construction (the constructor takes it
        # only through ``current_goal``); the fishing branch reads it to pick its skill.
        brain.goal_id = str(row.get("goal_id") or "")
        decision = brain.decide(world, registry)
        also_wrong = decision.skill == "OPEN_HOME"
        changed += 0 if also_wrong else 1
        print(
            "%-9s %-8s %-30s %-22s %-6s  %s / %s%s"
            % (
                str(row.get("recorded_at"))[11:19],
                str(row.get("role_id"))[-4:],
                str(row.get("decision_reason"))[:30],
                route[:22],
                world.resource_search_open,
                decision.skill,
                str(decision.reason)[:34],
                "   <-- STILL OPEN_HOME" if also_wrong else "",
            )
        )
    print()
    print(f"steps whose decision changed away from OPEN_HOME: {changed}/{len(rows)}")
    return 0 if changed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
