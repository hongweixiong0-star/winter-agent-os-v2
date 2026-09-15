"""WB-0AZ integration check: can the brain's BACK decision actually be dispatched
from Page.BEAST, and does anything earlier in decide() steal the branch?
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import runtime  # noqa: E402
from winter_agent_v2.brain import RuleBrain  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402
from winter_agent_v2.skills import v2_registry  # noqa: E402

BLOCKED = {
    "name": "大师悬赏",
    "level": 20,
    "available": False,
    "recommended_power": 189295920,
    "stamina_cost_displayed": 10,
    "blocked_reason": "POWER_BELOW_RECOMMENDED",
}


def main() -> None:
    reg = v2_registry()
    by_id = {s.id: s for s in reg.all()}

    print("=== is BACK dispatchable from an arbitrary page? ===")
    s = by_id.get("BACK")
    if s is None:
        print("  BACK NOT IN REGISTRY  <-- would be a hard blocker")
    else:
        print("  required_page :", getattr(s, "required_page", "?"))
        print("  state         :", getattr(s, "state", "?"))
        print("  verifier      :", repr(getattr(s, "verifier", None)))
        print("  action        :", getattr(s, "action", None))
    print("  BACK in LiveRuntime.VERIFIED_ATOMIC :", "BACK" in runtime.LiveRuntime.VERIFIED_ATOMIC)
    print("  VERIFIED_ATOMIC size :", len(runtime.LiveRuntime.VERIFIED_ATOMIC))
    if "BACK" not in runtime.LiveRuntime.VERIFIED_ATOMIC:
        print("  !! the brain can name BACK and the live loop would refuse it (the CHECK_MARCH class)")

    print()
    print("=== the decision, exactly as the live card produces it ===")
    world = WorldState(page=Page.BEAST, beast=dict(BLOCKED), confidence=0.99)
    for goal in ("INTEL", "AUTO_DISCOVERY", "GATHER_RESOURCE", "HOME"):
        brain = RuleBrain(current_goal=goal)
        d = brain.decide(world, reg)
        print(
            "  goal=%-16s -> %-8s reason=%-46s expected=%s"
            % (goal, d.skill, d.reason, d.expected_result)
        )

    print()
    print("=== is the skill the brain names registered and enabled? ===")
    d = RuleBrain(current_goal="INTEL").decide(world, reg)
    reg_ids = set(by_id)
    print("  decision skill in registry :", d.skill in reg_ids)
    print("  dispatchable by live loop  :", d.skill in runtime.LiveRuntime.VERIFIED_ATOMIC)

    print()
    print("=== what does the runtime do with a reason it does not know? ===")
    from winter_agent_v2.runtime_snapshot import NON_FATAL_STOPS, is_fatal_stop

    print("  reason                     :", d.reason)
    print("  in NON_FATAL_STOPS         :", d.reason in NON_FATAL_STOPS)
    print("  is_fatal_stop              :", is_fatal_stop(d.reason))

    print()
    print("=== is the branch reachable, i.e. does anything earlier claim Page.BEAST? ===")
    src = (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8").splitlines()
    first = None
    for i, ln in enumerate(src, 1):
        if "Page.BEAST" in ln and first is None:
            first = i
        if "unknown_page" in ln and first is None:
            print("  earlier guard at line", i, ":", ln.strip()[:100])
    print("  first Page.BEAST reference at line:", first)
    print("  ('unknown_page' safe-stop is the only earlier exit and needs world.known == False)")


if __name__ == "__main__":
    main()
