"""Loop the INTEL goal on the live client until the operator's task is done.

Operator directive 2026-09-14: keep running intel cycles until the intel task
list is drained (spend stamina on beasts first, claim every completed reward),
and only then move on to other goals.

Each cycle shells out to tools/run_live.py --goal INTEL, which is the real
loop (vision -> brain -> executor -> verifier, guard included).  The harness
only orchestrates repetition and bookkeeping; it never taps the game itself.

Stop conditions (all honest, reported in the summary):
- MAX_CYCLES reached
- stamina is below the cost of one beast march AND nothing is claimable
- the list stays NOT_AVAILABLE for QUIET_CYCLES consecutive cycles with no
  march out and nothing claimable (refresh timer governs; not observable
  from the intel page alone)
- a cycle crashes in a way the loop cannot recover from (kept: retry next)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_LIVE = ROOT / "tools" / "run_live.py"
LOG_DIR = ROOT / "evidence"
STAMP = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

MAX_CYCLES = int(sys.argv[1]) if len(sys.argv) > 1 else 12
CYCLE_TIMEOUT = 420          # seconds per run_live invocation
SLEEP_BETWEEN = 120          # seconds between cycles
QUIET_CYCLES = 3             # consecutive NOT_AVAILABLE before giving up
STAMINA_FLOOR = 10           # one beast march costs 10


def parse_result(text: str) -> dict:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}


def summarize(payload: dict) -> dict:
    steps = payload.get("steps") or []
    stamina_before = stamina_after = None
    dispatches = claims = 0
    for step in steps:
        skill = str((step.get("decision") or {}).get("skill"))
        verification = step.get("verification") or {}
        before = step.get("before") or {}
        after = step.get("after") or {}
        if (before.get("stamina") or {}).get("current") is not None:
            stamina_before = (before.get("stamina") or {}).get("current")
        if (after.get("stamina") or {}).get("current") is not None:
            stamina_after = (after.get("stamina") or {}).get("current")
        if skill == "DISPATCH_INTEL_BEAST" and verification.get("ok") is True:
            dispatches += 1
        if skill in ("INTEL_CLAIM_REWARDS", "CLAIM_INTEL_REWARD") and verification.get("ok") is True:
            claims += 1
    return {
        "stop_reason": payload.get("stop_reason"),
        "steps": len(steps),
        "dispatches": dispatches,
        "claims": claims,
        "stamina_before": stamina_before,
        "stamina_after": stamina_after,
    }


def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"intel_loop_{STAMP}.log"
    log = log_path.open("a", encoding="utf-8")
    cycles: list[dict] = []
    quiet = 0
    print(f"intel loop start {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
          f"max_cycles={MAX_CYCLES} log={log_path.name}", flush=True)
    try:
        for index in range(1, MAX_CYCLES + 1):
            capture = f"dataset/raw/control_panel/runtime_auto/intel_loop_{STAMP}_c{index:02d}"
            started = time.monotonic()
            proc = subprocess.run(
                [sys.executable, "-u", str(RUN_LIVE),
                 "--goal", "INTEL", "--max-actions", "14",
                 "--serial", "127.0.0.1:7555",
                 "--capture-dir", capture],
                capture_output=True, text=True, errors="replace",
                cwd=str(ROOT), timeout=CYCLE_TIMEOUT,
            )
            elapsed = round(time.monotonic() - started, 1)
            payload = parse_result(proc.stdout)
            info = summarize(payload)
            info.update({
                "cycle": index,
                "exit_code": proc.returncode,
                "elapsed_s": elapsed,
                "capture_dir": capture,
            })
            cycles.append(info)
            line = json.dumps(info, ensure_ascii=False)
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()

            stamina = info["stamina_after"] if info["stamina_after"] is not None else info["stamina_before"]
            if info["stop_reason"] == "intel_not_available" and not info["claims"] and not info["dispatches"]:
                quiet += 1
            else:
                quiet = 0
            if stamina is not None and stamina < STAMINA_FLOOR:
                print(f"STOP: stamina {stamina} below {STAMINA_FLOOR}; nothing left to spend", flush=True)
                break
            if quiet >= QUIET_CYCLES:
                print(f"STOP: intel list stayed empty for {QUIET_CYCLES} consecutive cycles; "
                      "waiting for the refresh timer is out of scope for this loop", flush=True)
                break
            if index < MAX_CYCLES:
                time.sleep(SLEEP_BETWEEN)
    except subprocess.TimeoutExpired:
        print("STOP: a cycle exceeded the per-cycle timeout", flush=True)
    finally:
        log.close()

    total_dispatch = sum(c["dispatches"] for c in cycles)
    total_claims = sum(c["claims"] for c in cycles)
    print("\n=== INTEL LOOP SUMMARY ===", flush=True)
    print(json.dumps({
        "cycles": len(cycles),
        "dispatches": total_dispatch,
        "claims": total_claims,
        "stamina_first_seen": next((c["stamina_before"] for c in cycles if c["stamina_before"] is not None), None),
        "stamina_last_seen": next((c["stamina_after"] for c in reversed(cycles) if c["stamina_after"] is not None), None),
        "per_cycle": cycles,
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
