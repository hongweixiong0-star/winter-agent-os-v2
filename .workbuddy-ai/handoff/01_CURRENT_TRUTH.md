# 01 — CURRENT TRUTH

- generated_at: `2026-09-16T11:56:59+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `44de622` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 83
- HEAD: `44de622` — docs(procedure): pin the live-observation workflow and the role facts it produced (2026-09-16T19:04:05+08:00)
- working tree: 61 dirty file(s)
  - `M .gitignore`
  - ` M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md`
  - ` M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md`
  - ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
  - ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
  - ` M .workbuddy-ai/handoff/05_RECENT_CHANGES.md`
  - ` M .workbuddy-ai/handoff/08_LIVE_METRICS.json`
  - ` M .workbuddy-ai/handoff/09_RUNTIME_STATE.json`
  - ` M .workbuddy-ai/handoff/10_LAST_HANDOFF.md`
  - ` M .workbuddy-ai/memory/2026-09-16.md`
  - ` M .workbuddy-ai/memory/MEMORY.md`
  - ` M .workbuddy/memory/2026-09-16.md`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M evidence/INDEX.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M learning/episodes.jsonl`
  - ` M learning/executor_backend.jsonl`
  - ` M learning/goal_state.json`
  - ` M learning/resource_rotation.json`
  - ` M learning/runtime_snapshot.json`

## B. Runtime

- agent_state: `DEGRADED`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: INTEL_BEAST_TARGET_NOT_PROVEN
- page: HOME  march: None/None
- updated_at: 2026-09-16T11:22:47.626484+00:00

## C. Episode stream

- rows: 1351 (production 1351)  modes: {'PRODUCTION': 1351}
- success / failure: 1006 / 340
- success rate over decided: **0.7474**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "OPEN_INTEL_BEAST_TARGET", "result": "FAILURE", "recorded_at": "2026-09-16T11:22:47.573385+00:00", "episode_id": "live_runtime", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\live_runtime\\live_runtime_step_001_before_20260916T112228940512.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\live_runtime\\live_runtime_step_001_after_20260916T112231479939.png"}`

## D. Registry and lifecycle

