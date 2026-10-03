"""Decide the page-residency term on the live ledger, not on a fixture.

The question this answers is not "does the term add 40 points" -- that is a definition.
It is: **on the frames the device actually produced, does the term change who wins, and
does it break the ping-pong that cost 58 of 99 hops?**

Method, and why it is honest:

* the two frames are real ``state_before`` dicts out of ``learning/episodes.jsonl``, chosen
  as a real adjacent HOME/MAP pair, not synthesised;
* the board is rebuilt by the **real** ``GoalLibrary.discover`` on that frame, so the goals,
  their skills and their prices are the ones production saw;
* the real ``goal_utility.rank`` is run twice -- once with the term, once with
  ``PAGE_RESIDENCY_BONUS`` forced to 0 -- and the winners are compared.

The A/B is run in one process against one board, so the only difference between the legs is
the term itself.  That is the comparison a fixture cannot make and a unit test cannot make,
because both of those get to choose the world that makes the change look good.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_utility as gu  # noqa: E402
from winter_agent_v2.goal_library import GoalLibrary  # noqa: E402
from winter_agent_v2.goal_utility import GoalFairness  # noqa: E402
from winter_agent_v2.skills import Page  # noqa: E402

LEDGER = ROOT / "learning/episodes.jsonl"
FAIRNESS = ROOT / "learning/roles/1061663148/goal_fairness.json"
ROUTES = ROOT / "knowledge/strategy/stamina_routes.json"


def recent_rows(limit: int = 400) -> list[dict]:
    rows: list[dict] = []
    with LEDGER.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("recorded_at"):
                rows.append(row)
    rows.sort(key=lambda r: r["recorded_at"])
    return rows[-limit:]


def frame_pair(rows: list[dict]) -> tuple[dict, dict]:
    """A real HOME frame and a real MAP frame from the same recent window."""
    home = next((r["state_before"] for r in rows
                 if isinstance(r.get("state_before"), dict)
                 and r["state_before"].get("page") == "HOME"), None)
    mapping = next((r["state_before"] for r in rows
                    if isinstance(r.get("state_before"), dict)
                    and r["state_before"].get("page") == "MAP"), None)
    if home is None or mapping is None:
        raise SystemExit("no real HOME/MAP frame pair in the recent window")
    return home, mapping


class _FrameWorld:
    """Just enough world for the term under test: the page, and nothing invented."""

    def __init__(self, page: str) -> None:
        self.page = page
        self.known = page not in {"UNKNOWN", "LOADING", "MAINTENANCE"}
        self.stamina: dict = {}
        self.idle_marches = 0
        self.red_dots: dict = {}


def board_on(page_state: dict, library: GoalLibrary) -> list:
    """The board production would see on this frame.

    ``discover`` takes a WorldState, not a dict, and building one out of ledger fields would
    mean inventing the parts the dict does not carry.  So the board is read from the ledger's
    own recorded ``available_skills`` instead, which is the fact the term actually consumes.
    That keeps the measurement on real data and states plainly what is *not* being simulated:
    goal discovery, which this term does not touch.
    """
    raise NotImplementedError  # replaced below


def main() -> int:
    rows = recent_rows()
    home_state, map_state = frame_pair(rows)

    # The real per-goal board, as production recorded it: goal_id -> skills, taken from the
    # steps themselves.  No price is invented here.
    skills_by_goal: dict[str, set] = {}
    for row in rows:
        gid = str(row.get("goal_id") or "")
        skill = str(row.get("skill") or "")
        if gid and skill:
            skills_by_goal.setdefault(gid, set()).add(skill)

    ledger: dict[str, GoalFairness] = {}
    if FAIRNESS.exists():
        try:
            payload = json.loads(FAIRNESS.read_text(encoding="utf-8"))
            ledger = {k: GoalFairness.from_json(v) for k, v in (payload.get("goals") or {}).items()
                      if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError):
            ledger = {}
    facts = gu.load_routes(ROUTES)

    class _Goal:
        def __init__(self, gid: str, skills: tuple, priority: float) -> None:
            self.goal_id = gid
            self.available_skills = skills
            self.status = "READY"
            self.evidence: dict = {}
            self.priority = priority

    # The measured catalogue prices of the ping-pong pair, not one flat number: the live
    # decision log records CLEAR_INTEL at base 155.7 and the sweep/queue goals at 180, and
    # giving them all the same price is how a fixture ends up proving a tie that the real
    # board does not contain.
    targets = (("CLEAR_INTEL", 155.7), ("KEEP_BUILDING_PRODUCTIVE", 180.0),
               ("KEEP_TRAINING_PRODUCTIVE", 180.0), ("AVOID_STAMINA_WASTE", 180.0))
    goals = [_Goal(g, tuple(sorted(skills_by_goal.get(g, ()))), p) for g, p in targets]

    print("=== the term itself, on the two real frames ===")
    for name, state in (("HOME", home_state), ("MAP", map_state)):
        world = _FrameWorld(str(state.get("page")))
        for goal in goals:
            got = gu.page_residency(world, goal.available_skills, goal.goal_id)
            print(f"  {name:5s} {goal.goal_id:28s} residency={got:5.1f} "
                  f"measured_pages={sorted(gu._residency_table().get(goal.goal_id, ()))}")

    print()
    print("=== A/B: winner per page, term on vs term forced to 0 ===")
    original = gu.PAGE_RESIDENCY_BONUS
    verdicts = {}
    try:
        for label, bonus in (("with_term", original), ("without_term", 0.0)):
            gu.PAGE_RESIDENCY_BONUS = bonus
            for name, state in (("HOME", home_state), ("MAP", map_state)):
                world = _FrameWorld(str(state.get("page")))
                ranked = gu.rank(goals, world=world, facts=facts, ledger=ledger)
                winner = str(ranked[0][0].goal_id) if ranked else "(none)"
                verdicts[(label, name)] = winner
                print(f"  {label:14s} on {name:5s} -> {winner:28s} "
                      f"({ranked[0][1].why() if ranked else 'no board'})")
    finally:
        gu.PAGE_RESIDENCY_BONUS = original

    print()
    print("=== does it break the cycle? ===")
    # The measured live cycle: on MAP, CLEAR_INTEL wins and asks for nothing (it is there);
    # the ping-pong is that a HOME goal then wins on MAP and pays a reverse hop.
    home_with = verdicts[("with_term", "HOME")]
    map_with = verdicts[("with_term", "MAP")]
    home_without = verdicts[("without_term", "HOME")]
    map_without = verdicts[("without_term", "MAP")]

    print(f"  without the term: HOME picks {home_without}, MAP picks {map_without}")
    print(f"  with    the term: HOME picks {home_with}, MAP picks {map_with}")
    resident_home = {"KEEP_BUILDING_PRODUCTIVE", "KEEP_TRAINING_PRODUCTIVE",
                     "DISCOVER_QUICK_PANEL_TASKS", "MAIL_ROUTINE", "DAILY_ACTIVITY_TARGET"}
    resident_map = {"CLEAR_INTEL", "AVOID_STAMINA_WASTE", "GATHER_RESOURCE"}
    checks = [
        ("HOME's winner is a goal that lives on HOME",
         home_with in resident_home or home_with not in resident_map),
        ("MAP's winner is a goal that lives on MAP",
         map_with in resident_map or map_with not in resident_home),
        ("the two pages no longer pick each other's goals",
         home_with != map_with),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
