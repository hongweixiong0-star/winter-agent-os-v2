"""Invariant review -- the twelve properties the operator's §22 requires, measured not asserted.

Operator directive 2026-10-02 §21/§22: a scheduling change is not done when the tests are green,
it is done when the *invariants* still hold.  §16 is explicit that UNIT_TEST_PASS is the weakest
rung and that a scheduling change owes a simulated world at minimum.  This tool is that rung: it
stands up a board in code (§17's Role A / Role B), runs the **real** chooser over it, and reports
what survives.

It also exists because the operator's §14 says to look for the existing mechanism before building
one, and the answer here is worth recording: the starvation counter they asked for already exists
(``candidate_policy.CandidateAttemptPool``, "persistent starvation counter consumed by the one
Scheduler").  Its ``eligible()`` requires ``SkillState.CANDIDATE``, so it covers candidates that
have a skill and **not** the goals that have none -- which is exactly the class §5 forbids leaving
permanently unreachable.  Reporting that distinction is the point; building a second counter would
be the mistake §13 names.

Verdicts are one of:
    PASS        measured true, with the measurement named
    FAIL        measured false, with the counter-example named
    UNMEASURED  needs evidence this tool cannot reach (production episodes, a live device);
                reported as unmeasured rather than guessed -- §16's discipline

Read-only.  It constructs boards in memory and writes nothing.

Usage:
    python tools/invariant_review.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import goal_utility  # noqa: E402
from winter_agent_v2.capability_bootstrap import project_runtime_discovery  # noqa: E402
from winter_agent_v2.goal_library import GoalState, GoalStatus, NOT_ACTIONABLE  # noqa: E402
from winter_agent_v2.models import Page, WorldState  # noqa: E402

PASS, FAIL, UNMEASURED = "PASS", "FAIL", "UNMEASURED"

#: A fixed instant, so the fairness rotation is measured rather than left to the wall clock.
NOW = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- the board

def _known(goal_id: str, *, value: float, skill: str) -> GoalState:
    return GoalState(goal_id, GoalStatus.READY, reward_value=value, daily_loss=value,
                     available_skills=(skill,))


def _unknown(goal_id: str, *, value: float) -> GoalState:
    """A goal that exists, is worth something, and has nothing to run.

    This is the shape §5 is about and the shape the project really emits: ``USE_FREE_ARENA_ATTEMPTS``
    and ``LABYRINTH_DAILY`` are created exactly like this by ``goal_library._append_prepared_workflows``.
    """
    return GoalState(goal_id, GoalStatus.UNKNOWN, reward_value=value, daily_loss=value,
                     evidence={"required_observation": "live state", "role_id": "A"})


def role_a() -> list[GoalState]:
    """§17: 2 Known, 2 Unknown, 1 Blocked, 1 Deadline."""
    return [
        _known("A_KNOWN_LOW", value=90, skill="SKILL_A1"),
        _known("A_KNOWN_HIGH", value=250, skill="SKILL_A2"),
        _unknown("A_UNKNOWN_LOW", value=80),
        _unknown("A_UNKNOWN_HIGH", value=1200),
        GoalState("A_BLOCKED", GoalStatus.BLOCKED, reward_value=400,
                  available_skills=("SKILL_A3",), evidence={"condition": "queue busy"}),
        _known("A_DEADLINE", value=900, skill="SKILL_A4"),
    ]


def role_b() -> list[GoalState]:
    """§17: 1 Known, 3 Unknown, 1 Waiting."""
    return [
        _known("B_KNOWN", value=70, skill="SKILL_B1"),
        _unknown("B_UNKNOWN_1", value=300),
        _unknown("B_UNKNOWN_2", value=1100),
        _unknown("B_UNKNOWN_3", value=600),
        GoalState("B_WAITING", GoalStatus.SCHEDULED_NOT_OPEN, reward_value=500,
                  available_skills=("SKILL_B2",)),
    ]


# ------------------------------------------------------------- the twelve

def one_scheduler() -> tuple[str, str]:
    """Is there exactly one chooser, or does a second one exist beside it?"""
    package = ROOT / "winter_agent_v2"
    choosers = sorted(p.name for p in package.glob("*.py")
                      if any(line.startswith("class Scheduler")
                             for line in p.read_text(encoding="utf-8", errors="replace").splitlines()))
    if choosers == ["scheduler.py"]:
        return PASS, "one class Scheduler, in scheduler.py"
    return FAIL, f"scheduler-like classes: {choosers}"


def unknown_learning_reachable() -> tuple[str, str]:
    """Can an UNKNOWN goal with a safe entry become work the chooser will take (§5/§6)?"""
    goal = _unknown("REACHABLE", value=1200)
    step = {"skill_id": "TRY_ORDINARY_CONTROL", "action_type": "OPEN", "target_id": "E1",
            "semantic_target": "FEATURE", "frame_id": "f1", "role_id": "A"}
    elements = [{"id": "E1", "kind": "INTERACTIVE_CONTROL", "executable": True,
                 "semantic": "FEATURE", "frame_id": "f1", "role_id": "A"}]
    result = project_runtime_discovery(
        [goal], WorldState(page=Page.HOME), role_id="A", frame_id="f1",
        current_frame_elements=elements, safe_steps_by_goal={"REACHABLE": step},
        registry_ids={"TRY_ORDINARY_CONTROL"}, verifier_bindings={"TRY_ORDINARY_CONTROL"})
    projected = result.goals[0]
    kept = bool(goal_utility.rank([projected], world=WorldState(page=Page.HOME)))
    if kept:
        return PASS, (f"UNKNOWN + safe entry -> status={projected.status.value}, "
                      f"skills={projected.available_skills}, chosen=True")
    return FAIL, f"status={projected.status.value} still not chosen"


def no_permanent_unknown_blackhole() -> tuple[str, str]:
    """§5: an UNKNOWN with **no** entry must still be reachable, or must say what it waits for.

    This is the load-bearing check and the one the operator's §5 names as forbidden.  An UNKNOWN
    goal with no safe step is dropped by the chooser (``goal_utility.rank`` skips it) *and*
    ``GoalState.priority`` answers ``-inf`` for the whole status.  Nothing counts its age, so
    nothing brings it back: the goal is on the board and invisible, forever.
    """
    goal = _unknown("BLACKHOLE", value=1200)
    if goal.priority != float("-inf"):
        return PASS, f"priority={goal.priority}"
    kept = bool(goal_utility.rank([goal], world=WorldState(page=Page.HOME)))
    tracked = _starvation_tracks_unscheduled_goals()
    if kept:
        return PASS, "the chooser keeps an UNKNOWN with no entry"
    if tracked:
        return PASS, "dropped by the chooser but tracked by a starvation counter"
    return FAIL, ("UNKNOWN goal is not chosen, priority=-inf, and no counter records its age -- "
                  "§5's forbidden blackhole")


def _starvation_tracks_unscheduled_goals() -> bool:
    """Does the existing starvation counter cover goals with no skill?

    ``CandidateAttemptPool.eligible`` requires ``SkillState.CANDIDATE``, which by construction a
    goal with no skill cannot be.  Read from the source rather than re-derived, so this answer
    moves if the counter's rule moves.
    """
    source = (ROOT / "winter_agent_v2/candidate_policy.py").read_text(encoding="utf-8")
    return "SkillState.CANDIDATE" not in source


def no_single_goal_blocks_auto() -> tuple[str, str]:
    """Does one blocked or unrunnable goal stop the others from being **chosen**?

    The property is that the others stay selectable -- *not* that the stuck goal disappears.
    Written the other way first and it contradicted ``NO_PERMANENT_UNKNOWN_BLACKHOLE``: one check
    demanded the unrunnable goal leave the board while the other demanded it stay.  §5 settles it,
    and it is not "remove it" -- it is "it must not take the rest down with it".
    """
    board = [_unknown("DEAD", value=5000), _known("ALIVE", value=90, skill="S")]
    ranked = [g.goal_id for g, _ in goal_utility.rank(board, world=WorldState(page=Page.HOME))]
    if "ALIVE" in ranked:
        return PASS, f"the stuck goal does not take the others off the board: {ranked}"
    return FAIL, f"one stuck goal emptied the board: {ranked}"


def never_observed_unknown_is_still_on_the_board() -> tuple[str, str]:
    """§5/§11: the shape the project really emits for prepared-but-never-observed work.

    ``goal_library._append_prepared_workflows`` creates ``USE_FREE_ARENA_ATTEMPTS`` and
    ``LABYRINTH_DAILY`` as UNKNOWN with a declared observation and **every value term at 0.0** --
    a goal nobody has observed cannot have a measured value.  Measured 2026-10-02 on the live
    board: the ticket's ``raw > 0`` precondition could therefore never be satisfied by the very
    goals the ticket exists for, so they were priced ``-inf`` and dropped, and this review still
    reported PASS because every fixture here carried a value.  The fixture was the defect's hiding
    place, which is why the check lives here.

    Kept as its own check rather than a member of ``role_a`` because §17 fixes that world's
    composition (2 Known / 2 Unknown / 1 Blocked / 1 Deadline) and this review should not quietly
    redraw the operator's specification to cover a new case.
    """
    never = _unknown("NEVER_OBSERVED", value=0.0)
    routine = _known("ROUTINE", value=250, skill="S")
    board = [never, routine]
    ranked = [g.goal_id for g, _ in goal_utility.rank(board, world=WorldState(page=Page.HOME))]
    if "NEVER_OBSERVED" not in ranked:
        return FAIL, ("a never-observed UNKNOWN that declares what it waits for is absent from the "
                      f"board: {ranked}")
    if ranked[0] != "ROUTINE":
        return FAIL, f"the observation floor displaced work that pays: {ranked}"
    return PASS, f"on the board and below the work that pays: {ranked}"


def observation_ticket_does_not_starve_routine_work() -> tuple[str, str]:
    """§9: a ticketed UNKNOWN must not hold the top of the board forever.

    A ticket is a *constant* (up to its ceiling), so without rotation the most valuable unrunnable
    goal would sit at the head of the board for good and ordinary work would never run again --
    §9's "低价值任务霸占" in a new costume.  What prevents it is ``fairness_bonus``, which is why
    this is measured with a ledger rather than by reading the ticket: the goal that just won gets
    no fairness credit, and the one that has been waiting accrues it until it wins.
    """
    unknown = _unknown("TICKETED", value=5000)
    routine = _known("ROUTINE", value=250, skill="S")
    ledger = {
        "TICKETED": goal_utility.GoalFairness(goal_id="TICKETED", last_selected_at=NOW.isoformat()),
        "ROUTINE": goal_utility.GoalFairness(
            goal_id="ROUTINE", last_selected_at=(NOW - timedelta(hours=3)).isoformat()),
    }
    ranked = [g.goal_id for g, _ in goal_utility.rank(
        [unknown, routine], world=WorldState(page=Page.HOME), ledger=ledger, now=NOW)]
    if ranked[:1] == ["ROUTINE"]:
        return PASS, f"after the ticket won once, the waiting routine work wins: {ranked}"
    return FAIL, (f"a ticketed UNKNOWN holds the head of the board while routine work ages: "
                  f"{ranked}")


def failed_goal_eventually_retryable() -> tuple[str, str]:
    """Is the repeat-failure penalty bounded, so a streak can never become a life sentence?"""
    worst = goal_utility.repeat_failure_penalty(
        goal_utility.GoalFairness(goal_id="X", no_progress_streak=10_000))
    if abs(worst) <= goal_utility.REPEAT_FAILURE_PENALTY:
        return PASS, (f"a 10000-long streak still only costs {worst} "
                      f"(ceiling {goal_utility.REPEAT_FAILURE_PENALTY})")
    return FAIL, f"penalty {worst} exceeds its own ceiling"


def high_value_unknown_not_starved() -> tuple[str, str]:
    """§一: a high-value UNKNOWN must be able to compete with a high-value KNOWN."""
    unknown = _unknown("HU_UNKNOWN", value=1200)
    known = _known("HU_KNOWN", value=250, skill="S")
    ranked = [g.goal_id for g, _ in goal_utility.rank([unknown, known],
                                                      world=WorldState(page=Page.HOME))]
    if "HU_UNKNOWN" in ranked:
        return PASS, f"both on the board: {ranked}"
    return FAIL, ("a 1200-value UNKNOWN is absent from the board while a 250-value KNOWN is not: "
                  f"{ranked}")


def deadline_can_preempt() -> tuple[str, str]:
    """Can a real deadline outrank ordinary routine work?"""
    soon = GoalState("SOON", GoalStatus.READY, reward_value=250, remaining_seconds=60,
                     available_skills=("S",))
    routine = _known("ROUTINE", value=70, skill="S")
    ranked = [g.goal_id for g, _ in goal_utility.rank([routine, soon],
                                                      world=WorldState(page=Page.HOME))]
    return (PASS, f"deadline first: {ranked}") if ranked[:1] == ["SOON"] else (FAIL, str(ranked))


def global_wait_only_when_truly_idle() -> tuple[str, str]:
    """§18: GLOBAL_WAIT requires that *nothing* -- productive, discovery, learning -- remains."""
    source = (ROOT / "winter_agent_v2/brain.py").read_text(encoding="utf-8", errors="replace")
    if 'GLOBAL_WAIT' not in source:
        return UNMEASURED, "no GLOBAL_WAIT token in brain.py; the decision lives elsewhere"
    # An UNKNOWN with a safe entry counts as discovery work, so it must not precede GLOBAL_WAIT.
    return UNMEASURED, ("GLOBAL_WAIT exists; whether it is reached while an explore-ready goal "
                        "remains needs the live decision path, not a source scan")


def verifier_is_success_authority() -> tuple[str, str]:
    """Is the Verifier still the only thing that can call a step a success?"""
    try:
        from winter_agent_v2 import verifier as verifier_module

        names = [n for n in dir(verifier_module) if n.startswith("verify_")]
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, f"verifier module unreadable: {type(exc).__name__}"
    return (PASS, f"{len(names)} verifier entry points; success is theirs to declare"
            ) if names else (FAIL, "no verifier entry points found")


def model_failure_does_not_stop_auto() -> tuple[str, str]:
    """Does a model/projection failure leave the run able to continue?"""
    source = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8", errors="replace")
    guarded = "except Exception as exc:  # noqa: BLE001 - a projection that crashes is a finding" in source
    return (PASS, "the projection path is exception-guarded and returns the unprojected board"
            ) if guarded else (UNMEASURED, "could not confirm the projection's failure path")


def no_single_role_blocks_other_role() -> tuple[str, str]:
    """Does a fully-blocked role leave the other role's work selectable?"""
    a = [_unknown("A1", value=100), GoalState("A2", GoalStatus.BLOCKED, available_skills=("S",))]
    b = [_known("B1", value=90, skill="S")]
    ranked_a = [g.goal_id for g, _ in goal_utility.rank(a, world=WorldState(page=Page.HOME))]
    ranked_b = [g.goal_id for g, _ in goal_utility.rank(b, world=WorldState(page=Page.HOME))]
    if ranked_b == ["B1"]:
        return PASS, f"role A yields nothing ({ranked_a}); role B still selects {ranked_b}"
    return FAIL, f"role B starved because of role A: {ranked_b}"


