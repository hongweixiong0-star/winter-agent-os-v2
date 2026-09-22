# 01 — CURRENT TRUTH

- generated_at: `2026-09-22T22:40:59+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `c2d80de` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 473
- HEAD: `c2d80de` — fix(home): the eighth OPEN_HOME emitter closes the search panel too -- six minutes of livelock, seven runs one step long (2026-09-23T06:39:53+08:00)
- working tree: 497 dirty file(s)
  - `M .workbuddy-ai/commander/CODEX_DIRECTIVES.md`
  - ` M .workbuddy-ai/commander/EXECUTION_STATE.json`
  - ` M .workbuddy-ai/commander/LAST_CODEX_REVIEW.md`
  - ` M .workbuddy-ai/commander/WORK_QUEUE.json`
  - ` M .workbuddy-ai/memory/2026-09-23.md`
  - ` M .workbuddy-ai/memory/MEMORY.md`
  - ` M .workbuddy/memory/2026-09-21.md`
  - ` M .workbuddy/memory/2026-09-23.md`
  - ` M config/control_panel_state.json`
  - ` M config/policy_state.json`
  - ` M dataset/candidate/template_manifest.json`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M evidence/INDEX.json`
  - ` M knowledge/game/capability_catalog.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M knowledge/goals/goal_capability_map.json`
  - ` M knowledge/perception/candidates/INDEX.json`
  - ` M knowledge/perception/candidates/alliance__eca25dc9a7/metadata.yaml`
  - ` M knowledge/perception/pages/INDEX.json`
  - ` M knowledge/preload/INDEX.json`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-09-22T22:40:59+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : c2d80de7c1992f66cabb9c732c5fd84c29c49a99
remote_head       : c2d80de7c1992f66cabb9c732c5fd84c29c49a99   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 0   (behind: 0)
git_dirty         : True (497 path(s))
last_push_at      : 2026-09-22T22:40:17.578005+00:00
last_push_status  : PUSHED
verdict           : GitHub mirrors the local tree
```

## B. Runtime

- agent_state: `IDLE`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 21
- last_fatal_error: None
- stop_reason: reserved_march_for_stamina
- page: MAP  march: 2/3
- updated_at: 2026-09-22T22:32:38.002771+00:00

## C. Episode stream

- rows: 6889 (production 6889)  modes: {'PRODUCTION': 6889}
- success / failure: 5650 / 1234
- success rate over decided: **0.8207**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "OPEN_MAP", "result": "SUCCESS", "recorded_at": "2026-09-22T22:31:58.359686+00:00", "episode_id": "20260923_062948_568906", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260923_062948_568906\\20260923_062948_568906_step_004_before_20260922T223128373025.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260923_062948_568906\\20260923_062948_568906_step_004_after_20260922T223143325021.png"}`

## D. Registry and lifecycle

