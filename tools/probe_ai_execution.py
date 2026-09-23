"""Watch the two live questions the operator asked, from the record, and say when they are answered.

    python tools/probe_ai_execution.py                 # one look, right now
    python tools/probe_ai_execution.py --watch 55       # keep looking for up to 55 minutes

Read-only: no device, no clicks, no network, no writes to anything but its own stdout.

**Question 1 -- was an AI advice really executed?**  The chain is
``request_id -> answer written -> AUTO adopts it -> MAA acts -> the after-frame verifies``, and each
link has its own evidence, so each is reported separately rather than being inferred from the next:

* ``answers``      -- the answer files on disk, with the time each landed;
* ``ai_advice``    -- steps whose episode carries one.  ``runtime.py`` fills that field only when an
  answer was really reached on a live frame, so a step here is the AUTO adopting advice;
* ``MAA``          -- of those steps, which ones the executor ran ``used_backend=MAA``;
* ``after``        -- the step's own ``state_after`` and ``verifier_evidence``, i.e. what changed.

**Question 2 -- did 实力详情 work on the real device?**  ``OPEN_POWER_DETAILS`` is reported per step:
its ``tap_point``, whether the after-frame is ``POWER_DETAILS``, and the failure type when it is not.
The judgement is the after-frame, not that a coordinate was produced.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
EXECUTOR = ROOT / "learning/executor_backend.jsonl"
ANSWERS = ROOT / "learning/unknown_requests/answers"

#: The commit that landed the printed-name fix for 实力详情 (``78bf834``).  A failure before it says
#: nothing about the fix; one after it does.  Kept as a string because it is compared to
#: ``recorded_at``, and the point of the constant is that a reader can see which side of the line
#: any given step falls on.
PRINTED_NAME_FIX_AT = "2026-09-23T09:58:56+00:00"


def _rows(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return out
    with handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _page(state: object) -> str:
    if not isinstance(state, dict):
        return ""
    page = state.get("page")
    return str(page.get("value") if isinstance(page, dict) else page or "")


def _stamp(value: object) -> str:
    return str(value or "")[11:19]


def look(*, verbose: bool = False) -> dict:
    """One pass over the artefacts.  Returns the findings, so a caller can decide to stop."""
    answers = sorted(
        (path for path in ANSWERS.glob("*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    found = {
        "answers": [
            {"name": path.name, "landed": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat()} for path in answers
        ],
        "advised_steps": [],
        "power_details": [],
    }

    episodes = _rows(EPISODES)
    executor = {str(row.get("recorded_at")): row for row in _rows(EXECUTOR) if row.get("recorded_at")}
    for row in episodes:
        if row.get("ai_advice"):
            found["advised_steps"].append(row)
        if str(row.get("skill")) == "OPEN_POWER_DETAILS":
            found["power_details"].append(row)
    found["executor"] = executor
    found["episodes"] = len(episodes)

    print(f"=== answers on disk: {len(answers)} ===")
    for item in found["answers"]:
        print(f"  {item['name']:<34} landed {item['landed'][11:19]}Z")

    print()
    print(f"=== steps that adopted an AI advice: {len(found['advised_steps'])} "
          f"(of {len(episodes)} episodes on file) ===")
    if not found["advised_steps"]:
        print("  (none yet -- runtime.py fills ai_advice only when an answer was really reached)")
    for row in found["advised_steps"][-6:]:
        advice = row.get("ai_advice") or {}
        if isinstance(advice, (list, tuple)) and advice:
            advice = advice[0]
        after = row.get("state_after") or {}
        print(f"  {str(row.get('recorded_at'))[5:19]} {str(row.get('skill'))}")
        print(f"     request_id : {advice.get('request_id') if isinstance(advice, dict) else advice}")
        print(f"     action     : {advice.get('proposed_action') if isinstance(advice, dict) else ''}"
              f"   basis {(advice.get('grounding_basis') if isinstance(advice, dict) else '')}")
        print(f"     result     : {row.get('result')}  {row.get('failure_type') or ''}")
        print(f"     after      : page {_page(after)!r} popup {after.get('popup')!r}")
        print(f"     evidence   : {json.dumps(row.get('verifier_evidence'), ensure_ascii=False)}")

    print()
    live = [row for row in found["power_details"]
            if str(row.get("recorded_at") or "") >= PRINTED_NAME_FIX_AT]
    print(f"=== OPEN_POWER_DETAILS since the printed-name fix ({PRINTED_NAME_FIX_AT[11:19]}Z): "
          f"{len(live)} step(s), of {len(found['power_details'])} all time ===")
    if not live:
        print("  (the popup has not been met since the fix landed, so the fix is still unexercised)")
    for row in live[-6:]:
        after = row.get("state_after") or {}
        point = executor.get(str(row.get("recorded_at")), {})
        print(f"  {str(row.get('recorded_at'))[5:19]} {row.get('result')} "
              f"{row.get('failure_type') or ''}")
        print(f"     tap_point  : {point.get('tap_point')}   backend {point.get('used_backend')}")
        print(f"     before     : {(row.get('state_before') or {}).get('popup')!r}"
              f"   after: page {_page(after)!r} popup {after.get('popup')!r}")
        print(f"     evidence   : {json.dumps(row.get('verifier_evidence'), ensure_ascii=False)}")
    if verbose:
        for row in found["power_details"][-3:]:
            print(f"  (all time) {str(row.get('recorded_at'))[5:19]} {row.get('result')} "
                  f"{row.get('failure_type') or ''}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", type=float, default=0.0,
                        help="keep looking for up to this many minutes")
    parser.add_argument("--every", type=float, default=60.0, help="seconds between looks")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--stop-when-seen", action="store_true",
                        help="return as soon as either live question has an answer, so a caller "
                             "waiting on this process is woken by the event and not by the clock")
    args = parser.parse_args()

    deadline = time.time() + max(0.0, args.watch) * 60.0
    baseline_advised = len(look(verbose=args.verbose)["advised_steps"]) if args.stop_when_seen else 0
    while True:
        found = look(verbose=args.verbose)
        landed = len(found["answers"])
        adopted = len(found["advised_steps"])
        power = [row for row in found["power_details"]
                 if str(row.get("recorded_at") or "") >= PRINTED_NAME_FIX_AT]
        print()
        print(f"[watch] answers={landed} advised_steps={adopted} power_details_since_fix={len(power)} "
              f"at {datetime.now(timezone.utc).isoformat()[11:19]}Z")
        if args.stop_when_seen and (adopted > baseline_advised or power):
            print("[watch] the thing being waited for is on file; stopping so the caller can read it")
            return 0
        if time.time() >= deadline:
            print("[watch] time is up; neither live question has an answer on file yet")
            return 0
        time.sleep(max(5.0, args.every))


if __name__ == "__main__":
    raise SystemExit(main())
