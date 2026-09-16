# CURRENT TRUTH

Generated (UTC): 2026-09-16T13:08:41.639676+00:00

Everything below is recomputed by `python tools/truth_audit.py`.
Do not trust numbers in older Markdown files.

## A. Runtime

- agent_state: `DEGRADED`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: mail_all_clear
- page: MAIL march: None/None

## B. Episodes

- total: 1356 (mode: PRODUCTION=1356)
- success / failure: 1011 / 340
- blocked: 4  in_progress: 1
- success rate over decided: **74.8%**
- success rate over total: 74.6%
- mixed-case `result` rows (must be normalized on read, never rewritten): 35

## C. Top failures

Failure type | Count | Skills | Top skills | Last seen
---|---:|---:|---|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 128 | 18 | SELECT_RESOURCE(44), SEARCH_RESOURCE(32), OPEN_MAIL(13) | 2026-09-16T04:09:40
`MARCH_PAGE_NOT_OPEN` | 60 | 1 | START_GATHER(60) | 2026-09-16T11:22:23
`RESOURCE_NOT_FOUND` | 30 | 1 | SUBMIT_RESOURCE_SEARCH(30) | 2026-09-14T06:42:03
`DISPATCH_NOT_PROVEN` | 29 | 1 | DISPATCH_MARCH(29) | 2026-09-14T05:25:20
`MAIL_CLAIM_FEEDBACK_NOT_PROVEN` | 10 | 1 | MAIL_CLAIM_REWARDS(10) | 
`STAMINA_SOURCES_NOT_OPEN` | 9 | 1 | OPEN_INTEL(9) | 2026-09-15T02:31:47
`INTEL_HERO_DISPATCH_NOT_PROVEN` | 8 | 1 | INTEL_HERO_DISPATCH(8) | 2026-09-14T12:19:55
`INTEL_BEAST_TARGET_NOT_PROVEN` | 6 | 1 | OPEN_INTEL_BEAST_TARGET(6) | 2026-09-16T11:22:47
`INTEL_RESCUE_START_NOT_PROVEN` | 6 | 1 | EXECUTE_INTEL_RESCUE_SURVIVORS(6) | 2026-09-14T17:17:43
`POPUP_CLOSE_NOT_PROVEN` | 5 | 2 | DISMISS_REAL_MONEY_OFFER(4), RECONNECT_SESSION(1) | 2026-09-13T21:08:40
`NO_EXECUTION` | 5 | 1 | SAFE_STOP(5) | 2026-09-15T12:27:40
`INTEL_CLAIM_FEEDBACK_NOT_PROVEN` | 3 | 1 | INTEL_CLAIM_REWARDS(3) | 2026-09-14T10:17:47

## D. Registry

- total skills: 87
- by state: {'VERIFIED': 45, 'CANDIDATE': 40, 'BLOCKED': 2}
- by latency: {'NORMAL': 71, 'FAST': 15, 'REALTIME': 1}
- REALTIME skills: ['JOIN_RALLY']
- BLOCKED skills: ['RESEARCH', 'ALLIANCE_HELP']

## E. Dataset

Area | Files | Empty dirs
---|---:|---:
`dataset/raw` | 3521 | 56
`dataset/candidate` | 535 | 0
`dataset/verified` | 5 | 0
`dataset/normalized` | 1 | 0
`dataset/production` | 0 | 0
`dataset/external` | 90 | 7

## F. Evidence integrity

- status: **PASS**
- episodes carrying screenshot references: 624 / 1356
- screenshots referenced: 1219
- screenshots missing: 0
- distinct episode ids: 133

## G. Skill lifecycle vs the episode stream

- registry total: 87
- live verified (>=1 production success): **59**
- only ever failed: 8
- never executed: 20

Never executed skills:

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

## H. Capability coverage (rebuilt model)

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- generated: 2026-09-16T13:08:28.961766+00:00 (0.0 days ago)
- FULLY_LIVE_VERIFIED: 2 / 16
- PARTIAL: 8  NEVER_TRIED: 0  BLOCKED: 4  DEGRADED: 2
- mean implementation coverage: 0.54
- mean live coverage: 0.5452

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

Retired: learning/goal_coverage.json (string-matching model; do not use)
