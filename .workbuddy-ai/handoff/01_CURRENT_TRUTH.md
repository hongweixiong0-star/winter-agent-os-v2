# 01 — CURRENT TRUTH

- generated_at: `2026-09-23T06:14:17+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `42b3b29` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 484
- HEAD: `42b3b29` — fix(ledger): a coordinate is a claim about one screen -- POPUP is 22 of them (2026-09-23T14:13:53+08:00)
- working tree: 542 dirty file(s)
  - `M .workbuddy-ai/commander/CODEX_DIRECTIVES.md`
  - ` M .workbuddy-ai/commander/EXECUTION_STATE.json`
  - ` M .workbuddy-ai/commander/LAST_CODEX_REVIEW.md`
  - ` M .workbuddy-ai/commander/WORK_QUEUE.json`
  - ` M .workbuddy/memory/2026-09-21.md`
  - ` M config/control_panel_state.json`
  - ` M config/policy_state.json`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M knowledge/game/capability_catalog.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M knowledge/goals/goal_capability_map.json`
  - ` M knowledge/perception/candidates/INDEX.json`
  - ` M knowledge/perception/candidates/alliance__eca25dc9a7/metadata.yaml`
  - ` M knowledge/perception/pages/INDEX.json`
  - ` M knowledge/preload/INDEX.json`
  - ` M knowledge/preload/TROOP_SELECT.json`
  - ` M knowledge/ui/page_transitions.json`
  - ` M learning/candidate_attempt_pool.json`
  - ` M learning/control_panel/latest.log`
  - ` M learning/control_panel/panel.log`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-09-23T06:14:17+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : 42b3b290035f6c7394def2656f5962c74aa425f0
remote_head       : 42b3b290035f6c7394def2656f5962c74aa425f0   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 0   (behind: 0)
git_dirty         : True (542 path(s))
last_push_at      : 2026-09-23T06:14:10.401295+00:00
last_push_status  : PUSHED
verdict           : GitHub mirrors the local tree
```

## B. Runtime

- agent_state: `RECOVERING`
- runtime_thread_alive: True / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 21
- last_fatal_error: None
- stop_reason: None
- page: HOME  march: None/None
- updated_at: 2026-09-23T06:14:14.320233+00:00

## C. Episode stream

- rows: 7209 (production 7209)  modes: {'PRODUCTION': 7209}
- success / failure: 5845 / 1359
- success rate over decided: **0.8114**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "BACK", "result": "SUCCESS", "recorded_at": "2026-09-23T06:13:04.059882+00:00", "episode_id": "20260923_140557_544859", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260923_140557_544859\\20260923_140557_544859_step_023_before_20260923T061239409091.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260923_140557_544859\\20260923_140557_544859_step_023_after_20260923T061250673181.png"}`

## D. Registry and lifecycle

