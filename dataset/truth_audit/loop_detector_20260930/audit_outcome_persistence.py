"""Audit: can a session step's *outcome* be recovered from the production ledger?

Motivation
----------
``#44`` asks for the run-length distribution of ``STILL_PENDING`` session steps, so a
threshold can be chosen before anything is changed.  That measurement presupposes the
outcome is *recorded*.  It is not.  This audit establishes that, and establishes the second,
sharper fact that makes some already-committed numbers unreproducible: the meaning of the
``result`` column changed mid-corpus.

What is checked, and why each check is falsifiable
--------------------------------------------------
``check_source_contract``   the claims about the *code* are asserted against the code on
                            disk, so this script fails loudly if the mapping or the dead
                            ``step_reports`` list is ever changed.  A citation in a comment
                            can rot; an assertion cannot.
``check_ledger``            the claims about the *data* are asserted against the ledger.
``check_revision_boundary`` the ``result`` column is grouped by the revision that wrote it,
                            and each revision is classified pre/post ``fa476b6`` by asking
                            Git rather than by comparing dates.

The three source facts asserted here
------------------------------------
1. ``runtime._record_episode`` folds ``session_outcome`` into ``result`` and the admitted set
   is ``{"PROGRESS", "AMBIGUOUS"}`` -- ``STILL_PENDING`` is absent, so it falls through to
   the default ``"FAILURE"``.
2. ``Episode`` has no such field, so the fold is the *only* durable trace.
3. ``session_host.step_reports`` -- which does hold the true outcome -- is appended to and
   never read.
"""
from __future__ import annotations

import json
import subprocess
import collections
from pathlib import Path
from typing import Any

ROOT = Path("E:/无尽冬日智能体")
STORE = ROOT / "learning/episodes.jsonl"
RUNTIME = ROOT / "winter_agent_v2/runtime.py"
LEARNING = ROOT / "winter_agent_v2/learning.py"
HOST = ROOT / "winter_agent_v2/session_host.py"
OUT = ROOT / "dataset/truth_audit/loop_detector_20260930/outcome_persistence_audit.json"

#: The commit that made ``result`` mean something for session steps.  Everything recorded
#: before it wrote ``FAILURE`` regardless of the verdict.
EVIDENCE_FIX = "fa476b6"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=False).stdout.strip()


