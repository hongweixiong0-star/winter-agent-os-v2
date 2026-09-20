# 01 — CURRENT TRUTH

- generated_at: `2026-09-20T13:03:05+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `a882c5c` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 322
- HEAD: `a882c5c` — docs(issues): #64 is deeper than refusal -- the dismissal is attempted and fails (2026-09-20T20:58:48+08:00)
- working tree: 149 dirty file(s)
  - `M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md`
  - ` M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md`
  - ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
  - ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
  - ` M .workbuddy-ai/handoff/05_RECENT_CHANGES.md`
  - ` M .workbuddy-ai/handoff/08_LIVE_METRICS.json`
  - ` M .workbuddy-ai/handoff/09_RUNTIME_STATE.json`
  - ` M .workbuddy-ai/handoff/10_LAST_HANDOFF.md`
  - ` M .workbuddy-ai/memory/MEMORY.md`
  - ` M .workbuddy/memory/2026-09-18.md`
  - ` M .workbuddy/memory/2026-09-20.md`
  - ` M config/control_panel_state.json`
  - ` M config/policy_state.json`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M docs/CURRENT_TRUTH.md`
  - ` M docs/LEGACY_AUDIT.md`
  - ` M evidence/INDEX.json`
  - ` M knowledge/game/capability_catalog.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M knowledge/goals/goal_capability_map.json`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-09-20T13:03:05+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : a882c5c4791a2e76221e680d42c17ce447404f86
remote_head       : a882c5c4791a2e76221e680d42c17ce447404f86   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 0   (behind: 0)
git_dirty         : True (149 path(s))
last_push_at      : 2026-09-18T10:00:11.524299+00:00
last_push_status  : PUSHED
verdict           : GitHub mirrors the local tree
```

## B. Runtime

- agent_state: `DEGRADED`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: generic_reward_without_goal_context
- page: POPUP  march: None/None
- updated_at: 2026-09-20T13:02:40.414459+00:00

## C. Episode stream

- rows: 3091 (production 3091)  modes: {'PRODUCTION': 3091}
- success / failure: 2339 / 747
- success rate over decided: **0.7579**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "DISMISS_INTEL_GENERIC_REWARD", "result": "FAILURE", "recorded_at": "2026-09-20T13:00:04.155708+00:00", "episode_id": "20260920_205419_420369", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260920_205419_420369\\20260920_205419_420369_step_014_before_20260920T130002712730.png", "after_screenshot": ""}`

## D. Registry and lifecycle