- registry total: 112  by_state: {'VERIFIED': 47, 'CANDIDATE': 63, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 96
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **20**  stable: 42  degraded: 20  only_failed: 11  never_executed: 21

### Never executed

- `CLAIM_REWARD` (CANDIDATE)
- `COLLECT_FINISHED_TRAINING_LANCER` (CANDIDATE)
- `COLLECT_FINISHED_TRAINING_MARKSMAN` (CANDIDATE)
- `COLLECT_MY_REWARDS_ROW` (CANDIDATE)
- `JOIN_RALLY` (CANDIDATE)
- `NAVIGATE_TO` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_ALLIANCE_DONATION` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_HERO_RECRUIT` (CANDIDATE)
- `OPEN_TASK_FROM_QUICK_PANEL_MY_REWARDS` (CANDIDATE)
- `READ_COUNTER` (CANDIDATE)
- `READ_INTEL_LIST` (CANDIDATE)
- `READ_TIMER` (CANDIDATE)
- `RECOVER_HOME` (CANDIDATE)
- `REINFORCE_TARGET` (CANDIDATE)
- `RELAX_RESOURCE_LEVEL` (CANDIDATE)
- `SELECT_INTEL_RESCUE_SURVIVORS` (VERIFIED)
- `SELECT_REWARD_OPTION` (CANDIDATE)
- `SEND_MARCH` (CANDIDATE)
- `START_RALLY` (CANDIDATE)
- `USE_ACTIVITY_ATTEMPT` (CANDIDATE)
- `VERIFY_GATHERING` (VERIFIED)

### Only ever failed

- `ALLIANCE_HELP` attempts=1 failure=0
- `CANCEL_DUPLICATE_TARGET` attempts=1 failure=1
- `DISMISS_EXPLORATION_REWARD` attempts=1 failure=1
- `DISMISS_MAIL_REWARD` attempts=1 failure=1
- `OPEN_TASK_FROM_QUICK_PANEL_MARKSMAN` attempts=1 failure=1
- `RESEARCH` attempts=1 failure=0
- `SAFE_STOP` attempts=47 failure=47
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `SELECT_BEAST_TARGET_MAMMOTH` attempts=8 failure=8
- `SELECT_INFANTRY_CAMP` attempts=3 failure=3
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=24 rate=0.96
- `ATTACK_BEAST_CARD` success=49 rate=0.98
- `BACK` success=682 rate=0.888
- `DAILY_CLAIM_REWARDS` success=29 rate=1.0
- `DISMISS_DAILY_GENERIC_REWARD` success=39 rate=0.9286
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=6 rate=1.0
- `DISMISS_INTEL_GENERIC_REWARD` success=124 rate=0.9612
- `DISPATCH_INTEL_BEAST` success=81 rate=0.9205
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=88 rate=0.9778
- `INTEL_CLAIM_REWARDS` success=153 rate=0.9808
- `INTEL_HERO_DISPATCH` success=38 rate=0.8261
- `INTEL_HERO_START_MARCH` success=47 rate=0.94
- `MAIL_CLAIM_REWARDS` success=77 rate=0.8851
- `NAVIGATE_RESEARCH_LAB` success=39 rate=0.975
- `OPEN_ALLIANCE` success=69 rate=0.8519
- `OPEN_ALLIANCE_GIFTS` success=87 rate=1.0
- `OPEN_DAILY` success=73 rate=0.9733
- `OPEN_EXPLORATION` success=38 rate=0.95
- `OPEN_HOME` success=295 rate=0.8501
- `OPEN_INFANTRY_TRAINING` success=35 rate=0.814
- `OPEN_INTEL` success=285 rate=0.8796
- `OPEN_INTEL_BEAST_TARGET` success=88 rate=0.8462
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=50 rate=0.9615
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=16 rate=1.0
- `OPEN_MAIL` success=114 rate=0.8702
- `OPEN_MAP` success=343 rate=0.9689
- `OPEN_POWER_DETAILS` success=122 rate=0.9531
- `OPEN_POWER_OVERVIEW` success=127 rate=0.9621
- `OPEN_RESEARCH` success=49 rate=1.0
- `OPEN_STAMINA_SOURCES` success=35 rate=1.0
- `SCAN_MAP_FOR_BEAST` success=676 rate=0.9912
- `SEARCH_RESOURCE` success=280 rate=0.8833
- `SELECT_DAILY_TAB` success=39 rate=0.9286
- `SELECT_INTEL_BEAST_MISSION` success=10 rate=0.8333
- `SELECT_INTEL_PIN` success=229 rate=0.9745
- `SELECT_MAIL_REPORT_TAB` success=11 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=7 rate=0.875
- `SELECT_TRAINING_CAMP` success=40 rate=0.9524
- `SUBMIT_BEAST_SEARCH` success=53 rate=0.9298
- `TRAIN_TROOPS` success=9 rate=0.9
- `WAIT_FOR_CAMP_MENU` success=138 rate=1.0

### Degraded

- `CHECK_MARCH` success=32 failure=11 rate=0.7442
- `CLAIM_FREE_STAMINA` success=14 failure=236 rate=0.056
- `CLOSE_POPUP` success=56 failure=24 rate=0.7
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=6 failure=2 rate=0.75
- `DISMISS_INTEL_REWARD` success=23 failure=36 rate=0.3898
- `DISMISS_MAIL_GENERIC_REWARD` success=45 failure=46 rate=0.4945
- `DISMISS_REAL_MONEY_OFFER` success=11 failure=5 rate=0.6875
- `DISPATCH_MARCH` success=107 failure=38 rate=0.7379
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=19 failure=7 rate=0.7308
- `EXPLORATION_IDLE_CLAIM` success=8 failure=41 rate=0.1633
- `LEAVE_FOREIGN_LAYER` success=19 failure=29 rate=0.3958
- `NAVIGATE_INFANTRY_CAMP` success=62 failure=27 rate=0.6966
- `OPEN_BEAST_SEARCH_TAB` success=5 failure=2 rate=0.7143
- `OPEN_TASK_FROM_QUICK_PANEL_RESEARCH` success=6 failure=4 rate=0.6
- `SELECT_BEAST_TARGET_LABELLED` success=21 failure=6 rate=0.7778
- `SELECT_MAIL_ALLIANCE_TAB` success=15 failure=4 rate=0.7895
- `SELECT_RESOURCE` success=94 failure=46 rate=0.6714
- `START_GATHER` success=111 failure=60 rate=0.6491
- `SUBMIT_RESOURCE_SEARCH` success=115 failure=55 rate=0.6765
- `TRY_ORDINARY_CONTROL` success=39 failure=32 rate=0.5493

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 376 | OPEN_HOME(45), SELECT_RESOURCE(44), DISMISS_MAIL_GENERIC_REWARD(42)
`SAFE_BACK_NOT_PROVEN` | 86 | BACK(86)
`NO_EXECUTION` | 47 | SAFE_STOP(47)
`BEAST_DISPATCH_NOT_PROVEN` | 41 | DISPATCH_BEAST(41)
`EXPLORATION_IDLE_DIALOG_NOT_PROVEN` | 39 | EXPLORATION_IDLE_CLAIM(39)
`INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN` | 27 | NAVIGATE_INFANTRY_CAMP(27)
`OPEN_INTEL_NOT_PROVEN` | 16 | OPEN_INTEL(16)
`RECALL_DIALOG_NOT_OPEN` | 11 | SELECT_MARCH_TO_RECALL(11)
`POPUP_CLOSE_NOT_PROVEN` | 14 | CLOSE_POPUP(8), DISMISS_REAL_MONEY_OFFER(5), RECONNECT_SESSION(1)
`MARCH_COUNT_NOT_READ` | 11 | CHECK_MARCH(11)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 1, "partial": 9, "never_tried": 0, "blocked": 3, "degraded": 3, "missing": 0, "fully_live_verified_percent": 6.2, "never_tried_percent": 0.0, "automation_coverage_mean": 0.5713, "live_coverage_mean": 0.5765}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 67% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 67% | 67% | 67% | SPEND_STAMINA_ON_RALLY
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 86% | 86% | 29% | VERIFY_GATHERING
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | OPEN_BUILDING_PAGE
KEEP_RESEARCH_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 50% | START_RESEARCH
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
MAIL_ROUTINE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 75% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 75% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
CLAIM_EXPLORATION_IDLE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 67% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 50% | 75% | 50% | ALLIANCE_HELP, ALLIANCE_TECH_CONTRIBUTE
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 0% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 20% | 20% | 0% | CHECK_BEAR_PHASE, JOIN_RALLY, SELECT_TROOP_PRESET, START_RALLY
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 11994  present: 11994
- missing: []
- episodes carrying screenshot references: 6157

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-22T22:32:21+00:00", "size_bytes": 43243, "last_stop_reason": null}
- recent crash reports: ['E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_082612_963293_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_084519_539259_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_090424_676980_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_092331_166289_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_094236_608796_unified_worker.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 6076 (last 200 summarised)
- used_backend: {"ADB": 127, "MAA": 73}
- capture_backend: {"ADB_EXEC_OUT": 127, "MAA_MUMU_EXTRAS": 73}
- promoted to MAA in routing: 10 ['BACK', 'CLOSE_POPUP', 'DISMISS_BATTLE_VICTORY', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'OPEN_HOME', 'OPEN_INTEL', 'SEARCH_RESOURCE', 'SELECT_RESOURCE', 'START_GATHER']
- promoted but RAN ON ADB: {}
- last step: OPEN_MAP via ADB at 2026-09-22T22:31:41.802709+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
