# 01 — CURRENT TRUTH

- generated_at: `2026-09-14T12:08:04+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `d2cc794` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `f8e145f`
- commits: 28
- HEAD: `d2cc794` — docs(mcp): capability audit - zero new MCP servers, host MCP usage policy (2026-09-14T19:47:35+08:00)
- working tree: 23 dirty file(s)
  - `M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md`
  - ` M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md`
  - ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
  - ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
  - ` M .workbuddy-ai/handoff/05_RECENT_CHANGES.md`
  - ` M .workbuddy-ai/handoff/08_LIVE_METRICS.json`
  - ` M .workbuddy-ai/handoff/09_RUNTIME_STATE.json`
  - ` M .workbuddy-ai/handoff/10_LAST_HANDOFF.md`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M evidence/INDEX.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M learning/candidate_attempt_pool.json`
  - ` M learning/episodes.jsonl`
  - ` M learning/goal_state.json`
  - ` M learning/runtime_snapshot.json`
  - ` M winter_agent_v2/brain.py`
  - `?? evidence/intel_pins_20260914_114746.json`
  - `?? evidence/intel_pins_20260914_115009.json`
  - `?? evidence/intel_pins_20260914_115407.json`
  - `?? tools/_h.txt`

## B. Runtime

- agent_state: `DEGRADED`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: INTEL_HERO_DISPATCH_NOT_PROVEN
- page: MARCH  march: None/None
- updated_at: 2026-09-14T11:57:02.929343+00:00

## C. Episode stream

- rows: 913 (production 913)  modes: {'PRODUCTION': 913}
- success / failure: 614 / 294
- success rate over decided: **0.6762**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "INTEL_HERO_DISPATCH", "result": "FAILURE", "recorded_at": "2026-09-14T11:57:02.877619+00:00", "episode_id": "intel_pins_20260914_115407_nav_00", "before_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\intel_pins_20260914_115407_nav_00\\intel_pins_20260914_115407_nav_00_step_001_before_20260914T115616603104.png", "after_screenshot": "dataset\\raw\\control_panel\\runtime_auto\\intel_pins_20260914_115407_nav_00\\intel_pins_20260914_115407_nav_00_step_001_after_20260914T115628441233.png"}`

## D. Registry and lifecycle

- registry total: 86  by_state: {'VERIFIED': 44, 'CANDIDATE': 40, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 68
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **23**  stable: 19  degraded: 9  only_failed: 11  never_executed: 26

### Never executed

- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CHECK_MARCH` (VERIFIED)
- `CLAIM_FREE_STAMINA` (CANDIDATE)
- `CLAIM_REWARD` (CANDIDATE)
- `DISMISS_ALLIANCE_GENERIC_REWARD` (CANDIDATE)
- `DISMISS_EXPLORATION_REWARD` (VERIFIED)
- `INTEL_HERO_START_MARCH` (CANDIDATE)
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
- `EXECUTE_INTEL_RESCUE_SURVIVORS` attempts=5 failure=5
- `INTEL_HERO_DISPATCH` attempts=3 failure=3
- `OPEN_INTEL_HERO_JOURNEY_TARGET` attempts=1 failure=1
- `RESEARCH` attempts=1 failure=0
- `SAFE_STOP` attempts=4 failure=4
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=12 rate=0.9231
- `BACK` success=41 rate=0.9762
- `CLOSE_POPUP` success=30 rate=0.9677
- `DISMISS_INTEL_GENERIC_REWARD` success=11 rate=1.0
- `DISMISS_MAIL_GENERIC_REWARD` success=6 rate=0.8571
- `DISPATCH_INTEL_BEAST` success=21 rate=0.9545
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=22 rate=1.0
- `INTEL_CLAIM_REWARDS` success=27 rate=0.9
- `OPEN_DAILY` success=5 rate=0.8333
- `OPEN_EXPLORATION` success=11 rate=0.9167
- `OPEN_HOME` success=20 rate=0.8696
- `OPEN_INTEL` success=60 rate=0.8571
- `OPEN_INTEL_BEAST_TARGET` success=20 rate=0.9524
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=5 rate=1.0
- `OPEN_MAP` success=24 rate=0.96
- `OPEN_POWER_DETAILS` success=9 rate=1.0
- `OPEN_POWER_OVERVIEW` success=9 rate=0.8182
- `SELECT_INTEL_BEAST_MISSION` success=9 rate=0.8182

### Degraded

- `DISMISS_INTEL_REWARD` success=17 failure=5 rate=0.7727
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
`SEMANTIC_TARGET_NOT_VERIFIED` | 110 | SELECT_RESOURCE(40), SEARCH_RESOURCE(32), OPEN_MAIL(13)
`MARCH_PAGE_NOT_OPEN` | 59 | START_GATHER(59)
`RESOURCE_NOT_FOUND` | 30 | SUBMIT_RESOURCE_SEARCH(30)
`DISPATCH_NOT_PROVEN` | 29 | DISPATCH_MARCH(29)
`MAIL_CLAIM_FEEDBACK_NOT_PROVEN` | 10 | MAIL_CLAIM_REWARDS(10)
`STAMINA_SOURCES_NOT_OPEN` | 7 | OPEN_INTEL(7)
`POPUP_CLOSE_NOT_PROVEN` | 5 | DISMISS_REAL_MONEY_OFFER(4), RECONNECT_SESSION(1)
`INTEL_RESCUE_START_NOT_PROVEN` | 5 | EXECUTE_INTEL_RESCUE_SURVIVORS(5)
`NO_EXECUTION` | 4 | SAFE_STOP(4)
`INTEL_CLAIM_FEEDBACK_NOT_PROVEN` | 3 | INTEL_CLAIM_REWARDS(3)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 1, "partial": 8, "never_tried": 0, "blocked": 4, "degraded": 3, "missing": 0, "fully_live_verified_percent": 6.2, "never_tried_percent": 0.0, "automation_coverage_mean": 0.54, "live_coverage_mean": 0.5452}

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
- referenced screenshots: 352  present: 352
- missing: []
- episodes carrying screenshot references: 181

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-14T03:45:35+00:00", "size_bytes": 0, "last_stop_reason": null}
- recent crash reports: (none)
