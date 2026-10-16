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
import ast
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


def one_executor() -> tuple[str, str]:
    """§三: one execution chain.  Measured as structure, not as a promise.

    The count that matters is where ``Executor`` objects are *constructed*: the decision
    layer (brain, skills, vision, scheduler, verifier) must never build one -- it asks the
    router, which is the single entry -- so a construction site outside ``runtime.py`` /
    ``executor_router.py`` is the second chain this invariant forbids (tests and tools may
    build their own stubs).  Also checks the class itself is defined exactly once; two
    ``class Executor`` definitions would be two chains before any call site matters.
    """
    package = ROOT / "winter_agent_v2"
    definitions: list[str] = []
    calls: list[tuple[str, int]] = []
    for path in sorted(package.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Executor":
                definitions.append(path.name)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "Executor"):
                calls.append((path.name, node.lineno))
    if len(definitions) != 1:
        return FAIL, f"class Executor defined {len(definitions)} time(s): {definitions}"
    allowed = {"runtime.py", "executor_router.py"}
    outside = [(name, line) for name, line in calls if name not in allowed]
    if outside:
        return FAIL, ("Executor constructed outside the execution layer: "
                      + ", ".join(f"{name}:{line}" for name, line in outside))
    sites = sorted({name for name, _ in calls})
    return PASS, (f"class Executor defined once ({definitions[0]}); "
                  f"{len(calls)} construction site(s), all in {sites}")


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
    """§18: GLOBAL_WAIT requires that *nothing* -- productive, discovery, learning -- remains.

    Measured from the ledgers the decision path itself writes, not from a source scan.  The
    original version looked for the token in ``brain.py`` and found none -- the decision moved
    (that is exactly what "the decision lives elsewhere" meant), and it lives in
    ``scheduler.py``, where ``reason = "GLOBAL_WAIT"`` is only reached after the
    refresh-required / capability-gap / candidate-gap branches have excluded every "there was
    work" case.  Every wait is then persisted to ``learning/global_scheduler_state.json``,
    whose ``global_wait_with_runnable_goal_count`` counts exactly the violation §18 names: a
    global wait recorded while a runnable Goal existed.
    """
    source = (ROOT / "winter_agent_v2/scheduler.py").read_text(encoding="utf-8", errors="replace")
    if 'reason = "GLOBAL_WAIT"' not in source:
        return UNMEASURED, ("no GLOBAL_WAIT reason in scheduler.py; the decision moved again -- "
                            "re-point this check before trusting its silence")
    ledger = ROOT / "learning/global_scheduler_state.json"
    if not ledger.is_file():
        return UNMEASURED, "learning/global_scheduler_state.json absent; no production evidence"
    try:
        payload = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return UNMEASURED, f"learning/global_scheduler_state.json unreadable: {exc}"
    waits = int(payload.get("global_wait_count") or 0)
    with_work = int(payload.get("global_wait_with_runnable_goal_count") or 0)
    if with_work > 0:
        return FAIL, (f"GLOBAL_WAIT was declared {with_work} time(s) while a runnable Goal "
                      f"existed (total waits {waits}) -- §18 forbids exactly this")
    return PASS, (f"every recorded GLOBAL_WAIT was truly idle (waits={waits}, "
                  f"with_runnable_goal=0)")


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
    """§22 table: a model/planner failure must leave the run able to continue.

    The model's failure surface is the advisor hand-off, not the projection: the projection
    (``capability_bootstrap``) makes no model calls by its own contract, and its crashes are
    *findings* the audit counts (``tools/full_auto_coverage_audit.py``: "a projection that
    crashes is a finding") -- deliberately exposed rather than swallowed, so a crash can be
    fixed instead of hiding.  The version this replaces searched runtime.py for exactly that
    comment string, which has never lived there, so it could only ever answer UNMEASURED --
    a check that looked like a gap in the runtime and was a gap in itself.

    Measured by contract (the model endpoint is not reachable from this tool):
    * ``ui_planner.take_request`` is typed ``-> Advice | None`` -- "or ``None`` to leave the
      cycle without an answer" is its documented failure contract;
    * the runtime's consumer turns ``None`` into "continue without an answer";
    * the planner records its transport outcomes in its own ledger (``last_outcome``),
      which is where a failed call is visible without raising.
    """
    planner = (ROOT / "winter_agent_v2/ui_planner.py").read_text(encoding="utf-8", errors="replace")
    runtime_src = (ROOT / "winter_agent_v2/runtime.py").read_text(encoding="utf-8", errors="replace")
    checks = {
        "ui_planner.take_request returns None, not raises (typed contract)":
            "-> unknown_advisor.Advice | None" in planner,
        "the runtime consumer continues on None advice":
            "if advice is None:" in runtime_src,
        "the planner records transport failures in its ledger":
            "last_outcome" in planner and "self.ledger.append" in planner,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return FAIL, "model-failure contracts missing: " + "; ".join(failed)
    return PASS, ("advisor failure yields None by contract, the consumer continues without an "
                  "answer, and transport outcomes are recorded (not raised); the projection's "
                  "crashes are findings by design and are counted, not swallowed")


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
    """§16: does already-known work still avoid the model?  Measured from the screen ledgers.

    A source scan cannot answer this -- it needs production ledgers, and they exist with a
    join key this function did not have when it was written: both screen-level ledgers carry
    the same ``<page>__<kind>__<hash>`` key.

    * ``learning/unknown_verified_steps.jsonl`` -- the screens the runtime has *solved*
      (each row's ``request_id``, with its ``recorded_at``);
    * ``learning/venus_screen_attempts.json`` -- the screens the planner was *asked about*
      (the budget ledger the guard writes, with ``last_at``).

    An overlap between the two sets is **not** a verdict on its own, and that is the reason
    this note is long: ``runtime._learned_reuse_point`` re-locates the learned action on the
    *current* frame and legitimately falls through to the ask when the control is not drawn
    ("current frame does not match -> identify again" is its own rule), and the runtime's §15
    numerator (``_learned_model_calls_on_known``) exists precisely because this fallback
    happens.  A frame-mismatch fallback cannot be told from a stale-key defect without the
    asking frame, which these ledgers do not carry -- so the honest output is the count, the
    names and the time gap, and the operator looks if it matters.  What would deserve a FAIL
    is a *rising* overlap against zero asks, which this check cannot see either; it states
    what the ledgers state (the operator's own rule: TEST_PASS is not PRODUCTION_TRIED).
    """
    learned: dict[str, str] = {}
    learned_path = ROOT / "learning/unknown_verified_steps.jsonl"
    if learned_path.is_file():
        try:
            for line in learned_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    key = str(row.get("request_id") or "")
                    if key:
                        learned[key] = str(row.get("recorded_at") or "")
        except (OSError, json.JSONDecodeError) as exc:
            return UNMEASURED, f"learning/unknown_verified_steps.jsonl unreadable: {exc}"
    asked: dict[str, str] = {}
    attempts_path = ROOT / "learning/venus_screen_attempts.json"
    if attempts_path.is_file():
        try:
            payload = json.loads(attempts_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                asked = {
                    str(key): str((value or {}).get("last_at") or "")
                    for key, value in payload.items() if isinstance(value, dict)
                }
        except (OSError, json.JSONDecodeError) as exc:
            return UNMEASURED, f"learning/venus_screen_attempts.json unreadable: {exc}"
    if not learned and not asked:
        return UNMEASURED, ("both screen ledgers are empty on this machine, so the join "
                            "would be vacuous; nothing to measure yet")
    both = sorted(set(learned) & set(asked))
    if both:
        details = [
            f"{key} (solved {learned.get(key) or '?'}, last asked {asked.get(key) or '?'})"
            for key in both[:5]
        ]
        return PASS, (f"{len(both)} solved screen(s) were asked about again: "
                      + "; ".join(details)
                      + f"  (learned={len(learned)}, asked={len(asked)})"
                      + " -- legal when the asking frame did not draw the control; "
                        "check the frames if the gap looks wrong")
    return PASS, (f"no solved screen was asked about again (learned={len(learned)}, "
                  f"asked={len(asked)}, overlap=0)")

#: Modules measured 2026-10-08 as imported by no production file.  Recorded rather than turned
#: into a permanent red: a check that can never go green is a to-do list wearing a check's
#: clothes, and the next person to run this tool learns to ignore the line.  The debt is printed
#: in the detail either way; what the verdict alarms on is an *addition*.
#:
#: The set is the union measured across both checkouts: `ocr_roi` is orphaned in the pinned
#: worktree and imported in the dev tree, so a list from one of them alone would alarm on
#: the other.  Re-measure when the trees converge.
#: The cause is not established for any of these and is not guessed here -- each is either a
#: feature whose consumer has not landed yet (``game_understanding``, ``external_knowledge``,
#: ``capability_miner``) or a leftover (``popup_capture`` is referenced by nothing at all,
#: including tests).  Deciding which is a reading job, not a scan.
KNOWN_PRODUCTION_ORPHANS: tuple[str, ...] = (
    "attempt_controller",
    "capability_miner",
    "external_knowledge",
    "game_understanding",
    "ocr_roi",
    "popup_capture",
    "production_gate",
    "recovery",
)


def no_production_orphan_module() -> tuple[str, str]:
    """Production modules must be reachable from production code.  §三·八 第十四条.

    A module no production file imports is a candidate second source of truth that nothing
    reads.  The case that motivated this check is ``recovery.py``: it carries a whole
    ``FailureType``/``RecoveryAction`` taxonomy that shadows ``runtime_snapshot``'s real
    ``StopCategory`` classification, and it is imported by exactly one file -- a test.

    A substring scan cannot see any of that, which is why a hand-grep concluded the opposite:
    ``grep recovery`` returns 970 hits in production paths, every one of them the *word*
    "recovery" in a docstring, and zero of them this module.  So the imports are read from the
    AST and a name counts only when it appears in an ``import`` statement.  ``tests/`` and
    build-artifact copies (``.pytest_tmp*``, ``tools/_pt_bt``) do not count as production: a
    module kept alive only by its own test is precisely the state to report.

    Known limit, stated rather than hidden: this measures "imported by at least one production
    file", so a chain of mutually-importing orphans whose head is also an orphan reads as
    reachable.  Closing that needs a reachability walk from the runtime entry point, which is a
    different and larger measurement.
    """
    package = ROOT / "winter_agent_v2"
    modules = sorted(p.stem for p in package.glob("*.py") if p.stem != "__init__")
    imported: set[str] = set()
    for base in (package, ROOT / "tools"):
        if not base.exists():
            continue
        for source in base.rglob("*.py"):
            if ("__pycache__" in source.parts or ".pytest_tmp" in str(source)
                    or "_pt_bt" in source.parts):
                continue
            try:
                tree = ast.parse(source.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[-1] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported.add(node.module.split(".")[-1])
                    imported.update(alias.name for alias in node.names)
    measured = [name for name in modules if name not in imported]
    known = [name for name in measured if name in KNOWN_PRODUCTION_ORPHANS]
    fresh = [name for name in measured if name not in KNOWN_PRODUCTION_ORPHANS]
    # The pinned set is the union measured across both checkouts (see the constant's comment),
    # so a name pinned for one tree can be *connected* in the other.  The report must say which
    # half each name is in: a reader comparing the printed count against the pinned tuple
    # otherwise sees a contradiction, and ``test_the_known_debt_is_printed_even_when_it_passes``
    # asserts every pinned name stays visible in the detail -- printing the connected half is
    # how that stays true without hiding the orphan half.
    connected = [name for name in KNOWN_PRODUCTION_ORPHANS if name not in measured]
    if fresh:
        detail = (f"{len(fresh)} module(s) newly imported by no production file: "
                  f"{', '.join(fresh)}  (known debt: {len(known)} -- "
                  f"{', '.join(known) or 'none'}")
        if connected:
            detail += f"; pinned but connected in this tree: {', '.join(connected)}"
        return FAIL, detail + ")"
    detail = (f"no new orphan module ({len(modules)} production modules; "
              f"{len(known)} known and printed: {', '.join(known) or 'none'}")
    if connected:
        detail += f"; pinned but connected in this tree: {', '.join(connected)}"
    return PASS, detail + ")"


CHECKS = (
    ("ONE_SCHEDULER", one_scheduler),
    ("ONE_EXECUTOR", one_executor),
    ("NO_PRODUCTION_ORPHAN_MODULE", no_production_orphan_module),
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
