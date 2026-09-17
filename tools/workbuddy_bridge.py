"""Command-line face of the V2 -> WorkBuddy escalation bridge.

Why a command and not just an importable class: every capability in this project
is expected to be runnable and re-verifiable by hand, and an escalation is the
one path whose *transport* must be provable without a device.  ``--check`` is
the connectivity probe the operator asked for, and it is also the thing that
tells the truth when an escalation silently stopped working.

    python tools/workbuddy_bridge.py --check
    python tools/workbuddy_bridge.py --prompt CAPABILITY_MISSING BUILDING_UPGRADE
    python tools/workbuddy_bridge.py --submit CAPABILITY_MISSING BUILDING_UPGRADE \\
        --failure "no route opens Page.BUILDING" --goal KEEP_BUILDING_PRODUCTIVE
    python tools/workbuddy_bridge.py --status <job-id>
    python tools/workbuddy_bridge.py --cancel <job-id>

The password is read from ``CODEBUDDY_GATEWAY_PASSWORD`` and is never accepted as
an argument, so it cannot end up in a shell history or a process listing.  Start
the gateway with the same variable set::

    CODEBUDDY_GATEWAY_PASSWORD=... codebuddy --serve --port 8080

``--check`` also reports whether anything is actually listening, so a missing
gateway reads as ``GATEWAY_UNREACHABLE`` instead of a stack trace.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.workbuddy_bridge import (  # noqa: E402
    ESCALATION_CONDITIONS,
    EscalationRefused,
    GatewayUnavailable,
    WorkBuddyBridge,
    build_prompt,
    escalation_request_from_project,
    gateway_base_url,
    gateway_password,
    is_escalation_condition,
)

EXIT_OK = 0
EXIT_UNAVAILABLE = 1
EXIT_REFUSED = 2
EXIT_FAILED = 3


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def cmd_check(bridge: WorkBuddyBridge) -> int:
    availability = bridge.is_available()
    _emit("=" * 70)
    _emit("WORKBUDDY GATEWAY CHECK")
    _emit("=" * 70)
    _emit(f"base url      : {gateway_base_url()}")
    _emit(f"credential    : {'set via ' + 'CODEBUDDY_GATEWAY_PASSWORD' if gateway_password() else 'MISSING'}")
    _emit(f"cwd (fixed)   : {bridge.cwd}")
    _emit(f"permission    : {bridge.permission_mode}")
    _emit(f"bg isolation  : {bridge.bg_isolation}")
    _emit("")
    _emit(availability.describe())
    _emit("")
    if availability:
        _emit("VERDICT: gateway is available; submit/status/cancel may be used.")
        return EXIT_OK
    _emit("VERDICT: escalation is NOT possible right now.  V2 keeps working")
    _emit("         locally; this is not a reason to stop the loop.")
    return EXIT_UNAVAILABLE


def _context_from_args(args: argparse.Namespace):
    return escalation_request_from_project(
        capability=args.capability,
        condition=args.condition,
        failure_reason=args.failure or "(not stated)",
        goal=args.goal or "",
        skill=args.skill or "",
        reuse_check=_read_optional(args.reuse_check),
        external_prior=_read_optional(args.external_prior),
        notes=args.notes or "",
        timebox_minutes=args.timebox,
    )


def _read_optional(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return f"(could not read {path}: {exc})"


def cmd_prompt(args: argparse.Namespace) -> int:
    context = _context_from_args(args)
    try:
        _emit(build_prompt(context))
    except EscalationRefused as exc:
        _emit(f"REFUSED: {exc}")
        return EXIT_REFUSED
    return EXIT_OK


def cmd_submit(bridge: WorkBuddyBridge, args: argparse.Namespace) -> int:
    if not is_escalation_condition(args.condition):
        _emit(f"REFUSED: {args.condition!r} is not an escalation condition.")
        _emit("allowed: " + ", ".join(ESCALATION_CONDITIONS))
        return EXIT_REFUSED
    availability = bridge.is_available()
    if not availability:
        _emit(availability.describe())
        return EXIT_UNAVAILABLE
    context = _context_from_args(args)
    try:
        submission = bridge.submit(context)
    except (EscalationRefused, GatewayUnavailable) as exc:
        _emit(f"SUBMIT FAILED: {exc}")
        return EXIT_FAILED
    _emit(f"submitted job : {submission.job_id}")
    _emit(f"state         : {submission.state}")
    _emit(f"cwd           : {submission.cwd}")
    _emit(f"poll with     : python tools/workbuddy_bridge.py --status {submission.job_id}")
    return EXIT_OK


def cmd_status(bridge: WorkBuddyBridge, args: argparse.Namespace) -> int:
    try:
        status = bridge.status(args.status_job)
    except GatewayUnavailable as exc:
        _emit(f"STATUS FAILED: {exc}")
        return EXIT_FAILED
    _emit(status.describe())
    if status.raw:
        _emit("")
        _emit("raw job:")
        _emit(json.dumps(dict(status.raw), ensure_ascii=False, indent=2))
    return EXIT_OK if status.terminal else EXIT_UNAVAILABLE


def cmd_cancel(bridge: WorkBuddyBridge, args: argparse.Namespace) -> int:
    try:
        bridge.cancel(args.cancel_job)
    except GatewayUnavailable as exc:
        _emit(f"CANCEL FAILED: {exc}")
        return EXIT_FAILED
    _emit(f"stopped job   : {args.cancel_job}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="probe the local gateway (is_available)")
    parser.add_argument("--prompt", metavar="CONDITION", nargs="?",
                        help="print the task prompt without sending it")
    parser.add_argument("--submit", metavar="CONDITION", nargs="?",
                        help="dispatch one escalation job")
    # ``dest`` is explicit on purpose.  These two options take the job id as their
    # value, so the default dest is the option name -- and reading ``args.job_id``
    # raised AttributeError the first time this was driven live.  A CLI wiring
    # mistake like that survives every unit test and only shows up on a real run.
    parser.add_argument("--status", dest="status_job", metavar="JOB_ID",
                        help="read one job back")
    parser.add_argument("--cancel", dest="cancel_job", metavar="JOB_ID",
                        help="stop one job")
    parser.add_argument("--capability", default="", help="capability id, e.g. BUILDING_UPGRADE")
    parser.add_argument("--failure", default="", help="why V2 is stuck, in one sentence")
    parser.add_argument("--goal", default="", help="V2 goal that wanted this")
    parser.add_argument("--skill", default="", help="skill V2 tried to dispatch")
    parser.add_argument("--reuse-check", default="", help="path to a saved Reuse Check output")
    parser.add_argument("--external-prior", default="", help="path to the external prior card/text")
    parser.add_argument("--notes", default="", help="anything else V2 wants the agent to know")
    parser.add_argument("--timebox", type=int, default=45, help="budget in minutes")
    parser.add_argument("--base-url", default=None, help="override the gateway URL")
    args = parser.parse_args(argv)

    bridge = WorkBuddyBridge(base_url=args.base_url) if args.base_url else WorkBuddyBridge()

    if args.check:
        return cmd_check(bridge)
    if args.status_job:
        return cmd_status(bridge, args)
    if args.cancel_job:
        return cmd_cancel(bridge, args)

    # ``--prompt`` / ``--submit`` both take the condition; argparse cannot bind a
    # second positional, so the capability comes from --capability.
    selected = args.prompt or args.submit
    if selected:
        if not args.capability:
            _emit("--capability is required with --prompt/--submit")
            return EXIT_REFUSED
        args.condition = selected
        if args.prompt:
            return cmd_prompt(args)
        return cmd_submit(bridge, args)

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
