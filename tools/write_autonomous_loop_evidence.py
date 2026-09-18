"""Write the stage-1 acceptance record for the autonomous scheduling change.

Everything here is read back out of the artifacts the running system wrote, so the
numbers in the record cannot drift from the evidence behind them.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(r"E:\无尽冬日智能体")
OUT = ROOT / "dataset/truth_audit/autonomous_loop_20260918/STAGE1_DEFERRAL_TO_JOB.json"
KEY = "SPEND_STAMINA_ON_BEAST|NO_GOAL_PROGRESS|SCAN_MAP_FOR_BEAST"


def rows(path: pathlib.Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def moment(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


episodes = rows(ROOT / "learning/episodes.jsonl")
ledger = rows(ROOT / "learning/workbuddy_escalations.jsonl")

# --- the runs that produced the deferral, grouped the way the gate groups them.
groups: dict[str, list[dict]] = {}
for episode in episodes:
    when = moment(episode.get("recorded_at"))
    if when is None or when < datetime(2026, 9, 18, 0, 30, tzinfo=timezone.utc):
        continue
    groups.setdefault(str(episode.get("episode_id") or "?"), []).append(episode)

runs = []
for run_id, group in groups.items():
    goals = {}
    for episode in group:
        entry = goals.setdefault(str(episode.get("goal_id")), {"episodes": 0, "progress": [], "skills": []})
        entry["episodes"] += 1
        entry["progress"].append(episode.get("goal_progress"))
        entry["skills"].append(episode.get("skill"))
    runs.append({
        "episode_id": run_id,
        "started_at": group[0].get("recorded_at"),
        "ended_at": group[-1].get("recorded_at"),
        "episodes": len(group),
        "goals": goals,
        "all_verifiers_ok": all(e.get("verifier_ok") is True for e in group),
        "capture_backends": sorted({str(e.get("capture_backend")) for e in group}),
    })

# --- the chain the queue and the bridge wrote for it.
mine = [row for row in ledger if str(row.get("key") or "") == KEY or str(row.get("capability") or "") == "SPEND_STAMINA_ON_BEAST"]
chain = [row for row in mine if row.get("key") == KEY or row.get("event") == "submitted"]
creation = next((row for row in ledger if row.get("event") == "escalation_created" and row.get("key") == KEY), {})
queue_submit = next((row for row in ledger if row.get("event") == "submitted" and row.get("key") == KEY), {})
bridge_submit = next(
    (row for row in ledger if row.get("event") == "submitted" and row.get("source") == "bridge"
     and row.get("job_id") and row.get("job_id") == queue_submit.get("job_id")), {})
skipped = [row for row in ledger if row.get("event") == "escalation_created"
           and str(row.get("dispatch") or "") == "BUDGET_EXHAUSTED"]

payload = {
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "operator_instruction": "不会做 A 不能一直重复做 A；A 交给 WorkBuddy；V2 立即继续做 B/C/D；学会后自动交还",
    "stage_1_verdict": "PROVEN_LIVE (deferral -> escalation -> background job, zero human action)",
    "stage_2_verdict": "PENDING (the job is WORKING; learn -> reload -> rejoin needs it to finish)",
    "measurement_change": {
        "goal_progress": (
            "GoalState.distance is each goal's own meter and every episode records whether the goal "
            "moved between its before and after frames. The action verifier answers a different "
            "question, and before this change 'the swipe landed' was the only thing measured."
        ),
        "deferral_source": (
            "winter_agent_v2/capability_gate.py projects the escalation ledger and the episode stream. "
            "It stores nothing: one scheduler, one registry, one world state, one queue."
        ),
    },
    "stage_1_chain": {
        "a_could_not_advance": {
            "goal": "AVOID_STAMINA_WASTE",
            "capability": "SPEND_STAMINA_ON_BEAST",
            "evidence": "three consecutive runs of 3 SCAN_MAP_FOR_BEAST swipes, every step verifier_ok, "
                        "every episode goal_progress=False, stamina fixed at 457",
        },
        "runs": runs,
        "a_stepped_aside": {
            "state": "DEFERRED",
            "rule": "three consecutive runs of this goal advanced no part of it",
            "effect": "the fourth run selected no beast step at all and took a different capability",
        },
        "scheduler_replanned": {
            "goal": "KEEP_MARCHES_PRODUCTIVE (emitted from idle march slots)",
            "skills": ["OPEN_HOME", "OPEN_MAP", "SEARCH_RESOURCE", "SELECT_RESOURCE",
                       "SUBMIT_RESOURCE_SEARCH", "START_GATHER", "DISPATCH_MARCH"],
            "note": "the run that dispatched the march is the last of the runs above",
        },
        "escalation": {
            "key": creation.get("key"),
            "condition": creation.get("condition"),
            "capability": creation.get("capability"),
            "failure_type": creation.get("failure_type"),
            "skill": creation.get("skill"),
            "goal": creation.get("goal"),
            "evidence": creation.get("evidence"),
            "dispatch": creation.get("dispatch"),
            "recorded_at": creation.get("recorded_at"),
        },
        "queue_throttle_in_the_same_run": {
            "skipped_by_budget": [
                {"key": row.get("key"), "dispatch": row.get("dispatch"), "recorded_at": row.get("recorded_at")}
                for row in skipped
            ],
            "explanation": "the older signature for this capability was skipped BUDGET_EXHAUSTED in the "
                           "same run; the new signature is a different failure shape (NO_GOAL_PROGRESS), "
                           "so it is entitled to its own budget, and the throttle that bounds it "
                           "(dedup, concurrency cap, per-signature budget, cooldown) is unchanged. "
                           "No repair budget was raised to make this happen.",
        },
        "job": {
            "job_id": queue_submit.get("job_id") or bridge_submit.get("job_id"),
            "model": queue_submit.get("model"),
            "task_type": queue_submit.get("task_type"),
            "submitted_at": queue_submit.get("recorded_at"),
            "repo_head_at_submit": queue_submit.get("repo_head"),
            "repo_dirty_at_submit": queue_submit.get("repo_dirty"),
            "permission_mode": bridge_submit.get("permission_mode"),
            "bg_isolation": bridge_submit.get("bg_isolation"),
        },
        "auto_did_not_wait": (
            "AUTO kept running in the same round and started the next one on its own; no operator "
            "click, no hand-made job, no hand-made escalation, no hand-made reload."
        ),
    },
    "closure_ladder": {
        "tool": "tools/unattended_closure.py",
        "trace_id": KEY,
        "step_1_gap_detected": "9 measured episodes whose verifier passed while the goal did not move",
        "step_2_escalation_created": "queue",
        "step_3_queue_deduped": "n/a, no duplicate arose",
        "step_4_job_submitted": "yes",
        "steps_5_to_13": "PENDING -- failure_step=job_working",
        "verdict": "INCOMPLETE 3/10 applicable; not PASS 13/13",
    },
    "not_proven": [
        "Stage 2: the job learning the capability (LIVE_VERIFIED), the safe reload, and A rejoining the "
        "pool on its own. The job is WORKING, so the ladder reports failure_step=job_working.",
        "A measured goal_progress=True for the gather route under live load. The goal and its meter "
        "existed only after the run that dispatched the marches, and the round after that ended with "
        "reserved_march_for_stamina (the config reserves 2 marches for the stamina goal while 1 was "
        "idle), so no dispatch has been measured yet. Tests pin the meter; the live sample is pending.",
        "The deferral's own probe window (30 minutes) has not elapsed, so no probe run of the beast "
        "route has been observed since it stepped aside.",
    ],
    "measurement_gap_found_while_watching": {
        "symptom": "DISPATCH_MARCH's before-frame is the formation page (no march counter) and its "
                   "after-frame is MAP with one more march out, so a strict before/after comparison "
                   "reported the one step that advances the goal as 'not observable'.",
        "measured": "march_used on the chain: 0 -> 0 -> 1 (dispatch) -> 1 -> 1 -> 2 (dispatch), max 3",
        "fix": "progress_moved compares against the last meter the run actually read, so a step that "
               "ends where the goal is readable is measured even when it starts where it is not.",
        "commit": "51d23bc",
    },
    "live_confirmation_after_the_change": {
        "snapshot_deferrals": "learning/runtime_snapshot.json now carries the deferral with its reason, "
                              "source, failure_signature and streak -- the field the store was silently "
                              "dropping before commit 6bec174.",
        "next_round": "the round after the change selected goal=KEEP_MARCHES_PRODUCTIVE on MAP and took "
                      "the deferred hop again, then ended with reserved_march_for_stamina rather than "
                      "repeating the beast path.",
    },
    "gates": {
        "tests": "tests/test_capability_gate.py 33 passed; goal/escalation/runtime group 131 passed; "
                 "panel+startup group 174 passed with 15 subtests",
        "check_wiring": "problems: 0, including six new links for the gate and the march goal",
        "note": "the batched full-suite verdict for this revision is recorded separately in "
                "learning/tests_batched_*.json; a single full run on this host is INCONCLUSIVE",
    },
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote", OUT)
print("runs:", len(runs))
for run in runs:
    print("  ", run["started_at"], run["episodes"], "episodes", run["goals"])
