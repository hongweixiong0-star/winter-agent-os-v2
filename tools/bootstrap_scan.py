"""Capability Bootstrap / Preload — scan the catalog, brief the missing, dispatch one.

Why this exists
---------------
Read `winter_agent_v2/capability_bootstrap.py` for the mechanism.  This is its
command line, and it answers three questions the operator asked by name:

    python tools/bootstrap_scan.py --status      what would be preloaded, and why not
    python tools/bootstrap_scan.py --top 20      the ranked candidates, with briefs
    python tools/bootstrap_scan.py --write       write the report under learning/
    python tools/bootstrap_scan.py --preload-once  one real pass (gate decides)

Two things it will never do: touch the device, and promote anything to
LIVE_VERIFIED.  A preload prepares a capability; only a production episode with a
passing verifier, recorded after the job, does the promoting.

Read-only except for ``--write`` / ``--preload-once``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2 import capability_bootstrap as bootstrap  # noqa: E402
from winter_agent_v2.capability_bootstrap import (  # noqa: E402
    BOOTSTRAP_MAX_LIFECYCLE,
    CLASS_ZH,
    PRIORITY_ZH,
    SOURCE_ZH,
    BootstrapScanner,
)


def _arm_block(root: Path) -> list[str]:
    armed, reason, detail = bootstrap.arm_state(root)
    return [
        "MECHANISM",
        f"  armed        : {armed}  ({reason})",
        f"  detail       : {detail}",
        f"  ceiling      : {BOOTSTRAP_MAX_LIFECYCLE} -- never "
        f"{', '.join(bootstrap.FORBIDDEN_LIFECYCLES)}",
        "  when it runs : background, low priority; refused while a real gap is owed, "
        "while an agent holds the single slot, while a validation owns the device, "
        "or while V2 is in a REALTIME activity",
        "",
    ]


def _gate_block(root: Path, scanner: BootstrapScanner) -> list[str]:
    """The gate as it would decide *right now*, with the four inputs named."""
    from winter_agent_v2.escalation_queue import EscalationLedger, EscalationPolicy, fold

    ledger = EscalationLedger(root / "learning/workbuddy_escalations.jsonl")
    snapshot = fold(ledger.events())
    policy = EscalationPolicy()
    armed, arm_reason, arm_detail = bootstrap.arm_state(root)
    holder = ""
    try:
        from winter_agent_v2.device_lease import DeviceLease

        record = DeviceLease(root).holder()
        holder = str(getattr(record, "owner", "") or "") if record is not None else ""
    except Exception:  # noqa: BLE001
        holder = ""
    runtime = {}
    try:
        runtime = json.loads((root / "learning/runtime_snapshot.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        runtime = {}
    active = snapshot.active_jobs()
    pending = [r for r in snapshot.records.values()
               if r.state in ("NEW", "QUEUED")
               and r.condition in ("CAPABILITY_MISSING", "UNKNOWN_UI", "UNKNOWN_GAME_MECHANIC",
                                   "REPEATED_LIVE_FAILURE", "STUCK_15_MIN")]
    gate = bootstrap.preload_gate(
        armed=armed, arm_reason=arm_reason, arm_detail=arm_detail,
        active_jobs=len(active), pending_records=len(pending),
        lease_holder=holder, runtime=runtime, actionable=len(scanner.candidates()),
    )
    return [
        "GATE (would a preload dispatch right now?)",
        f"  allowed      : {gate.allowed}",
        f"  reason       : {gate.reason}  --  {bootstrap.GATE_ZH.get(gate.reason, '')}",
        f"  detail       : {gate.detail or '-'}",
        f"  inputs       : active_jobs={len(active)} pending={len(pending)} "
        f"lease={holder or 'idle'} runtime_goal={runtime.get('current_goal') or '-'}",
        "",
    ]


def _candidate_lines(scanner: BootstrapScanner, top: int, *, briefs: bool) -> list[str]:
    lines = [
        f"TOP {top} PRELOAD CANDIDATES",
        "  order = the operator's priority ladder, then how cheap the preload is "
        "(knowledge rung), then how much it unblocks",
        "",
        f"  {'cap':<9} {'code':<30} {'priority':<22} {'state':<16} {'src':<16} score",
    ]
    for plan in scanner.candidates()[:top]:
        lines.append(
            f"  {plan.capability_id:<9} {plan.code:<30} {plan.priority:<22} "
            f"{plan.plan_state:<16} {plan.knowledge_source:<16} {plan.score:6.1f}"
        )
        if briefs:
            lines.append(
                f"      {PRIORITY_ZH.get(plan.priority, '')} / "
                f"{SOURCE_ZH.get(plan.knowledge_source, '')}"
            )
            lines.append(
                f"      classes: {', '.join(CLASS_ZH.get(c, c) for c in plan.classes)}"
                f"   risk={plan.risk}  unknown={plan.unknown_fields or '-'}"
            )
            if plan.external:
                lines.append(
                    f"      external prior: {plan.external.get('capability')} "
                    f"[{plan.external.get('repo')}] reuse={plan.external.get('reuse_level')} "
                    f"license={plan.external.get('license')}"
                )
            lines.append(
                f"      targeted test: {plan.targeted_test.get('name')} -> "
                f"{plan.targeted_test.get('verdict')} ({plan.targeted_test.get('detail')})"
            )
    lines.append("")
    return lines


def _inflight_lines(scanner: BootstrapScanner, top: int = 12) -> list[str]:
    refused = [p for p in scanner.plans() if p.in_flight]
    lines = [
        f"REFUSED AS DUPLICATE BOOTSTRAP ({len(refused)} rows)",
        "  WORKING / DEVELOPMENT_PENDING / CANDIDATE / LIVE_VERIFY_PENDING / "
        "LIVE_VERIFIED (+ COOLDOWN / BLOCKED) -- no second agent for these",
        "",
    ]
    for plan in refused[:top]:
        lines.append(
            f"  {plan.capability_id:<9} {plan.code:<30} {plan.in_flight:<22} "
            f"{plan.in_flight_reason[:80]}"
        )
    if len(refused) > top:
        lines.append(f"  ... and {len(refused) - top} more (see the JSON report)")
    lines.append("")
    return lines


def _one_brief(scanner: BootstrapScanner, code: str) -> int:
    wanted = code.strip().upper()
    for plan in scanner.plans():
        if plan.code.upper() == wanted or plan.capability_id.upper() == wanted:
            print(plan.markdown())
            print()
            print(bootstrap.work_order_brief(plan))
            return 0
    print(f"no catalog row matches {code!r}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="mechanism + gate + summary only")
    parser.add_argument("--top", type=int, default=0, help="print the N ranked candidates")
    parser.add_argument("--briefs", action="store_true", help="include brief detail for each candidate")
    parser.add_argument("--capability", default="", help="print one capability's brief (code or id)")
    parser.add_argument("--write", action="store_true", help="write the report under learning/")
    parser.add_argument("--preload-once", action="store_true",
                        help="one real preload pass through the existing queue (the gate decides)")
    parser.add_argument("--cycle", action="store_true",
                        help="run one full knowledge-bootstrap loop pass "
                             "(SCAN -> ... -> SELECT NEXT); dispatches unless --dry-run")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --cycle: do everything except send a job")
    parser.add_argument("--state", action="store_true",
                        help="print the controller's live state (the watchdog's questions)")
    parser.add_argument("--coverage", action="store_true",
                        help="print the five coverages, over the unlocked subset")
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = parser.parse_args()

    scanner = BootstrapScanner.load(ROOT)

    if args.capability:
        return _one_brief(scanner, args.capability)

    # The controller branch runs *before* the report writer and falls through to it, so
    # `--cycle --write` really writes the report the cycle produced.  An earlier version
    # returned early and `--write` was silently ignored -- which is how a stale report
    # survives a code change.
    handled_states = args.state or args.cycle or args.coverage
    if handled_states:
        from winter_agent_v2.capability_bootstrap import KnowledgeBootstrapController

        controller = KnowledgeBootstrapController(ROOT)
        if args.cycle:
            report = controller.cycle(dispatch=not args.dry_run)
            print("KNOWLEDGE BOOTSTRAP CYCLE (one pass of the permanent loop)")
            print(f"  {report.line}")
            for key in ("stage", "selected", "tier", "decision", "note",
                        "missing", "questions", "next_capability", "dispatch"):
                print(f"  {key:<16}: {report.as_row()[key]}")
            print()
        if args.coverage:
            coverage = controller.coverage(scanner)
            print("COVERAGE (denominators printed with the numbers)")
            for scope in ("unlocked", "all"):
                block = coverage[scope]
                print(f"  {scope:<9} total={block['total']:<4} "
                      f"observed={block['observed_percent']}% "
                      f"candidate={block['candidate_percent']}% "
                      f"live_tried={block['live_tried']} ({block['live_tried_percent']}%) "
                      f"LIVE_VERIFIED={block['live_verified']} "
                      f"({block['live_verified_percent']}%)")
            print(f"  knowledge {json.dumps(coverage['knowledge'], ensure_ascii=False)}")
            for key, why in coverage["definitions"].items():
                print(f"    {key}: {why}")
            print()
        if args.state or args.cycle:
            state = controller.state(scanner=scanner)
            path = controller.write_state(scanner=scanner)
            print("CONTROLLER STATE (the watchdog's seven questions)")
            for key in ("controller", "stage", "decision", "learning", "learning_missing",
                        "preloading", "developing", "awaiting_calibration", "knowledge_blocked",
                        "last_preload_at", "last_confirmed_at", "next_capability",
                        "knowledge_records"):
                value = state.get(key)
                if isinstance(value, list):
                    value = ", ".join(str(v) for v in value) or "-"
                print(f"  {key:<20}: {value or '-'}")
            print(f"  written: {path}")
            print()

    if args.write:
        json_path, md_path = bootstrap.write_report(ROOT, scanner, limit=max(args.top, 40))
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")

    if handled_states:
        return 0

    if args.json:
        print(json.dumps(scanner.report(limit=max(args.top, 40)), ensure_ascii=False, indent=1))
        return 0

    report = scanner.report(limit=1)
    summary = report["summary"]
    print("=" * 92)
    print("CAPABILITY BOOTSTRAP / PRELOAD")
    print("=" * 92)
    print()
    for line in _arm_block(ROOT):
        print(line)
    for line in _gate_block(ROOT, scanner):
        print(line)
    print("CATALOG SCAN")
    print(f"  rows         : {summary['catalog_rows']}")
    print(f"  preloadable  : {summary['actionable']}")
    print(f"  in flight    : {summary['in_flight']}  (refused as duplicate bootstrap)")
    print(f"  by priority  : { {PRIORITY_ZH.get(k, k): v for k, v in summary['by_priority'].items()} }")
    print(f"  by state     : {summary['by_plan_state']}")
    print(f"  by class     : { {CLASS_ZH.get(k, k): v for k, v in summary['by_class'].items()} }")
    print(f"  by source    : { {SOURCE_ZH.get(k, k): v for k, v in summary['by_knowledge_source'].items()} }")
    print()

    if args.top:
        for line in _candidate_lines(scanner, args.top, briefs=args.briefs):
            print(line)
    for line in _inflight_lines(scanner):
        print(line)

    if args.preload_once:
        from winter_agent_v2.escalation_queue import EscalationLedger, EscalationQueueAdapter

        adapter = EscalationQueueAdapter(
            root=ROOT, ledger=EscalationLedger(ROOT / "learning/workbuddy_escalations.jsonl")
        )
        observation = adapter.preload()
        print("PRELOAD PASS (one, real, through the existing queue)")
        print(f"  {observation.line}")
        if observation.preloaded:
            print(f"  dispatched for: {', '.join(observation.preloaded)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
