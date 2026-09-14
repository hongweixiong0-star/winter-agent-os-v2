"""Cold-start simulation: can a brand-new account continue from START_HERE alone?

Replays exactly the steps START_HERE.md prescribes, in order, and asserts each
one produces usable output.  This is the acceptance test for the handoff
mechanism itself: if a new account cannot follow it, the mechanism has failed
regardless of how good the files look.

Run: python tools/simulate_new_account.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / ".workbuddy-ai/handoff"
failures: list[str] = []


def step(number: int, title: str) -> None:
    print(f"\n--- step {number}: {title}")


def ok(condition: bool, message: str) -> None:
    print(f"    {'OK  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)


# Step 1: the constitution.
step(1, "read the master rules")
rules = HANDOFF / "00_MASTER_RULES.md"
ok(rules.is_file() and rules.stat().st_size > 2000, "00_MASTER_RULES.md is present and substantial")
rules_text = rules.read_text(encoding="utf-8") if rules.is_file() else ""
for required in ("Single Scheduler", "Verifier", "Semantic", "真实支付", "72"):
    ok(required in rules_text, f"master rules cover: {required}")

# Step 2: rebuild the truth.
step(2, "run the handoff generator")
proc = subprocess.run(
    [sys.executable, str(ROOT / "tools/update_workbuddy_handoff.py")],
    capture_output=True, text=True, cwd=str(ROOT),
)
ok(proc.returncode == 0, f"generator exited 0 (got {proc.returncode})")
for name in ("01_CURRENT_TRUTH.md", "08_LIVE_METRICS.json", "09_RUNTIME_STATE.json"):
    ok((HANDOFF / name).is_file(), f"{name} regenerated")

# Step 3: read the four continuation files.
step(3, "read the continuation files")
for name in ("01_CURRENT_TRUTH.md", "03_NEXT_ACTION.md", "04_OPEN_ISSUES.md", "10_LAST_HANDOFF.md"):
    path = HANDOFF / name
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    ok(len(text) > 800, f"{name} carries enough content ({len(text)} chars)")

next_action = (HANDOFF / "03_NEXT_ACTION.md").read_text(encoding="utf-8")
for field in ("CURRENT PRIORITY", "CURRENT TASK", "NEXT EXACT ACTION", "ACCEPTANCE", "DO NOT"):
    ok(field in next_action, f"03_NEXT_ACTION.md exposes {field}")

handoff = (HANDOFF / "10_LAST_HANDOFF.md").read_text(encoding="utf-8")
for field in ("HANDOFF TIME", "LAST GOOD COMMIT", "WHAT LIVE VERIFIED", "WHAT NOT VERIFIED",
              "NEXT EXACT STEP", "KNOWN RISKS", "DO NOT REPEAT"):
    ok(field in handoff, f"10_LAST_HANDOFF.md exposes {field}")

# Step 4: verify against the primary sources.
step(4, "cross-check the primary sources")
metrics = json.loads((HANDOFF / "08_LIVE_METRICS.json").read_text(encoding="utf-8"))
ok(bool(metrics.get("commit")), "metrics record the commit they were computed at")
ok(bool(metrics.get("generated_at")), "metrics record generated_at")
ok(metrics.get("source", "").endswith("update_workbuddy_handoff.py"), "metrics name their producer")

episodes = ROOT / "learning/episodes.jsonl"
recorded = sum(1 for line in episodes.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip().startswith("{"))
ok(recorded == metrics["episodes"]["total"], f"episode count matches the file ({recorded})")

snapshot = json.loads((ROOT / "learning/runtime_snapshot.json").read_text(encoding="utf-8"))
ok(snapshot.get("agent_state") == metrics["runtime"]["agent_state"], "runtime snapshot agrees with metrics")

# The decisive question: could a new account act on this?
step(5, "is there enough to act on")
ok(metrics["evidence_integrity"]["status"] in {"PASS", "FAIL"},
   f"evidence integrity is stated ({metrics['evidence_integrity']['status']})")
blocked = [goal for goal, status in metrics["goal_status"].items() if status == "BLOCKED"]
ok(bool(blocked or metrics["goal_status"]), "goal statuses are enumerated")
ok("check repo code" not in next_action.lower(), "next action is not a placeholder")

print()
if failures:
    print(f"COLD START FAILED ({len(failures)}):")
    for item in failures:
        print(f"  - {item}")
    raise SystemExit(1)
print("COLD START OK — a new account can continue from START_HERE.md alone")
