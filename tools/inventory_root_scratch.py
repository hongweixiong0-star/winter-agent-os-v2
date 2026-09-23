"""Inventory the repo root's command-output scratch files before touching any of them.

Why this exists rather than a shell one-liner: the operator asked for a *classified* cleanup
(2026-09-23 item 5), and the classification needs facts this machine can only get from Python --
``.gitignore``'s own rule set, whether anything in the repository names a file, and how old it is.
It was also the only way to find out that ``.gitignore`` already documents this class:

    # command-output capture files: this machine cannot pipe stdout (no coreutils),
    # so every probe writes out_*.txt and pages it back with Read
    out.txt
    out_*.txt

so the files are ignored by design and the sibling rule for ``out_*.png`` says "Ignored rather than
deleted".  The cleanup therefore **moves** them into a dated archive rather than removing them, and
the archive keeps a manifest so every path is reversible.

Reference search covers tracked text files only: the code, tests, tools, knowledge, docs and the
handoff.  A name that appears in one of those is in use; a name that appears nowhere was written by
a probe and read once.

Usage:
    python tools/inventory_root_scratch.py                 # report only
    python tools/inventory_root_scratch.py --apply         # archive the ARCHIVE class
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Where a moved file goes.  Inside the project (nothing outside it is touched) and under a name
#: the existing ``out_*.txt`` ignore rule still matches, so a moved file cannot start appearing in
#: ``git status``.
ARCHIVE_DIR = ROOT / "learning/archive/root_scratch_20260923"

SEARCH_SUFFIXES = (".py", ".json", ".jsonl", ".log", ".md", ".txt", ".yaml", ".yml", ".toml",
                   ".ini", ".cfg", ".tsv")
SKIP_DIRS = {".git", "dataset", "node_modules", "__pycache__", ".venv", "learning/archive"}


def _scratch_files(pattern: str) -> list[Path]:
    return sorted(path for path in ROOT.glob(pattern) if path.is_file())


def _is_ignored(path: Path) -> bool:
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-q", str(path.relative_to(ROOT))],
            cwd=ROOT, capture_output=True,
        )
    except OSError:
        return False
    return done.returncode == 0


def _referenced_names(names: set[str]) -> set[str]:
    """Which of these file names anything in the repository mentions."""
    found: set[str] = set()
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.name in names:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SEARCH_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in names:
            if name in found:
                continue
            if name in text:
                found.add(name)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="out*.txt")
    parser.add_argument("--apply", action="store_true", help="move the ARCHIVE class")
    parser.add_argument("--recent-hours", type=float, default=12.0,
                        help="a file this new belongs to the task still running")
    parser.add_argument("--archive", type=Path, default=ARCHIVE_DIR)
    args = parser.parse_args()

    files = _scratch_files(args.pattern)
    if not files:
        print("nothing matched -- nothing to do")
        return 0
    names = {path.name for path in files}
    referenced = _referenced_names(names)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.recent_hours)

    rows = []
    for path in files:
        stat = path.stat()
        moment = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if path.name in referenced:
            verdict = "KEEP_REFERENCED"
        elif moment >= cutoff:
            verdict = "KEEP_IN_USE"
        else:
            verdict = "ARCHIVE"
        rows.append({
            "path": str(path.relative_to(ROOT)),
            "name": path.name,
            "bytes": stat.st_size,
            "modified": moment.isoformat(),
            "git_ignored": _is_ignored(path),
            "referenced_by": sorted(
                f"{p.relative_to(ROOT)}" for p in ()
            ),
            "verdict": verdict,
        })

    by_verdict: dict[str, list[dict]] = {}
    for row in rows:
        by_verdict.setdefault(row["verdict"], []).append(row)

    print(f"pattern {args.pattern!r}: {len(rows)} files, "
          f"{sum(row['bytes'] for row in rows) / 1024 / 1024:.1f} MB")
    for verdict in sorted(by_verdict):
        group = by_verdict[verdict]
        print(f"  {verdict:<16} {len(group):>4} files  "
              f"{sum(row['bytes'] for row in group) / 1024 / 1024:>7.1f} MB")
    print()
    print(f"  ignored by .gitignore : {sum(1 for row in rows if row['git_ignored'])} of {len(rows)}")
    print(f"  referenced anywhere   : {len(referenced)} name(s): {sorted(referenced)[:8]}")
    oldest = min(row["modified"] for row in rows)
    newest = max(row["modified"] for row in rows)
    print(f"  modified between      : {oldest[:19]} .. {newest[:19]}")
    print()
    for row in sorted(by_verdict.get("KEEP_REFERENCED", []), key=lambda r: r["name"])[:12]:
        print(f"  KEEP {row['name']:<28} {row['bytes']:>9} B  {row['modified'][:19]}")

    if not args.apply:
        print()
        print("report only (--apply moves the ARCHIVE class)")
        return 0

    args.archive.mkdir(parents=True, exist_ok=True)
    moved = []
    for row in sorted(by_verdict.get("ARCHIVE", []), key=lambda r: r["name"]):
        source = ROOT / row["path"]
        target = args.archive / row["name"]
        if target.exists():
            target = args.archive / f"{source.stem}__{source.stat().st_mtime_ns}{source.suffix}"
        shutil.move(str(source), str(target))
        moved.append({**row, "archived_as": str(target.relative_to(ROOT))})
    manifest = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "pattern": args.pattern,
        "recent_hours_kept": args.recent_hours,
        "moved": moved,
        "kept": [row for row in rows if row["verdict"] != "ARCHIVE"],
    }
    (args.archive / "INDEX.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"archived {len(moved)} file(s) into {args.archive.relative_to(ROOT)} "
          f"({sum(row['bytes'] for row in moved) / 1024 / 1024:.1f} MB)")
    print(f"kept {len(manifest['kept'])} in the root; manifest: "
          f"{(args.archive / 'INDEX.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
