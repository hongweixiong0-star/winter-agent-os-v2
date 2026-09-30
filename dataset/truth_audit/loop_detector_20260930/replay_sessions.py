"""LOOP_DETECTOR_V1 replayed over the **Session Engine's own** production steps.

``replay_episodes.py`` replays the whole stream, where a session step is 81 rows in 10,145.
This script replays *only* those rows, grouped the way the engine groups them -- one detector
per session -- because that is the only scope in which the four metrics the directive names
can be read without mixing them together.

Why this is real evidence and not a simulation
----------------------------------------------
These rows were written by the live AUTO against the real client.  ``decision_reason`` starts
with ``session:`` because ``LiveRuntimeSessionHost.record_step`` wrote them, so
``SESSION_PREFIX`` selects exactly the Session Engine's steps and nothing else.  The detector
is fed the same five-field state hash the live path uses and the same action/feedback columns.

What this does **not** prove
----------------------------
The detector has never run in production.  ``revision_audit`` below checks, per row, whether
the revision that produced it contains ``winter_agent_v2/loop_detector.py`` -- the answer is
zero rows, because the pinned production revision (``6ba2ab5``) is the commit *before* the one
that added the module.  So this proves the detector's **policy on the real AUTO's own
sequences**; it does not claim the running AUTO fed it these signatures.  The engine half is
proved by ``tests/test_loop_detector_boundary.py`` (real ``LiveRuntime``, real single
Scheduler), and the run-keeps-going half is cross-checked against the AUTO's own round ledger,
``learning/auto_uptime.jsonl``.

Two readings, and the one that matters here
-------------------------------------------
* ``declared`` -- ``goal_progress``, the Goal-level fact.  Every one of the 81 rows carries it,
  so this reading is complete.
* ``outcome`` -- ``goal_progress``, else ``progress_from_outcome(result)``.  This is what
  ``SessionEngine._signature_for`` does today, because no business adapter declares
  ``progress`` yet.

Both readings are run, and the measured result is that they are **identical on every one of
the 81 rows**: because ``record_step`` always writes ``goal_progress``, the ``declared`` value
is never ``None`` and the ``progress_from_outcome`` fallback is never reached.  That is the
tri-state doing its job -- and it is reported as a measurement rather than assumed, because the
rows carry a second, *disagreeing* signal: **42 of the 81 steps are ``result=FAILURE`` while
``goal_progress=true``** (the click did not verify, the Goal still advanced).  A detector fed
``result`` alone would read those 42 verified advances as "no progress".  The fallback is safe
here only because nothing ever reaches it; it is not safe by construction, and that is what
``declared_true_but_result_failed`` in the report is for.

Two state readings, and why both
--------------------------------
A session step records ``state_before`` and an **empty** ``state_after`` (a session step does
not take its own post-read).  ``replay_episodes.py`` picked ``state_after`` whenever it was a
``Mapping`` -- and ``{}`` is one, so the context hash was computed over an all-``None``
projection for these rows.  ``recorded`` here prefers a **non-empty** ``state_after`` and falls
back to ``state_before``; ``after_only`` reproduces the earlier behaviour.  Both are run, so
the correction is measured instead of asserted.

Usage::

    .venv/Scripts/python.exe dataset/truth_audit/loop_detector_20260930/replay_sessions.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.loop_detector import (  # noqa: E402
    LOOP_DEFERRED,
    LOOP_DETECTED,
    LOOP_DETECTED_NET,
    LOOP_FALSE_POSITIVE,
    LOOP_RECOVERED,
    RECOVERY_LADDER,
    LoopDetector,
    LoopSignature,
    progress_from_outcome,
    relevant_state_hash,
)

EPISODES = ROOT / "learning" / "episodes.jsonl"
UPTIME_LEDGER = ROOT / "learning" / "auto_uptime.jsonl"
UPTIME_ACCEPTANCE = ROOT / "learning" / "auto_uptime_acceptance.json"
OUT_DIR = Path(__file__).resolve().parent

#: The prefix ``LiveRuntimeSessionHost.record_step`` writes, and the only mark a session step
#: carries.  There is no ``session_id`` column: the id lives inside the decision reason.
SESSION_PREFIX = "session:"

#: The episode vocabulary, mapped onto the engine's five outcomes.  ``PROGRESS`` is its own
#: outcome in the engine, and ``INCOMPLETE`` is what ``_record_episode`` writes for an
#: ``AMBIGUOUS`` session verdict -- which must stay unread rather than become a failure.
_RESULT_TO_OUTCOME = {
    "SUCCESS": "SUCCESS",
    "PROGRESS": "PROGRESS",
    "FAILURE": "FAILED",
    "INCOMPLETE": "AMBIGUOUS",
}


def load_rows(path: Path) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    rows: list[tuple[int, dict[str, Any]]] = []
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((line_no, json.loads(line)))
            except json.JSONDecodeError:
                skipped += 1
    return rows, skipped


def session_id_of(row: Mapping[str, Any]) -> str | None:
    """The session a row belongs to, or ``None`` for a goal-driven step."""
    reason = str(row.get("decision_reason") or "")
    if not reason.startswith(SESSION_PREFIX):
        return None
    return reason[len(SESSION_PREFIX):].split(":", 1)[0]


def step_reason_of(row: Mapping[str, Any]) -> str:
    reason = str(row.get("decision_reason") or "")
    if not reason.startswith(SESSION_PREFIX):
        return ""
    rest = reason[len(SESSION_PREFIX):]
    return rest.split(":", 1)[1] if ":" in rest else ""


def episode_fields(row: Mapping[str, Any], *, state_source: str) -> dict[str, Any]:
    """The episode's own vocabulary, normalised once so every reading shares it."""
    after_raw = row.get("state_after")
    before_raw = row.get("state_before")
    after = after_raw if isinstance(after_raw, Mapping) else None
    before = before_raw if isinstance(before_raw, Mapping) else None
    if state_source == "after_only":
        state = after if after is not None else {}
    else:
        # ``recorded``: a session step's post-state is empty on purpose, so the context the
        # action was taken in is the pre-state.  An empty mapping means "not read here", and
        # ``empty != none`` says not-read must not be confused with read-empty.
        state = after if after else (before if before is not None else {})
    action = row.get("action")
    action = action if isinstance(action, Mapping) else {}
    result = str(row.get("result") or "").upper()
    return {
        "role_id": str(row.get("role_id") or ""),
        "page": str(state.get("page") or ""),
        "goal_id": str(row.get("goal_id") or ""),
        "skill_id": str(row.get("skill") or action.get("kind") or ""),
        "semantic_target": str(row.get("control") or action.get("target") or ""),
        "state_hash": relevant_state_hash(state),
        "outcome": _RESULT_TO_OUTCOME.get(result, result),
        "result": result,
        "declared_progress": row.get("goal_progress"),
        "revision": str(row.get("repo_revision") or "").split("+", 1)[0] or "(none)",
        "recorded_at": str(row.get("recorded_at") or ""),
    }


