# 01 — CURRENT TRUTH

- generated_at: `2026-09-23T18:35:19+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `d6d1a47` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 502
- HEAD: `d6d1a47` — fix(gateway-service): a service must not be started inside someone else's tool call (2026-09-24T02:22:05+08:00)
- working tree: 598 dirty file(s)
  - `M .workbuddy-ai/commander/CODEX_DIRECTIVES.md`
  - ` M .workbuddy-ai/commander/EXECUTION_STATE.json`
  - ` M .workbuddy-ai/commander/LAST_CODEX_REVIEW.md`
  - ` M .workbuddy-ai/commander/WORK_QUEUE.json`
  - ` M .workbuddy-ai/handoff/00_MASTER_RULES.md`
  - ` M .workbuddy-ai/handoff/01_CURRENT_TRUTH.md`
  - ` M .workbuddy-ai/handoff/02_CURRENT_PROGRESS.md`
  - ` M .workbuddy-ai/handoff/03_NEXT_ACTION.md`
  - ` M .workbuddy-ai/handoff/04_OPEN_ISSUES.md`
  - ` M .workbuddy-ai/handoff/05_RECENT_CHANGES.md`
  - ` M .workbuddy-ai/handoff/07_EXTERNAL_REUSE.md`
  - ` M .workbuddy-ai/handoff/08_LIVE_METRICS.json`
  - ` M .workbuddy-ai/handoff/09_RUNTIME_STATE.json`
  - ` M .workbuddy-ai/handoff/10_LAST_HANDOFF.md`
  - ` M .workbuddy-ai/memory/2026-09-23.md`
  - ` M .workbuddy/memory/2026-09-21.md`
  - ` M .workbuddy/memory/2026-09-23.md`
  - ` M config/control_panel_state.json`
  - ` M config/policy_state.json`
  - ` M dataset/candidate/template_manifest.json`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-09-23T18:35:19+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : d6d1a477b692c2eb6479632e47d3795fdc7dac17
remote_head       : 63b17c31d4e1a1285985332bcf8b7fc42df3450d   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 2   (behind: 0)
git_dirty         : True (598 path(s))
last_push_at      : 2026-09-23T14:43:30.540683+00:00
last_push_status  : PUSHED
verdict           : LOCAL IS AHEAD by 2 commit(s) -- run `python tools/git_sync.py push`
```

## B. Runtime

- agent_state: `RECOVERING`
- runtime_thread_alive: True / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 21
- last_fatal_error: None
- stop_reason: None
- page: HOME  march: None/None
- updated_at: 2026-09-23T18:35:15.100303+00:00

## C. Episode stream

- rows: 7864 (production 7864)  modes: {'PRODUCTION': 7864}
- success / failure: 6425 / 1434
- success rate over decided: **0.8175**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "OPEN_HOME", "result": "SUCCESS", "recorded_at": "2026-09-23T18:34:17.663078+00:00", "episode_id": "20260924_023347_469892", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260924_023347_469892\\20260924_023347_469892_step_001_before_20260923T183353118199.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260924_023347_469892\\20260924_023347_469892_step_001_after_20260923T183408647188.png"}`

## D. Registry and lifecycle

