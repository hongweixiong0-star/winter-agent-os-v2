"""Preflight: can the interpreter that is about to run production actually do it?

Run this before trusting a run's numbers.

    python tools/preflight.py
    python tools/preflight.py --json

Exit code is 0 only when the resolved interpreter can import every module the
production loop depends on *and* -- unless MAA is switched off in
``config/v2.json`` -- MAA is among them.

Why a command and not a paragraph: on 2026-09-17 the desktop launcher pinned a
generic Codex runtime python that ships numpy/PIL and nothing else, and the
control panel spawned its worker with its own interpreter, so the worker ran
with ``MAA_IMPORT_FAILED:ModuleNotFoundError`` and stayed on ADB.  No executed
step in those runs belonged to a skill promoted to MAA, so nothing had been
measured through the slow path yet -- but a promoted skill would have taken ADB
capture at 324 ms instead of MAA EmulatorExtras' 8.92 ms, and the run would have
looked healthy.  The only trace was one line inside a worker's piped stdout.

So this prints both halves of the question: what the interpreter *can* do, and
what the ledger says it *has been* doing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winter_agent_v2 import runtime_env  # noqa: E402

LEDGER = ROOT / "learning/executor_backend.jsonl"


def ledger_summary(limit: int = 200) -> dict[str, object]:
    """What the executor ledger says production has actually been using.

    Reads only; the ledger is append-only production evidence and is never
    rewritten.  ``used_backend`` is the axis that matters: it is what the step
    really did, not what was preferred.
    """
    if not LEDGER.is_file():
        return {"rows": 0, "note": "no ledger yet"}
    lines = LEDGER.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    recent = lines[-limit:]
    used: Counter[str] = Counter()
    capture: Counter[str] = Counter()
    parsed = 0
    last: dict[str, object] | None = None
    for line in recent:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed += 1
        used[str(row.get("used_backend") or "(none)")] += 1
        capture[str(row.get("capture_backend") or "(none)")] += 1
        last = row
    return {
        "rows": len(lines),
        "rows_examined": parsed,
        "used_backend": dict(used.most_common()),
        "capture_backend": dict(capture.most_common()),
        "last_recorded_at": (last or {}).get("recorded_at"),
        "last_skill": (last or {}).get("skill_id"),
        "last_used_backend": (last or {}).get("used_backend"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Winter Agent OS V2 runtime preflight")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--ledger-limit", type=int, default=200, help="ledger rows to summarise")
    args = parser.parse_args(argv)

    maa_enabled = runtime_env.maa_enabled_from_config(ROOT)
    report = runtime_env.resolve_for_project(ROOT)
    ledger = ledger_summary(args.ledger_limit)

    if args.json:
        print(json.dumps(
            {
                "root": str(ROOT),
                "maa_enabled": maa_enabled,
                "ok": report.ok,
                "reason": report.reason,
                "interpreter": str(report.python_exe),
                "present": list(report.present),
                "missing": list(report.missing),
                "errors": report.errors,
                "fell_back_from": str(report.fell_back_from) if report.fell_back_from else None,
                "candidates": [{"exe": exe, "ok": ok} for exe, ok in report.candidates],
                "requirements": [
                    {"module": module, "role": role, "why": why}
                    for module, role, why in runtime_env.requirements_table(maa_enabled=maa_enabled)
                ],
                "ledger": ledger,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0 if report.ok else 1

    print("== Winter Agent OS V2 preflight ==")
    print(f"root        : {ROOT}")
    print(f"MAA enabled : {maa_enabled}  (config/v2.json -> executor.maa.enabled)")
    print()
    print(report.describe())
    print()
    print("candidates probed:")
    for exe, ok in report.candidates:
        print(f"  [{'OK  ' if ok else 'FAIL'}] {exe}")
    print()
    print("executor ledger (what production has really been using):")
    print(f"  rows              : {ledger.get('rows')}")
    print(f"  used_backend      : {json.dumps(ledger.get('used_backend'), ensure_ascii=False)}")
    print(f"  capture_backend   : {json.dumps(ledger.get('capture_backend'), ensure_ascii=False)}")
    print(f"  last step         : {ledger.get('last_skill')} via {ledger.get('last_used_backend')} "
          f"at {ledger.get('last_recorded_at')}")
    print()
    if report.ok:
        print(f"VERDICT: PASS - {report.python_exe} can run production")
        return 0
    print(f"VERDICT: FAIL - {report.reason}")
    if maa_enabled and "maa" in report.missing:
        print("         MAA is enabled but not importable here. The production loop would")
        print("         silently fall back to ADB, which is a defect, not a degradation.")
    print("         Fix the interpreter (config/v2.json -> runtime.python_path) or the env.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