- registry total: 94  by_state: {'VERIFIED': 46, 'CANDIDATE': 46, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 78
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **20**  stable: 30  degraded: 18  only_failed: 10  never_executed: 18

### Never executed

- `ATTACK_BEAST_CARD` (CANDIDATE)
- `CANCEL_DUPLICATE_TARGET` (VERIFIED)
- `CLAIM_REWARD` (CANDIDATE)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `READ_COUNTER` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
- `READ_TIMER` (CANDIDATE)
- `RECOVER_HOME` (CANDIDATE)
- `REINFORCE_TARGET` (CANDIDATE)
- `RELAX_RESOURCE_LEVEL` (CANDIDATE)
- `SELECT_BEAST_TARGET_MAMMOTH` (CANDIDATE)
- `SELECT_INTEL_RESCUE_SURVIVORS` (VERIFIED)
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
- `SELECT_INFANTRY_CAMP` attempts=2 failure=2
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=24 rate=0.96
- `BACK` success=217 rate=0.9435
- `CHECK_MARCH` success=22 rate=0.9565
- `DAILY_CLAIM_REWARDS` success=8 rate=1.0
- `DISMISS_INTEL_GENERIC_REWARD` success=48 rate=0.9231
- `DISPATCH_INTEL_BEAST` success=44 rate=0.898
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=48 rate=0.96
- `INTEL_CLAIM_REWARDS` success=76 rate=0.962
- `INTEL_HERO_START_MARCH` success=20 rate=0.8696
- `NAVIGATE_RESEARCH_LAB` success=6 rate=1.0
- `OPEN_ALLIANCE` success=11 rate=1.0
- `OPEN_ALLIANCE_GIFTS` success=11 rate=1.0
- `OPEN_DAILY` success=23 rate=0.92
- `OPEN_EXPLORATION` success=17 rate=0.9444
- `OPEN_HOME` success=79 rate=0.9405
- `OPEN_INTEL` success=147 rate=0.875
- `OPEN_INTEL_BEAST_TARGET` success=48 rate=0.8571
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=23 rate=0.92
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=11 rate=1.0
- `OPEN_MAP` success=106 rate=0.9381
- `OPEN_POWER_DETAILS` success=33 rate=1.0
- `OPEN_POWER_OVERVIEW` success=33 rate=0.9167
- `OPEN_RESEARCH` success=8 rate=1.0
- `OPEN_STAMINA_SOURCES` success=30 rate=1.0
- `SCAN_MAP_FOR_BEAST` success=401 rate=0.9877
- `SELECT_DAILY_TAB` success=11 rate=0.8462
- `SELECT_INTEL_BEAST_MISSION` success=10 rate=0.8333
- `SELECT_INTEL_PIN` success=74 rate=0.961
- `WAIT_FOR_CAMP_MENU` success=39 rate=1.0

### Degraded

- `CLAIM_FREE_STAMINA` success=11 failure=236 rate=0.0445
- `CLOSE_POPUP` success=40 failure=16 rate=0.7143
- `DISMISS_DAILY_GENERIC_REWARD` success=7 failure=3 rate=0.7
- `DISMISS_INTEL_REWARD` success=23 failure=36 rate=0.3898
- `DISMISS_MAIL_GENERIC_REWARD` success=11 failure=42 rate=0.2075
- `DISMISS_REAL_MONEY_OFFER` success=7 failure=5 rate=0.5833
- `DISPATCH_MARCH` success=85 failure=38 rate=0.6911
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=6 failure=7 rate=0.4615
- `INTEL_HERO_DISPATCH` success=14 failure=8 rate=0.6364
- `MAIL_CLAIM_REWARDS` success=28 failure=10 rate=0.7368
- `NAVIGATE_INFANTRY_CAMP` success=15 failure=12 rate=0.5556
- `OPEN_INFANTRY_TRAINING` success=6 failure=2 rate=0.75
- `OPEN_MAIL` success=47 failure=17 rate=0.7344
- `SEARCH_RESOURCE` success=117 failure=34 rate=0.7748
- `SELECT_MAIL_ALLIANCE_TAB` success=8 failure=4 rate=0.6667
- `SELECT_RESOURCE` success=64 failure=46 rate=0.5818
- `START_GATHER` success=89 failure=60 rate=0.5973
- `SUBMIT_RESOURCE_SEARCH` success=91 failure=33 rate=0.7339

## E. Top failures

Failure | Count | Top skills
---|---:|---
`FREE_STAMINA_CLAIM_NOT_PROVEN` | 236 | CLAIM_FREE_STAMINA(236)
`SEMANTIC_TARGET_NOT_VERIFIED` | 224 | SELECT_RESOURCE(44), DISMISS_MAIL_GENERIC_REWARD(39), DISMISS_INTEL_REWARD(35)
`ALLIANCE_GIFTS_CLAIM_NOT_PROVEN` | 11 | ALLIANCE_GIFTS(11)
`INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN` | 12 | NAVIGATE_INFANTRY_CAMP(12)
`SAFE_BACK_NOT_PROVEN` | 13 | BACK(13)
`EXPLORATION_IDLE_DIALOG_NOT_PROVEN` | 8 | EXPLORATION_IDLE_CLAIM(8)
`RESOURCE_NOT_FOUND` | 33 | SUBMIT_RESOURCE_SEARCH(33)
`MAIL_REWARD_DISMISS_NOT_PROVEN` | 3 | DISMISS_MAIL_GENERIC_REWARD(3)
`OPEN_MAIL_NOT_PROVEN` | 4 | OPEN_MAIL(4)
`OPEN_MAP_NOT_PROVEN` | 7 | OPEN_MAP(7)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 1, "partial": 9, "never_tried": 0, "blocked": 3, "degraded": 3, "missing": 0, "fully_live_verified_percent": 6.2, "never_tried_percent": 0.0, "automation_coverage_mean": 0.5713, "live_coverage_mean": 0.5765}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 67% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 67% | 67% | 67% | SPEND_STAMINA_ON_RALLY
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 86% | 86% | 14% | VERIFY_GATHERING
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | OPEN_BUILDING_PAGE
KEEP_RESEARCH_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 50% | START_RESEARCH
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
MAIL_ROUTINE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 0% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 50% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 0% | -
CLAIM_EXPLORATION_IDLE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 33% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 50% | 75% | 25% | ALLIANCE_HELP, ALLIANCE_TECH_CONTRIBUTE
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 0% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 20% | 20% | 0% | CHECK_BEAR_PHASE, JOIN_RALLY, SELECT_TROOP_PRESET, START_RALLY
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 4593  present: 4593
- missing: []
- episodes carrying screenshot references: 2359

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-20T13:02:38+00:00", "size_bytes": 8852, "last_stop_reason": "generic_reward_without_goal_context"}
- recent crash reports: (none)

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 2174 (last 200 summarised)
- used_backend: {"ADB": 161, "MAA": 39}
- capture_backend: {"ADB_EXEC_OUT": 161, "MAA_MUMU_EXTRAS": 39}
- promoted to MAA in routing: 10 ['BACK', 'CLOSE_POPUP', 'DISMISS_BATTLE_VICTORY', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'OPEN_HOME', 'OPEN_INTEL', 'SEARCH_RESOURCE', 'SELECT_RESOURCE', 'START_GATHER']
- promoted but RAN ON ADB: {}
- last step: DISMISS_INTEL_GENERIC_REWARD via ADB at 2026-09-20T13:00:04.148533+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
