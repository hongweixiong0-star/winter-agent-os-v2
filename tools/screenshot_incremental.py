# -*- coding: utf-8 -*-
"""Incremental screenshot processing: register what is new, skip what is already analysed, resume.

Reuses the existing durable state instead of inventing a task database:

* the inventory   -- ``knowledge/ui/screenshot_audit/SCREENSHOT_INVENTORY.csv`` (one row per file,
  with its SHA-256 and duplication group);
* the processed set -- ``SCREENSHOT_ANALYSIS.jsonl``: an image counts as processed when its sha256 has
  a row whose ``analysis_status`` is anything other than ``NOT_ANALYSED_IN_THIS_PASS``;
* the progress file -- a small JSON beside them, so an interrupted run continues instead of restarting.

Why hash-keyed rather than path-keyed: the corpus is live. Measured 2026-10-10, 145 of the files
hashed at 10:36 were gone by 10:58 while 108 new ones existed, because ``retention.py`` prunes RAW
captures on a 3-day TTL. A path-keyed diff would report churn that is not knowledge; a content-keyed
one reports only images nobody has seen before, and is immune to renames.

CLI:
    python tools/screenshot_incremental.py --root . [--json]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path("knowledge/ui/screenshot_audit")
INVENTORY_NAME = "SCREENSHOT_INVENTORY.csv"
ANALYSIS_NAME = "SCREENSHOT_ANALYSIS.jsonl"
PROGRESS_NAME = "incremental_progress.json"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

#: Statuses that mean "a model actually looked at this image". Anything else, including a missing
#: row, counts as not yet processed.
NOT_PROCESSED_STATUS = "NOT_ANALYSED_IN_THIS_PASS"


def sha256_of(path: Path, *, chunk: int = 1 << 20) -> str | None:
    """Content hash, or None when the file cannot be read (a pruned or locked capture)."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(chunk), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def scan_images(root: Path) -> dict[str, list[str]]:
    """``sha256 -> [paths]`` for every image under root, skipping VCS internals."""
    found: dict[str, list[str]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules"}]
        for name in filenames:
            if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            path = Path(dirpath) / name
            digest = sha256_of(path)
            if digest:
                found.setdefault(digest, []).append(str(path))
    return found


def load_processed(audit_dir: Path) -> set[str]:
    """sha256 values that already have a real analysis row."""
    processed: set[str] = set()
    path = audit_dir / ANALYSIS_NAME
    if not path.is_file():
        return processed
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            digest = str(row.get("sha256") or "")
            if digest and str(row.get("analysis_status") or "") != NOT_PROCESSED_STATUS:
                processed.add(digest)
    return processed


def plan(root: Path, audit_dir: Path | None = None) -> dict:
    """What is new, what is already analysed, and what has gone away since the inventory was written."""
    audit = audit_dir or (root / AUDIT_DIR)
    present = scan_images(root)
    processed = load_processed(audit)

    inventoried: set[str] = set()
    inventory_path = audit / INVENTORY_NAME
    if inventory_path.is_file():
        with inventory_path.open(encoding="utf-8", errors="replace") as handle:
            inventory_path_rows = csv.DictReader(handle)
            inventoried = {str(r.get("sha256") or "") for r in inventory_path_rows}
    inventoried.discard("")

    new = sorted(set(present) - inventoried)
    gone = sorted(inventoried - set(present)) if inventoried else []
    # An image with a real analysis row must never re-enter the work list, even when the inventory
    # is missing or stale. Keying this on the inventory alone made an analysed image look like new
    # work whenever the inventory was absent, which is exactly the case a resume has to survive.
    needs_analysis = [digest for digest in new if digest not in processed]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "images_present": sum(len(v) for v in present.values()),
        "unique_by_content": len(present),
        "already_processed": sorted(set(present) & processed),
        "new_since_inventory": new,
        "gone_since_inventory": gone,
        "needs_analysis": needs_analysis,
        "root": str(root),
    }


def write_progress(audit_dir: Path, payload: dict, *, completed: list[str] | None = None) -> Path:
    """Persist the run so an interruption resumes instead of redoing work."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / PROGRESS_NAME
    previous = load_progress(audit_dir)
    already = set(previous.get("completed") or ())
    already |= set(completed or ())
    record = {
        "schema_version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "root": payload.get("root"),
        "new_since_inventory": payload.get("new_since_inventory") or [],
        "completed": sorted(already),
        "remaining": sorted(set(payload.get("new_since_inventory") or ()) - already),
        "counts": {
            "images_present": payload.get("images_present"),
            "unique_by_content": payload.get("unique_by_content"),
            "already_processed": len(payload.get("already_processed") or ()),
            "new_since_inventory": len(payload.get("new_since_inventory") or ()),
            "gone_since_inventory": len(payload.get("gone_since_inventory") or ()),
        },
        "failures": previous.get("failures") or [],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_progress(audit_dir: Path) -> dict:
    """The last persisted run, or an empty record. Never raises."""
    path = audit_dir / PROGRESS_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def record_failure(audit_dir: Path, digest: str, reason: str) -> None:
    """Failures are kept with their reason, per the round's requirement to be able to continue."""
    record = load_progress(audit_dir)
    failures = [f for f in record.get("failures") or [] if f.get("sha256") != digest]
    failures.append({"sha256": digest, "reason": reason,
                     "at": datetime.now(timezone.utc).isoformat()})
    record["failures"] = failures
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / PROGRESS_NAME).write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--audit-dir", default=None)
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    parser.add_argument("--write-progress", action="store_true",
                        help="persist the plan so an interrupted run can resume")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    audit = Path(args.audit_dir).resolve() if args.audit_dir else (root / AUDIT_DIR)
    result = plan(root, audit)

    if args.write_progress:
        path = write_progress(audit, result)
        result["progress_file"] = str(path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"root                 : {root}")
        print(f"images present       : {result['images_present']}")
        print(f"unique by content    : {result['unique_by_content']}")
        print(f"already processed    : {len(result['already_processed'])}")
        print(f"NEW since inventory  : {len(result['new_since_inventory'])}")
        print(f"gone since inventory : {len(result['gone_since_inventory'])}")
        if result.get("progress_file"):
            print(f"progress written to  : {result['progress_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
