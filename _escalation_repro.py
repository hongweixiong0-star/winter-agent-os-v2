"""Why did a demonstrably-working capability escalate as "no verified episode"?

Reproduces the escalation's own inputs: reads the real escalation record, resolves the capability
the same way `classify_condition`'s caller does, and runs `new_live_episodes` with the same
arguments -- then reports, gate by gate, which rows were dropped and why.

Read-only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from winter_agent_v2.escalation_queue import (  # noqa: E402
    capability_for_skill, new_live_episodes,
)

LEDGER = ROOT / "learning/workbuddy_escalations.jsonl"
EPISODES = ROOT / "learning/episodes.jsonl"

records = []
for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if line.startswith("{"):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass

hits = [r for r in records if "FOCUSED_CAMP_ACTION_BAR_NOT_PROVEN" in json.dumps(r, ensure_ascii=False)]
print("escalation records mentioning the camp action bar:", len(hits))
for r in hits[-3:]:
    print(json.dumps(r, ensure_ascii=False)[:700])
    print("-" * 80)

if not hits:
    raise SystemExit("no record to reproduce")

record = hits[-1]
skill = str(record.get("skill") or record.get("signature", {}).get("skill") or "")
if not skill:
    for key in ("reason", "message", "detail"):
        text = str(record.get(key) or "")
        if "TAP_FOCUSED_TRAINING_CAMP" in text:
            for token in text.replace("/", " ").replace(":", " ").split():
                if token.startswith("TAP_FOCUSED_TRAINING_CAMP"):
                    skill = token
                    break
print()
print("skill from the record:", skill)
capability = capability_for_skill(skill, root=ROOT)
print("capability_for_skill ->", repr(capability))

stamp = str(record.get("recorded_at") or record.get("created_at") or "")
first_seen = None
for key in ("first_seen", "first_occurrence", "since"):
    value = record.get(key)
    if value:
        try:
            first_seen = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
        break
print("record recorded_at:", stamp, "| first_seen in record:", first_seen)

rows = []
for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if line.startswith("{"):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
print("episodes on file:", len(rows))

same_skill = [r for r in rows if r.get("skill") == skill]
print()
print("episodes whose skill is exactly %r: %d" % (skill, len(same_skill)))
print("   by result:", dict(Counter(r.get("result") for r in same_skill)))
print("   verifier_ok True:", sum(1 for r in same_skill if r.get("verifier_ok") is True))
print("   verifier_ok True AND recorded_at present:",
      sum(1 for r in same_skill if r.get("verifier_ok") is True and r.get("recorded_at")))
print("   ... AND both screenshots present:",
      sum(1 for r in same_skill if r.get("verifier_ok") is True and r.get("recorded_at")
          and r.get("before_screenshot") and r.get("after_screenshot")))
newest = [r for r in same_skill if r.get("verifier_ok") is True]
print("   newest verified:", str(newest[-1].get("recorded_at")) if newest else "(none)")

print()
print("new_live_episodes(capability, skill=skill, since=first_seen) ->")
for since in (first_seen,):
    got = new_live_episodes(capability, skill=skill, since=since, root=ROOT)
    print("   since=%s -> %d row(s)" % (since, len(got)))
got_no_since = new_live_episodes(capability, skill=skill, since=None, root=ROOT)
print("   since=None -> %d row(s)" % len(got_no_since))
by_skill_only = new_live_episodes("", skill=skill, since=None, root=ROOT)
print("   capability='' skill=skill since=None -> %d row(s)" % len(by_skill_only))
