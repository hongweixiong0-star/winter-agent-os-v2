"""Do the pending escalation records still describe the running client?  Read-only.

Why this exists
---------------
The Bootstrap preload gate refuses to dispatch while real gaps are pending
(``reason=REAL_GAP_WAITING``), so a record that no longer describes the running tree
holds the background line shut.  A record is a *claim about a route* -- the
``NO_GOAL_PROGRESS`` ones read "<capability>|NO_GOAL_PROGRESS|<skill>: the route is
running but it cannot reach the goal" -- and the production episode stream can
falsify that claim directly: if the goal reported ``goal_progress == True`` on any
episode recorded **after the record was filed**, then some part of it did advance,
and "no part of it advanced" is no longer true of the client on disk.

This audits exactly that, per pending record, and nothing else.

What it deliberately does NOT do
--------------------------------
It does not mutate the queue.  Retiring a record is the operator's call: the queue
has no "superseded/stale" state, and ``tools/escalations.py --correct`` corrects an
*outcome* -- these records are ``NEW`` and have none, so correcting them would be
abusing the channel.  This tool reports; a human decides.

It also does not claim the *specific skill* named in the signature is fixed.  A goal
progressing proves the route can now advance; it does not prove which step advanced.

    python tools/audit_escalation_premises.py
    python tools/audit_escalation_premises.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import EscalationLedger, fold  # noqa: E402

#: The same condition set the Bootstrap gate counts as "a real gap is owed".
GAP_CONDITIONS = (
    "CAPABILITY_MISSING", "UNKNOWN_UI", "UNKNOWN_GAME_MECHANIC",
    "REPEATED_LIVE_FAILURE", "STUCK_15_MIN",
)
PENDING_STATES = ("NEW", "QUEUED")


def _moment(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def scan_stream(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, int], dict[str, int]]:
    """``(progress_by_goal, episodes_by_failure_type, episodes_by_skill)`` in one pass.

    Streamed, because the episode ledger is ~135 MB; a whole-file ``json.loads``
    would put the peak in the hundreds of MB for no reason.  All three answers come
    from the same scan because all three are ranked decisions and splitting them
    across three passes over a 135 MB file would be the expensive kind of tidy.
    """
    progress: dict[str, dict[str, object]] = {}
    failures: dict[str, int] = {}
    skills: dict[str, int] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                episode = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(episode, dict):
                continue
            failure = str(episode.get("failure_type") or "")
            if failure:
                failures[failure] = failures.get(failure, 0) + 1
            skill = str(episode.get("skill") or "")
            if skill:
                skills[skill] = skills.get(skill, 0) + 1
            goal = str(episode.get("goal_id") or "")
            if not goal:
                continue
            row = progress.setdefault(goal, {"n": 0, "advanced": 0, "last_advanced": None})
            row["n"] = int(row["n"]) + 1  # type: ignore[arg-type]
            if episode.get("goal_progress") is True:
                row["advanced"] = int(row["advanced"]) + 1  # type: ignore[arg-type]
                at = _moment(episode.get("recorded_at"))
                if at is not None and (row["last_advanced"] is None or at > row["last_advanced"]):  # type: ignore[operator]
                    row["last_advanced"] = at
    return progress, failures, skills


def audit(root: Path) -> list[dict[str, object]]:
    ledger = EscalationLedger(root / "learning/workbuddy_escalations.jsonl")
    snapshot = fold(ledger.events())
    progress, failures, skills = scan_stream(root / "learning/episodes.jsonl")

    rows: list[dict[str, object]] = []
    for record in snapshot.records.values():
        if getattr(record, "state", "") not in PENDING_STATES:
            continue
        if getattr(record, "condition", "") not in GAP_CONDITIONS:
            continue
        goal = str(getattr(record, "goal", "") or "")
        filed = _moment(getattr(record, "first_seen", None))
        seen = progress.get(goal)
        row: dict[str, object] = {
            "key": str(getattr(record, "key", "")),
            "condition": str(getattr(record, "condition", "")),
            "goal": goal,
            "capability": str(getattr(record, "capability", "")),
            "skill": str(getattr(record, "skill", "")),
            "failure_type": str(getattr(record, "failure_type", "")),
            "filed": filed.isoformat() if filed else "",
            "episodes": int(seen["n"]) if seen else 0,
            "episodes_advanced": int(seen["advanced"]) if seen else 0,
            "last_advanced": seen["last_advanced"].isoformat() if seen and seen["last_advanced"] else "",
            # How often this record's own failure was measured in the production
            # stream.  A record whose failure never recurred cannot be worth a
            # device slice however true its premise still is.
            "failure_episodes": failures.get(str(getattr(record, "failure_type", "")), 0),
            # How often the skill the record names has run at all.  Zero is a
            # stronger statement than "not yet re-observed": the claim cannot be
            # tested against the stream because nothing reaches that code.
            "skill_episodes": skills.get(str(getattr(record, "skill", "")), 0),
        }
        # The verdict.  Only a ``NO_GOAL_PROGRESS`` record claims "no part of it
        # advanced", so only that claim can be tested against goal progress.
        #
        # A ``*_NOT_PROVEN`` record claims the *client* showed something V2 could not
        # read or locate.  Whether the goal advanced is beside the point -- another
        # skill advancing it proves nothing about the recognition that failed, and
        # letting progress stand in as evidence would be the "two root causes, one
        # reason" mistake this project has already paid for once.  That claim needs a
        # frame, so it gets its own verdict rather than a borrowed one.
        if str(getattr(record, "failure_type", "")) != "NO_GOAL_PROGRESS":
            # ...unless the named skill has never run, which is worth saying first:
            # a recognition claim about a hop nothing dispatches is not waiting on a
            # frame, it is waiting on the hop existing.  Measured 2026-10-14, five of
            # the seventeen pending records name a skill with zero episodes.
            row["premise"] = (
                "SKILL_NEVER_DISPATCHED" if not row["skill_episodes"]
                else "RECOGNITION_CLAIM_NEEDS_A_FRAME"
            )
        elif seen is None:
            # A goal absent from the stream never ran -- a third answer, not a quiet "no".
            row["premise"] = "GOAL_NEVER_RAN"
        elif int(seen["advanced"]) == 0:
            row["premise"] = "HOLDS_NEVER_ADVANCED"
        else:
            last = seen["last_advanced"]
            advanced_after = last is not None and filed is not None and last > filed
            row["premise"] = "FALSIFIED_SINCE_FILING" if advanced_after else "ADVANCED_BEFORE_FILING"
        rows.append(row)
    # Rank by premise, then by how much the failure actually recurs -- so the top of
    # the board is the record that both still holds AND happens often.
    rows.sort(key=lambda r: (str(r["premise"]), -int(r["failure_episodes"])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable rows")
    args = parser.parse_args()

    rows = audit(ROOT)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    frozen = datetime.fromtimestamp(
        (ROOT / "learning/episodes.jsonl").stat().st_mtime, tz=timezone.utc
    )
    print("ESCALATION PREMISE AUDIT (read-only -- nothing is retired here)")
    print(f"  ledger stream frozen at : {frozen.isoformat()}")
    print(f"  pending gap records     : {len(rows)}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["premise"])] = counts.get(str(row["premise"]), 0) + 1
    print(f"  by premise              : {counts}")
    print()
    print(f"  {'premise':<30} {'skill':<38} {'n_fail':>6} {'skill_eps':>9} filed")
    for row in rows:
        print(
            f"  {str(row['premise']):<30} {str(row['skill'] or '-'):<38} "
            f"{row['failure_episodes']:>6} {row['skill_episodes']:>9} "
            f"{str(row['filed'])[:10]}"
        )
    print()
    print("  n_fail    = how many production episodes carried this record's failure_type.")
    print("              A *generic* type (SEMANTIC_TARGET_NOT_VERIFIED) is shared by many")
    print("              skills, so for those rows read n_fail as an upper bound on this")
    print("              record's own share, not as this record's count.")
    print("  skill_eps = how many production episodes ran the skill this record names.")
    print("              Zero means the hop never runs, so the claim cannot be re-tested at all.")
    print()
    print("  FALSIFIED_SINCE_FILING         : the goal advanced after the record was filed, so")
    print("                                   'no part of it advanced' is no longer true of the client.")
    print("  HOLDS_NEVER_ADVANCED           : the goal has never advanced in the whole stream.")
    print("  GOAL_NEVER_RAN                 : the goal never appears -- it is held at the deferral gate.")
    print("  ADVANCED_BEFORE_FILING         : advanced, but only before this record -- premise stands.")
    print("  RECOGNITION_CLAIM_NEEDS_A_FRAME: a *_NOT_PROVEN claim about what the client drew;")
    print("                                   progress cannot test it, only a frame can.")
    print("  SKILL_NEVER_DISPATCHED         : the skill the record names has zero episodes in")
    print("                                   the stream, so nothing reaches that claim at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