def signature_of(fields: Mapping[str, Any], *, reading: str) -> LoopSignature:
    declared = fields["declared_progress"]
    progress = None if declared is None else bool(declared)
    if reading != "declared" and progress is None:
        progress = progress_from_outcome(fields["outcome"])
    return LoopSignature(
        role_id=fields["role_id"], page=fields["page"], goal_id=fields["goal_id"],
        skill_id=fields["skill_id"], semantic_target=fields["semantic_target"],
        state_hash=fields["state_hash"], verifier_outcome=fields["outcome"],
        progress=progress,
    )


def contains_detector(commit: str, cache: dict[str, bool | None]) -> bool | None:
    """Does this revision ship ``winter_agent_v2/loop_detector.py``?

    Asked of Git rather than inferred from the date: a revision's own tree is the only
    thing that decides what it could have executed.
    """
    if commit in cache:
        return cache[commit]
    if not commit or commit == "(none)":
        cache[commit] = None
        return None
    try:
        result = subprocess.run(
            ["git", "ls-tree", commit, "winter_agent_v2/loop_detector.py"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20, check=False,
        )
    except OSError:
        cache[commit] = None
        return None
    cache[commit] = bool(result.stdout.strip()) if result.returncode == 0 else None
    return cache[commit]


def replay(rows: list[tuple[int, dict[str, Any]]], *, state_source: str, reading: str,
           rev_cache: dict[str, bool | None]) -> dict[str, Any]:
    """One detector per session, fed that session's rows in stream order."""
    sessions: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for line_no, row in rows:
        sid = session_id_of(row)
        if sid is not None:
            sessions[sid].append((line_no, row))

    order = sorted(sessions, key=lambda sid: sessions[sid][0][0])
    totals: Counter = Counter()
    patterns: Counter = Counter()
    detail: list[dict[str, Any]] = []
    disagreements = 0
    session_steps = 0

    for sid in order:
        group = sessions[sid]
        detector = LoopDetector()
        detections: list[dict[str, Any]] = []
        retractions: list[dict[str, Any]] = []
        defer_at: int | None = None
        sequence: list[dict[str, Any]] = []
        feeds: list[dict[str, Any]] = []

        for position, (line_no, row) in enumerate(group, start=1):
            session_steps += 1
            fields = episode_fields(row, state_source=state_source)
            if fields["declared_progress"] is True and fields["outcome"] == "FAILED":
                disagreements += 1
            signature = signature_of(fields, reading=reading)
            verdict = detector.observe(signature)
            feeds.append({"position": position, "line": line_no, "rung": verdict.rung,
                          "detected": verdict.detected, "retracted": verdict.retracted})
            sequence.append({
                "position": position, "line": line_no, "page": fields["page"],
                "skill_id": fields["skill_id"], "semantic_target": fields["semantic_target"],
                "result": fields["result"], "outcome": fields["outcome"],
                "goal_progress": fields["declared_progress"],
                "progress": signature.progress, "signature": signature.digest,
                "state_hash": fields["state_hash"], "reason": step_reason_of(row),
                "detected": verdict.detected, "rung": verdict.rung,
                "retracted": verdict.retracted, "escalated": verdict.escalated,
                "detection_reason": verdict.reason,
            })
            if verdict.retracted:
                retractions.append({"position": position, "line": line_no,
                                    "pattern": verdict.pattern, "reason": verdict.reason})
            if verdict.detected:
                detections.append({"position": position, "line": line_no,
                                   "pattern": verdict.pattern, "rung": verdict.rung,
                                   "repeats": verdict.repeats, "escalated": verdict.escalated,
                                   "reason": verdict.reason,
                                   "signature": verdict.signature_digest})
                if verdict.wants_defer and defer_at is None:
                    defer_at = position

        summary = detector.summary()
        totals.update({k: int(v) for k, v in summary.items()
                       if k.startswith("LOOP_") and isinstance(v, int)})
        patterns.update({k: int(v) for k, v in summary.get("LOOP_PATTERNS", {}).items()})
        revisions = sorted({episode_fields(row, state_source=state_source)["revision"]
                            for _line, row in group})
        detail.append({
            "session_id": sid,
            "first_line": group[0][0], "last_line": group[-1][0],
            "steps": len(group),
            "goal_ids": sorted({str(row.get("goal_id") or "") for _line, row in group}),
            "role_ids": sorted({str(row.get("role_id") or "") for _line, row in group}),
            "revisions": revisions,
            "revision_contains_detector": sorted(
                str(contains_detector(rev, rev_cache)) for rev in revisions),
            "counters": {
                LOOP_DETECTED: int(summary[LOOP_DETECTED]),
                LOOP_FALSE_POSITIVE: int(summary[LOOP_FALSE_POSITIVE]),
                LOOP_RECOVERED: int(summary[LOOP_RECOVERED]),
                LOOP_DEFERRED: int(summary[LOOP_DEFERRED]),
            },
            "ladder_top": summary["LOOP_LADDER_TOP"],
            "detections": detections,
            "retractions": retractions,
            "defer_at_step": defer_at,
            "sequence": sequence,
            "feeds": feeds,
        })

    return {
        "state_source": state_source,
        "reading": reading,
        "sessions": len(order),
        "session_steps": session_steps,
        "counters": {
            LOOP_DETECTED: totals.get(LOOP_DETECTED, 0),
            LOOP_FALSE_POSITIVE: totals.get(LOOP_FALSE_POSITIVE, 0),
            LOOP_RECOVERED: totals.get(LOOP_RECOVERED, 0),
            LOOP_DEFERRED: totals.get(LOOP_DEFERRED, 0),
            LOOP_DETECTED_NET: totals.get(LOOP_DETECTED_NET, 0),
        },
        "patterns": dict(patterns),
        "sessions_that_reached_defer": sum(1 for item in detail if item["defer_at_step"]),
        "declared_true_but_result_failed": disagreements,
        "detail": detail,
    }


def code_revision() -> str:
    """The revision this replay actually executed.

    Not decoration.  ``LOOP_DETECTOR_V1``'s counting rules changed twice on 2026-09-30 *after*
    the first replay was written -- ``772c0f9`` wired production widening and added the timeline
    fields, ``014a4df`` made ``LOOP_RECOVERED`` require verified progress on the new action
    rather than merely a different one.  A count without the revision it came from is not
    evidence, so the revision travels with it.
    """
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=20,
                                check=False)
    except OSError:
        return "(unknown)"
    return result.stdout.strip() or "(unknown)"


