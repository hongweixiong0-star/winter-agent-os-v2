"""Read or set the panel's operator intent (RUNNING / PAUSED / STOPPED).

The panel already owns this switch -- ``OPERATOR_INTENTS`` and the pause button write the same
file -- so an experiment that needs the device to itself must go through it rather than killing
processes.  ``PAUSED`` does not truncate a run: the panel stops *starting* new ones and lets the
cycle in flight finish, which is exactly what "pause every other automation" has to mean when a
goal is mid-step on a real account.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "config/control_panel_state.json"
INTENTS = ("RUNNING", "PAUSED", "STOPPED")


def read() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write(intent: str, reason: str) -> dict:
    state = read()
    state["operator_intent"] = intent
    state["operator_intent_at"] = datetime.now().astimezone().isoformat()
    state["operator_intent_reason"] = reason
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return state


def workers() -> list[str]:
    try:
        import psutil
    except ImportError:
        return []
    out = []
    for p in psutil.process_iter(["pid", "ppid", "cmdline"]):
        cl = " ".join(p.info["cmdline"] or [])
        if "run_live.py" in cl:
            out.append(f"{p.info['pid']}|{p.info['ppid']}|{cl[:90]}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", nargs="?", choices=INTENTS, help="omit to only read")
    parser.add_argument("--reason", default="")
    parser.add_argument("--wait-workers", type=float, default=0.0,
                        help="after setting, wait up to this many seconds for run_live to drain")
    args = parser.parse_args()

    if args.intent:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write(args.intent, args.reason or f"set by tools/operator_intent.py at {now}")
        print(f"operator_intent -> {args.intent}")

    state = read()
    print(f"operator_intent  = {state.get('operator_intent')}")
    print(f"updated_at       = {state.get('updated_at')}")
    print(f"reason           = {state.get('operator_intent_reason')}")

    deadline = time.time() + max(0.0, args.wait_workers)
    while True:
        live = workers()
        if not live or time.time() >= deadline:
            break
        time.sleep(2.0)
    live = workers()
    print(f"run_live workers = {len(live)}")
    for row in live:
        print("   ", row)
    return 0 if not live else 1


if __name__ == "__main__":
    sys.exit(main())
