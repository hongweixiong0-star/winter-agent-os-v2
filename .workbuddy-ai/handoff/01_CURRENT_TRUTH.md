# 01 — CURRENT TRUTH

- generated_at: `2026-09-18T03:21:24+00:00`
- source: `tools/update_workbuddy_handoff.py` (reads git, registry, capability map, episode stream, snapshot, logs)
- commit: `6b31d45` on `main`

> This file is regenerated. Never hand-edit it; edit the project instead.

## A. Version control

- repository: yes
- last good commit: `e4fd245`
- commits: 188
- HEAD: `6b31d45` — feat(preload): read once, store once, reuse many times (2026-09-18T11:20:56+08:00)
- working tree: 40 dirty file(s)
  - `M config/control_panel_state.json`
  - ` M config/policy_state.json`
  - ` M docs/CAPABILITY_COVERAGE.md`
  - ` M knowledge/game/capability_catalog.json`
  - ` M knowledge/goals/capability_skill_map.json`
  - ` M learning/control_panel/latest.log`
  - ` M learning/episodes.jsonl`
  - ` M learning/executor_backend.jsonl`
  - ` M learning/goal_state.json`
  - ` M learning/resource_rotation.json`
  - ` M learning/runtime_snapshot.json`
  - ` M learning/workbuddy_escalations.jsonl`
  - ` M learning/workbuddy_model_stats.jsonl`
  - ` M tests/test_capability_gate.py`
  - ` M winter_agent_v2/capability_gate.py`
  - `?? dataset/raw/control_panel/probe/`
  - `?? dataset/truth_audit/map_beast_search_20260918/`
  - `?? dataset/truth_audit/nav_to_map_20260918/key/live_20260918_job57848179_after_MAP.png`
  - `?? dataset/truth_audit/nav_to_map_20260918/key/live_20260918_job57848179_before_HOME.png`
  - `?? dataset/truth_audit/nav_to_map_20260918/regression_fix_57848179.json`

### A2. Public mirror

The repository is PUBLIC, so 'is the mirror current' is part of the truth this file
reports, not a side note. `remote_head` is the local remote-tracking ref: it is as
fresh as the last fetch, and `tools/git_sync.py status` is what refreshes it.

```
SYNC STATE at 2026-09-18T03:21:24+00:00
remote            : https://github.com/hongweixiong0-star/winter-agent-os-v2.git
branch            : main
local_head        : 6b31d45722e129adfe264ef926d14f3ce2a817bf
remote_head       : b5c962cb3ba9e912ea2ea8f81f4bd83083c6e46d   (local remote-tracking ref; run tools/git_sync.py status to refresh)
unpushed_commits  : 1   (behind: 0)
git_dirty         : True (40 path(s))
last_push_at      : 2026-09-18T03:03:28.160217+00:00
last_push_status  : PUSHED
verdict           : LOCAL IS AHEAD by 1 commit(s) -- run `python tools/git_sync.py push`
```

## B. Runtime

- agent_state: `IDLE`
- runtime_thread_alive: False / scheduler_loop_alive: False
- unexpected_worker_exits: 15
- watchdog_restart_count: 13
- last_fatal_error: None
- stop_reason: reserved_march_for_stamina
- page: MAP  march: 2/3
- updated_at: 2026-09-18T03:17:39.325489+00:00

## C. Episode stream

- rows: 1985 (production 1985)  modes: {'PRODUCTION': 1985}
- success / failure: 1614 / 366
- success rate over decided: **0.8152**
- mixed-case `result` rows (normalise on read, never rewrite): 35
- last episode: `{"skill": "OPEN_MAP", "result": "SUCCESS", "recorded_at": "2026-09-18T03:17:20.803377+00:00", "episode_id": "20260918_111617_064140", "before_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260918_111617_064140\\20260918_111617_064140_step_002_before_20260918T031650768487.png", "after_screenshot": "E:\\无尽冬日智能体\\dataset\\raw\\control_panel\\runtime_auto\\20260918_111617_064140\\20260918_111617_064140_step_002_after_20260918T031705875798.png"}`

## D. Registry and lifecycle