def live_detector_telemetry(root: Path) -> dict[str, Any]:
    """What the **deployed** detector said about itself, from the runs that have one.

    ``772c0f9`` gave the runtime ``_record_session_timeline``, which appends one row per event
    to ``<capture_dir>/session_timeline.jsonl``: ``SESSION_ENDED`` carries the session's full
    metrics dict -- including every ``LOOP_*`` counter and the detector's own bounded
    ``LOOP_TIMELINE`` -- and ``AUTO_CONTINUED`` is emitted by the run loop when a session ended
    ``SESSION_DOMAIN_STUCK`` and the next Goal was selected.

    This is the only place the four metrics can be read as the *running* system produced them
    rather than as a replay of what it wrote.  Files are found by walking the run capture
    directories, and a file is included only when its own ``repo_revision`` says the run shipped
    the detector -- an older run's silence is not evidence about the detector.
    """
    runs_root = root / "dataset" / "raw" / "control_panel" / "runtime_auto"
    files: list[Path] = []
    if runs_root.is_dir():
        # Newest first: the live run is the one that matters, and the corpus is large.
        for child in sorted(runs_root.iterdir(), key=lambda p: p.name, reverse=True):
            candidate = child / "session_timeline.jsonl"
            if candidate.is_file():
                files.append(candidate)

    sessions: list[dict[str, Any]] = []
    continued: list[dict[str, Any]] = []
    revisions: Counter = Counter()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            revision = str(row.get("repo_revision") or "").split("+")[0]
            revisions[revision or "(none)"] += 1
            if row.get("event") == "AUTO_CONTINUED":
                continued.append({"run": path.parent.name, "revision": revision, **row})
                continue
            if row.get("event") != "SESSION_ENDED":
                continue
            metrics = row.get("metrics") or {}
            timeline = metrics.get("LOOP_TIMELINE") or []
            sessions.append({
                "run": path.parent.name,
                "revision": revision,
                "timestamp": row.get("timestamp"),
                "session_id": row.get("session_id"),
                "goal_id": row.get("goal_id"),
                "reason": row.get("reason"),
                "steps": metrics.get("SESSION_STEPS"),
                "verified_steps": metrics.get("SESSION_VERIFIED_STEPS"),
                "ambiguous_retries": metrics.get("SESSION_AMBIGUOUS_RETRIES"),
                "semantic_retries": metrics.get("SESSION_SEMANTIC_RETRIES"),
                "observes": metrics.get("SESSION_OBSERVES"),
                "observations_shown_to_the_detector": len(timeline),
                "loop_metrics": {key: value for key, value in metrics.items()
                                 if key.startswith("LOOP_") and not isinstance(value, (list, dict))},
                "loop_patterns": metrics.get("LOOP_PATTERNS"),
                "loop_timeline": timeline,
            })
    return {
        "runs_root": str(runs_root.relative_to(root)) if runs_root.is_dir() else str(runs_root),
        "files": [str(path) for path in files],
        "revisions": dict(revisions),
        "sessions": sessions,
        "auto_continued_events": continued,
    }