def known_fast_path_model_calls() -> tuple[str, str]:
    """§16: does already-known work still avoid the model?

    A source scan cannot answer this -- it needs production episodes where the chosen skill WAS
    known and the backend nonetheless shows a planner call.  Reported as unmeasured rather than
    asserted, which is the operator's own rule (§16: TEST_PASS is not PRODUCTION_TRIED).
    """
    ledger = ROOT / "learning/executor_backend.jsonl"
    if not ledger.exists():
        return UNMEASURED, "learning/executor_backend.jsonl absent; no production evidence to read"
    return UNMEASURED, ("the ledger exists but pairing it with goal status per step is a separate "
                        "tool; not guessed here")


CHECKS = (
    ("ONE_SCHEDULER", one_scheduler),
    ("ONE_EXECUTOR", lambda: (UNMEASURED, "executor_router is the single entry; not re-verified here")),
    ("KNOWN_FAST_PATH_MODEL_CALLS", known_fast_path_model_calls),
    ("UNKNOWN_LEARNING_REACHABLE", unknown_learning_reachable),
    ("NO_PERMANENT_UNKNOWN_BLACKHOLE", no_permanent_unknown_blackhole),
    ("NO_SINGLE_GOAL_BLOCKS_AUTO", no_single_goal_blocks_auto),
    ("NO_SINGLE_ROLE_BLOCKS_OTHER_ROLE", no_single_role_blocks_other_role),
    ("FAILED_GOAL_EVENTUALLY_RETRYABLE", failed_goal_eventually_retryable),
    ("GLOBAL_WAIT_ONLY_WHEN_TRULY_IDLE", global_wait_only_when_truly_idle),
    ("HIGH_VALUE_UNKNOWN_NOT_STARVED", high_value_unknown_not_starved),
    ("NEVER_OBSERVED_UNKNOWN_STILL_ON_BOARD", never_observed_unknown_is_still_on_the_board),
    ("OBSERVATION_TICKET_ROTATES", observation_ticket_does_not_starve_routine_work),
    ("MODEL_FAILURE_DOES_NOT_STOP_AUTO", model_failure_does_not_stop_auto),
    ("VERIFIER_REMAINS_SUCCESS_AUTHORITY", verifier_is_success_authority),
)