- registry total: 92  by_state: {'VERIFIED': 46, 'CANDIDATE': 44, 'BLOCKED': 2}
- live dispatchable (verifier-backed): 76
- BLOCKED skills: ['ALLIANCE_HELP', 'RESEARCH']
- live_verified: **24**  stable: 30  degraded: 11  only_failed: 10  never_executed: 19

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
- `SELECT_INFANTRY_CAMP` attempts=2 failure=2
- `WAIT` attempts=1 failure=1

### Stable

- `ALLIANCE_ALLY_GIFT_CLAIM` success=23 rate=0.9583
- `BACK` success=123 rate=0.9762
- `CHECK_MARCH` success=21 rate=0.9545
- `CLAIM_FREE_STAMINA` success=6 rate=1.0
- `CLOSE_POPUP` success=37 rate=0.9487
- `DAILY_CLAIM_REWARDS` success=5 rate=1.0
- `DISMISS_INTEL_GENERIC_REWARD` success=36 rate=1.0
- `DISMISS_INTEL_REWARD` success=23 rate=0.8214
- `DISMISS_MAIL_GENERIC_REWARD` success=7 rate=0.875
- `DISPATCH_INTEL_BEAST` success=38 rate=0.8837
- `GATHER_RESOURCE` success=8 rate=1.0
- `INTEL_BEAST_START_MARCH` success=42 rate=0.9545
- `INTEL_CLAIM_REWARDS` success=62 rate=0.9538
- `INTEL_HERO_START_MARCH` success=17 rate=0.85
- `NAVIGATE_INFANTRY_CAMP` success=12 rate=0.8571
- `OPEN_DAILY` success=10 rate=0.8333
- `OPEN_EXPLORATION` success=11 rate=0.9167
- `OPEN_HOME` success=38 rate=0.9268
- `OPEN_INTEL` success=115 rate=0.8519
- `OPEN_INTEL_BEAST_TARGET` success=42 rate=0.84
- `OPEN_INTEL_HERO_JOURNEY_TARGET` success=20 rate=0.9091
- `OPEN_INTEL_RESCUE_SURVIVORS_TARGET` success=7 rate=1.0
- `OPEN_MAP` success=56 rate=0.9032
- `OPEN_POWER_DETAILS` success=16 rate=1.0
- `OPEN_POWER_OVERVIEW` success=16 rate=0.8889
- `OPEN_STAMINA_SOURCES` success=16 rate=1.0
- `SCAN_MAP_FOR_BEAST` success=355 rate=0.9861
- `SELECT_INTEL_BEAST_MISSION` success=10 rate=0.8333
- `SELECT_INTEL_PIN` success=48 rate=0.9412
- `WAIT_FOR_CAMP_MENU` success=35 rate=1.0

### Degraded

- `DISMISS_REAL_MONEY_OFFER` success=6 failure=5 rate=0.5455
- `DISPATCH_MARCH` success=44 failure=37 rate=0.5432
- `INTEL_HERO_DISPATCH` success=12 failure=8 rate=0.6
- `MAIL_CLAIM_REWARDS` success=19 failure=10 rate=0.6552
- `OPEN_INFANTRY_TRAINING` success=5 failure=2 rate=0.7143
- `OPEN_MAIL` success=34 failure=15 rate=0.6939
- `SEARCH_RESOURCE` success=70 failure=34 rate=0.6731
- `SELECT_MAIL_ALLIANCE_TAB` success=7 failure=4 rate=0.6364
- `SELECT_RESOURCE` success=24 failure=45 rate=0.3478
- `START_GATHER` success=47 failure=60 rate=0.4393
- `SUBMIT_RESOURCE_SEARCH` success=48 failure=30 rate=0.6154

## E. Top failures