- registry total: 87  by_state: {'VERIFIED': 45, 'CANDIDATE': 40, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 71
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **26**  stable: 25  degraded: 9  only_failed: 9  never_executed: 20

### Never executed

- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CLAIM_REWARD` (CANDIDATE)
- `DISMISS_ALLIANCE_GENERIC_REWARD` (CANDIDATE)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `READ_COUNTER` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
- `READ_TIMER` (CANDIDATE)
- `RECALL_MARCH` (CANDIDATE)
- `RECOVER_HOME` (CANDIDATE)
- `REINFORCE_TARGET` (CANDIDATE)
- `RELAX_RESOURCE_LEVEL` (CANDIDATE)
- `SELECT_INFANTRY_CAMP` (CANDIDATE)
- `SELECT_INTEL_RESCUE_SURVIVORS` (VERIFIED)
- `SELECT_MARCH_TO_RECALL` (CANDIDATE)
- `SELECT_REWARD_OPTION` (CANDIDATE)
- `SEND_MARCH` (CANDIDATE)
- `START_RALLY` (CANDIDATE)
- `USE_ACTIVITY_ATTEMPT` (CANDIDATE)
- `VERIFY_GATHERING` (VERIFIED)

### Only ever failed

- `ALLIANCE_HELP` attempts=1 failure=0
- `CONFIRM_EXPLORATION_IDLE_CLAIM` attempts=2 failure=2
- `DISMISS_EXPLORATION_REWARD` attempts=1 failure=1
- `DISMISS_MAIL_REWARD` attempts=1 failure=1
- `DISPATCH_BEAST` attempts=1 failure=1
- `RESEARCH` attempts=1 failure=0
- `SAFE_STOP` attempts=5 failure=5
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=23 rate=0.9583
- `BACK` success=93 rate=0.9894
- `CHECK_MARCH` success=21 rate=0.9545
- `CLOSE_POPUP` success=30 rate=0.9677
- `DISMISS_INTEL_GENERIC_REWARD` success=36 rate=1.0
- `DISMISS_INTEL_REWARD` success=23 rate=0.8214
- `DISMISS_MAIL_GENERIC_REWARD` success=6 rate=0.8571
- `DISPATCH_INTEL_BEAST` success=37 rate=0.881
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=41 rate=0.9535
- `INTEL_CLAIM_REWARDS` success=60 rate=0.9524
- `INTEL_HERO_START_MARCH` success=17 rate=0.85
- `OPEN_DAILY` success=5 rate=0.8333
- `OPEN_EXPLORATION` success=11 rate=0.9167
- `OPEN_HOME` success=20 rate=0.8696
- `OPEN_INTEL` success=112 rate=0.855
- `OPEN_INTEL_BEAST_TARGET` success=41 rate=0.8723
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=20 rate=0.9091
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=7 rate=1.0
- `OPEN_MAP` success=29 rate=0.9062
- `OPEN_POWER_DETAILS` success=9 rate=1.0
- `OPEN_POWER_OVERVIEW` success=9 rate=0.8182
- `OPEN_STAMINA_SOURCES` success=13 rate=1.0
- `SELECT_INTEL_BEAST_MISSION` success=10 rate=0.8333
- `SELECT_INTEL_PIN` success=43 rate=0.9348

### Degraded

- `DISPATCH_MARCH` success=34 failure=35 rate=0.4928
- `INTEL_HERO_DISPATCH` success=12 failure=8 rate=0.6
- `MAIL_CLAIM_REWARDS` success=14 failure=10 rate=0.5833
- `NAVIGATE_INFANTRY_CAMP` success=7 failure=2 rate=0.7778
- `OPEN_MAIL` success=31 failure=15 rate=0.6739
- `SEARCH_RESOURCE` success=46 failure=34 rate=0.575
- `SELECT_RESOURCE` success=14 failure=45 rate=0.2373
- `START_GATHER` success=37 failure=60 rate=0.3814
- `SUBMIT_RESOURCE_SEARCH` success=38 failure=30 rate=0.5588

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 128 | SELECT_RESOURCE(44), SEARCH_RESOURCE(32), OPEN_MAIL(13)
`INTEL_HERO_DISPATCH_NOT_PROVEN` | 8 | INTEL_HERO_DISPATCH(8)
`INTEL_BEAST_TARGET_NOT_PROVEN` | 6 | OPEN_INTEL_BEAST_TARGET(6)
`STAMINA_SOURCES_NOT_OPEN` | 9 | OPEN_INTEL(9)
`DAILY_REWARD_ADVANCE_NOT_PROVEN` | 3 | DISMISS_DAILY_REWARD(3)
`OPEN_MAP_NOT_PROVEN` | 3 | OPEN_MAP(3)
`INTEL_BEAST_MARCH_NOT_PROVEN` | 2 | INTEL_BEAST_START_MARCH(2)
`MARCH_PAGE_NOT_OPEN` | 60 | START_GATHER(60)
`INTEL_RESCUE_START_NOT_PROVEN` | 6 | EXECUTE_INTEL_RESCUE_SURVIVORS(6)
`NO_EXECUTION` | 5 | SAFE_STOP(5)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 2, "partial": 8, "never_tried": 0, "blocked": 4, "degraded": 2, "missing": 0, "fully_live_verified_percent": 12.5, "never_tried_percent": 0.0, "automation_coverage_mean": 0.54, "live_coverage_mean": 0.5452}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 83% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 67% | 67% | 33% | SPEND_STAMINA_ON_RALLY
KEEP_MARCHES_PRODUCTIVE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 86% | 86% | 14% | VERIFY_GATHERING
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | OPEN_BUILDING_PAGE
KEEP_RESEARCH_PRODUCTIVE | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_RESEARCH_PAGE, START_RESEARCH
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
MAIL_ROUTINE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 0% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 25% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
CLAIM_EXPLORATION_IDLE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 33% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 50% | 75% | 25% | ALLIANCE_HELP, ALLIANCE_TECH_CONTRIBUTE
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 0% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 20% | 20% | 0% | CHECK_BEAR_PHASE, JOIN_RALLY, SELECT_TROOP_PRESET, START_RALLY
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 1209  present: 1209
- missing: []
- episodes carrying screenshot references: 619

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-14T03:45:35+00:00", "size_bytes": 0, "last_stop_reason": null}
- recent crash reports: (none)