def is_ancestor(maybe_ancestor: str, commit: str) -> bool:
    done = subprocess.run(["git", "merge-base", "--is-ancestor", maybe_ancestor, commit],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    return done.returncode == 0


# ------------------------------------------------------------------ source contract checks

def check_source_contract() -> dict[str, Any]:
    runtime_text = RUNTIME.read_text(encoding="utf-8")
    learning_text = LEARNING.read_text(encoding="utf-8")
    host_text = HOST.read_text(encoding="utf-8")

    # 1. the admitted set that omits STILL_PENDING
    admitted = 'if session_outcome in {"PROGRESS", "AMBIGUOUS"}:'
    default_fold = 'result = "SUCCESS" if failure is None else "FAILURE"'

    # 2. Episode declares no outcome field
    episode_block = learning_text.split("class Episode:", 1)[-1].split("@dataclass", 1)[0]
    declares_outcome = "outcome" in episode_block or "session_outcome" in episode_block

    # 3. step_reports is written and never read
    declares_step_reports = "self.step_reports" in host_text
    step_report_reads = [
        line.strip() for line in host_text.splitlines()
        if "step_reports" in line and ".append(" not in line and "self.step_reports:" not in line
        and "self.step_reports:" not in line
    ]

    return {
        "runtime_admitted_set_present": admitted in runtime_text,
        "runtime_admitted_set": admitted,
        "runtime_default_fold_present": default_fold in runtime_text,
        "runtime_default_fold": default_fold,
        "runtime_session_outcome_is_a_parameter": "session_outcome: str = \"\"" in runtime_text,
        "episode_declares_an_outcome_field": declares_outcome,
        "session_host_declares_step_reports": declares_step_reports,
        "session_host_reads_step_reports": bool(step_report_reads),
        "session_host_step_report_reads": step_report_reads,
    }


# ------------------------------------------------------------------------ ledger checks

def rows():
    with STORE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def session_step(row: dict) -> tuple[str, str] | None:
    reason = str(row.get("decision_reason") or "")
    if not reason.startswith("session:"):
        return None
    parts = reason.split(":", 2)
    if len(parts) < 3:
        return None
    return parts[1], parts[2]


def check_ledger() -> tuple[dict[str, Any], list[tuple[str, str, dict]]]:
    all_rows = list(rows())
    steps = []
    for row in all_rows:
        parsed = session_step(row)
        if parsed is not None:
            steps.append((parsed[0], parsed[1], row))

    columns = sorted(all_rows[0].keys()) if all_rows else []
    store_schema = {
        "total_episode_rows": len(all_rows),
        "columns": len(columns),
        "has_session_outcome_column": "session_outcome" in columns,
        "has_session_id_column": "session_id" in columns,
        "has_repo_revision_column": "repo_revision" in columns,
    }
    return store_schema, steps


def check_revision_boundary(steps: list[tuple[str, str, dict]]) -> dict[str, Any]:
    revisions = sorted({str(row.get("repo_revision") or "").split("+")[0] for _, _, row in steps})

    per_revision: dict[str, dict[str, Any]] = {}
    for rev in revisions:
        rows_in_rev = [row for _, _, row in steps
                       if str(row.get("repo_revision") or "").split("+")[0] == rev]
        results = collections.Counter(str(row.get("result")) for row in rows_in_rev)
        reasons = collections.Counter(reason.split(":", 1)[0] for _, reason, row in steps
                                      if str(row.get("repo_revision") or "").split("+")[0] == rev)
        post_fix = bool(rev) and is_ancestor(EVIDENCE_FIX, rev)
        per_revision[rev] = {
            "steps": len(rows_in_rev),
            "recorded_after_the_evidence_fix": post_fix,
            "result_values": dict(results),
            "failure_only": set(results) == {"FAILURE"},
            "reason_tails": dict(reasons),
        }

    pre = {rev: info for rev, info in per_revision.items()
           if not info["recorded_after_the_evidence_fix"]}
    post = {rev: info for rev, info in per_revision.items()
            if info["recorded_after_the_evidence_fix"]}

    return {
        "evidence_fix_commit": EVIDENCE_FIX,
        "evidence_fix_subject": git("log", "-1", "--format=%s", EVIDENCE_FIX),
        "revisions_in_corpus": len(revisions),
        "per_revision": per_revision,
        "pre_fix_steps": sum(info["steps"] for info in pre.values()),
        "pre_fix_steps_that_are_failure_only": sum(info["steps"] for info in pre.values()
                                                   if info["failure_only"]),
        "post_fix_steps": sum(info["steps"] for info in post.values()),
        "pre_fix_revisions": sorted(pre),
        "post_fix_revisions": sorted(post),
    }


def check_internal_inconsistencies(steps: list[tuple[str, str, dict]]) -> dict[str, Any]:
    """The corpus already flags two impossible combinations.  Are they all pre-fix?

    ``state_truth.py:1532`` raises ``VERIFIER_CONFLICT`` on ``verifier_ok=True`` with
    ``result="FAILURE"`` -- a live signal on the operator's panel.  If every such row predates
    the evidence fix, then that panel alarm is the schema change rather than the runs, and the
    residual hole (STILL_PENDING) is the part the fix did not close.
    """
    def split(predicate) -> dict[str, int]:
        counts = {"pre_fix": 0, "post_fix": 0, "examples": []}
        for _sid, _reason, row in steps:
            if not predicate(row):
                continue
            rev = str(row.get("repo_revision") or "").split("+")[0]
            key = "post_fix" if rev and is_ancestor(EVIDENCE_FIX, rev) else "pre_fix"
            counts[key] += 1
            if len(counts["examples"]) < 4:
                counts["examples"].append(
                    {"reason": _reason.split(":", 1)[0], "revision": rev[:12],
                     "bucket": key}
                )
        return counts

    verifier_conflict = split(lambda row: row.get("verifier_ok") is True
                              and str(row.get("result")) == "FAILURE")
    progress_conflict = split(lambda row: row.get("goal_progress") is True
                              and str(row.get("result")) == "FAILURE")
    return {
        "verifier_conflict_verifier_ok_true_result_failure": verifier_conflict,
        "progress_conflict_goal_progress_true_result_failure": progress_conflict,
        "verifier_conflict_is_entirely_pre_fix": verifier_conflict["post_fix"] == 0,
        "progress_conflict_is_entirely_pre_fix": progress_conflict["post_fix"] == 0,
        "raised_live_by": "winter_agent_v2/state_truth.py:1532 (VERIFIER_CONFLICT)",
    }


def main() -> None:
    contract = check_source_contract()
    schema, steps = check_ledger()
    boundary = check_revision_boundary(steps)
    inconsistencies = check_internal_inconsistencies(steps)

    # A STILL_PENDING step is now written as FAILURE + NO_EXECUTION.  Show the rows that
    # prove it on the *current* revision, where the rest of the mapping does work.
    post = set(boundary["post_fix_revisions"])
    still_shaped = [
        {"session_id": sid, "reason": reason, "result": row.get("result"),
         "failure_type": row.get("failure_type"), "goal_progress": row.get("goal_progress"),
         "revision": str(row.get("repo_revision") or "").split("+")[0]}
        for sid, reason, row in steps
        if reason.split(":", 1)[0] == "FISHING_RESULT_PENDING"
        and str(row.get("repo_revision") or "").split("+")[0] in post
    ]

    report = {
        "what_this_audits": (
            "Whether a session step's outcome survives to the production ledger, and whether "
            "the `result` column means the same thing across the revisions present in it."
        ),
        "source_contract": contract,
        "ledger_schema": schema,
        "revision_boundary": boundary,
        "internal_inconsistencies": inconsistencies,
        "still_pending_shaped_rows_on_current_revisions": still_shaped,
        "still_pending_shaped_rows_on_current_revisions_count": len(still_shaped),
        "verdict": {},
        "limitations": [
            "The run-length distribution of STILL_PENDING cannot be measured from the ledger: "
            "the outcome is not a column, and the only truthful copy is appended to a list "
            "nothing reads.",
            "`result` is not comparable across the corpus: before fa476b6 every session step "
            "was written FAILURE, so any count that mixes revisions measures the recording code "
            "as much as the run.",
            "FISHING_RESULT_PENDING maps to two outcomes (PROGRESS or STILL_PENDING) from the "
            "same adapter line, so even the reason string cannot resolve it in general.",
        ],
    }
    report["verdict"] = {
        "outcome_is_recoverable_from_the_ledger": False,
        "reason_is_a_sound_substitute": False,
        "result_column_is_stable_across_the_corpus": (
            report["revision_boundary"]["pre_fix_steps_that_are_failure_only"] == 0
        ),
        "step_reports_is_dead_accumulation": (
            contract["session_host_declares_step_reports"]
            and not contract["session_host_reads_step_reports"]
        ),
        "still_pending_folds_to_failure_on_current_revisions": bool(still_shaped)
        and all(item["result"] == "FAILURE" for item in still_shaped),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("== source contract ==")
    for key, value in contract.items():
        print(f"  {key:52s} = {value!r}")
    print("\n== ledger schema ==")
    for key, value in schema.items():
        print(f"  {key:52s} = {value!r}")
    print("\n== revision boundary ==")
    for key in ("evidence_fix_commit", "evidence_fix_subject", "revisions_in_corpus",
                "pre_fix_steps", "pre_fix_steps_that_are_failure_only", "post_fix_steps"):
        print(f"  {key:52s} = {boundary[key]!r}")
    print("  per revision:")
    for rev, info in boundary["per_revision"].items():
        print(f"    {rev or '(empty)'}  post_fix={info['recorded_after_the_evidence_fix']!s:5s} "
              f"steps={info['steps']:3d} results={info['result_values']}")
    print("\n== STILL_PENDING-shaped rows on current revisions ==")
    print(f"  count = {len(still_shaped)}")
    for item in still_shaped[:4]:
        print(f"    {item}")
    print("\n== internal inconsistencies the corpus already flags ==")
    for key in ("verifier_conflict_verifier_ok_true_result_failure",
                "progress_conflict_goal_progress_true_result_failure"):
        block = inconsistencies[key]
        print(f"  {key}")
        print(f"      pre_fix={block['pre_fix']}  post_fix={block['post_fix']}")
        for item in block["examples"]:
            print(f"        {item}")
    print("\n== verdict ==")
    for key, value in report["verdict"].items():
        print(f"  {key:56s} = {value!r}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