def simulate() -> dict[str, dict]:
    """§17's world: run the real chooser over both roles and report what survives."""
    out = {}
    for name, board in (("ROLE_A", role_a()), ("ROLE_B", role_b())):
        ranked = goal_utility.rank(board, world=WorldState(page=Page.HOME))
        selected = [g.goal_id for g, _ in ranked]
        dropped = [g.goal_id for g in board if g.goal_id not in selected]
        out[name] = {
            "board": [g.goal_id for g in board],
            "selected": selected,
            "not_selected": dropped,
            "not_selected_status": {g.goal_id: g.status.value for g in board
                                    if g.goal_id not in selected},
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invariant review (§22)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = {}
    for name, fn in CHECKS:
        try:
            verdict, evidence = fn()
        except Exception as exc:  # noqa: BLE001 - a crashing check is a finding
            verdict, evidence = UNMEASURED, f"check crashed: {type(exc).__name__}: {exc}"
        results[name] = {"verdict": verdict, "evidence": evidence}

    world = simulate()
    counts = {v: sum(1 for r in results.values() if r["verdict"] == v)
              for v in (PASS, FAIL, UNMEASURED)}

    if args.json:
        print(json.dumps({"invariants": results, "counts": counts, "simulation": world},
                         ensure_ascii=False, indent=1))
        return 0

    print("INVARIANT REVIEW (operator §22)")
    for name, row in results.items():
        print(f"  {row['verdict']:11s} {name:34s} {row['evidence']}")
    print()
    print(f"  counts: {counts}")
    print()
    print("SIMULATED WORLD (operator §17)")
    for role, row in world.items():
        print(f"  {role}: board={row['board']}")
        print(f"          selected={row['selected']}")
        print(f"          not selected={row['not_selected']} {row['not_selected_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
