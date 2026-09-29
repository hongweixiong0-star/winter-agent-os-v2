"""Classify every Git-tracked file under the mounted data root, and stop Git controlling live state.

Why this exists
---------------
``config``/``knowledge``/``learning``/``dataset`` are junctions into the shared
DATA_ROOT (``E:\\无尽冬日智能体``) that the pinned production worktree mounts.  A
``git checkout`` or ``git rebase`` in that worktree therefore writes *through*
those junctions, and on 2026-09-29 that silently rolled the live production state
back to a committed copy 11 days old -- the wrong account, a 10k-row episode
ledger truncated to 2.1k rows, a scheduler snapshot from a role no longer on the
device.  Restoring the values was the easy part; the structural fix is to stop
Git from owning state the running loop rewrites.

The classification (every file gets exactly one):

    RUNTIME_MUTABLE      the running loop writes it; it belongs in the DATA_ROOT and
                         must not be checkout-controlled.  Untracked + ignored.
    VERSIONED_KNOWLEDGE  rules, skill definitions, event registry, verified rules,
                         templates, human-confirmed assets.  Stays in Git.
    VERSIONED_EVIDENCE   reviewed evidence corpora and historical records.
    GENERATED_ARTIFACT   reproducible from code + knowledge + evidence by a tool.
                         May stay tracked, but a generator must never delete hand
                         knowledge (see knowledge/goals/capability_skill_map.manual.json).

Usage::

    python tools/build_runtime_state_manifest.py            # report only
    python tools/build_runtime_state_manifest.py --json PATH
    python tools/build_runtime_state_manifest.py --apply     # untrack + ignore RUNTIME_MUTABLE
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANIFEST_PATH = ROOT / ".workbuddy-ai" / "RUNTIME_MUTABLE_STATE_MANIFEST.json"
GITIGNORE = ROOT / ".gitignore"
BLOCK_BEGIN = "# --- runtime-mutable state (RUNTIME_MUTABLE_STATE_MANIFEST) ---"
BLOCK_END = "# --- /runtime-mutable state ---"

SCAN_DIRS = ("config", "knowledge", "learning", "dataset", "evidence", ".workbuddy-ai")

RUNTIME_MUTABLE = "RUNTIME_MUTABLE"
VERSIONED_KNOWLEDGE = "VERSIONED_KNOWLEDGE"
VERSIONED_EVIDENCE = "VERSIONED_EVIDENCE"
GENERATED_ARTIFACT = "GENERATED_ARTIFACT"

# --- rules, in evaluation order (first match wins) -------------------------
# RUNTIME_MUTABLE: exactly what the running loop rewrites.  Every pattern here is
# justified by a writer in winter_agent_v2/ or tools/run_live.py, or by the change
# set observed during a live AUTO run.
RUNTIME_MUTABLE_GLOBS: tuple[str, ...] = (
    # ledgers: append-only streams the loop writes every cycle
    "learning/**/*.jsonl",
    # control-panel runtime state, including the pump heartbeat and the pid
    "learning/control_panel/**",
    # role-local timer/state (resource rotation, stamina supply, goal fairness, ...)
    "learning/roles/**",
    # runtime knowledge-bootstrap / capability-bootstrap live progress
    "learning/knowledge_bootstrap/**",
    "learning/capability_bootstrap/**",
    # named live state -- the operator's own enumeration, each with a writer in
    # winter_agent_v2/ or tools/run_live.py
    "learning/runtime_snapshot.json",
    "learning/goal_state.json",
    "learning/event_goal_state.json",
    "learning/role_identity.json",
    "learning/global_scheduler_state.json",
    "learning/DEVICE_LEASE.json",
    "learning/timed_event_schedule.json",
    "learning/stamina_supply.json",
    "learning/stamina_priority_state.json",
    "learning/resource_rotation.json",
    "learning/candidate_attempt_pool.json",
    "learning/bear_role.json",
    # control panel + policy runtime state (operator intent, task toggles)
    "config/control_panel_state.json",
    "config/policy_state.json",
    "config/*.bak_*",
)

GENERATED_ARTIFACT_GLOBS: tuple[str, ...] = (
    "knowledge/analysis/top_failures.json",
    "knowledge/analysis/current_failures.json",
    "knowledge/goals/capability_skill_map.json",
    "knowledge/preload/INDEX.json",
    "knowledge/preload/TROOP_SELECT.json",
    "knowledge/perception/candidates/INDEX.json",
    "knowledge/perception/pages/INDEX.json",
    "knowledge/ui/page_transitions.json",
    "evidence/INDEX.json",
    "learning/current_truth.json",
    "learning/goal_coverage.json",
    "learning/truth_source_audit/**",
    "docs/CAPABILITY_COVERAGE.md",
    "docs/TOP_FAILURES.md",
    "docs/CURRENT_TRUTH.md",
    ".workbuddy-ai/handoff/**",
    ".workbuddy-ai/RUNTIME_MUTABLE_STATE_MANIFEST.json",
)


def _glob_to_regex(glob: str) -> str:
    """gitignore-style glob: ``**/`` matches zero or more directories, ``*`` stays in one.

    ``fnmatch`` is the wrong tool here: it lets ``*`` cross ``/``, so
    ``learning/**/*.jsonl`` accidentally matched ``learning/sub/deep.jsonl`` but not
    ``learning/executor_backend.jsonl`` -- a ledger the loop appends to every cycle.
    Measured on the first pass of this classifier.
    """
    out: list[str] = []
    index, size = 0, len(glob)
    while index < size:
        if glob.startswith("/**/", index):
            out.append("/(?:.*/)?")
            index += 4
            continue
        if glob.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        char = glob[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    return "^" + "".join(out) + "$"


_REGEX_CACHE: dict[str, re.Pattern[str]] = {}


def _matches(path: str, globs: tuple[str, ...]) -> bool:
    for glob in globs:
        pattern = _REGEX_CACHE.get(glob)
        if pattern is None:
            pattern = _REGEX_CACHE[glob] = re.compile(_glob_to_regex(glob))
        if pattern.match(path):
            return True
    return False


def classify(path: str) -> str:
    if _matches(path, RUNTIME_MUTABLE_GLOBS):
        return RUNTIME_MUTABLE
    if _matches(path, GENERATED_ARTIFACT_GLOBS):
        return GENERATED_ARTIFACT
    top = path.split("/", 1)[0]
    if top == "knowledge":
        return VERSIONED_KNOWLEDGE
    if top == "config":
        return VERSIONED_KNOWLEDGE
    if top in ("dataset", "evidence"):
        return VERSIONED_EVIDENCE
    if top == "learning":
        # Anything left here is a historical note/probe kept for the record.
        return VERSIONED_EVIDENCE
    if top == ".workbuddy-ai":
        return GENERATED_ARTIFACT
    return "UNCLASSIFIED"


def tracked_files() -> list[str]:
    # ``core.quotepath=false``: without it Git octal-escapes non-ASCII paths and wraps
    # them in double quotes, so a path like dataset/candidate/.../城郭_01.png arrives as
    # "\"dataset/...\345\237\216..." and classifies as UNCLASSIFIED.  Measured.
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", *SCAN_DIRS], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [line.strip().strip('"') for line in result.stdout.splitlines() if line.strip()]


def _gitignore_block(runtime_files: list[str]) -> str:
    patterns = [
        "learning/**/*.jsonl",
        "learning/control_panel/**",
        "learning/roles/**",
        "learning/knowledge_bootstrap/**",
        "learning/capability_bootstrap/**",
        "learning/runtime_snapshot.json",
        "learning/goal_state.json",
        "learning/event_goal_state.json",
        "learning/role_identity.json",
        "learning/timed_event_schedule.json",
        "learning/stamina_supply.json",
        "learning/stamina_priority_state.json",
        "learning/resource_rotation.json",
        "learning/candidate_attempt_pool.json",
        "learning/bear_role.json",
        "config/control_panel_state.json",
        "config/policy_state.json",
        "config/*.bak_*",
    ]
    lines = [
        BLOCK_BEGIN,
        "# Written by tools/build_runtime_state_manifest.py --apply.",
        "# These files live in the shared DATA_ROOT and are rewritten by the running loop.",
        "# Git must not checkout over them: the 2026-09-29 rebase rolled the live role,",
        "# the 10k-row episode ledger and the scheduler snapshot back to an 11-day-old copy.",
        f"# {len(runtime_files)} tracked files were untracked in favour of this rule.",
    ]
    lines += patterns
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def apply_untrack(runtime_files: list[str]) -> None:
    for index in range(0, len(runtime_files), 60):
        chunk = runtime_files[index:index + 60]
        done = subprocess.run(["git", "rm", "--cached", "--quiet", "--", *chunk], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode:
            print("git rm --cached failed:", done.stderr.strip()[:300])
    existing = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    if BLOCK_BEGIN in existing and BLOCK_END in existing:
        head, rest = existing.split(BLOCK_BEGIN, 1)
        _, tail = rest.split(BLOCK_END, 1)
        existing = head.rstrip("\n") + "\n\n" + _gitignore_block(runtime_files) + tail.lstrip("\n")
    else:
        existing = existing.rstrip("\n") + "\n\n" + _gitignore_block(runtime_files)
    GITIGNORE.write_text(existing, encoding="utf-8")


def live_state_on_disk() -> list[str]:
    """Files that exist under the data root and are ruled RUNTIME_MUTABLE, tracked or not.

    After ``--apply`` nothing is RUNTIME_MUTABLE *and tracked*, so the audit signal
    would be an empty list and the manifest would stop saying what the DATA_ROOT owns.
    This walks the live-state subtrees instead, so the file records the real inventory.
    """
    found: list[str] = []
    for top in ("learning", "config"):
        base = ROOT / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if _matches(relative, RUNTIME_MUTABLE_GLOBS):
                found.append(relative)
    return sorted(found)


def _markdown(payload: dict) -> str:
    summary = payload["summary"]
    on_disk = payload["runtime_mutable_on_disk"]
    shown = on_disk[:80]
    lines = [
        "# RUNTIME_MUTABLE_STATE_MANIFEST",
        "",
        "Which Git-tracked files under the shared DATA_ROOT (`E:\\无尽冬日智能体`) belong to Git,",
        "and which belong to the running loop.",
        "",
        "Why it matters: `config`/`knowledge`/`learning`/`dataset` in the pinned production worktree",
        "are junctions into this data root, so a `git checkout`/`git rebase` writes *through* them.",
        "On 2026-09-29 that rolled the live state back to an 11-day-old committed copy (wrong account,",
        "10k-row ledger truncated to 2.1k rows, scheduler snapshot from a role no longer on the device).",
        "",
        "Generated by `tools/build_runtime_state_manifest.py`; the machine-readable copy is",
        "`.workbuddy-ai/RUNTIME_MUTABLE_STATE_MANIFEST.json`.",
        "",
        "## Categories",
        "",
        "| Category | Meaning | In Git? |",
        "|---|---|---|",
        "| RUNTIME_MUTABLE | the running loop writes it | **no** (untracked + ignored, kept in DATA_ROOT) |",
        "| VERSIONED_KNOWLEDGE | rules, skill definitions, event registry, verified rules, templates, human-confirmed assets | yes |",
        "| VERSIONED_EVIDENCE | reviewed evidence corpora and historical records | yes |",
        "| GENERATED_ARTIFACT | reproducible from code + knowledge + evidence by a tool | yes (generators must preserve hand knowledge) |",
        "",
        "## Counts",
        "",
        f"- tracked files scanned: {summary['tracked_total']}",
        f"- RUNTIME_MUTABLE **and still tracked**: {summary[RUNTIME_MUTABLE]} (must be 0)",
        f"- VERSIONED_KNOWLEDGE: {summary[VERSIONED_KNOWLEDGE]}",
        f"- VERSIONED_EVIDENCE: {summary[VERSIONED_EVIDENCE]}",
        f"- GENERATED_ARTIFACT: {summary[GENERATED_ARTIFACT]}",
        f"- UNCLASSIFIED: {summary['UNCLASSIFIED']}",
        f"- live-state files on disk owned by the DATA_ROOT: {len(on_disk)}",
        "",
        "## Live state owned by the DATA_ROOT, not Git",
        "",
    ]
    lines += [f"- `{path}`" for path in shown]
    if len(on_disk) > len(shown):
        lines.append(f"- … and {len(on_disk) - len(shown)} more (see the JSON manifest)")
    lines += [
        "",
        "## Known residual risk (needs an operator decision)",
        "",
        "These files are rewritten by the running loop but are still tracked, because the project's",
        "READ-ONCE philosophy wants learned catalogs to accumulate in Git.  A checkout can still roll",
        "them back; they are re-learnable, so the blast radius is far smaller than the live state above:",
        "",
        "- `knowledge/preload/INDEX.json`, `knowledge/preload/TROOP_SELECT.json`",
        "- `knowledge/perception/pages/INDEX.json`, `knowledge/perception/candidates/INDEX.json`",
        "- `knowledge/ui/page_transitions.json`, `evidence/INDEX.json`",
        "- `knowledge/analysis/top_failures.json`, `knowledge/goals/capability_skill_map.json`",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify tracked data-root files; untrack live state")
    parser.add_argument("--json", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--md", type=Path, default=ROOT / "docs" / "RUNTIME_MUTABLE_STATE_MANIFEST.md")
    parser.add_argument("--apply", action="store_true", help="untrack RUNTIME_MUTABLE files and write .gitignore")
    parser.add_argument("--list", choices=[RUNTIME_MUTABLE, GENERATED_ARTIFACT, "UNCLASSIFIED"],
                        help="print the files in one category and exit")
    args = parser.parse_args(argv)

    files = tracked_files()
    classified = [(path, classify(path)) for path in files]
    counts = Counter(category for _, category in classified)

    runtime_files = sorted(path for path, category in classified if category == RUNTIME_MUTABLE)

    if args.list:
        for path, category in classified:
            if category == args.list:
                print(path)
        return 0

    payload = {
        "schema_version": "1.0",
        "generated_by": "tools/build_runtime_state_manifest.py",
        "data_root": r"E:\无尽冬日智能体",
        "scanned_dirs": list(SCAN_DIRS),
        "summary": {
            "tracked_total": len(files),
            **{category: counts.get(category, 0) for category in (
                RUNTIME_MUTABLE, VERSIONED_KNOWLEDGE, VERSIONED_EVIDENCE,
                GENERATED_ARTIFACT, "UNCLASSIFIED")},
        },
        "rules": {
            RUNTIME_MUTABLE: list(RUNTIME_MUTABLE_GLOBS),
            GENERATED_ARTIFACT: list(GENERATED_ARTIFACT_GLOBS),
            "VERSIONED_KNOWLEDGE": ["knowledge/**", "config/** (not runtime state)"],
            "VERSIONED_EVIDENCE": ["dataset/**", "evidence/**", "learning/** (historical notes/probes)"],
        },
        "runtime_mutable": runtime_files,
        "runtime_mutable_on_disk": live_state_on_disk(),
        "classifications": [{"path": path, "category": category} for path, category in classified],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md is not None:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(_markdown(payload), encoding="utf-8")

    print(f"scanned tracked files: {len(files)}")
    for category in (RUNTIME_MUTABLE, VERSIONED_KNOWLEDGE, VERSIONED_EVIDENCE, GENERATED_ARTIFACT, "UNCLASSIFIED"):
        print(f"  {category:20} {counts.get(category, 0)}")
    print(f"manifest: {args.json}")
    unclassified = [path for path, category in classified if category == "UNCLASSIFIED"]
    if unclassified:
        print("UNCLASSIFIED (must be fixed before this is trusted):")
        for path in unclassified[:20]:
            print("   ", path)

    if args.apply:
        before = len(runtime_files)
        apply_untrack(runtime_files)
        print(f"untracked {before} RUNTIME_MUTABLE files and updated {GITIGNORE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
