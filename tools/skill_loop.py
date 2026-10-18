"""Drive the WorkBuddy skill loop from a console.

    python tools/skill_loop.py status
    python tools/skill_loop.py brief [--no-advance]
    python tools/skill_loop.py verdict --skill DISMISS_GET_MORE_STAMINA
    python tools/skill_loop.py record --skill X --verdict VERIFIED --request <id> --note "..."

What this tool is, and is not
-----------------------------
It is the *plumbing* of the loop: it reads what the runtime wrote, hands the analysing half a
brief that only contains rows it has not seen, and records what was decided.  It does not think:
the generation and the correction are the analysing half's job (WorkBuddy, this session), and the
execution is the runtime's (``Executor`` + MAA + ``Verifier``).

Exit codes matter to a caller that is not a person: 0 = ok, 1 = nothing to do, 2 = usage/IO.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import skill_loop  # noqa: E402


def _cmd_status(_args: argparse.Namespace) -> int:
    print(json.dumps(skill_loop.state(), ensure_ascii=False, indent=2))
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    cursor = skill_loop.load_cursor()
    rows, offset = skill_loop.read_new_episodes(cursor)
    unknowns = skill_loop.read_new_unknowns(cursor)
    if not rows and not unknowns:
        print("nothing new: no episode rows and no UNKNOWN requests since the cursor")
        return 1
    brief = skill_loop.build_brief(rows, unknowns, cursor=cursor)
    path = skill_loop.write_brief(brief)
    print(json.dumps({
        "brief": str(path),
        "counts": brief["counts"],
        "popups_without_named_skill": brief["popups_without_named_skill"],
        "skills_without_verifier_sample": brief["skills_without_verifier"][:10],
        "failures": brief["episodes"]["failures"][:10],
    }, ensure_ascii=False, indent=2))
    if not args.no_advance:
        skill_loop.save_cursor(brief["cursor_after"])
        print(f"cursor advanced: episodes_offset={brief['cursor_after']['episodes_offset']} "
              f"seen_requests={len(brief['cursor_after']['seen_requests'])}")
    return 0


def _cmd_verdict(args: argparse.Namespace) -> int:
    cursor = {"episodes_offset": 0, "seen_requests": []}
    rows, _ = skill_loop.read_new_episodes(cursor)
    verdict = skill_loop.promotion_verdict(args.skill, rows,
                                           min_passes=args.min_passes, window=args.window)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict.get("promote") else 1


def _cmd_record(args: argparse.Namespace) -> int:
    row = skill_loop.record_outcome(
        args.skill, verdict=args.verdict,
        evidence=json.loads(args.evidence) if args.evidence else {},
        request_id=args.request, note=args.note,
    )
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="cursor and what is waiting behind it").set_defaults(func=_cmd_status)

    brief = sub.add_parser("brief", help="read the increment and write a brief")
    brief.add_argument("--no-advance", action="store_true",
                       help="write the brief but leave the cursor so the rows can be re-read")
    brief.set_defaults(func=_cmd_brief)

    verdict = sub.add_parser("verdict", help="is the measured evidence enough to promote a skill")
    verdict.add_argument("--skill", required=True)
    verdict.add_argument("--min-passes", type=int, default=skill_loop.PROMOTION_MIN_PASSES)
    verdict.add_argument("--window", type=int, default=skill_loop.PROMOTION_WINDOW)
    verdict.set_defaults(func=_cmd_verdict)

    record = sub.add_parser("record", help="append one loop decision to outcomes.jsonl")
    record.add_argument("--skill", required=True)
    record.add_argument("--verdict", required=True)
    record.add_argument("--request", default=None)
    record.add_argument("--note", default="")
    record.add_argument("--evidence", default="", help="JSON object describing the run")
    record.set_defaults(func=_cmd_record)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
