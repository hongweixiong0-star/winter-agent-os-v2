"""Capability landing queue for the CAPABILITY-FIRST phase (2026-09-16).

The operator's phase directive fixes both the goal and the order:

    GATHER_RESOURCE / RECALL_MARCH
      -> CLAIM_REWARD / MAIL / VIP / FREE CLAIM
      -> TRAIN / PROMOTE / HEAL
      -> RESEARCH / BUILD
      -> ALLIANCE_HELP / ALLIANCE_GIFT / ALLIANCE_TECH
      -> HUNT_BEAST
      -> ARENA / EXPLORATION / LABYRINTH / PET
      -> JOIN_RALLY / START_RALLY
      -> BEAR
      -> other actually-unlocked features

with one minimum acceptance per capability: Preconditions -> Execute -> Verifier
PASS -> Production Episode -> Evidence.

This prints the facts that decide whether a capability can be landed at all.  Per
the coverage-audit skill's warning, "never tried" and "not implemented" are
different problems and must not be conflated -- the project has already mislabelled
five unimplemented goals as never-tried.  Four independent things matter:

    registry    is the skill declared at all
    judge       is it in ``LiveRuntime.VERIFIED_ATOMIC`` -- the map of verifiers the
                runtime actually consults.  ``Skill.verifier`` is only the *declared*
                name of a verifier, and the two disagree: RR-003 in the handoff is
                exactly the case of "declares one" / "the runtime has none", or the
                reverse.  Only the runtime's map decides whether a step can be judged.
    dispatched  a skill can be judged and still unreachable, if it is not in that map
                (the runtime refuses to dispatch what it cannot evaluate).
    state       the record's own SkillState, which is where LIVE_VERIFIED lives.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

from winter_agent_v2.runtime import LiveRuntime
from winter_agent_v2.skills import v2_registry

# The operator's order, verbatim.  Each tuple is one capability and the skills that
# could realise it.  A skill the operator named but that does not exist yet is kept
# in the list on purpose: its absence is the finding.
QUEUE: list[tuple[str, tuple[str, ...]]] = [
    ("GATHER_RESOURCE", ("OPEN_MAP", "SEARCH_RESOURCE", "SELECT_RESOURCE", "SUBMIT_RESOURCE_SEARCH", "START_GATHER", "DISPATCH_MARCH")),
    ("RECALL_MARCH", ("RECALL_MARCH",)),
    ("CLAIM_REWARD / MAIL / VIP / FREE CLAIM", ("OPEN_MAIL", "CLAIM_MAIL", "OPEN_VIP", "CLAIM_VIP", "OPEN_STAMINA_SOURCES", "CLAIM_FREE_STAMINA", "OPEN_DAILY", "CLAIM_DAILY")),
    ("TRAIN / PROMOTE / HEAL", ("OPEN_TRAINING", "START_TRAINING", "PROMOTE_TROOPS", "HEAL_TROOPS", "OPEN_HOSPITAL")),
    ("RESEARCH / BUILD", ("OPEN_RESEARCH", "START_RESEARCH", "OPEN_BUILD", "START_BUILD")),
    ("ALLIANCE_HELP / GIFT / TECH", ("OPEN_ALLIANCE", "OPEN_ALLIANCE_HELP", "ALLIANCE_HELP", "OPEN_ALLIANCE_GIFTS", "CLAIM_ALLIANCE_GIFT", "OPEN_ALLIANCE_TECH", "START_ALLIANCE_TECH")),
    ("HUNT_BEAST", ("OPEN_BEAST", "DISPATCH_BEAST", "DISPATCH_INTEL_BEAST")),
    ("ARENA / EXPLORATION / LABYRINTH / PET", ("OPEN_ARENA", "START_ARENA_FIGHT", "OPEN_EXPLORATION", "FIGHT_HERO_CAMP", "OPEN_LABYRINTH", "OPEN_PET")),
    ("JOIN_RALLY / START_RALLY", ("OPEN_RALLY", "JOIN_RALLY", "START_RALLY")),
    ("BEAR", ("OPEN_BEAR", "START_BEAR_RALLY", "JOIN_BEAR_RALLY")),
]


def episode_stats() -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        bucket = stats.setdefault(str(row.get("skill") or ""), {})
        result = str(row.get("result") or "?").upper()
        bucket[result] = bucket.get(result, 0) + 1
    return stats


def main() -> int:
    registry = v2_registry()
    judges = LiveRuntime.VERIFIED_ATOMIC
    stats = episode_stats()

    print("%-36s %-22s %-5s %-6s %-6s %-22s %s" % (
        "capability", "skill", "reg", "judge", "tried", "state", "episodes"))
    print("-" * 140)

    unimplemented: list[str] = []
    unjudgeable: list[str] = []
    judgeable_never_tried: list[tuple[str, str]] = []

    for capability, skills in QUEUE:
        for index, name in enumerate(skills):
            skill = registry.get(name)
            counts = stats.get(name) or {}
            tried = sum(counts.values())
            if skill is None:
                unimplemented.append(name)
            elif name not in judges:
                unjudgeable.append(name)
            elif tried == 0:
                judgeable_never_tried.append((capability, name))
            print("%-36s %-22s %-5s %-6s %-6s %-22s %s" % (
                capability if index == 0 else "",
                name,
                "yes" if skill else "NO",
                "yes" if name in judges else "NO",
                str(tried) if tried else "NO",
                getattr(skill, "state").value if skill else "-",
                ", ".join("%s=%d" % (k.lower(), v) for k, v in sorted(counts.items())) or "-",
            ))
        print()

    print("=" * 140)
    print("NOT IMPLEMENTED -- not in the registry (%d):" % len(unimplemented))
    print("   " + (", ".join(unimplemented) or "-"))
    print()
    print("IMPLEMENTED BUT UNJUDGEABLE -- registered, absent from VERIFIED_ATOMIC (%d):" % len(unjudgeable))
    print("   " + (", ".join(unjudgeable) or "-"))
    print("   (the runtime will never dispatch a step it cannot evaluate)")
    print()
    print("JUDGEABLE AND NEVER EXECUTED -- the cheapest coverage this phase (%d):" % len(judgeable_never_tried))
    for capability, name in judgeable_never_tried:
        print("   %-38s %s" % (capability, name))
    print()
    print("VERIFIED_ATOMIC=%d  registry=%d  episodes=%d" % (
        len(judges), len(registry.all()), sum(sum(c.values()) for c in stats.values())))

    coverage = ROOT / "learning/goal_coverage.json"
    print("goal_coverage.json:", "present" if coverage.exists() else "absent",
          "| builder:", "present" if (ROOT / "tools/build_capability_coverage.py").exists() else "absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
