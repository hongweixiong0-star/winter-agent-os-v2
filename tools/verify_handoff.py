"""Verify the handoff mechanism's structural invariants.

The cross-account handoff is only useful if its *structure* is guaranteed: the
required files exist, every AUTO block has exactly one pair of markers (so
regeneration is idempotent and hand-written prose is never duplicated), the
generated files declare their provenance instead of hard-coding history, and
START_HERE.md actually warns a fresh account about the environment traps that
waste hours if unknown.

``audit()`` is importable so the test suite can assert the same invariants.

Run: python tools/verify_handoff.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "00_MASTER_RULES.md",
    "01_CURRENT_TRUTH.md",
    "02_CURRENT_PROGRESS.md",
    "03_NEXT_ACTION.md",
    "04_OPEN_ISSUES.md",
    "05_RECENT_CHANGES.md",
    "06_DECISIONS.md",
    "07_EXTERNAL_REUSE.md",
    "08_LIVE_METRICS.json",
    "09_RUNTIME_STATE.json",
    "10_LAST_HANDOFF.md",
]
AUTO_FILES = {
    "02_CURRENT_PROGRESS.md": "progress",
    "03_NEXT_ACTION.md": "next_action",
    "04_OPEN_ISSUES.md": "open_issues",
    "05_RECENT_CHANGES.md": "recent_commits",
    "10_LAST_HANDOFF.md": "last_handoff",
}
GENERATED_MARKERS = {
    "01_CURRENT_TRUTH.md": ["generated_at", "commit:", "source:"],
    "08_LIVE_METRICS.json": ["generated_at", "commit", "source"],
    "09_RUNTIME_STATE.json": ["generated_at", "commit", "source"],
}
START_HERE_TRAPS = ["coreutils", "PowerShell", "dongri-mumu-bot", "MuMuManager"]
HANDWRITTEN = {
    "00_MASTER_RULES.md": ["顶层架构冻结", "Semantic", "Verifier", "真实支付", "72"],
    "03_NEXT_ACTION.md": ["手写", "坑"],
    "04_OPEN_ISSUES.md": ["P0"],
    "06_DECISIONS.md": ["D-013", "D-001"],
    "07_EXTERNAL_REUSE.md": ["REFERENCE_ONLY", "接入台账"],
    "10_LAST_HANDOFF.md": ["DO NOT REPEAT", "WHAT NOT VERIFIED"],
}


def audit(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Return ``(report_lines, failures)`` for the handoff directory."""
    handoff = root / ".workbuddy-ai" / "handoff"
    lines: list[str] = []
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    lines.append("1. required files")
    for name in REQUIRED:
        path = handoff / name
        ok = path.is_file() and path.stat().st_size > 200
        check(ok, f"missing or empty: {name}")
        lines.append(f"   {'OK ' if ok else 'MISS'} {name}")
    start = root / "START_HERE.md"
    check(start.is_file(), "START_HERE.md missing at repo root")
    lines.append(f"   {'OK ' if start.is_file() else 'MISS'} START_HERE.md (repo root)")

    lines.append("2. AUTO block structure")
    for name, block in AUTO_FILES.items():
        path = handoff / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        opens = text.count(f"<!-- AUTO:{block} -->")
        closes = text.count(f"<!-- /AUTO:{block} -->")
        ok = opens == 1 and closes == 1
        check(ok, f"{name}: AUTO:{block} opens={opens} closes={closes}")
        lines.append(f"   {'OK ' if ok else 'BAD'} {name} AUTO:{block} opens={opens} closes={closes}")

    lines.append("3. generated files declare provenance")
    for name, markers in GENERATED_MARKERS.items():
        path = handoff / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        missing = [m for m in markers if m not in text]
        check(not missing, f"{name}: missing markers {missing}")
        lines.append(f"   {'OK ' if not missing else 'BAD'} {name}")

    lines.append("4. START_HERE warns about the environment traps")
    start_text = start.read_text(encoding="utf-8") if start.is_file() else ""
    missing_traps = [t for t in START_HERE_TRAPS if t not in start_text]
    check(not missing_traps, f"START_HERE.md missing environment warnings: {missing_traps}")
    lines.append(f"   {'OK ' if not missing_traps else 'BAD'} traps={START_HERE_TRAPS}")

    lines.append("5. hand-written sections survived regeneration")
    for name, needles in HANDWRITTEN.items():
        path = handoff / name
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        missing = [n for n in needles if n not in text]
        check(not missing, f"{name}: lost hand-written content {missing}")
        lines.append(f"   {'OK ' if not missing else 'BAD'} {name}")

    lines.append("6. metrics json parses and carries provenance")
    metrics_path = handoff / "08_LIVE_METRICS.json"
    metrics = {}
    if metrics_path.is_file():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            check(False, f"08_LIVE_METRICS.json unparsable: {exc}")
    for key in ("generated_at", "source", "commit", "episodes", "skills", "goals", "evidence_integrity"):
        check(key in metrics, f"08_LIVE_METRICS.json missing {key}")
    lines.append(f"   keys={sorted(metrics)[:8]}")

    lines.append("7. AUTO markers use only word characters")
    for name, block in AUTO_FILES.items():
        check(bool(re.fullmatch(r"[a-z_]+", block)), f"{name}: bad block id {block}")
    return lines, failures


def main() -> int:
    lines, failures = audit()
    for line in lines:
        print(line)
    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("ALL HANDOFF INVARIANTS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
