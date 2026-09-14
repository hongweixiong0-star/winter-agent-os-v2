# 01 — CURRENT TRUTH

- generated_at: `2026-09-14T05:12:29+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `65b2955` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `68e3540`
- commits: 6
- HEAD: `65b2955` — docs(handoff): regenerate truth and record the new last-good commit (2026-09-14T13:12:09+08:00)
- working tree: 2 dirty file(s)
  - `?? tools/coldstart.txt`
  - `?? tools/simulate_new_account.py`

## B. Runtime

- agent_state: `IDLE`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: TARGET_SKILL_VERIFIED
- page: MAP  march: 5/6
- updated_at: 2026-09-14T05:00:15.304769+00:00

## C. Episode stream

- rows: 761 (production 761)  modes: {'PRODUCTION': 761}
- success / failure: 510 / 246
- success rate over decided: **0.6746**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "DISPATCH_MARCH", "result": "SUCCESS", "recorded_at": "2026-09-14T05:00:15.248850+00:00", "episode_id": "accept_20260914_125232_run03", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\accept_20260914_125232_run03\\accept_20260914_125232_run03_step_006_before_20260914T045955757128.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\accept_20260914_125232_run03\\accept_20260914_125232_run03_step_006_after_20260914T050000610623.png"}`

## D. Registry and lifecycle

- registry total: 80  by_state: {'VERIFIED': 44, 'CANDIDATE': 34, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 61
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **23**  stable: 16  degraded: 10  only_failed: 7  never_executed: 25

### Never executed

- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CHECK_MARCH` (VERIFIED)
- `CLAIM_REWARD` (CANDIDATE)
- `DISMISS_ALLIANCE_GENERIC_REWARD` (CANDIDATE)
- `DISMISS_EXPLORATION_REWARD` (VERIFIED)
- `DISMISS_INTEL_GENERIC_REWARD` (CANDIDATE)
- `EXECUTE_INTEL_RESCUE_SURVIVORS` (VERIFIED)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `OPEN_ALLIANCE_GIFTS` (CANDIDATE)
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` (VERIFIED)
- `READ_COUNTER` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
- `READ_TIMER` (CANDIDATE)
- `RECALL_MARCH` (CANDIDATE)
- `RECOVER_HOME` (CANDIDATE)
- `REINFORCE_TARGET` (CANDIDATE)
- `RELAX_RESOURCE_LEVEL` (CANDIDATE)
- `SELECT_INFANTRY_CAMP` (CANDIDATE)
- `SELECT_INTEL_RESCUE_SURVIVORS` (VERIFIED)
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
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=12 rate=0.9231
- `BACK` success=14 rate=0.9333
- `CLOSE_POPUP` success=30 rate=0.9677
- `DISMISS_MAIL_GENERIC_REWARD` success=6 rate=0.8571
- `DISPATCH_INTEL_BEAST` success=12 rate=0.9231
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=13 rate=1.0
- `INTEL_CLAIM_REWARDS` success=15 rate=0.9375
- `OPEN_DAILY` success=5 rate=0.8333
- `OPEN_EXPLORATION` success=11 rate=0.9167
- `OPEN_HOME` success=20 rate=0.8696
- `OPEN_INTEL` success=50 rate=0.9434
- `OPEN_INTEL_BEAST_TARGET` success=12 rate=1.0
- `OPEN_MAP` success=24 rate=0.96
- `OPEN_POWER_DETAILS` success=9 rate=1.0
- `OPEN_POWER_OVERVIEW` success=9 rate=0.8182

### Degraded

- `DISMISS_INTEL_REWARD` success=15 failure=5 rate=0.75
- `DISPATCH_MARCH` success=32 failure=28 rate=0.5333
- `MAIL_CLAIM_REWARDS` success=14 failure=10 rate=0.5833
- `NAVIGATE_INFANTRY_CAMP` success=7 failure=2 rate=0.7778
- `OPEN_MAIL` success=31 failure=15 rate=0.6739
- `SEARCH_RESOURCE` success=39 failure=34 rate=0.5342
- `SELECT_INTEL_BEAST_MISSION` success=6 failure=2 rate=0.75
- `SELECT_RESOURCE` success=7 failure=41 rate=0.1458
- `START_GATHER` success=34 failure=59 rate=0.3656
- `SUBMIT_RESOURCE_SEARCH` success=34 failure=12 rate=0.7391

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 104 | SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
`MARCH_PAGE_NOT_OPEN` | 59 | START_GATHER(59)
`DISPATCH_NOT_PROVEN` | 28 | DISPATCH_MARCH(28)
`RESOURCE_NOT_FOUND` | 12 | SUBMIT_RESOURCE_SEARCH(12)
`MAIL_CLAIM_FEEDBACK_NOT_PROVEN` | 10 | MAIL_CLAIM_REWARDS(10)
`POPUP_CLOSE_NOT_PROVEN` | 5 | DISMISS_REAL_MONEY_OFFER(4), RECONNECT_SESSION(1)
`EXPLORATION_REWARD_FEEDBACK_NOT_PROVEN` | 3 | CONFIRM_EXPLORATION_IDLE_CLAIM(2), EXPLORATION_IDLE_CLAIM(1)
`INTEL_MISSION_SELECTION_NOT_PROVEN` | 2 | SELECT_INTEL_BEAST_MISSION(2)
`MAIL_TAB_SELECTION_NOT_PROVEN` | 2 | SELECT_MAIL_ALLIANCE_TAB(1), SELECT_MAIL_SYSTEM_TAB(1)
`OPEN_HOME_NOT_PROVEN` | 2 | OPEN_HOME(2)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 1, "partial": 8, "never_tried": 0, "blocked": 4, "degraded": 3, "missing": 0, "fully_live_verified_percent": 6.2, "never_tried_percent": 0.0, "automation_coverage_mean": 0.54, "live_coverage_mean": 0.5452}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 50% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 67% | 67% | 33% | SPEND_STAMINA_ON_RALLY
KEEP_MARCHES_PRODUCTIVE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 86% | 86% | 14% | VERIFY_GATHERING
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | OPEN_BUILDING_PAGE
KEEP_RESEARCH_PRODUCTIVE | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_RESEARCH_PAGE, START_RESEARCH
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
MAIL_ROUTINE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 0% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 25% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
CLAIM_EXPLORATION_IDLE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 33% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 50% | 75% | 25% | ALLIANCE_HELP, ALLIANCE_TECH_CONTRIBUTE
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 0% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 20% | 20% | 0% | CHECK_BEAR_PHASE, JOIN_RALLY, SELECT_TROOP_PRESET, START_RALLY
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 58  present: 58
- missing: []
- episodes carrying screenshot references: 29

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-14T03:45:35+00:00", "size_bytes": 0, "last_stop_reason": null}
- recent crash reports: (none)
