"""One command for everything the learning loop produces.

Operator directive 2026-10-01.  The runtime files verified steps and answers questions as it goes;
this is the operator's side of the same loop, and it is deliberately **read-mostly**: three of its
four actions only summarise what the runtime already recorded, and the one that writes
(``--compile``) writes candidate skills, never the registry.

    python tools/learning_report.py                # the console block, plus a refresh of the file
    python tools/learning_report.py --funnel       # same, explicit
    python tools/learning_report.py --compile      # fold verified steps into candidate skills
    python tools/learning_report.py --offline      # group the day's unread frames (never touches a device)
    python tools/learning_report.py --funnel --json

Exit status is 0 even when the funnel reports nothing: an empty funnel is a measurement, not a
failure, and a tool that failed on it would be run less often for no reason.  The one exception is
a missing project root, which is a real error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import learning_funnel, offline_learning, unknown_learning  # noqa: E402


def _episodes(root: Path, limit: int = 20000) -> list[dict]:
    """The tail of the episode stream, for the offline pass's failure frames.

    Bounded because the file grows without limit in production and this pass is about today's
    pile, not about replaying the project's whole history.
    """
    path = root / learning_funnel.EPISODES
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _run_compile(root: Path) -> int:
    ledger = unknown_learning.VerifiedStepLedger(
        root / unknown_learning.LEARNED_STEPS_PATH
    )
    rows = ledger.verified()
    compiled = unknown_learning.compile_candidate_skills(
        rows, out_dir=root / unknown_learning.CANDIDATE_SKILL_DIR
    )
    stats = unknown_learning.LearningStats.load(
        ledger=ledger, skill_dir=root / unknown_learning.CANDIDATE_SKILL_DIR
    )
    print(f"verified steps on file : {len(rows)}  (distinct {stats.distinct_steps})")
    print(f"candidate skills       : {stats.candidate_skills} "
          f"(strengthened {stats.strengthened_skills})")
    print(f"risk routes            : fast {stats.fast_route_skills} / "
          f"slow {stats.slow_route_skills} / blocked {stats.blocked_skills}")
    for record in compiled:
        print(f"  {record.skill_id}  [{record.risk_route}]  {record.semantic_goal}")
    if not compiled:
        print("  (nothing compiled yet -- a skill needs either 2 contiguous verified steps in "
              "one session, or 1 step verified in 2 different sessions)")
    return 0


def _run_offline(root: Path) -> int:
    summary = offline_learning.run_offline_pass(
        root=root, episodes=_episodes(root), write=True
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(ROOT), help="project root (default: this repo)")
    parser.add_argument("--funnel", action="store_true", help="build and print the learning funnel")
    parser.add_argument("--compile", action="store_true", help="compile candidate skills")
    parser.add_argument("--offline", action="store_true", help="group the unread frames")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--days", type=int, default=1, help="window for the console numbers")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / "winter_agent_v2").exists():
        print(f"not a Winter Agent OS project root: {root}", file=sys.stderr)
        return 2

    if args.compile:
        return _run_compile(root)
    if args.offline:
        return _run_offline(root)

    funnel = learning_funnel.refresh(root=root, window_days=max(1, args.days))
    if args.json:
        print(json.dumps(funnel.to_row(), ensure_ascii=False, indent=1))
    else:
        print(learning_funnel.render_console(funnel))
        print()
        print(f"已写入 {root / 'learning' / 'learning_funnel.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
