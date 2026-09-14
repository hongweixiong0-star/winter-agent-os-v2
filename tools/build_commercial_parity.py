"""Commercial-bot parity tracker.

A commercial Whiteout Survival script is the practical yardstick: if a mature
paid script can do a thing reliably, that thing is a fair expectation here.  This
file records, for each of the 21 tracked features, what the production episode
stream can actually prove: attempts, verified successes, failure rate, and the
lifecycle the capability model assigns.

The point is the honest gap.  A feature with zero attempts is reported as zero,
not as "supported because the code exists".

Writes: knowledge/coverage/commercial_bot_parity.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Feature -> the goal whose capability set describes it.
FEATURES: dict[str, str] = {
    "CLAIM_REWARD": "CLAIM_FREE_REWARDS",
    "MAIL": "MAIL_ROUTINE",
    "VIP": "CLAIM_FREE_REWARDS",
    "DAILY": "DAILY_ACTIVITY_TARGET",
    "ALLIANCE_HELP": "ALLIANCE_ROUTINE",
    "ALLIANCE_GIFT": "ALLIANCE_ROUTINE",
    "ALLIANCE_TECH": "ALLIANCE_ROUTINE",
    "TRAIN": "KEEP_TRAINING_PRODUCTIVE",
    "PROMOTE": "KEEP_TRAINING_PRODUCTIVE",
    "HEAL": "HEAL_TROOPS",
    "RESEARCH": "KEEP_RESEARCH_PRODUCTIVE",
    "BUILD": "KEEP_BUILDING_PRODUCTIVE",
    "GATHER_RESOURCE": "KEEP_MARCHES_PRODUCTIVE",
    "INTEL": "CLEAR_INTEL",
    "HUNT_BEAST": "AVOID_STAMINA_WASTE",
    "ARENA": "USE_FREE_ARENA_ATTEMPTS",
    "LABYRINTH": "LABYRINTH_DAILY",
    "JOIN_RALLY": "PARTICIPATE_BEAR",
    "START_RALLY": "PARTICIPATE_BEAR",
    "BEAR": "PARTICIPATE_BEAR",
    "PET": "PET_ROUTINE",
}

# Skills that map onto each feature, used to attribute episode evidence.
FEATURE_SKILLS: dict[str, tuple[str, ...]] = {
    "CLAIM_REWARD": ("CLAIM_REWARD", "CLAIM_OFFLINE_REWARDS", "ALLIANCE_ALLY_GIFT_CLAIM", "EXPLORATION_IDLE_CLAIM"),
    "MAIL": ("OPEN_MAIL", "MAIL_CLAIM_REWARDS", "SELECT_MAIL_ALLIANCE_TAB", "SELECT_MAIL_SYSTEM_TAB", "SELECT_MAIL_REPORT_TAB", "DISMISS_MAIL_REWARD"),
    "VIP": ("OPEN_VIP", "CLAIM_VIP_FREE"),
    "DAILY": ("OPEN_DAILY", "DAILY_CLAIM_REWARDS", "DAILY_HERO_RECRUIT", "DISMISS_DAILY_REWARD"),
    "ALLIANCE_HELP": ("ALLIANCE_HELP",),
    "ALLIANCE_GIFT": ("ALLIANCE_GIFTS", "OPEN_ALLIANCE_GIFTS", "ALLIANCE_ALLY_GIFT_CLAIM"),
    "ALLIANCE_TECH": ("ALLIANCE_TECH_CONTRIBUTE",),
    "TRAIN": ("TRAIN_TROOPS", "OPEN_INFANTRY_TRAINING", "NAVIGATE_INFANTRY_CAMP", "SELECT_INFANTRY_CAMP", "OPEN_POWER_OVERVIEW", "OPEN_POWER_DETAILS"),
    "PROMOTE": ("PROMOTE_TROOPS",),
    "HEAL": ("HEAL_TROOPS", "OPEN_HOSPITAL"),
    "RESEARCH": ("RESEARCH", "OPEN_RESEARCH"),
    "BUILD": ("BUILDING_UPGRADE", "OPEN_BUILDING"),
    "GATHER_RESOURCE": ("SEARCH_RESOURCE", "SELECT_RESOURCE", "SUBMIT_RESOURCE_SEARCH", "START_GATHER", "DISPATCH_MARCH", "GATHER_RESOURCE", "OPEN_MAP", "OPEN_HOME"),
    "INTEL": ("OPEN_INTEL", "READ_INTEL_LIST", "SELECT_INTEL_BEAST_MISSION", "OPEN_INTEL_BEAST_TARGET", "INTEL_BEAST_START_MARCH", "DISPATCH_INTEL_BEAST", "INTEL_CLAIM_REWARDS", "DISMISS_INTEL_REWARD"),
    "HUNT_BEAST": ("SELECT_BEAST_TARGET", "BEAST_HUNT", "DISPATCH_BEAST"),
    "ARENA": ("OPEN_ARENA", "READ_FREE_ATTEMPTS", "SELECT_ARENA_OPPONENT", "START_ARENA", "VERIFY_ARENA_RESULT"),
    "LABYRINTH": ("OPEN_LABYRINTH", "READ_LABYRINTH_ATTEMPTS", "START_LABYRINTH", "VERIFY_LABYRINTH_RESULT"),
    "JOIN_RALLY": ("JOIN_RALLY", "JOIN_POLAR_TERROR_RALLY", "JOIN_BEAR_RALLY"),
    "START_RALLY": ("START_RALLY", "PREPARE_BEAR_MARCH"),
    "BEAR": ("CHECK_ALLIANCE_EVENT", "READ_BEAR_TIMER", "START_RALLY", "JOIN_RALLY"),
    "PET": ("OPEN_PET", "PET_COLLECT"),
}


def episode_stats(path: Path) -> dict[str, dict]:
    stats: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "success": 0, "failure": 0})
    if not path.is_file():
        return {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("mode", "")).upper() != "PRODUCTION":
            continue
        skill = str(row.get("skill", ""))
        if not skill:
            continue
        result = str(row.get("result", "")).upper()
        stats[skill]["attempts"] += 1
        stats[skill]["success"] += int(result == "SUCCESS")
        stats[skill]["failure"] += int(result == "FAILURE")
    return dict(stats)


def main() -> None:
    stats = episode_stats(ROOT / "learning" / "episodes.jsonl")
    coverage_path = ROOT / "knowledge" / "goals" / "capability_skill_map.json"
    goal_status: dict[str, dict] = {}
    if coverage_path.is_file():
        payload = json.loads(coverage_path.read_text(encoding="utf-8"))
        goal_status = {row["goal"]: row for row in payload.get("goals", [])}

    features = []
    parity = 0
    for feature, goal in FEATURES.items():
        skills = FEATURE_SKILLS.get(feature, ())
        attempts = success = failure = 0
        observed: list[dict] = []
        for skill in skills:
            row = stats.get(skill)
            if not row:
                continue
            attempts += row["attempts"]
            success += row["success"]
            failure += row["failure"]
            observed.append({"skill_id": skill, **row})
        decided = success + failure
        coverage_row = goal_status.get(goal, {})
        lifecycle = coverage_row.get("status", "NOT_TRACKED")
        if success > 0:
            parity += 1
        features.append({
            "feature": feature,
            "goal": goal,
            "lifecycle": lifecycle,
            "attempts": attempts,
            "success": success,
            "failure": failure,
            "success_rate": round(success / decided, 4) if decided else None,
            "live_evidence": bool(success),
            "observed_skills": observed,
            "implementation_coverage": coverage_row.get("implementation_coverage"),
            "live_coverage": coverage_row.get("live_coverage"),
        })

    out = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "learning/episodes.jsonl (PRODUCTION rows only) + capability coverage",
        "definition": (
            "parity means the production episode stream contains at least one verified success "
            "for the feature; attempts/failure are reported so a lucky single success is visible"
        ),
        "summary": {
            "features_tracked": len(FEATURES),
            "features_with_live_success": parity,
            "parity_fraction": round(parity / len(FEATURES), 4),
        },
        "features": features,
    }
    out_path = ROOT / "knowledge" / "coverage" / "commercial_bot_parity.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"parity: {parity}/{len(FEATURES)}")
    for row in features:
        print(f"  {row['feature']:18s} {row['lifecycle']:22s} attempts={row['attempts']:4d} "
              f"success={row['success']:4d} rate={row['success_rate']}")


if __name__ == "__main__":
    main()