Failure | Count | Top skills
---|---:|---
`SEMANTIC_TARGET_NOT_VERIFIED` | 132 | SELECT_RESOURCE(44), SEARCH_RESOURCE(32), OPEN_MAIL(13)
`BEAST_SCAN_NOT_PROVEN` | 5 | SCAN_MAP_FOR_BEAST(5)
`INTEL_BEAST_TARGET_NOT_PROVEN` | 8 | OPEN_INTEL_BEAST_TARGET(8)
`OPEN_MAP_NOT_PROVEN` | 6 | OPEN_MAP(6)
`DAILY_REWARD_ADVANCE_NOT_PROVEN` | 5 | DISMISS_DAILY_REWARD(5)
`SAFE_BACK_NOT_PROVEN` | 3 | BACK(3)
`INFANTRY_CAMP_MENU_NOT_PROVEN` | 2 | SELECT_INFANTRY_CAMP(2)
`TRAINING_PAGE_NOT_PROVEN` | 2 | OPEN_INFANTRY_TRAINING(2)
`DAILY_TAB_NOT_SELECTED` | 2 | SELECT_DAILY_TAB(2)
`MARCH_PAGE_NOT_OPEN` | 60 | START_GATHER(60)

## F. Goal capability coverage

- model: Goal -> Canonical Capability -> Registered Skill -> Production Evidence
- summary: {"total": 16, "fully_live_verified": 2, "partial": 9, "never_tried": 0, "blocked": 3, "degraded": 2, "missing": 0, "fully_live_verified_percent": 12.5, "never_tried_percent": 0.0, "automation_coverage_mean": 0.5713, "live_coverage_mean": 0.5765}

Goal | Status | Runtime | design | impl | live | stable | blocked by
---|---|---|---:|---:|---:|---:|---
CLEAR_INTEL | PARTIAL | RUNTIME_DISCOVERED | 100% | 100% | 83% | 83% | -
AVOID_STAMINA_WASTE | PARTIAL | RUNTIME_DISCOVERED | 100% | 67% | 67% | 33% | SPEND_STAMINA_ON_RALLY
KEEP_MARCHES_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 86% | 86% | 14% | VERIFY_GATHERING
KEEP_BUILDING_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | OPEN_BUILDING_PAGE
KEEP_RESEARCH_PRODUCTIVE | PARTIAL | RUNTIME_DISCOVERED | 100% | 50% | 50% | 0% | START_RESEARCH
KEEP_TRAINING_PRODUCTIVE | FULLY_LIVE_VERIFIED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 50% | -
MAIL_ROUTINE | DEGRADED | RUNTIME_DISCOVERED | 100% | 100% | 100% | 0% | -
DAILY_ACTIVITY_TARGET | PARTIAL | RUNTIME_DISCOVERED | 100% | 75% | 75% | 50% | READ_DAILY_PROGRESS
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
- referenced screenshots: 2473  present: 2473
- missing: []
- episodes carrying screenshot references: 1253

## H. Commercial bot parity

- present: True
- summary: {"features_tracked": 21, "features_with_live_success": 10, "parity_fraction": 0.4762}
- features without live evidence: ['VIP', 'ALLIANCE_HELP', 'PROMOTE', 'HEAL', 'RESEARCH', 'ARENA', 'LABYRINTH', 'JOIN_RALLY', 'START_RALLY', 'BEAR', 'PET']

## I. Latest runtime log

- {"path": "E:\\无尽冬日智能体\\learning\\control_panel\\latest.log", "modified_at": "2026-09-18T03:17:36+00:00", "size_bytes": 7820, "last_stop_reason": "reserved_march_for_stamina"}
- recent crash reports: (none)

## J. Backend axis (MAA vs ADB)

- source: `learning/executor_backend.jsonl` vs `knowledge/execution/backend_routing.json`
- ledger rows: 1063 (last 200 summarised)
- used_backend: {"ADB": 151, "MAA": 49}
- capture_backend: {"ADB_EXEC_OUT": 151, "MAA_MUMU_EXTRAS": 49}
- promoted to MAA in routing: 10 ['BACK', 'CLOSE_POPUP', 'DISMISS_BATTLE_VICTORY', 'INTEL_HERO_DISPATCH', 'INTEL_HERO_START_MARCH', 'OPEN_HOME', 'OPEN_INTEL', 'SEARCH_RESOURCE', 'SELECT_RESOURCE', 'START_GATHER']
- promoted but RAN ON ADB: {}
- last step: OPEN_MAP via ADB at 2026-09-18T03:17:04.370750+00:00

> used_backend is what the step really did. A skill listed under promoted_but_ran_on_adb took the 324 ms ADB frame path while its own record claims MAA EmulatorExtras at 8.92 ms -- check tools/preflight.py before trusting the run.