- registry total: 112  by_state: {'VERIFIED': 47, 'CANDIDATE': 63, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 96
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **20**  stable: 43  degraded: 19  only_failed: 11  never_executed: 21

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
- `SAFE_STOP` attempts=48 failure=48
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `SELECT_BEAST_TARGET_MAMMOTH` attempts=8 failure=8
- `SELECT_INFANTRY_CAMP` attempts=3 failure=3
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=24 rate=0.96
- `ATTACK_BEAST_CARD` success=51 rate=0.9808
- `BACK` success=706 rate=0.8869
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=8 rate=0.8
- `DAILY_CLAIM_REWARDS` success=30 rate=1.0
- `DISMISS_DAILY_GENERIC_REWARD` success=41 rate=0.9318
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=8 rate=1.0
- `DISMISS_INTEL_GENERIC_REWARD` success=133 rate=0.9568
- `DISPATCH_INTEL_BEAST` success=87 rate=0.9255
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=94 rate=0.9792
- `INTEL_CLAIM_REWARDS` success=163 rate=0.9819
- `INTEL_HERO_DISPATCH` success=41 rate=0.8367
- `INTEL_HERO_START_MARCH` success=51 rate=0.9444
- `MAIL_CLAIM_REWARDS` success=81 rate=0.8901
- `NAVIGATE_RESEARCH_LAB` success=39 rate=0.975
- `OPEN_ALLIANCE` success=73 rate=0.8588
- `OPEN_ALLIANCE_GIFTS` success=90 rate=1.0
- `OPEN_DAILY` success=79 rate=0.9753
- `OPEN_EXPLORATION` success=40 rate=0.9524
- `OPEN_HOME` success=309 rate=0.8536
- `OPEN_INFANTRY_TRAINING` success=35 rate=0.814
- `OPEN_INTEL` success=297 rate=0.8839
- `OPEN_INTEL_BEAST_TARGET` success=94 rate=0.8545
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=52 rate=0.963
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=17 rate=1.0
- `OPEN_MAIL` success=118 rate=0.8741
- `OPEN_MAP` success=361 rate=0.9704
- `OPEN_POWER_DETAILS` success=122 rate=0.8971
- `OPEN_POWER_OVERVIEW` success=129 rate=0.9627
- `OPEN_RESEARCH` success=52 rate=1.0
- `OPEN_STAMINA_SOURCES` success=37 rate=1.0
- `SCAN_MAP_FOR_BEAST` success=676 rate=0.9912
- `SEARCH_RESOURCE` success=283 rate=0.8844
- `SELECT_DAILY_TAB` success=43 rate=0.9149
- `SELECT_INTEL_BEAST_MISSION` success=11 rate=0.8462
- `SELECT_INTEL_PIN` success=241 rate=0.9757
- `SELECT_MAIL_REPORT_TAB` success=11 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=7 rate=0.875
- `SELECT_TRAINING_CAMP` success=40 rate=0.9524
- `SUBMIT_BEAST_SEARCH` success=55 rate=0.9322
- `TRAIN_TROOPS` success=9 rate=0.9
- `WAIT_FOR_CAMP_MENU` success=138 rate=1.0

### Degraded

- `CHECK_MARCH` success=32 failure=11 rate=0.7442
- `CLAIM_FREE_STAMINA` success=15 failure=236 rate=0.0598
- `CLOSE_POPUP` success=59 failure=120 rate=0.3296
- `DISMISS_INTEL_REWARD` success=23 failure=36 rate=0.3898
- `DISMISS_MAIL_GENERIC_REWARD` success=49 failure=46 rate=0.5158
- `DISMISS_REAL_MONEY_OFFER` success=11 failure=5 rate=0.6875
- `DISPATCH_MARCH` success=107 failure=38 rate=0.7379
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=20 failure=7 rate=0.7407
- `EXPLORATION_IDLE_CLAIM` success=9 failure=41 rate=0.18
- `LEAVE_FOREIGN_LAYER` success=21 failure=29 rate=0.42
- `NAVIGATE_INFANTRY_CAMP` success=62 failure=27 rate=0.6966
- `OPEN_BEAST_SEARCH_TAB` success=5 failure=2 rate=0.7143
- `OPEN_TASK_FROM_QUICK_PANEL_RESEARCH` success=8 failure=4 rate=0.6667
- `SELECT_BEAST_TARGET_LABELLED` success=21 failure=6 rate=0.7778
- `SELECT_MAIL_ALLIANCE_TAB` success=15 failure=4 rate=0.7895
- `SELECT_RESOURCE` success=95 failure=46 rate=0.6738
- `START_GATHER` success=112 failure=60 rate=0.6512
- `SUBMIT_RESOURCE_SEARCH` success=116 failure=55 rate=0.6784
- `TRY_ORDINARY_CONTROL` success=41 failure=41 rate=0.5

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 405 | OPEN_HOME(45), SELECT_RESOURCE(44), DISMISS_MAIL_GENERIC_REWARD(42)
`POPUP_CLOSE_NOT_PROVEN` | 88 | CLOSE_POPUP(82), DISMISS_REAL_MONEY_OFFER(5), RECONNECT_SESSION(1)
`SAFE_BACK_NOT_PROVEN` | 90 | BACK(90)
`NO_EXECUTION` | 48 | SAFE_STOP(48)
`BEAST_DISPATCH_NOT_PROVEN` | 43 | DISPATCH_BEAST(43)
`EXPLORATION_IDLE_DIALOG_NOT_PROVEN` | 39 | EXPLORATION_IDLE_CLAIM(39)
`INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN` | 27 | NAVIGATE_INFANTRY_CAMP(27)
`OPEN_INTEL_NOT_PROVEN` | 16 | OPEN_INTEL(16)
`RECALL_DIALOG_NOT_OPEN` | 13 | SELECT_MARCH_TO_RECALL(13)
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
- referenced screenshots: 12602  present: 12602
- missing: []
- episodes carrying screenshot references: 6477

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-23T06:13:24+00:00", "size_bytes": 210562, "last_stop_reason": null}
- recent crash reports: ['E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_082612_963293_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_084519_539259_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_090424_676980_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_092331_166289_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_094236_608796_unified_worker.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 6420 (last 200 summarised)
- used_backend: {"MAA": 126, "ADB": 74}
- capture_backend: {"MAA_MUMU_EXTRAS": 126, "ADB_EXEC_OUT": 74}
- promoted to MAA in routing: 10 ['BACK', 'CLOSE_POPUP', 'DISMISS_BATTLE_VICTORY', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'OPEN_HOME', 'OPEN_INTEL', 'SEARCH_RESOURCE', 'SELECT_RESOURCE', 'START_GATHER']
- promoted but RAN ON ADB: {}
- last step: BACK via MAA at 2026-09-23T06:12:49.156002+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