def auto_continued(rows: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    """Did the real AUTO keep going after a session ended?

    Two independent accounts, because neither alone is enough:

    * **the stream**: a session that ends is followed by more rows, and eventually by another
      session.  This is what the run actually did.
    * **the round ledger** (``learning/auto_uptime.jsonl``): the panel's own record of each
      round's ``stop_reason``, ``stop_category``, ``healthy`` and ``continues``.  This is what
      the run *said* about itself, and it names the one thing the stream cannot show -- whether
      a stop was fatal.
    """
    sessions: dict[str, list[int]] = defaultdict(list)
    for line_no, row in rows:
        sid = session_id_of(row)
        if sid is not None:
            sessions[sid].append(line_no)
    order = sorted(sessions, key=lambda sid: sessions[sid][0])
    last_line = rows[-1][0] if rows else 0

    per_session: list[dict[str, Any]] = []
    for index, sid in enumerate(order):
        lines = sessions[sid]
        following = [line for line, _row in rows if line > lines[-1]]
        per_session.append({
            "session_id": sid,
            "last_line": lines[-1],
            "rows_after": len(following),
            "next_session_started": order[index + 1] if index + 1 < len(order) else "",
            "is_last_session": index + 1 == len(order),
        })

    ledger_rows: list[dict[str, Any]] = []
    if UPTIME_LEDGER.exists():
        with UPTIME_LEDGER.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        ledger_rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    acceptance: dict[str, Any] = {}
    if UPTIME_ACCEPTANCE.exists():
        try:
            acceptance = json.loads(UPTIME_ACCEPTANCE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            acceptance = {}

    continues = [bool(item.get("continues")) for item in ledger_rows]
    categories = Counter(str(item.get("stop_category") or "") for item in ledger_rows)
    return {
        "from_the_stream": {
            "sessions": len(order),
            "sessions_followed_by_more_rows": sum(1 for item in per_session
                                                  if item["rows_after"] > 0),
            "sessions_followed_by_another_session": sum(1 for item in per_session
                                                        if item["next_session_started"]),
            "stream_last_line": last_line,
            "per_session": per_session,
        },
        "from_the_round_ledger": {
            "path": str(UPTIME_LEDGER.relative_to(ROOT)),
            "rounds": len(ledger_rows),
            "continuing_rounds": sum(1 for value in continues if value),
            "halted_rounds": sum(1 for value in continues if not value),
            "stop_categories": dict(categories),
            "stop_reasons": dict(Counter(str(item.get("stop_reason") or "")
                                         for item in ledger_rows)),
            "unhealthy_rounds": sum(1 for item in ledger_rows
                                    if item.get("healthy") is False),
            "revisions": dict(Counter(str(item.get("repo_revision") or "(empty)")
                                      for item in ledger_rows)),
        },
        "panel_acceptance": {
            "path": str(UPTIME_ACCEPTANCE.relative_to(ROOT)),
            "loaded_revision": acceptance.get("loaded_revision", ""),
            "loaded_at": acceptance.get("loaded_at", ""),
            "scope": acceptance.get("scope", ""),
            "summary": acceptance.get("summary", {}),
        },
    }


def main() -> int:
    rows, skipped = load_rows(EPISODES)
    rev_cache: dict[str, bool | None] = {}

    session_rows = [(line, row) for line, row in rows if session_id_of(row) is not None]
    bases = Counter(episode_fields(row, state_source="recorded")["revision"]
                    for _line, row in rows)
    rows_from_detector = sum(
        count for base, count in bases.items() if contains_detector(base, rev_cache)
    )
    sequence = [str(row.get("result") or "").upper() for _line, row in session_rows]

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": code_revision(),
        "source": {
            "path": str(EPISODES.relative_to(ROOT)),
            "rows": len(rows),
            "unparseable": skipped,
            "session_steps": len(session_rows),
            "sessions": len({session_id_of(row) for _line, row in session_rows}),
            "first_session_line": session_rows[0][0] if session_rows else None,
            "last_session_line": session_rows[-1][0] if session_rows else None,
            "session_result_values": dict(Counter(sequence)),
        },
        "recovery_ladder": list(RECOVERY_LADDER),
        "telemetry_note": [
            "A session step carries no session_id column: the id is inside decision_reason, "
            "written by LiveRuntimeSessionHost.record_step as 'session:<id>:<reason>'.",
            "A session step carries no session_outcome column either: record_step passes it to "
            "_record_episode, which folds it into 'result' (PROGRESS / INCOMPLETE / SUCCESS / "
            "FAILURE). 'result' is therefore the session verdict as the stream records it.",
            "A session step records state_before and an empty state_after, so the context hash "
            "must fall back to state_before; see state_source below.",
        ],
        "revision_audit": {
            "distinct_base_commits_in_stream": len(bases),
            "rows": len(rows),
            "rows_from_a_revision_that_ships_loop_detector": rows_from_detector,
            "newest_base_commit": (
                episode_fields(rows[-1][1], state_source="recorded")["revision"] if rows else ""
            ),
            "newest_revision_ships_loop_detector": contains_detector(
                episode_fields(rows[-1][1], state_source="recorded")["revision"] if rows else "",
                rev_cache,
            ),
            "per_session": sorted({
                rev for _line, row in session_rows
                for rev in [episode_fields(row, state_source="recorded")["revision"]]
            }),
        },
        "readings": {
            "recorded/declared": replay(rows, state_source="recorded", reading="declared",
                                        rev_cache=rev_cache),
            "recorded/outcome": replay(rows, state_source="recorded", reading="outcome",
                                       rev_cache=rev_cache),
            "after_only/declared": replay(rows, state_source="after_only", reading="declared",
                                          rev_cache=rev_cache),
            "after_only/outcome": replay(rows, state_source="after_only", reading="outcome",
                                         rev_cache=rev_cache),
        },
        "auto_continued": auto_continued(rows),
        "live_detector_telemetry": live_detector_telemetry(ROOT),
        "limitations": [
            "The detector has never run in production: revision_audit reports how many rows "
            "came from a revision whose tree contains winter_agent_v2/loop_detector.py, and "
            "that number is the honest scope of every count below.",
            "These rows were produced by the runtime's own session host, not by the detector, "
            "so this proves the detector's policy on real AUTO sequences -- not that the "
            "running AUTO fed the detector these signatures. That half is proved on the real "
            "LiveRuntime by tests/test_loop_detector_boundary.py.",
            "LOOP_RECOVERED is counted by the detector itself when a rung had been spent and "
            "the flow then moved. Replayed over a finished stream it is a statement about "
            "policy; in a live session it is also a statement about the host performing the "
            "rung, which this replay cannot exercise.",
            "AUTO_CONTINUED is emitted by the caller that owns the run loop, not by the "
            "detector, so it cannot be read off these rows at all. It is evidenced here from "
            "the run's own round ledger instead, and on the real LiveRuntime by "
            "tests/test_loop_detector_boundary.py.",
            "skill_id/semantic_target are reconstructed from episode columns that mix "
            "registered skills and step kinds; a different mapping moves the counts and the "
            "script can be re-run to see by how much.",
        ],
    }

    (OUT_DIR / "replay_sessions_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"rows {len(rows)}  session steps {len(session_rows)}  "
          f"sessions {report['source']['sessions']}")
    print(f"session result values: {report['source']['session_result_values']}")
    print(f"rows from a detector-bearing revision: "
          f"{report['revision_audit']['rows_from_a_revision_that_ships_loop_detector']} "
          f"/ {len(rows)}  (newest base "
          f"{report['revision_audit']['newest_base_commit'][:12]}, ships="
          f"{report['revision_audit']['newest_revision_ships_loop_detector']})")
    for name, block in report["readings"].items():
        print(f"---- {name}: counters={block['counters']} patterns={block['patterns']} "
              f"sessions_that_reached_defer={block['sessions_that_reached_defer']} "
              f"declared_true_but_result_failed={block['declared_true_but_result_failed']}")
    print("---- AUTO_CONTINUED ----")
    print(json.dumps({k: v for k, v in report["auto_continued"].items()
                      if k != "from_the_stream"}, ensure_ascii=False, indent=2))
    stream = report["auto_continued"]["from_the_stream"]
    print(json.dumps({k: v for k, v in stream.items() if k != "per_session"},
                     ensure_ascii=False, indent=2))
    live = report["live_detector_telemetry"]
    print("---- live detector telemetry (the deployed revision's own account) ----")
    print(f"files: {len(live['files'])}  revisions: {live['revisions']}")
    for sess in live["sessions"]:
        print(f"  {sess['timestamp']} {sess['session_id']} {sess['goal_id']} "
              f"reason={sess['reason']}")
        print(f"     steps={sess['steps']} verified={sess['verified_steps']} "
              f"observes={sess['observes']} "
              f"observations_shown_to_the_detector="
              f"{sess['observations_shown_to_the_detector']} "
              f"ambiguous_retries={sess['ambiguous_retries']}")
        print(f"     loop_metrics={sess['loop_metrics']}")
    print(f"AUTO_CONTINUED events recorded live: {len(live['auto_continued_events'])}")
    print(f"---- wrote {OUT_DIR / 'replay_sessions_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