- registry total: 112  by_state: {'VERIFIED': 47, 'CANDIDATE': 63, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 98
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **20**  stable: 44  degraded: 18  only_failed: 11  never_executed: 21

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
- `SAFE_STOP` attempts=52 failure=52
- `SELECT_BEAST_TARGET` attempts=1 failure=1
- `SELECT_BEAST_TARGET_MAMMOTH` attempts=8 failure=8
- `SELECT_INFANTRY_CAMP` attempts=3 failure=3
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=24 rate=0.96
- `ATTACK_BEAST_CARD` success=65 rate=0.9848
- `BACK` success=777 rate=0.889
- `CONFIRM_EXPLORATION_IDLE_CLAIM` success=14 rate=0.875
- `DAILY_CLAIM_REWARDS` success=30 rate=1.0
- `DISMISS_DAILY_GENERIC_REWARD` success=41 rate=0.9318
- `DISMISS_EXPLORATION_GENERIC_REWARD` success=14 rate=1.0
- `DISMISS_INTEL_GENERIC_REWARD` success=150 rate=0.9615
- `DISPATCH_INTEL_BEAST` success=91 rate=0.9286
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=99 rate=0.9802
- `INTEL_CLAIM_REWARDS` success=179 rate=0.9835
- `INTEL_HERO_DISPATCH` success=47 rate=0.8545
- `INTEL_HERO_START_MARCH` success=57 rate=0.95
- `MAIL_CLAIM_REWARDS` success=98 rate=0.9074
- `NAVIGATE_RESEARCH_LAB` success=39 rate=0.975
- `OPEN_ALLIANCE` success=81 rate=0.871
- `OPEN_ALLIANCE_GIFTS` success=97 rate=1.0
- `OPEN_DAILY` success=86 rate=0.9773
- `OPEN_EXPLORATION` success=44 rate=0.9565
- `OPEN_HOME` success=363 rate=0.8726
- `OPEN_INFANTRY_TRAINING` success=36 rate=0.8182
- `OPEN_INTEL` success=322 rate=0.892
- `OPEN_INTEL_BEAST_TARGET` success=99 rate=0.8462
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=54 rate=0.9643
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=22 rate=1.0
- `OPEN_MAIL` success=133 rate=0.8867
- `OPEN_MAP` success=428 rate=0.9749
- `OPEN_POWER_OVERVIEW` success=145 rate=0.9667
- `OPEN_RESEARCH` success=60 rate=1.0
- `OPEN_STAMINA_SOURCES` success=38 rate=1.0
- `OPEN_TASK_FROM_QUICK_PANEL_RESEARCH` success=16 rate=0.8
- `SCAN_MAP_FOR_BEAST` success=706 rate=0.9916
- `SEARCH_RESOURCE` success=309 rate=0.8931
- `SELECT_DAILY_TAB` success=49 rate=0.9245
- `SELECT_INTEL_BEAST_MISSION` success=11 rate=0.8462
- `SELECT_INTEL_PIN` success=270 rate=0.9747
- `SELECT_MAIL_ALLIANCE_TAB` success=16 rate=0.8
- `SELECT_MAIL_REPORT_TAB` success=13 rate=1.0
- `SELECT_MAIL_SYSTEM_TAB` success=7 rate=0.875
- `SELECT_TRAINING_CAMP` success=41 rate=0.9318
- `SUBMIT_BEAST_SEARCH` success=69 rate=0.9452
- `TRAIN_TROOPS` success=11 rate=0.9167
- `WAIT_FOR_CAMP_MENU` success=138 rate=1.0

### Degraded

- `CHECK_MARCH` success=32 failure=11 rate=0.7442
- `CLAIM_FREE_STAMINA` success=16 failure=236 rate=0.0635
- `CLOSE_POPUP` success=74 failure=120 rate=0.3814
- `DISMISS_INTEL_REWARD` success=23 failure=36 rate=0.3898
- `DISMISS_MAIL_GENERIC_REWARD` success=65 failure=46 rate=0.5856
- `DISMISS_REAL_MONEY_OFFER` success=12 failure=6 rate=0.6667
- `DISPATCH_MARCH` success=107 failure=38 rate=0.7379
- `EXECUTE_INTEL_RESCUE_SURVIVORS` success=24 failure=8 rate=0.75
- `EXPLORATION_IDLE_CLAIM` success=15 failure=41 rate=0.2679
- `LEAVE_FOREIGN_LAYER` success=27 failure=29 rate=0.4821
- `NAVIGATE_INFANTRY_CAMP` success=62 failure=27 rate=0.6966
- `OPEN_BEAST_SEARCH_TAB` success=5 failure=2 rate=0.7143
- `OPEN_POWER_DETAILS` success=122 failure=34 rate=0.7821
- `SELECT_BEAST_TARGET_LABELLED` success=23 failure=6 rate=0.7931
- `SELECT_RESOURCE` success=95 failure=49 rate=0.6597
- `START_GATHER` success=112 failure=60 rate=0.6512
- `SUBMIT_RESOURCE_SEARCH` success=116 failure=55 rate=0.6784
- `TRY_ORDINARY_CONTROL` success=56 failure=61 rate=0.4786

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 429 | TRY_ORDINARY_CONTROL(51), SELECT_RESOURCE(47), OPEN_HOME(45)
`POPUP_CLOSE_NOT_PROVEN` | 89 | CLOSE_POPUP(82), DISMISS_REAL_MONEY_OFFER(6), RECONNECT_SESSION(1)
`SAFE_BACK_NOT_PROVEN` | 97 | BACK(97)
`BEAST_DISPATCH_NOT_PROVEN` | 58 | DISPATCH_BEAST(58)
`NO_EXECUTION` | 52 | SAFE_STOP(52)
`POWER_DETAILS_NOT_PROVEN` | 20 | OPEN_POWER_DETAILS(20)
`EXPLORATION_IDLE_DIALOG_NOT_PROVEN` | 39 | EXPLORATION_IDLE_CLAIM(39)
`OPEN_INTEL_NOT_PROVEN` | 16 | OPEN_INTEL(16)
`INFANTRY_CAMP_HIGHLIGHT_NOT_PROVEN` | 27 | NAVIGATE_INFANTRY_CAMP(27)
`ORDINARY_CONTROL_ALREADY_USED_THIS_RUN` | 10 | TRY_ORDINARY_CONTROL(10)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 1, "partial": 9, "never_tried": 0, "blocked": 3, "degraded": 3, "missing": 0, "fully_live_verified_percent": 6.2, "never_tried_percent": 0.0, "automation_coverage_mean": 0.6171, "live_coverage_mean": 0.5765}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 83% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 67% | 67% | -
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 86% | 86% | 29% | VERIFY_GATHERING
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | OPEN_BUILDING_PAGE
KEEP_RESEARCH_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 50% | START_RESEARCH
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 100% | -
MAIL_ROUTINE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 75% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 75% | READ_DAILY_PROGRESS
CLAIM_FREE_REWARDS | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
CLAIM_EXPLORATION_IDLE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 67% | -
ALLIANCE_ROUTINE | PARTIAL | NOT_A_RUNTIME_GOAL | 100% | 50% | 75% | 50% | ALLIANCE_HELP, ALLIANCE_TECH_CONTRIBUTE
EVENT_MINIMUM_GUARANTEE | PARTIAL | RUNTIME_DISCOVERED | 100% | 17% | 17% | 17% | CLAIM_EVENT_TIER, OPEN_EVENT_PAGE, READ_EVENT_PROGRESS, READ_EVENT_RULES, READ_EVENT_TIMER
ALLIANCE_TIMED_EVENTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | CHECK_ALLIANCE_EVENT, CLAIM_EVENT_TIER, READ_ALLIANCE_EVENT_TIMER
PARTICIPATE_BEAR | PARTIAL | RUNTIME_DISCOVERED | 100% | 60% | 20% | 0% | CHECK_BEAR_PHASE, SELECT_TROOP_PRESET
USE_FREE_ARENA_ATTEMPTS | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_ARENA_PAGE, READ_FREE_ATTEMPTS, SELECT_ARENA_OPPONENT, START_ARENA, VERIFY_ARENA_RESULT
LABYRINTH_DAILY | BLOCKED | RUNTIME_DISCOVERED | 100% | 0% | 0% | 0% | OPEN_LABYRINTH_PAGE, READ_LABYRINTH_ATTEMPTS, START_LABYRINTH, VERIFY_LABYRINTH_RESULT

## G. Evidence integrity

- status: **PASS**
- referenced screenshots: 13877  present: 13877
- missing: []
- episodes carrying screenshot references: 7132

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-23T18:34:35+00:00", "size_bytes": 23884, "last_stop_reason": null}
- recent crash reports: ['E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_082612_963293_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_084519_539259_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_090424_676980_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_092331_166289_unified_worker.json', 'E:\\无尽冬日智能体\\learning\\control_panel\\crashes\\20260921_094236_608796_unified_worker.json']

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 7115 (last 200 summarised)
- used_backend: {"ADB": 131, "MAA": 69}
- capture_backend: {"ADB_EXEC_OUT": 131, "MAA_MUMU_EXTRAS": 69}
- promoted to MAA in routing: 10 ['BACK', 'CLOSE_POPUP', 'DISMISS_BATTLE_VICTORY', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'OPEN_HOME', 'OPEN_INTEL', 'SEARCH_RESOURCE', 'SELECT_RESOURCE', 'START_GATHER']
- promoted but RAN ON ADB: {}
- last step: OPEN_HOME via MAA at 2026-09-23T18:34:07.131555+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
