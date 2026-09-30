"""Repin the pinned production worktree to a target commit WITHOUT touching the shared data root.

Reusable version of the _repin_prod*.py one-offs.  The pinned worktree mounts
config/knowledge/learning/dataset as junctions into E:\\无尽冬日智能体 (the shared DATA_ROOT), so a
plain ``git checkout <new>`` writes tracked files *through* those junctions and rolls live
runtime state back -- measured 2026-09-29, when that truncated a 10k-row episode ledger to 2.1k.
So this moves HEAD + index only (``reset --mixed`` never touches the working tree) and then syncs
the *code* paths, explicitly excluding the four mounted data directories.

usage:
    python tools/repin_production.py --to <commit> [--check-only]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKTREE_HOME = Path(r"C:\Users\xhw\.codex\worktrees\winter-prod-pinned")
WT = WORKTREE_HOME / "无尽冬日智能体"
MANIFEST = WORKTREE_HOME / "PRODUCTION_PIN.json"
DATA = ("config", "knowledge", "learning", "dataset")
# Untracked evidence dirs are pre-existing and not part of the code sync.
IGNORE_PREFIXES = ("evidence/gui_workbuddy_loop",)


def git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    result = subprocess.run(["git", "-C", str(cwd or WT), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout, result.stderr


def outside_rows() -> tuple[list[str], list[str]]:
    _, out, _ = git("-c", "core.quotepath=false", "status", "--porcelain=v1",
                    "--untracked-files=normal")
    rows = [line.rstrip("\n") for line in out.splitlines() if line.strip()]
    outside = []
    for line in rows:
        path = line[3:].strip().strip('"').replace("\\", "/")
        if any(path == name or path.startswith(name + "/") for name in DATA):
            continue
        if any(path.startswith(prefix) for prefix in IGNORE_PREFIXES):
            continue
        outside.append(line)
    return rows, outside


def report(tag: str) -> int:
    _, out, _ = git("rev-parse", "HEAD")
    print(f"[{tag}] HEAD = {out.strip()}")
    rows, outside = outside_rows()
    print(f"[{tag}] status rows total={len(rows)} outside_data_dirs={len(outside)}")
    for line in outside[:60]:
        print("   OUT", line)
    return len(outside)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True, help="commit to pin (full sha preferred)")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--no-manifest", action="store_true",
                        help="do not rewrite PRODUCTION_PIN.json.expected_commit")
    args = parser.parse_args(argv)

    print(f"WT = {WT}")
    print(f"TARGET = {args.to}")
    print("=" * 70)
    dirty = report("BEFORE")
    if args.check_only:
        print("RESULT:", "CLEAN_OUTSIDE_DATA" if dirty == 0 else f"STILL_DIRTY={dirty}")
        return 0 if dirty == 0 else 1

    print("=" * 70)
    rc, _, err = git("reset", "--mixed", args.to)
    print("git reset --mixed rc =", rc, "|", err.strip()[:300])
    if rc != 0:
        return 1
    report("AFTER_RESET")

    print("=" * 70)
    rc, _, err = git("checkout", args.to, "--", ".",
                     ":(exclude)config", ":(exclude)knowledge",
                     ":(exclude)learning", ":(exclude)dataset")
    print("git checkout (code only) rc =", rc, "|", err.strip()[:400])
    if rc != 0:
        return 1
    n_out = report("AFTER_CHECKOUT")

    if not args.no_manifest:
        _, sha, _ = git("rev-parse", "HEAD")
        sha = sha.strip()
        import json

        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        previous = data.get("expected_commit")
        data["expected_commit"] = sha
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[manifest] expected_commit {previous} -> {sha}")

    print("=" * 70)
    print("RESULT:", "CLEAN_OUTSIDE_DATA" if n_out == 0 else f"STILL_DIRTY={n_out}")
    return 0 if n_out == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
