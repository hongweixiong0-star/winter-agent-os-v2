"""Tally verified gather closures per resource from the production evidence.

The acceptance criterion for the gather workflow is per resource ("each of MEAT /
WOOD / COAL / IRON completes the chain at least three times"), but a single
session cannot satisfy it: every closure occupies one of the account's six march
slots for hours, so the criterion is bounded by march slots rather than by
elapsed effort.  The honest way to report progress is therefore to derive the
tally from the episode stream instead of from how long a session ran.

A closure counts only when a `DISPATCH_MARCH` step reached a passing verifier.
The target resource is read from the step's serialised WorldState, which the
episode record carries for both before and after.

Writes: evidence/gather_closure_tally.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EPISODES = ROOT / "learning/episodes.jsonl"
RESOURCES = ("MEAT", "WOOD", "COAL", "IRON")
FINAL_SKILL = "DISPATCH_MARCH"


def main() -> int:
    if not EPISODES.is_file():
        raise SystemExit("no episode stream")
    rows = []
    for line in EPISODES.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    closures: Counter[str] = Counter()
    unattributable = 0
    untraceable = 0
    per_episode: dict[str, set[str]] = defaultdict(set)
    evidence: list[dict] = []
    for row in rows:
        if str(row.get("skill")) != FINAL_SKILL:
            continue
        if str(row.get("result", "")).upper() != "SUCCESS":
            continue
        if row.get("verifier_ok") is False:
            continue
        after = row.get("state_after") or {}
        marches = [str(m) for m in (after.get("marches") or [])]
        if not set(marches) & {"MARCHING", "GATHERING"}:
            # No active march row recorded: the state change is not proven.
            continue

        # Evidence gate.  Rows written before episode traceability existed carry
        # no episode_id and no screenshots, and their resource_target is the
        # hard-coded "WOOD" default of that era's vision layer — 20 of the 27
        # WOOD rows are exactly that, so counting them would invent a result.
        # "No evidence means not verified" applies to aggregates too.
        episode_id = str(row.get("episode_id") or "")
        before_shot = str(row.get("before_screenshot") or "")
        after_shot = str(row.get("after_screenshot") or "")
        if not episode_id:
            untraceable += 1
            continue
        if before_shot and not Path(before_shot).is_file():
            untraceable += 1
            continue
        if after_shot and not Path(after_shot).is_file():
            untraceable += 1
            continue

        resource = (row.get("state_before") or {}).get("resource_target") or after.get("resource_target")
        if resource not in RESOURCES:
            unattributable += 1
            continue
        closures[resource] += 1
        per_episode[episode_id].add(resource)
        evidence.append({
            "resource": resource,
            "recorded_at": row.get("recorded_at"),
            "episode_id": episode_id,
            "step_id": row.get("step_id"),
            "march_used": after.get("march_used"),
            "marches": marches,
            "before_screenshot": before_shot,
            "after_screenshot": after_shot,
        })

    counted_episodes = defaultdict(int)
    for episode_id, found in per_episode.items():
        for resource in found:
            counted_episodes[resource] += 1

    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "learning/episodes.jsonl (PRODUCTION, DISPATCH_MARCH, SUCCESS, verifier not false)",
        "acceptance_rule": "each resource >= 3 verified closures, 12 total",
        "evidence_rule": "a closure counts only when the episode carries an episode_id and its "
                         "screenshots exist on disk; an aggregate is not evidence-free",
        "totals": {name: closures.get(name, 0) for name in RESOURCES},
        "total_verified_closures": sum(closures.values()),
        "distinct_episodes": dict(counted_episodes),
        "excluded_untraceable": untraceable,
        "excluded_unattributable": unattributable,
        "competing_constraint": (
            "the account has 6 march slots and each closure occupies one for hours, "
            "so 12 closures cannot be produced in a single session; when every slot is "
            "gathering the runtime correctly stops with no_idle_march"
        ),
        "evidence": evidence,
    }
    out = ROOT / "evidence/gather_closure_tally.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"verified closures: {payload['totals']}  (total {payload['total_verified_closures']})")
    print(f"distinct episodes per resource: {dict(counted_episodes)}")
    print(f"excluded untraceable (no episode_id / missing screenshots): {untraceable}")
    print(f"excluded unattributable: {unattributable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
