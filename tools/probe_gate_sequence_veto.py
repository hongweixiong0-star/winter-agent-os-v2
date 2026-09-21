"""What does the capability gate actually refuse right now, and why?

Operator section 5 asks about one line: ``capability_gate.py:559-565``, where a SEQUENCE goal
is refused if *any* of its capabilities has a blocker.  That would be wrong for the operator's
case -- the early steps runnable, only a later ordinary-interaction step unlearned -- but
"would be" is not the same as "is".  This probe reads the live artifacts and prints, per goal:

  * the composition (SEQUENCE or ANY_OF) and its capability list, in order,
  * the state of each capability as the gate sees it,
  * which capability the gate names and with what state,

so the question "is a goal being held back by a later step" is answered from the current
ledger rather than from the code's shape.

Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.capability_gate import (  # noqa: E402
    DEFERRING_STATES, SOURCE_QUEUE, CapabilityGate,
)
from winter_agent_v2.goal_library import GoalLibrary  # noqa: E402


def main() -> int:
    gate = CapabilityGate.load(ROOT)
    print("compositions:", len(gate.compositions))
    print("capability states the gate knows:", len(gate.capabilities))
    print()

    library = GoalLibrary()
    from winter_agent_v2.models import WorldState

    world = WorldState()
    goals = library.discover(world)
    print("goals discoverable from an empty world:", [g.goal_id for g in goals])
    print()

    interesting = (
        "KEEP_TRAINING_PRODUCTIVE", "AVOID_STAMINA_WASTE", "CLEAR_INTEL",
        "DAILY_ACTIVITY_TARGET", "CLAIM_EXPLORATION_IDLE", "KEEP_RESEARCH_PRODUCTIVE",
        "KEEP_MARCHES_PRODUCTIVE", "MAIL_ROUTINE", "ALLIANCE_ROUTINE",
    )
    for goal_id in interesting:
        composition = gate.compositions.get(goal_id)
        print(f"=== {goal_id}")
        if composition is None:
            print("    no composition recorded -> the gate can never refuse it")
            continue
        print(f"    composition: {composition.composition}")
        for capability in composition.capabilities:
            found = gate.capabilities.get(capability)
            if found is None:
                print(f"      {capability:34} (no state recorded)")
            else:
                state, reason, until = found
                mark = "DEFERS" if state in DEFERRING_STATES else "ok"
                print(f"      {capability:34} {state:22} {mark:6} {str(reason)[:60]}")
        verdict = gate._capability_deferral(goal_id)
        if verdict is None:
            print("    -> gate refuses nothing")
        else:
            print(f"    -> REFUSES as {verdict.state} / {verdict.source}: "
                  f"{verdict.capability} -- {str(verdict.reason)[:90]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
