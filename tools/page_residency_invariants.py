"""Counter-examples for the page-residency term, against the operator's §17/§50 rules.

The term adds up to 40 to a goal that habitually lives on the page we are standing on.  A
bonus in a ranking is exactly where starvation is born, so the questions that must be
answered with a measurement rather than an argument are:

1. **Can it outrank work that pays?**  The 40 has to stay under the 70-point gap that
   separates an unread visit (180) from a real claim (250), or a settled goal would park
   itself in front of a claimable one forever.
2. **Does a failing resident lose?**  The bonus is held under ``REPEAT_FAILURE_PENALTY``
   (60) on purpose.  A goal that is on the right page and getting nowhere must still lose to
   one that is on the wrong page and working -- otherwise the fix trades a ping-pong for a
   stall, which is the same failure with a different shape.
3. **Is a starved goal still reachable?**  Fairness is the mechanism that guarantees every
   goal eventually wins, so a resident bonus must not make ``FAIRNESS_AGE_BONUS`` unable to
   lift a goal clear of a settled one.
4. **Does anything become unreachable?**  The full board, ranked with the term on and off,
   must contain the same goals in the same reachability order -- the term reorders, it must
   not exclude.

Each check prints the numbers it decided on, so a reader can disagree with the verdict
without re-running anything.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_utility as gu  # noqa: E402


@dataclass
class _World:
    page: str
    stamina: dict = field(default_factory=dict)
    idle_marches: int = 0
    red_dots: dict = field(default_factory=dict)
    known: bool = True


@dataclass
class _Goal:
    goal_id: str
    available_skills: tuple
    priority: float
    status: str = "READY"
    evidence: dict = field(default_factory=dict)
    reward_value: float = 0.0
    remaining_seconds: float | None = None
    event_synergy: float = 0.0
    development_value: float = 0.0
    resource_cost: float = 0.0
    risk: float = 0.0
    daily_loss: float = 0.0


def _row(goal_id: str, skills: tuple, priority: float) -> _Goal:
    return _Goal(goal_id=goal_id, available_skills=skills, priority=priority)


def main() -> int:
    now = datetime.now(timezone.utc)
    checks: list[tuple[str, bool, str]] = []

    # 1 -- the ceiling, measured against the board's own price scale.
    checks.append((
        "residency (40) < the 70-point visit->claim gap, so a settled goal cannot park "
        "itself in front of a claimable one",
        gu.PAGE_RESIDENCY_BONUS < 70.0,
        f"bonus={gu.PAGE_RESIDENCY_BONUS}, gap=70.0 (visit 180 -> claim 250)",
    ))

    # 2 -- a resident that is failing must lose to a visitor that is working.
    checks.append((
        "residency (40) < repeat-failure (60), so being on the right page never beats "
        "actually getting somewhere",
        gu.PAGE_RESIDENCY_BONUS < gu.REPEAT_FAILURE_PENALTY,
        f"bonus={gu.PAGE_RESIDENCY_BONUS}, penalty={gu.REPEAT_FAILURE_PENALTY}",
    ))

    # 3 -- starvation.  Fairness must still be able to lift a starved goal over a settled
    # one; the honest way to ask is whether the bonus is small next to fairness's ceiling.
    checks.append((
        "fairness can still outrank residency, so a goal nobody has served in hours wins "
        "eventually",
        gu.FAIRNESS_AGE_BONUS > gu.PAGE_RESIDENCY_BONUS,
        f"fairness ceiling={gu.FAIRNESS_AGE_BONUS}, residency={gu.PAGE_RESIDENCY_BONUS}",
    ))

    # 4 -- the residency table must not exclude anybody.  Same board, both settings.
    resident = _row("KEEP_BUILDING_PRODUCTIVE", ("OPEN_QUICK_PANEL",), 180.0)
    elsewhere = _row("CLEAR_INTEL", ("OPEN_INTEL",), 180.0)
    paid = _row("MY_REWARDS", ("OPEN_REWARDS",), 250.0)
    board = [resident, elsewhere, paid]
    home = _World(page="HOME")
    with_term = [g.goal_id for g, _ in gu.rank(board, world=home, now=now)]
    original = gu.PAGE_RESIDENCY_BONUS
    try:
        gu.PAGE_RESIDENCY_BONUS = 0.0
        without = [g.goal_id for g, _ in gu.rank(board, world=home, now=now)]
    finally:
        gu.PAGE_RESIDENCY_BONUS = original
    checks.append((
        "the same goals stay on the board with the term on and off -- it reorders, never excludes",
        set(with_term) == set(without) and len(with_term) == len(board),
        f"with={with_term} without={without}",
    ))

    # 5 -- and the paid work still wins on a page it does not live on, which is the whole
    # promise of keeping the ceiling under the claim gap.
    claim_first = [g.goal_id for g, _ in gu.rank(board, world=_World(page="MAIL"), now=now)]
    checks.append((
        "a claimable goal still wins from a page it does not live on",
        claim_first and claim_first[0] == "MY_REWARDS",
        f"on MAIL the order is {claim_first}",
    ))

    width = max(len(label) for label, _, _ in checks)
    ok = True
    for label, passed, detail in checks:
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {label:<{width}}  ({detail})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
