"""Reconnaissance for WB-R19-LOW-RISK-GOAL-ATTEMPT: is there a safe candidate?

The order asks for one bounded live attempt on a capability that has never run,
and its stop_condition is "no candidate satisfies the safety and verifier
conditions".  Choosing that candidate is a filter over the registry plus the
episode corpus, and it costs nothing to compute -- so compute it rather than
reason about it, and so the answer for the next session is evidence rather than
recollection.

A candidate must be: never executed; risk NONE or LOW; carrying a verifier AND a
recovery path (the order's own requirement); and not in the areas the order fences
off (Arena, Labyrinth, Rally, payment, account security).

Read-only.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.skills import v2_registry  # noqa: E402

FENCED = ("arena", "labyrinth", "rally", "payment", "purchase", "account", "login", "bind")


def main() -> int:
    registry = v2_registry()
    skills = registry.all()

    executed: Counter[str] = Counter()
    results: Counter[str] = Counter()
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        skill = row.get("skill")
        if not skill:
            continue
        executed[skill] += 1
        if str(row.get("result")).upper() == "SUCCESS":
            results[skill] += 1

    print("registry skills: %d   distinct skills seen in episodes: %d" % (len(skills), len(executed)))
    print()
    never = [s for s in skills if s.id not in executed]
    print("never executed (%d):" % len(never))
    for skill in sorted(never, key=lambda s: s.id):
        print("   %-34s risk=%-18s verifier=%-26s recovery=%s"
              % (skill.id, skill.risk, skill.verifier or "-", skill.recovery or "-"))
    print()

    print("=== candidates that satisfy the order's own conditions ===")
    safe: list = []
    for skill in never:
        if skill.risk.upper() not in ("NONE", "LOW"):
            continue
        if not skill.verifier or not skill.recovery:
            continue
        blob = (skill.id + " " + skill.description).lower()
        if any(word in blob for word in FENCED):
            continue
        safe.append(skill)
    if not safe:
        print("   NONE.  Every never-executed skill fails at least one condition:")
        for skill in sorted(never, key=lambda s: s.id):
            reasons = []
            if skill.risk.upper() not in ("NONE", "LOW"):
                reasons.append("risk=%s" % skill.risk)
            if not skill.verifier:
                reasons.append("no verifier")
            if not skill.recovery:
                reasons.append("no recovery")
            blob = (skill.id + " " + skill.description).lower()
            for word in FENCED:
                if word in blob:
                    reasons.append("fenced:%s" % word)
            print("     %-34s %s" % (skill.id, ", ".join(reasons) or "?"))
    else:
        for skill in safe:
            print("   %-34s risk=%-12s verifier=%-26s recovery=%s"
                  % (skill.id, skill.risk, skill.verifier, skill.recovery))
    print()
    print("=== executed skills, for context (success/attempts) ===")
    for skill, count in executed.most_common(20):
        print("   %-34s %3d attempts / %3d success" % (skill, count, results[skill]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
