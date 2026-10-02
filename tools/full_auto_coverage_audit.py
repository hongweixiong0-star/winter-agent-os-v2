"""FULL AUTO COVERAGE -- which enabled goals the Scheduler can actually see, and why not.

Operator directive 2026-10-01 (§二十八/§三十/§三十五).  ``goal_discovery_audit.py`` already
answers "can ``discover()`` emit this goal at all".  This tool answers the **next** question,
which nothing measured before it:

    the goal is on the board -- can the Scheduler ever *choose* it?

Those are different facts and the gap between them is where the operator's complaint lives.
``goal_utility.rank`` walks the discovered board and drops any goal with no
``available_skills`` (its line 515), so a goal can be defined, discoverable, priced at 1200,
printed on the panel -- and never once selected, with no record anywhere saying so.  The
operator's §三十.1 names exactly this: "Goal 已存在但 Scheduler 永远不选".

Measured the same way as ``goal_discovery_audit``: by feeding the real ``GoalLibrary`` one
WorldState per domain and asking the **real** ``rank`` what survives.  Nothing here restates
the rules; if the rule changes, this number changes with it.

The per-goal verdicts are the operator's §十八 matrix, limited to the columns that are
measurable from the engine itself.  The rest (VENUS_REACHABLE, VERIFIER_AVAILABLE) are owned
by other ledgers and are deliberately **not guessed here** -- a fabricated "true" is worse
than an honest "not measured".

Read-only: writes nothing, changes nothing.

Usage:
    python tools/full_auto_coverage_audit.py [--json] [--show-blocked]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.goal_discovery_audit import PROBES, defined_goals  # noqa: E402
from winter_agent_v2 import goal_utility  # noqa: E402
from winter_agent_v2.capability_bootstrap import project_runtime_discovery  # noqa: E402
from winter_agent_v2.goal_library import NOT_ACTIONABLE, GoalLibrary  # noqa: E402

GOAL_STATE = ROOT / "learning/goal_state.json"
FAIRNESS = ROOT / "learning/goal_fairness.json"

#: The audit stands on one frame, exactly like the runtime does.  It is deliberately *not* a real
#: role or a real screenshot: what is being measured is the shape of the board, and inventing a
#: role name would only make the numbers look more real than they are.
AUDIT_ROLE = "AUDIT"
AUDIT_FRAME = "audit-frame"


def _verifier_bindings() -> frozenset[str]:
    """The skills that have a production verifier, read from the project's own table.

    Returning an empty set on failure is the safe direction: the audit then reports
    ``MISSING_VERIFIER`` for runnable work, which is a *visible* wrong answer, rather than
    ``READY_EXECUTABLE``, which would be an invisible fabricated one.
    """
    for module_name, attr in (("winter_agent_v2.verifier", "VERIFIED_ATOMIC"),
                              ("winter_agent_v2.runtime", "VERIFIED_ATOMIC")):
        try:
            module = __import__(module_name, fromlist=[attr])
            table = getattr(module, attr)
        except (ImportError, AttributeError):
            continue
        try:
            return frozenset(str(item) for item in table)
        except TypeError:
            return frozenset()
    return frozenset()

#: Verdicts, most-blocked last.  ``SCHEDULER_CANDIDATE`` is the only one that can be worked on
#: right now; ``BOARD_ONLY_NO_SKILL`` is the operator's §五 "missing_skill -> EXPLORATION_CANDIDATE"
#: -- on the board, priced, and invisible to the chooser.
CANDIDATE = "SCHEDULER_CANDIDATE"
BOARD_ONLY_NO_SKILL = "BOARD_ONLY_NO_SKILL"
BOARD_ONLY_STATUS = "BOARD_ONLY_STATUS"
ORDER = (CANDIDATE, BOARD_ONLY_STATUS, BOARD_ONLY_NO_SKILL)

#: The reason vocabulary.  Taken from the chooser's own terms, not from the status.
#:
#: A goal's ``priority`` is a *property* that answers ``-inf`` for every non-actionable status, so
#: on 2026-10-02 it read ``-inf`` for 26 of the 33 live rows and could not tell any two of them
#: apart -- including the three the chooser really does carry, priced as observation work at
#: ``goal_utility.OBSERVATION_TICKET_FLOOR``.  Operator §二十八 asks that an unknown goal not be
#: dressed up and that a stated one say why; one number for 26 different facts is the opposite of
#: that, and the number was not measured -- ``goal_utility.utility``'s own docstring says the static
#: priority "is the base and is never recomputed here".
CHOOSER_REASONS = frozenset({
    "ON_BOARD_SKILL_REGISTERED",
    "ON_BOARD_OBSERVATION_ONLY_NO_SKILL",
    "ON_BOARD_NO_REGISTERED_SKILL",
    "OFF_BOARD_DECLARED_OBSERVATION_BUT_UNPRICED",
    "OFF_BOARD_NOTHING_DECLARED",
    "OFF_BOARD_NO_REGISTERED_SKILL",
})


def chooser_reason(*, kept: bool, skills, registered, observation: float) -> str:
    """Why the chooser carries this goal, or does not -- in the chooser's own terms.

    ``kept`` is the answer from ``goal_utility.rank``, and ``observation`` is the ticket that
    ``goal_utility.utility`` used when the catalogue price was ``-inf``.  Nothing here restates the
    status: a goal can be ``UNKNOWN`` and on the board, which is the whole point of the ticket.
    """
    has_registered = any(str(skill) in registered for skill in skills)
    if kept:
        if has_registered:
            return "ON_BOARD_SKILL_REGISTERED"
        if observation > 0:
            return "ON_BOARD_OBSERVATION_ONLY_NO_SKILL"
        return "ON_BOARD_NO_REGISTERED_SKILL"
    if observation > 0:
        # A goal that declared what it waits for is priced by the ticket, so these two cannot both
        # hold.  If they ever do, the ticket stopped reaching rank() and that is the finding.
        return "OFF_BOARD_DECLARED_OBSERVATION_BUT_UNPRICED"
    if not skills:
        return "OFF_BOARD_NOTHING_DECLARED"
    return "OFF_BOARD_NO_REGISTERED_SKILL"


def _status_name(goal) -> str:
    status = getattr(goal, "status", "")
    return str(getattr(status, "value", status) or "")


def survey() -> tuple[dict[str, dict], Counter]:
    """Probe the real library, project it like the runtime does, and ask the real rank.

    The projection step is not optional and this tool measured the wrong thing without it.
    ``GoalLibrary.discover`` alone is the *raw board*; the runtime replaces part of it with safe
    same-goal discovery candidates before anything is chosen (``runtime._project_capability_discovery``).
    Auditing the raw board reported ``BOARD_ONLY_NO_SKILL: 0`` while the operator was seeing goals
    that never run -- because the raw board is not what the Scheduler sees.

    ``safe_steps_by_goal`` is passed **empty on purpose**.  That is the honest worst case and the
    case the operator's §十二 is about: the goal is known, the page is not, and no candidate step
    exists because nothing has ever located an entry control for it on the current frame.  A goal
    that survives *this* is auto-discoverable with no prior knowledge at all.
    """
    library = GoalLibrary()
    registered = frozenset()
    try:
        from winter_agent_v2 import skills as skills_module

        registered = frozenset(str(skill.id) for skill in skills_module.v2_registry().all())
    except Exception:  # noqa: BLE001 - an unreadable registry must not stop the audit
        pass
    verifiers = _verifier_bindings()

    seen: dict[str, dict] = {}
    diagnostics: Counter = Counter()
    for label, world in PROBES:
        try:
            goals = library.discover(world)
        except Exception as exc:  # noqa: BLE001 - a crashing probe is a finding, not a stop
            seen.setdefault(f"<probe crashed: {type(exc).__name__}>",
                            {"verdict": "PROBE_CRASHED", "probes": []})["probes"].append(label)
            continue
        projected = goals
        try:
            result = project_runtime_discovery(
                goals, world, role_id=AUDIT_ROLE, frame_id=AUDIT_FRAME,
                current_frame_elements={"frame_id": AUDIT_FRAME, "role_id": AUDIT_ROLE,
                                        "elements": []},
                safe_steps_by_goal={}, registry_ids=registered, verifier_bindings=verifiers,
            )
            projected = list(result.goals)
            for row in result.diagnostics:
                diagnostics[str(row.get("reason") or "?")] += 1
        except Exception as exc:  # noqa: BLE001 - a projection that crashes is a finding
            diagnostics[f"<projection crashed: {type(exc).__name__}>"] += 1

        for goal in projected:
            goal_id = str(goal.goal_id)
            skills = tuple(str(s) for s in (getattr(goal, "available_skills", ()) or ()))
            # What the chooser really did with it, and the number it used.  ``rank`` filters, so a
            # dropped goal has to be priced through ``utility`` to be reportable at all -- and the
            # filtered verdict alone is what left 26 rows sharing one indistinguishable value.
            ranked = goal_utility.rank([goal], world=world)
            kept = bool(ranked)
            breakdown = ranked[0][1] if kept else goal_utility.utility(goal, world=world)
            reason = chooser_reason(kept=kept, skills=skills, registered=registered,
                                    observation=float(breakdown.observation))
            row = seen.setdefault(goal_id, {
                "goal_id": goal_id,
                "probes": [],
                "status": _status_name(goal),
                "priority": float(goal.priority),
                "chooser_base": float(breakdown.base),
                "chooser_total": float(breakdown.total),
                "observation": float(breakdown.observation),
                "reason": reason,
                "skills": list(skills),
                "bootstrap_stage": str((getattr(goal, "evidence", None) or {}).get("bootstrap_stage") or ""),
                "verdict": "",
            })
            row["probes"].append(label)
            # The verdict is the measured one: what does the real chooser do with it?
            if kept:
                verdict = CANDIDATE
            elif getattr(goal, "status", None) in NOT_ACTIONABLE:
                verdict = BOARD_ONLY_STATUS
            elif not skills:
                verdict = BOARD_ONLY_NO_SKILL
            else:
                verdict = BOARD_ONLY_STATUS
            # A goal may exist under several probes; the best verdict wins, because that is
            # what the Scheduler sees on the frame that can actually produce it.
            if not row["verdict"] or ORDER.index(verdict) < ORDER.index(row["verdict"]):
                row["verdict"] = verdict
                row["status"] = _status_name(goal)
                row["priority"] = float(goal.priority)
                row["chooser_base"] = float(breakdown.base)
                row["chooser_total"] = float(breakdown.total)
                row["observation"] = float(breakdown.observation)
                row["reason"] = reason
                row["skills"] = list(skills)
                row["bootstrap_stage"] = str(
                    (getattr(goal, "evidence", None) or {}).get("bootstrap_stage") or "")
    return seen, diagnostics


def fairness_counts() -> tuple[set[str], set[str]]:
    """``(selected_at_least_once, never_selected)`` from the fairness ledger, if readable."""
    try:
        payload = json.loads(FAIRNESS.read_text(encoding="utf-8")).get("goals") or {}
    except (OSError, json.JSONDecodeError):
        return set(), set()
    tried, never = set(), set()
    for goal_id, body in payload.items():
        if int(body.get("selected") or 0) > 0:
            tried.add(str(goal_id))
        else:
            never.add(str(goal_id))
    return tried, never


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full AUTO coverage audit")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--show-blocked", action="store_true",
                        help="list every board-only goal, not just the counts")
    args = parser.parse_args(argv)

    defined = defined_goals()
    rows, diagnostics = survey()
    tried, never = fairness_counts()

    by_verdict: dict[str, list[str]] = {name: [] for name in ORDER}
    for goal_id, row in sorted(rows.items()):
        by_verdict.setdefault(row["verdict"], []).append(goal_id)
    # Per-goal reasons, so "why is this one out" is answerable for each goal rather than
    # answered once for a whole status.  Crash rows carry no reason and are excluded.
    reason_counts: Counter = Counter(
        row["reason"] for goal_id, row in rows.items()
        if not goal_id.startswith("<probe") and "reason" in row
    )

    reachable = set(by_verdict[CANDIDATE])
    auto_discoverable = {g for g in rows if not g.startswith("<probe")}

    kpi = {
        "TOTAL_ENABLED_GOALS": len(defined),
        "AUTO_DISCOVERABLE_GOALS": len(auto_discoverable),
        "KNOWN_EXECUTABLE_GOALS": len(reachable),
        "BOARD_ONLY_NO_SKILL": len(by_verdict[BOARD_ONLY_NO_SKILL]),
        "BOARD_ONLY_STATUS": len(by_verdict[BOARD_ONLY_STATUS]),
        "DYNAMIC_GOALS_PAST_THE_MAP": len(auto_discoverable - set(defined)),
        "NEVER_TRIED_GOALS": len(never),
    }

    report = {
        "kpi": kpi,
        "by_verdict": {k: sorted(v) for k, v in by_verdict.items()},
        "board_only_no_skill": sorted(by_verdict[BOARD_ONLY_NO_SKILL]),
        "board_only_status": sorted(by_verdict[BOARD_ONLY_STATUS]),
        "rows": {k: {"status": v["status"], "priority": round(v["priority"], 1),
                     "chooser_base": round(v["chooser_base"], 1),
                     "chooser_total": round(v["chooser_total"], 1),
                     "observation": round(v["observation"], 1),
                     "reason": v["reason"],
                     "skills": v["skills"], "verdict": v["verdict"], "probes": v["probes"]}
                 for k, v in sorted(rows.items())},
        "reasons": dict(reason_counts),
        "never_selected_in_ledger": sorted(never),
        "selected_before": sorted(tried),
        "bootstrap_diagnostics": dict(diagnostics),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0

    print("FULL AUTO COVERAGE AUDIT")
    for key, value in kpi.items():
        print(f"  {key:28s}: {value}")
    print()
    print("  -- verdicts (what the REAL chooser does) --")
    for name in ORDER:
        print(f"     {name:24s} {len(by_verdict[name])}")
    print()
    print("  -- bootstrap projection reasons (runtime's own vocabulary, worst case: no known entry) --")
    for reason, count in diagnostics.most_common():
        print(f"     {reason:34s} {count}")
    print()
    print(f"  -- BOARD_ONLY_NO_SKILL ({len(by_verdict[BOARD_ONLY_NO_SKILL])}): "
          "on the board, invisible to the chooser -- operator §五 --")
    for goal_id in sorted(by_verdict[BOARD_ONLY_NO_SKILL]):
        row = rows[goal_id]
        print(f"     {goal_id:38s} priority={row['priority']:8.1f} status={row['status']}")
    print()
    if args.show_blocked:
        print(f"  -- BOARD_ONLY_STATUS ({len(by_verdict[BOARD_ONLY_STATUS])}) --")
        counts = Counter(rows[g]["status"] for g in by_verdict[BOARD_ONLY_STATUS])
        for status, n in counts.most_common():
            print(f"     {status:24s} {n}")
        print()
    print(f"  -- SCHEDULER_CANDIDATE ({len(by_verdict[CANDIDATE])}) --")
    for goal_id in sorted(by_verdict[CANDIDATE]):
        row = rows[goal_id]
        print(f"     {goal_id:38s} chooser={row['chooser_total']:8.1f} "
              f"(catalogue {row['priority']:7.1f}) skills={len(row['skills'])} "
              f"{row['reason']}")
    print()
    print("  -- why each goal is where it is (the chooser's own terms) --")
    for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"     {reason:42s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
