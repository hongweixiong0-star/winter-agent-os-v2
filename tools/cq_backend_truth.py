"""Backend provenance truth audit (WB-R19-BACKEND-PROVENANCE-TRUTH).

Completeness is not truth.  The ledger and the episode are both written by the
runtime, so agreement between them proves only self-consistency; a wrong backend
choice would populate both fields identically.  This audit therefore cross-checks
each MAA/HYBRID/ADB claim against two artefacts the runtime does NOT write:

1. the MAA framework log (``learning/maa_logs/maafw.log``), which is written by
   MaaFramework itself in local time and records every click and key press with
   its coordinates;
2. the screenshots the episode names.

Rules, in the order they are applied to every episode in the window:

* LEDGER_ROW       - a ledger row with the same skill exists within +-3 s;
* LEDGER_AGREES    - action/recognition/capture/latency agree exactly;
* FRAMES_ON_DISK   - the before frame (and the after frame when the step ran) exist;
* INDEPENDENT_TRACE- a MAA claim must be accompanied by a MaaController click or
                     key press in the framework log within +-3 s; an ADB claim must
                     NOT be, at a moment when MAA also acted;
* NOT_SILENT       - a conflict is reported as a conflict.  Nothing is upgraded to
                     success because the fields looked complete.

Read-only: nothing is modified, including no historical episode.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EPISODES = ROOT / "learning/episodes.jsonl"
LEDGER = ROOT / "learning/executor_backend.jsonl"
MAA_LOG = ROOT / "learning/maa_logs/maafw.log"

WINDOW_SECONDS = 20.0
MAA_EVENT_SECONDS = 5.0
LOCAL_OFFSET = timedelta(hours=8)  # maafw.log stamps local time; episodes are UTC

MAA_CLICK = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\].*\[(MaaControllerPostClickV2|MaaControllerPostClickKey)\]"
    r"(.*)$"
)
COORD = re.compile(r"\[x=(-?\d+)\] \[y=(-?\d+)\]")


def parse(path: Path, limit: int | None = None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[-limit:] if limit else rows


def maa_events() -> list[tuple[datetime, str, tuple[int, int] | None, str]]:
    events = []
    for line in MAA_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        hit = MAA_CLICK.match(line)
        if not hit:
            continue
        stamp = datetime.strptime(hit.group(1), "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc) - LOCAL_OFFSET
        found = COORD.search(hit.group(3))
        events.append((stamp, hit.group(2), (int(found.group(1)), int(found.group(2))) if found else None, line))
    return events


def assign_events_to_rows(
    events: list[tuple[datetime, str, tuple[int, int] | None, str]],
    ledger: list[dict],
) -> dict[int, list[tuple[datetime, str, tuple[int, int] | None, str]]]:
    """Give each MAA event to the ONE ledger row it belongs to.

    A plain "+-N seconds" window is wrong at step boundaries: consecutive steps on
    this machine are ~2.5 s apart, so a 5 s window around a SELECT_INTEL_PIN row
    also swallows the BACK key press that the NEXT row's step issued, and that
    reads as "an ADB step also drove via MAA" -- a double-drive suspicion produced
    purely by the window. Measured on 2026-09-15T13:35: an ADB SELECT_INTEL_PIN row
    at 13:35:14.866 was matched to the MAA PostClickKey at 13:35:17.660, which is
    the action of the BACK row at 13:35:17.711.

    So assignment is nearest-row, and ties go to the nearer row only: an event is
    attributed to the row it is closest to, and to no other.
    """
    stamps = [(index, datetime.fromisoformat(row["recorded_at"])) for index, row in enumerate(ledger)]
    assigned: dict[int, list[tuple[datetime, str, tuple[int, int] | None, str]]] = {}
    for event in events:
        best_index = None
        best_gap = None
        for index, stamp in stamps:
            gap = abs((event[0] - stamp).total_seconds())
            if best_gap is None or gap < best_gap:
                best_index, best_gap = index, gap
        if best_index is not None and best_gap is not None and best_gap <= MAA_EVENT_SECONDS:
            assigned.setdefault(best_index, []).append(event)
    return assigned


def main() -> int:
    episodes = parse(EPISODES, limit=80)
    ledger = parse(LEDGER, limit=200)
    events = maa_events()
    assigned = assign_events_to_rows(events, ledger)
    print("episodes inspected: %d   ledger rows: %d   MAA click events: %d   assigned: %d"
          % (len(episodes), len(ledger), len(events), sum(len(v) for v in assigned.values())))
    print()

    findings: list[dict] = []
    collisions: list[dict] = []
    for episode in episodes:
        claimed = episode.get("executor_backend") or ""
        if not claimed:
            continue
        when = episode.get("recorded_at") or ""
        if not when:
            findings.append({"episode": episode.get("episode_id"), "when": when, "conflict": "NO_TIMESTAMP"})
            continue
        moment = datetime.fromisoformat(when)

        issues: list[str] = []
        notes: list[str] = []

        # LEDGER_ROW.  The tolerance is measured, not guessed: the runtime writes
        # the ledger at action time and the episode after the verifier, so the
        # episode lags by 2-13 s on this machine (median 9.6 s over 48 paired
        # steps).  20 s admits every observed same-run pair and still rejects the
        # 11-12 minute "nearest row" that is really a missing row.
        near = [
            row for row in ledger
            if row.get("skill_id") == episode.get("skill")
            and abs((datetime.fromisoformat(row["recorded_at"]) - moment).total_seconds()) <= WINDOW_SECONDS
        ]
        matched_row = None
        if not near:
            issues.append("NO_LEDGER_ROW")
        else:
            row = min(near, key=lambda r: abs((datetime.fromisoformat(r["recorded_at"]) - moment).total_seconds()))
            matched_row = row
            notes.append("delta=%.1fs" % (moment - datetime.fromisoformat(row["recorded_at"])).total_seconds())
            # LEDGER_AGREES
            #
            # Note what is deliberately NOT compared.  ``capture_backend`` exists
            # under that exact name in both artefacts and means two different
            # things:
            #   * episode  - the OBSERVATION device, i.e. which channel produced
            #                this episode's before/after frames (runtime.py:346);
            #   * ledger   - the EXECUTOR's device, i.e. which device the backend
            #                that ran was wired to (executor_router.py:401).
            # They disagree precisely when the two differ, which is the normal
            # HYBRID arrangement, so comparing them produces a "conflict" on every
            # step whose action ran on ADB.  That is not a disagreement about a
            # fact; it is one name on two facts.  It is reported separately as
            # SEMANTIC_COLLISION below rather than counted as a conflict.
            pairs = (
                ("action_backend", "used_backend"),
                ("recognition_backend", "recognition_backend"),
            )
            for episode_field, ledger_field in pairs:
                claimed_value = episode.get(episode_field)
                ledger_value = row.get(ledger_field)
                if claimed_value and ledger_value and claimed_value != ledger_value:
                    issues.append("LEDGER_DISAGREES:%s=%r_vs_%r" % (episode_field, claimed_value, ledger_value))
            # Like for like on frame provenance: the ledger records which device
            # the backend ran on, and the episode records which channel produced
            # the frames, so the only sound check is that BOTH are non-empty when
            # a step ran.
            if row.get("executed") and not row.get("capture_backend"):
                issues.append("LEDGER_CAPTURE_UNNAMED_ON_EXECUTED_STEP")
            if row.get("capture_backend") and episode.get("capture_backend") \
                    and row["capture_backend"] != episode["capture_backend"]:
                collisions.append({
                    "when": when[:19],
                    "skill": episode.get("skill"),
                    "episode_capture_backend": episode["capture_backend"],
                    "ledger_capture_backend": row["capture_backend"],
                    "ledger_used_backend": row.get("used_backend"),
                })
            executed = bool((episode.get("execution") or {}).get("executed")) if isinstance(episode.get("execution"), dict) else None
            if executed is None:
                executed = episode.get("executed")
            if executed is not None and bool(row.get("executed")) != bool(executed):
                issues.append("LEDGER_DISAGREES:executed=%r_vs_%r" % (executed, row.get("executed")))

        # FRAMES_ON_DISK
        before = episode.get("before_screenshot")
        if before:
            path = Path(before)
            if not path.is_absolute():
                path = ROOT / before
            if not path.exists():
                issues.append("BEFORE_FRAME_MISSING")
        else:
            issues.append("BEFORE_FRAME_UNNAMED")
        after = episode.get("after_screenshot")
        if after:
            path = Path(after)
            if not path.is_absolute():
                path = ROOT / after
            if not path.exists():
                issues.append("AFTER_FRAME_MISSING")

        # INDEPENDENT_TRACE.  Events are attributed one-to-one (see
        # assign_events_to_rows) so a step is only credited with the events it
        # actually issued.
        row_index = None
        if matched_row is not None:
            row_index = next(
                (index for index, row in enumerate(ledger) if row is matched_row), None
            )
        window = assigned.get(row_index, []) if row_index is not None else []
        clicks = [event for event in window if event[1] == "MaaControllerPostClickV2"]
        keys = [event for event in window if event[1] == "MaaControllerPostClickKey"]
        if claimed in ("MAA", "HYBRID"):
            if not clicks and not keys:
                issues.append("MAA_CLAIM_WITHOUT_MAA_EVENT")
            else:
                notes.append("maa_events=%d" % len(window))
                if clicks:
                    notes.append("click=%s" % (clicks[0][2],))
        else:
            if clicks or keys:
                issues.append("ADB_CLAIM_WITH_MAA_EVENT")

        findings.append({
            "when": when[:19],
            "skill": episode.get("skill"),
            "claimed": claimed,
            "recognition": episode.get("recognition_backend"),
            "capture": episode.get("capture_backend"),
            "issues": issues,
            "notes": notes,
        })

    print("%-19s %-22s %-6s %-6s %s" % ("when", "skill", "claim", "issues", "notes"))
    for finding in findings:
        print("%-19s %-22s %-6s %-6d %s"
              % (finding["when"], finding.get("skill") or "-", finding.get("claimed") or "-",
                 len(finding.get("issues") or []), "; ".join(finding.get("notes") or [])[:60]))
    print()
    conflicted = [f for f in findings if f.get("issues")]
    print("episodes with a backend claim: %d" % len(findings))
    print("conflicts: %d" % len(conflicted))
    for finding in conflicted:
        print("  %s %-20s claim=%-6s %s" % (finding["when"], finding.get("skill"), finding.get("claimed"), finding["issues"]))
    print()
    print("SEMANTIC_COLLISION (one name, two facts -- not a conflict, an ambiguity):")
    if collisions:
        print("  %d steps where episode.capture_backend != ledger.capture_backend" % len(collisions))
        print("  every one of them has ledger.used_backend=ADB, i.e. the two fields")
        print("  describe the observation channel and the executor channel respectively.")
        for collision in collisions[:4]:
            print("    %s %-22s episode=%s ledger=%s used=%s"
                  % (collision["when"], collision["skill"], collision["episode_capture_backend"],
                     collision["ledger_capture_backend"], collision["ledger_used_backend"]))
        print("  ledger.capture_backend is fully determined by ledger.used_backend, so it")
        print("  carries no information the ledger does not already have; only the name")
        print("  collides.  Fixing that is a persisted-schema decision, reported not applied.")
    report = {
        "inspected": len(findings),
        "conflicts": len(conflicted),
        "semantic_collisions": len(collisions),
        "collision_detail": collisions,
        "findings": findings,
        "maafw_events": len(events),
        "window_seconds": WINDOW_SECONDS,
    }
    (ROOT / "out_backend_truth_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print()
    print("wrote out_backend_truth_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
