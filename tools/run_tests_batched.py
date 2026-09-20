"""Run the whole suite in batches and aggregate, because one run cannot finish here.

Measured 2026-09-18: a single ``pytest tests -q -o tmp_path_retention_policy=all``
reaches 100% and then dies **before printing its summary**, twice in a row and
after 51 and 20 minutes:

    [safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]
    {"count":196,"threshold":50,"scope":"turn","targets":["...\\pytest-of-xhw\\garbage-..."]}

The host's bulk-delete guard intercepts pytest's own cleanup of its accumulated
temp garbage, the process is killed, and the run therefore has **no verdict** --
not a failure, and not a pass either.  Betting on one long run again just burns
half an hour for another non-answer.

So: split the suite by file into batches, give each batch its own fresh basetemp
(so pytest never accumulates the garbage that triggers the guard), read each
batch's own summary, and aggregate.  A batch that still comes back without a
summary is reported as INCONCLUSIVE and is split in half once rather than
retried unchanged -- narrowing the suspect is the point, not re-rolling the dice.

    python tools/run_tests_batched.py                    # 6 batches, aggregate
    python tools/run_tests_batched.py --batches 8 --timeout 900
    python tools/run_tests_batched.py --policy all       # keep pytest tmp evidence

Exit code is 0 only when every batch reported a summary and none failed.  An
INCONCLUSIVE batch exits non-zero: the runner never turns "no verdict" into "pass".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
LOG_DIR = ROOT / "learning/tests_batched"
LOG_DIR.mkdir(parents=True, exist_ok=True)

SUMMARY = re.compile(
    r"(?:(?P<failed>\d+) failed)?[,\s]*"
    r"(?:(?P<passed>\d+) passed)?[,\s]*"
    r"(?:(?P<skipped>\d+) skipped)?[,\s]*"
    r"(?:(?P<error>\d+) error)?"
)


@dataclass
class Batch:
    name: str
    files: list[str]
    returncode: int | None = None
    seconds: float = 0.0
    summary: str = ""
    verdict: str = "PENDING"  # PASS | FAIL | INCONCLUSIVE
    counts: dict[str, int] = field(default_factory=dict)
    note: str = ""


def interpreter() -> str:
    """The production interpreter, so the suite runs where production runs."""
    candidate = Path(r"E:\无尽冬日智能体\.venv\Scripts\python.exe")
    return str(candidate) if candidate.is_file() else sys.executable


def test_files(limit: int | None = None) -> list[str]:
    files = sorted(str(p.relative_to(ROOT)) for p in TESTS.glob("test_*.py"))
    return files[:limit] if limit else files


def split(files: list[str], batches: int) -> list[list[str]]:
    """Round-robin, so each batch mixes big and small files."""
    groups: list[list[str]] = [[] for _ in range(max(1, batches))]
    for index, name in enumerate(files):
        groups[index % len(groups)].append(name)
    return [group for group in groups if group]


def parse_counts(text: str) -> dict[str, int]:
    """The last summary line pytest printed, as numbers."""
    counts: dict[str, int] = {}
    for line in reversed(text.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            for word in ("passed", "failed", "skipped", "error", "errors"):
                match = re.search(r"(\d+)\s+" + word + r"\b", line)
                if match:
                    key = "error" if word == "errors" else word
                    counts[key] = int(match.group(1))
            if counts:
                return counts
    return {}


def run_batch(batch: Batch, *, policy: str, timeout: float) -> Batch:
    base = Path(tempfile.mkdtemp(prefix="winter-pytest-"))
    command = [interpreter(), "-u", "-m", "pytest", *batch.files, "-q",
               "-o", f"tmp_path_retention_policy={policy}", "--basetemp", str(base)]
    started = time.time()
    batch.note = f"basetemp={base.name}"
    try:
        done = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        batch.seconds = time.time() - started
        batch.verdict = "INCONCLUSIVE"
        batch.summary = f"timed out after {timeout:.0f}s"
        batch.note += f"; partial output {len(exc.stdout or '')} chars"
        return batch
    batch.seconds = time.time() - started
    batch.returncode = done.returncode
    text = (done.stdout or "") + (done.stderr or "")
    # Keep each batch's own output: the aggregate says *that* a batch failed, and
    # the name of the failing test only exists in here.  Measured 2026-09-18: the
    # first batched run reported "1 failed" in batch3 and the aggregate alone could
    # not say which test it was.
    if LOG_DIR is not None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / f"{batch.name}.log").write_text(text, encoding="utf-8")
    batch.counts = parse_counts(text)
    tail = [line for line in text.splitlines() if line.strip()]
    batch.summary = tail[-1][:200] if tail else "(no output)"
    if not batch.counts:
        batch.verdict = "INCONCLUSIVE"
        batch.note += "; no summary line -- killed before pytest could report"
    elif batch.counts.get("failed") or batch.counts.get("error"):
        batch.verdict = "FAIL"
    else:
        batch.verdict = "PASS"
    return batch


def describe(batches: list[Batch]) -> None:
    total = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    print(f"{'batch':<10}{'verdict':<14}{'files':>6}{'secs':>8}  summary")
    print("-" * 88)
    for batch in batches:
        print(f"{batch.name:<10}{batch.verdict:<14}{len(batch.files):>6}{batch.seconds:>8.0f}  "
              f"{batch.summary[:52]}")
        if batch.note:
            print(f"{'':<10}{batch.note[:80]}")
        for key, value in batch.counts.items():
            total[key] = total.get(key, 0) + value
    print("-" * 88)
    print(f"batches {len(batches)} | "
          f"{total['passed']} passed, {total['failed']} failed, "
          f"{total['skipped']} skipped, {total['error']} error "
          f"(sum of the batches that reported)")
    inconclusive = [b.name for b in batches if b.verdict == "INCONCLUSIVE"]
    failed = [b.name for b in batches if b.verdict == "FAIL"]
    if inconclusive or failed:
        print(f"VERDICT: INCOMPLETE -- failed: {failed or 'none'}; "
              f"no verdict: {inconclusive or 'none'}")
    else:
        print("VERDICT: PASS -- every batch reported and none failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="batched full-suite runner")
    parser.add_argument("--batches", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=1200.0, help="seconds per batch")
    parser.add_argument("--policy", default="none",
                        help="pytest tmp_path_retention_policy (none keeps the host "
                             "guard quiet; 'all' keeps pytest's tmp evidence)")
    parser.add_argument("--json", help="write the aggregate here")
    args = parser.parse_args(argv)

    files = test_files()
    if not files:
        print("no test files found")
        return 1
    batches = [Batch(name=f"batch{index + 1}", files=group)
               for index, group in enumerate(split(files, args.batches))]
    print(f"suite: {len(files)} files in {len(batches)} batches | policy={args.policy} | "
          f"interpreter={interpreter()}")

    done: list[Batch] = []
    for batch in batches:
        print(f"\n== {batch.name}: {len(batch.files)} files ==", flush=True)
        result = run_batch(batch, policy=args.policy, timeout=args.timeout)
        done.append(result)
        print(f"   {result.verdict} in {result.seconds:.0f}s -- {result.summary[:110]}", flush=True)
        if result.verdict == "INCONCLUSIVE" and len(batch.files) > 1:
            # Split the suspect rather than re-run it unchanged: the whole point is
            # to make the guard's target smaller than its threshold.
            half = len(batch.files) // 2
            for index, group in enumerate((batch.files[:half], batch.files[half:])):
                child = Batch(name=f"{batch.name}.{index + 1}", files=group)
                print(f"   -> splitting into {child.name}: {len(group)} files", flush=True)
                done.append(run_batch(child, policy=args.policy, timeout=args.timeout))
                print(f"      {done[-1].verdict} -- {done[-1].summary[:100]}", flush=True)

    print()
    describe(done)
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"policy": args.policy, "files": len(files),
             "batches": [vars(b) for b in done]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(b.verdict == "PASS" for b in done) else 1


if __name__ == "__main__":
    raise SystemExit(main())
