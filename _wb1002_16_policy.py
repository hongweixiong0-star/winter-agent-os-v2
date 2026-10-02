"""What would the gather policy say if the resource were the plan rather than the frozen placeholder?

The verifier refuses DISPATCH_MARCH with STALE_OR_ROLE_UNSCOPED_FORMATION and never evaluates the
policy, because the role-scope clause short-circuits first.  ``evaluate_gather_formation`` takes the
resource as an argument and does not read ``observation["resource_type"]``, so the policy can be
evaluated honestly on the recorded formation -- for both candidate resources.

If the plan-resource policy says READY, then the only thing standing between the run and a real
march is the broken clause.

    .venv/Scripts/python.exe _wb1002_16_policy.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.hero_portraits import evaluate_gather_formation  # noqa: E402

EPISODE = "20261002_172120_360764"
WINDOW = 4_000_000


def rows_for(episode: str):
    path = ROOT / "learning" / "episodes.jsonl"
    size = path.stat().st_size
    rows = []
    with path.open("rb") as stream:
        stream.seek(max(0, size - WINDOW))
        for line in stream.read().decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("episode_id") == episode:
                rows.append(row)
    return sorted(rows, key=lambda r: r.get("step_id") or 0)


def main() -> int:
    for row in rows_for(EPISODE):
        state = row.get("state_before") or {}
        formation = ((state.get("hero_troop") or {}).get("gather_formation"))
        if not isinstance(formation, dict):
            continue
        plan = str(state.get("resource_target") or "")
        frozen = str(formation.get("resource_type") or "")
        print(f"step {row.get('step_id')}  plan={plan!r}  frozen={frozen!r}  "
              f"skill={row.get('skill')}")
        for resource in (plan, frozen):
            if not resource:
                continue
            policy = evaluate_gather_formation(resource, formation)
            print(f"    policy({resource!r}) -> {policy.get('status')} "
                  f"remove_slots={policy.get('remove_slots')} "
                  f"expected={policy.get('expected_hero_id')}")
        occupied = [(slot.get("slot"), slot.get("state"), slot.get("identity_status"),
                     slot.get("hero_id")) for slot in (formation.get("slots") or [])]
        print(f"    slots={occupied}")
        print(f"    empty_slots={formation.get('empty_slots')} "
              f"specialist_availability={formation.get('specialist_availability')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
