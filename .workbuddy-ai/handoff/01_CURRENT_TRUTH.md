# 01 — CURRENT TRUTH

- generated_at: `2026-09-15T00:08:13+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `c2908ad` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `c2908ad`
- commits: 47
- HEAD: `c2908ad` — fix(intel): count mission pins instead of trusting header text; a full board was reported empty (2026-09-15T08:08:13+08:00)
- working tree: 2 dirty file(s)
  - `M .workbuddy-ai/handoff/.last_good_commit`
  - `?? .workbuddy-ai/handoff/.checkpoints.jsonl`

## B. Runtime

- agent_state: `DEGRADED`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: STAMINA_SOURCES_NOT_OPEN
- page: INTEL  march: None/None
- updated_at: 2026-09-14T23:37:22.345482+00:00

## C. Episode stream

- rows: 1004 (production 1004)  modes: {'PRODUCTION': 1004}
- success / failure: 690 / 309
- success rate over decided: **0.6907**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "OPEN_INTEL", "result": "FAILURE", "recorded_at": "2026-09-14T23:37:22.332132+00:00", "episode_id": "repro_intel_073638", "before_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\repro_intel_073638\\repro_intel_073638_step_001_before_20260914T233640944691.png", "after_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\repro_intel_073638\\repro_intel_073638_step_001_after_20260914T233654787876.png"}`

## D. Registry and lifecycle

- registry total: 87  by_state: {'VERIFIED': 44, 'CANDIDATE': 41, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 69
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **27**  stable: 19  degraded: 9  only_failed: 8  never_executed: 26

### Never executed

- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CHECK_MARCH` (VERIFIED)
- `CLAIM_FREE_STAMINA` (CANDIDATE)
- `CLAIM_REWARD` (CANDIDATE)
- `DISMISS_ALLIANCE_GENERIC_REWARD` (CANDIDATE)
- `DISMISS_EXPLORATION_REWARD` (VERIFIED)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `OPEN_ALLIANCE_GIFTS` (CANDIDATE)
- `OPEN_STAMINA_SOURCES` (CANDIDATE)
- `READ_COUNTER` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
- `READ_TIMER` (CANDIDATE)
- `RECALL_MARCH` (CANDIDATE)
- `RECOVER_HOME` (CANDIDATE)
- `REINFORCE_TARGET` (CANDIDATE)
- `RELAX_RESOURCE_LEVEL` (CANDIDATE)
- `SELECT_INFANTRY_CAMP` (CANDIDATE)
- `SELECT_INTEL_PIN` (CANDIDATE)
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
- `DISMISS_MAIL_REWARD` attempts=1 failure=1
- `DISPATCH_BEAST` attempts=1 failure=1
- `RESEARCH` attempts=1 failure=0
- `SAFE_STOP` attempts=4 failure=4
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=12 rate=0.9231
- `BACK` success=49 rate=0.98
- `CLOSE_POPUP` success=30 rate=0.9677
- `DISMISS_INTEL_GENERIC_REWARD` success=22 rate=1.0
- `DISMISS_MAIL_GENERIC_REWARD` success=6 rate=0.8571
- `DISPATCH_INTEL_BEAST` success=26 rate=0.963
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=27 rate=0.9643
- `INTEL_CLAIM_REWARDS` success=40 rate=0.9302
- `OPEN_DAILY` success=5 rate=0.8333
- `OPEN_EXPLORATION` success=11 rate=0.9167
- `OPEN_HOME` success=20 rate=0.8696
- `OPEN_INTEL` success=74 rate=0.8605
- `OPEN_INTEL_BEAST_TARGET` success=25 rate=0.9259
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=6 rate=1.0
- `OPEN_MAP` success=25 rate=0.9259
- `OPEN_POWER_DETAILS` success=9 rate=1.0
- `OPEN_POWER_OVERVIEW` success=9 rate=0.8182
- `SELECT_INTEL_BEAST_MISSION` success=9 rate=0.8182

### Degraded

- `DISMISS_INTEL_REWARD` success=18 failure=5 rate=0.7826
- `DISPATCH_MARCH` success=32 failure=35 rate=0.4776
- `MAIL_CLAIM_REWARDS` success=14 failure=10 rate=0.5833
- `NAVIGATE_INFANTRY_CAMP` success=7 failure=2 rate=0.7778
- `OPEN_MAIL` success=31 failure=15 rate=0.6739
- `SEARCH_RESOURCE` success=41 failure=34 rate=0.5467
- `SELECT_RESOURCE` success=11 failure=41 rate=0.2115
- `START_GATHER` success=35 failure=59 rate=0.3723
- `SUBMIT_RESOURCE_SEARCH` success=35 failure=30 rate=0.5385

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 112 | SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
`MARCH_PAGE_NOT_OPEN` | 59 | START_GATHER(59)
`RESOURCE_NOT_FOUND` | 30 | SUBMIT_RESOURCE_SEARCH(30)
`DISPATCH_NOT_PROVEN` | 29 | DISPATCH_MARCH(29)
`MAIL_CLAIM_FEEDBACK_NOT_PROVEN` | 10 | MAIL_CLAIM_REWARDS(10)
`STAMINA_SOURCES_NOT_OPEN` | 8 | OPEN_INTEL(8)
`INTEL_HERO_DISPATCH_NOT_PROVEN` | 8 | INTEL_HERO_DISPATCH(8)
`INTEL_RESCUE_START_NOT_PROVEN` | 6 | EXECUTE_INTEL_RESCUE_SURVIVORS(6)
`POPUP_CLOSE_NOT_PROVEN` | 5 | DISMISS_REAL_MONEY_OFFER(4), RECONNECT_SESSION(1)
`NO_EXECUTION` | 4 | SAFE_STOP(4)

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
- referenced screenshots: 532  present: 532
- missing: []
- episodes carrying screenshot references: 272

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-14T03:45:35+00:00", "size_bytes": 0, "last_stop_reason": null}
- recent crash reports: (none)
