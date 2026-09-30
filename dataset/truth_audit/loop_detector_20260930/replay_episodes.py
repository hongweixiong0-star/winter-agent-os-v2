"""LOOP_DETECTOR_V1 replayed over the production episode stream.

Why a replay rather than a new live run: the detector's whole claim is "this sequence is a
loop", and the production stream already contains thousands of honest sequences -- including
the ones this module exists for.  Replaying them costs nothing, touches no device, and can be
re-run by anyone, which a live observation of a rare event cannot.

What is exact and what is approximated (this is the part a reader must not have to guess):

* **Exact.**  ``learning/episodes.jsonl`` records the full ``WorldState`` on both sides of
  every step, so ``relevant_state_hash`` is recomputed from the *same five fields* the live
  path hashes, with the same ``empty != none`` rule (an unread march count stays ``None``).
* **Approximated.**  The live signature's ``skill_id``/``semantic_target`` come from a
  ``SessionStep``; the episode carries ``skill`` (which mixes registered skills and step
  kinds) plus ``control`` and ``action.kind``.  The mapping is written into the report so a
  reader can disagree with it and re-run.
* **Not claimed.**  These rows were produced by the runtime's own step loop, not by the
  Session Engine.  So this proves the detector's *policy* on real sequences; it does not claim
  the engine fed these exact signatures.  The engine half is proved by
  ``tests/test_loop_detector_boundary.py``.

Two readings of ``progress``, and the reason both are reported
-------------------------------------------------------------
``progress`` is the *Goal*-level fact.  It can come from two places:

* **declared** -- ``goal_progress``, the episode's own record of whether the Goal advanced.
  This is what an adapter declaring ``StepVerdict.progress`` supplies, and it is the reading
  the design wants.
* **outcome** -- when nothing declared it, the step's own result.  **This is what the engine
  does today**: ``SessionEngine._signature_for`` falls back to ``progress_from_outcome``
  because none of the four business adapters declares ``progress`` yet.

Reporting only the first would describe a detector that does not exist yet; reporting only the
second would hide the signal the tri-state was built for.  Both are measured, and the
difference between them is itself the finding.

Detections are counted **per repeat, not per incident**: a run of eight identical steps
produces six detections, one per rung of the ladder, because that is what the engine does with
them.  The number a reader should compare against production is ``steps_until_first_deferral``
-- until a ladder is spent, every detection is only the cheapest rung.

Usage::

    .venv/Scripts/python.exe dataset/truth_audit/loop_detector_20260930/replay_episodes.py
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2.loop_detector import (  # noqa: E402
    LOOP_DEFERRED,
    LoopPattern,
    no_progress_block,
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
OUT_DIR = Path(__file__).resolve().parent

#: The engine's five outcomes, as the episode stream spells them.
_RESULT_TO_OUTCOME = {"SUCCESS": "SUCCESS", "FAILURE": "FAILED"}
#: The session budgets the four routes declare, for the comparison the report makes.
TYPICAL_SESSION_BUDGETS = (5, 8, 12)


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


def episode_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """The episode's own vocabulary, normalised once so both readings share it."""
    after = row.get("state_after")
    if not isinstance(after, Mapping):
        after = row.get("state_before")
    if not isinstance(after, Mapping):
        after = {}
    action = row.get("action")
    action = action if isinstance(action, Mapping) else {}
    return {
        "role_id": str(row.get("role_id") or ""),
        "page": str(after.get("page") or ""),
        "goal_id": str(row.get("goal_id") or ""),
        "skill_id": str(row.get("skill") or action.get("kind") or ""),
        "semantic_target": str(row.get("control") or action.get("target") or ""),
        "state_hash": relevant_state_hash(after),
        "outcome": _RESULT_TO_OUTCOME.get(str(row.get("result") or "").upper(), ""),
        "declared_progress": row.get("goal_progress"),
    }


def signature_of(fields: Mapping[str, Any], *, reading: str) -> LoopSignature:
    declared = fields["declared_progress"]
    if reading == "declared":
        progress = None if declared is None else bool(declared)
    else:
        progress = (None if declared is None else bool(declared))
        progress = progress_from_outcome(fields["outcome"]) if progress is None else progress
    return LoopSignature(
        role_id=fields["role_id"], page=fields["page"], goal_id=fields["goal_id"],
        skill_id=fields["skill_id"], semantic_target=fields["semantic_target"],
        state_hash=fields["state_hash"], verifier_outcome=fields["outcome"],
        progress=progress,
    )


def group_key(fields: Mapping[str, Any], *, per_run: bool) -> tuple[str, ...]:
    run = str(fields.get("trace_id") or "")
    if per_run:
        return (run,)
    return (run, fields["goal_id"])


class _PageOnlyNavigation(LoopDetector):
    """The navigation pattern *before* it was tightened, kept so the change can be measured.

    It matched the cycle on ``page_key`` alone.  That fires on ``HOME -> ALLIANCE -> HOME ->
    ALLIANCE`` where a different control is tapped on each visit -- a client being used, not
    walked in a circle.  Running both on the same rows is what turns "the stricter test is
    better" from a preference into a number.
    """

    def _match_navigation(self, sigs):
        n = len(sigs)
        for period in range(self.nav_min_period, self.nav_max_period + 1):
            span = period * self.nav_repeats
            if n < span:
                continue
            block = sigs[-span:]
            pages = [s.page_key for s in block]
            if len({pages[i] for i in range(period)}) < 2:
                continue
            if any(pages[i] != pages[i % period] for i in range(span)):
                continue
            if not no_progress_block(block):
                continue
            names = [str(p[1]) for p in pages[:period]]
            return (LoopPattern.NAVIGATION_LOOP, self.nav_repeats,
                    f"pages {' -> '.join(names)} cycled {self.nav_repeats}x with no progress")


def replay(rows: Iterable[tuple[int, dict[str, Any]]], *, reading: str, per_run: bool,
           detector_factory: type[LoopDetector] = LoopDetector,
           keep_detections: bool = True) -> dict:
    """One fresh detector per group, fed every row of that group in stream order."""
    flows: dict[tuple[str, ...], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for line_no, row in rows:
        fields = episode_fields(row)
        fields["trace_id"] = str(row.get("trace_id") or "")
        flows[group_key(fields, per_run=per_run)].append((line_no, fields))

    totals: Counter = Counter()
    patterns: Counter = Counter()
    detections: list[dict[str, Any]] = []
    retractions: list[dict[str, Any]] = []
    defer_after: list[int] = []
    seen_patterns: set[str] = set()
    steps = 0

    for key in sorted(flows):
        detector = detector_factory()
        last: dict[str, Any] | None = None
        issued = 0
        deferred_at: int | None = None
        tail: list[dict[str, Any]] = []
        for line_no, fields in flows[key]:
            steps += 1
            issued += 1
            signature = signature_of(fields, reading=reading)
            verdict = detector.observe(signature)
            # The block a detection matched is the *flow's* last entries, which are not
            # necessarily contiguous lines in the file -- rows from other roles and Goals are
            # interleaved.  Rendering contiguous file lines as "the block" produced a worked
            # example that did not reproduce its own claim, so the flow's own tail is kept.
            tail.append({
                "line": line_no, "page": fields["page"], "skill": fields["skill_id"],
                "target": fields["semantic_target"], "outcome": fields["outcome"],
                "goal_progress": fields["declared_progress"], "signature": signature.digest,
            })
            tail = tail[-8:]
            if verdict.retracted:
                record = {
                    "group": list(key), "line": line_no, "pattern": verdict.pattern,
                    "rung": verdict.rung, "reason": verdict.reason,
                    "detection_line": (last or {}).get("line"),
                    "goal_id": fields["goal_id"], "skill_id": fields["skill_id"],
                    "target": fields["semantic_target"], "outcome": fields["outcome"],
                    "progress": True,
                }
                retractions.append(record)
                if last is not None:
                    detections[last["index"]]["retracted_at_line"] = line_no
                    detections[last["index"]]["retraction"] = record
                    detections[last["index"]]["flow_tail"] = list(tail)
                last = None
                continue
            if verdict.detected:
                detections.append({
                    "index": len(detections), "group": list(key), "line": line_no,
                    "goal_id": fields["goal_id"], "skill_id": fields["skill_id"],
                    "target": fields["semantic_target"], "page": fields["page"],
                    "outcome": fields["outcome"], "progress": fields["declared_progress"],
                    "pattern": verdict.pattern, "rung": verdict.rung,
                    "repeats": verdict.repeats, "signature": verdict.signature_digest,
                    "reason": verdict.reason, "escalated": verdict.escalated,
                    "retracted_at_line": None,
                })
                last = detections[-1]
                # The matched block is kept only where a reader needs to check one: the first
                # detection of each pattern (the worked example) and every retraction.
                # Embedding it for all 1439 detections made the report 15 MB, which is not an
                # artifact anybody opens.
                if verdict.pattern not in seen_patterns:
                    detections[-1]["flow_tail"] = list(tail)
                seen_patterns.add(verdict.pattern)
                if verdict.wants_defer and deferred_at is None:
                    deferred_at = issued
        if deferred_at is not None:
            defer_after.append(deferred_at)
        summary = detector.summary()
        totals.update({k: int(v) for k, v in summary.items()
                       if k.startswith("LOOP_") and isinstance(v, int)})
        patterns.update({k: int(v) for k, v in summary.get("LOOP_PATTERNS", {}).items()})

    return {
        "reading": reading,
        "grouping": "trace_id" if per_run else "(trace_id, goal_id)",
        "groups": len(flows),
        "steps": steps,
        "counters": {
            LOOP_DETECTED: totals.get(LOOP_DETECTED, 0),
            LOOP_FALSE_POSITIVE: totals.get(LOOP_FALSE_POSITIVE, 0),
            LOOP_DETECTED_NET: totals.get(LOOP_DETECTED_NET, 0),
            LOOP_RECOVERED: totals.get(LOOP_RECOVERED, 0),
            LOOP_DEFERRED: totals.get(LOOP_DEFERRED, 0),
        },
        "patterns": dict(patterns),
        "flows_that_reached_defer": len(defer_after),
        "steps_until_first_deferral": {
            "min": min(defer_after) if defer_after else None,
            "median": statistics.median(defer_after) if defer_after else None,
            "max": max(defer_after) if defer_after else None,
            "within_a_typical_session_budget": {
                str(budget): sum(1 for value in defer_after if value <= budget)
                for budget in TYPICAL_SESSION_BUDGETS
            },
        },
        # The two secondary readings exist for one comparison each, and their numbers are in
        # the summary dict; keeping ~1400 detection rows for every variant made the report
        # 5x larger for evidence nobody reads.  The primary readings keep everything.
        "detections": detections if keep_detections else [],
        "retractions": retractions,
        "detections_retained": keep_detections,
    }


def worked_examples(result: dict) -> dict[str, Any]:
    """One real, hand-checkable instance per pattern, with the flow's own tail behind it."""
    examples: dict[str, Any] = {}
    for detection in result["detections"]:
        pattern = detection["pattern"]
        if pattern in examples:
            continue
        examples[pattern] = {"detection": {k: v for k, v in detection.items()
                                          if k != "flow_tail"},
                             "block": detection.get("flow_tail", [])}
    return examples


def main() -> int:
    rows, skipped = load_rows(EPISODES)
    print(f"loaded {len(rows)} rows from {EPISODES} (skipped {skipped} unparseable)")

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(EPISODES.relative_to(ROOT)), "rows": len(rows),
                   "unparseable": skipped},
        "mapping": {
            "role_id": "role_id",
            "page": "state_after.page (falls back to state_before)",
            "goal_id": "goal_id",
            "skill_id": "skill (falls back to action.kind)",
            "semantic_target": "control (falls back to action.target)",
            "state_hash": "relevant_state_hash(state_after) -- the same five fields as live",
            "verifier_outcome": "result, FAILURE normalised to the engine's FAILED",
            "progress[declared]": "goal_progress; None when the row does not carry it",
            "progress[outcome]": "goal_progress, else progress_from_outcome(result) "
                                 "-- what the engine does today",
            "flow": "(trace_id, goal_id) -- the closest thing the stream has to a session",
            "run": "trace_id",
            "ladder": list(RECOVERY_LADDER),
        },
        "readings": {
            "declared": replay(rows, reading="declared", per_run=False),
            "outcome": replay(rows, reading="outcome", per_run=False),
            "outcome_per_run": replay(rows, reading="outcome", per_run=True,
                                      keep_detections=False),
            "page_only_navigation": replay(rows, reading="outcome", per_run=False,
                                           detector_factory=_PageOnlyNavigation,
                                           keep_detections=False),
        },
        "limitations": [
            "Rows were produced by the runtime's own step loop, not by the Session Engine; "
            "this proves the detector's policy on real sequences, not that the engine fed them.",
            "skill_id/semantic_target are reconstructed from episode fields that mix registered "
            "skills and step kinds; a different mapping moves the counts and can be re-run.",
            "Detections are counted per repeat, not per incident: a run of eight identical "
            "steps yields six detections, one per rung. The interpretable number is "
            "steps_until_first_deferral.",
            "A flow here spans a whole (trace_id, goal_id), which is longer than a production "
            "session (budget 5-12 steps), so a deferral the replay reaches may never be "
            "reached in production -- see steps_until_first_deferral.",
            "The secondary readings (outcome_per_run, page_only_navigation) record their "
            "counters only: their per-detection rows are not retained, and a re-run is the "
            "way to inspect them.",
        ],
    }
    report["worked_examples"] = worked_examples(report["readings"]["outcome"])

    (OUT_DIR / "replay_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name in ("declared", "outcome", "outcome_per_run", "page_only_navigation"):
        block = report["readings"][name]
        print(f"---- {name}: groups={block['groups']} steps={block['steps']}")
        print(json.dumps({"counters": block["counters"], "patterns": block["patterns"],
                          "flows_that_reached_defer": block["flows_that_reached_defer"],
                          "steps_until_first_deferral": block["steps_until_first_deferral"]},
                         ensure_ascii=False, indent=2))

    print("---- retractions (LOOP_FALSE_POSITIVE candidates), reading=outcome")
    for row in report["readings"]["outcome"]["retractions"][:6]:
        print(json.dumps(row, ensure_ascii=False))

    print("---- worked examples, one per pattern (each block is the FLOW's own tail)")
    for pattern, example in report["worked_examples"].items():
        detection = example["detection"]
        print(f"[{pattern}] line {detection['line']} rung={detection['rung']} "
              f"goal={detection['goal_id']} skill={detection['skill_id']} "
              f"target={detection['target']} reason={detection['reason']}")
        for row in example["block"]:
            print("   ", json.dumps(row, ensure_ascii=False))
    print(f"---- wrote {OUT_DIR / 'replay_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
